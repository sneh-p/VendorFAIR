#!/usr/bin/env bash
#
# VendorFAIR installer -- clone from GitHub and set up the app on a Linux host.
#
# One-line install (downloads + runs this script):
#   curl -fsSL https://raw.githubusercontent.com/sneh-p/VendorFAIR/main/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/sneh-p/VendorFAIR/main/install.sh | bash -s -- --with-ollama --service
#
# Or clone first, then run in place:
#   git clone https://github.com/sneh-p/VendorFAIR.git
#   cd VendorFAIR && bash install.sh --with-ollama --service
#
# Options:
#   --dir PATH        install directory                     (default: /opt/vendorfair)
#   --repo URL        git repository                         (default: the VendorFAIR repo)
#   --branch NAME     git branch                             (default: main)
#   --org "NAME"      ORG_NAME written to .env               (default: "Your MSP Name")
#   --port N          Streamlit port                         (default: 8501)
#   --model NAME      Ollama model for the local fallback    (default: llama3.2:1b)
#   --with-ollama     install Ollama + pull the model (enables offline/no-key research)
#   --service         install + enable a systemd service (needs root/systemd)
#   --run             launch the app in the foreground after install
#   -h, --help        show this help
#
# Idempotent: re-running updates the checkout and dependencies and never
# overwrites an existing .env or the data/ directory.
#
set -euo pipefail

# ----------------------------------------------------------------- defaults
REPO_URL="https://github.com/sneh-p/VendorFAIR.git"
BRANCH="main"
INSTALL_DIR="/opt/vendorfair"
ORG_NAME="Your MSP Name"
PORT="8501"
OLLAMA_MODEL="llama3.2:1b"
WITH_OLLAMA="false"
WITH_SERVICE="false"
RUN_FG="false"
DIR_SET="false"
APP_DIR=""

# ----------------------------------------------------------------- logging
_c() { [ -t 1 ] && printf '\033[%sm' "$1" || true; }
log()  { printf '%s[vendorfair]%s %s\n' "$(_c '1;36')" "$(_c 0)" "$*"; }
ok()   { printf '%s[  ok  ]%s %s\n'     "$(_c '1;32')" "$(_c 0)" "$*"; }
warn() { printf '%s[ warn ]%s %s\n'     "$(_c '1;33')" "$(_c 0)" "$*" >&2; }
die()  { printf '%s[ fail ]%s %s\n'     "$(_c '1;31')" "$(_c 0)" "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

usage() { sed -n '3,30p' "$0" 2>/dev/null | sed 's/^#\{1,2\} \{0,1\}//; s/^#$//'; }

# ----------------------------------------------------------------- args
while [ $# -gt 0 ]; do
  case "$1" in
    --dir)        INSTALL_DIR="$2"; DIR_SET="true"; shift 2 ;;
    --repo)       REPO_URL="$2"; shift 2 ;;
    --branch)     BRANCH="$2"; shift 2 ;;
    --org)        ORG_NAME="$2"; shift 2 ;;
    --port)       PORT="$2"; shift 2 ;;
    --model)      OLLAMA_MODEL="$2"; shift 2 ;;
    --with-ollama) WITH_OLLAMA="true"; shift ;;
    --no-ollama)  WITH_OLLAMA="false"; shift ;;
    --service)    WITH_SERVICE="true"; shift ;;
    --no-service) WITH_SERVICE="false"; shift ;;
    --run)        RUN_FG="true"; shift ;;
    -h|--help)    usage; exit 0 ;;
    *)            die "Unknown option: $1  (try --help)" ;;
  esac
done

if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi

# ----------------------------------------------------------------- steps
install_prereqs() {
  local pkgs="git python3 python3-venv python3-pip curl ca-certificates"
  if have apt-get; then
    log "Installing system packages ($pkgs)"
    $SUDO apt-get update -qq
    $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $pkgs >/dev/null
  else
    warn "Non-apt system detected; ensure these are present: $pkgs"
  fi
}

check_python() {
  have python3 || die "python3 not found"
  python3 - <<'PY' || die "Python 3.11+ is required"
import sys
raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)
PY
  ok "Python $(python3 -V | awk '{print $2}')"
}

# Use an existing local checkout if the script is run from inside the repo;
# otherwise clone (or update) into INSTALL_DIR.
fetch_repo() {
  local self="${BASH_SOURCE[0]:-$0}" script_dir="" d
  [ -f "$self" ] && script_dir="$(cd "$(dirname "$self")" && pwd)"
  if [ -n "$script_dir" ] && [ "$DIR_SET" != "true" ]; then
    for d in "$script_dir" "$script_dir"/*/; do
      if [ -f "${d%/}/app.py" ] && [ -f "${d%/}/requirements.txt" ]; then
        APP_DIR="${d%/}"; INSTALL_DIR="$APP_DIR"
        log "Installing in place from existing checkout: $APP_DIR"
        return
      fi
    done
  fi

  if [ -d "$INSTALL_DIR/.git" ]; then
    log "Updating existing checkout in $INSTALL_DIR"
    git -C "$INSTALL_DIR" fetch --depth 1 origin "$BRANCH"
    git -C "$INSTALL_DIR" reset --hard "origin/$BRANCH"
  elif [ -e "$INSTALL_DIR" ] && [ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]; then
    die "$INSTALL_DIR exists and is not a VendorFAIR checkout -- pick another --dir or remove it."
  else
    log "Cloning $REPO_URL ($BRANCH) -> $INSTALL_DIR"
    $SUDO mkdir -p "$INSTALL_DIR"
    $SUDO chown "$(id -un)":"$(id -gn)" "$INSTALL_DIR" 2>/dev/null || true
    git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
  fi
}

locate_app_dir() {
  [ -n "$APP_DIR" ] && return
  local d
  for d in "$INSTALL_DIR" "$INSTALL_DIR"/*/; do
    if [ -f "${d%/}/app.py" ] && [ -f "${d%/}/requirements.txt" ]; then
      APP_DIR="${d%/}"; break
    fi
  done
  [ -n "$APP_DIR" ] && [ -f "$APP_DIR/app.py" ] \
    || die "Could not find app.py + requirements.txt in $INSTALL_DIR"
  ok "Project directory: $APP_DIR"
}

setup_venv() {
  log "Setting up virtualenv + dependencies (this can take a few minutes)..."
  [ -d "$APP_DIR/.venv" ] || python3 -m venv "$APP_DIR/.venv"
  "$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
  "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
  ok "Dependencies installed"
}

setup_env() {
  if [ -f "$APP_DIR/.env" ]; then
    warn ".env already exists -- leaving it untouched"
    return
  fi
  cp "$APP_DIR/env.example" "$APP_DIR/.env"
  local esc
  esc=$(printf '%s' "$ORG_NAME" | sed -e 's/[\\&|]/\\&/g')
  sed -i "s|^ORG_NAME=.*|ORG_NAME=$esc|" "$APP_DIR/.env" 2>/dev/null || echo "ORG_NAME=$ORG_NAME" >> "$APP_DIR/.env"
  if grep -q '^OLLAMA_MODEL=' "$APP_DIR/.env"; then
    sed -i "s|^OLLAMA_MODEL=.*|OLLAMA_MODEL=$OLLAMA_MODEL|" "$APP_DIR/.env"
  else
    echo "OLLAMA_MODEL=$OLLAMA_MODEL" >> "$APP_DIR/.env"
  fi
  ok ".env created (API keys left empty -- local fallback is the active path)"
}

setup_ollama() {
  if have ollama; then
    ok "Ollama already installed"
  else
    log "Installing Ollama"
    have zstd || { have apt-get && $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq zstd >/dev/null; } || true
    curl -fsSL https://ollama.com/install.sh | sh
  fi
  $SUDO systemctl enable --now ollama 2>/dev/null || warn "Could not enable ollama via systemd -- start it manually."
  log "Pulling model '$OLLAMA_MODEL' (downloads ~1+ GB on first run)..."
  ollama pull "$OLLAMA_MODEL"
  ok "Ollama ready with $OLLAMA_MODEL"
}

setup_service() {
  have systemctl || { warn "systemd not available -- skipping service install"; return; }
  local unit=/etc/systemd/system/vendorfair.service
  log "Installing systemd unit ($unit)"
  $SUDO tee "$unit" >/dev/null <<EOF
[Unit]
Description=VendorFAIR (Streamlit) third-party risk app
After=network-online.target ollama.service
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$APP_DIR
# Force TCP DNS on networks that drop UDP DNS (harmless otherwise):
Environment=RES_OPTIONS=use-vc
ExecStart=$APP_DIR/.venv/bin/streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true --browser.gatherUsageStats false
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  $SUDO systemctl daemon-reload
  $SUDO systemctl enable --now vendorfair
  sleep 3
  if $SUDO systemctl is-active --quiet vendorfair; then
    ok "Service started"
  else
    warn "Service did not become active -- check: journalctl -u vendorfair"
  fi
}

# ----------------------------------------------------------------- run
log "VendorFAIR installer"
install_prereqs
check_python
fetch_repo
locate_app_dir
setup_venv
setup_env
if [ "$WITH_OLLAMA" = "true" ]; then
  setup_ollama
else
  warn "Skipping Ollama. Local-LLM research is off until you re-run with --with-ollama (or set a cloud API key in Settings)."
fi
[ "$WITH_SERVICE" = "true" ] && setup_service

echo
ok "VendorFAIR installed at $APP_DIR"
echo "    Login:   admin / ChangeMe123!   (change it at first login)"
echo "    Config:  $APP_DIR/.env"
if [ "$WITH_SERVICE" = "true" ]; then
  echo "    URL:     http://<this-host-ip>:$PORT      (systemctl status vendorfair)"
elif [ "$RUN_FG" = "true" ]; then
  log "Launching on port $PORT (Ctrl-C to stop)..."
  cd "$APP_DIR"
  exec "$APP_DIR/.venv/bin/streamlit" run app.py --server.port "$PORT" --server.address 0.0.0.0 --server.headless true
else
  echo "    Start:   cd $APP_DIR && .venv/bin/streamlit run app.py --server.port $PORT --server.address 0.0.0.0"
fi
