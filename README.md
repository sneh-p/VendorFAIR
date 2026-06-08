# VendorFAIR — FAIR-Based Vendor Risk Intake Platform

A full-stack vendor/third-party risk platform for MSP security specialists, combining:

1. **Vendor Risk Intake Automation** — AI-powered research that pre-populates a vendor's security posture, with a **cloud engine** (Claude / Gemini / OpenAI + web search) and an automatic **local-LLM fallback** (DuckDuckGo + Ollama) when no API key is configured.
2. **FAIR Risk Quantification** — Monte Carlo (10,000 iterations, PERT distributions) producing dollar-range annualized loss exposure.
3. **Risk Memo Generator** — professional DOCX/PDF reports for client QBRs and compliance evidence.
4. **Multi-tenant Risk Register** — sortable, filterable dashboard with trend tracking and CSV/XLSX export.

## Quick Start

```bash
cd vendorfair
python3.11 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then set ORG_NAME and (optionally) an API key
streamlit run app.py
```

Open http://localhost:8501. Default login is **`admin` / `ChangeMe123!`** — change it at first login.

## AI Research: two engines, automatic selection

VendorFAIR picks the research engine at runtime based on whether an API key is available for the selected provider:

| Condition | Engine used | Confidence |
|---|---|---|
| API key configured (Settings DB **or** `.env`) | **Cloud** — provider's model + native web search | up to High |
| No API key anywhere, local Ollama reachable | **Local fallback** — DuckDuckGo + scraping + Ollama | capped at Medium |
| No API key and no local LLM | Research disabled (rest of the app still works) | — |

The **local fallback** (`modules/local_researcher.py`) runs a small agentic pipeline: three targeted DuckDuckGo
searches (compliance / breach / trust-center), scrapes the top hits with `trafilatura`, makes one focused,
JSON-constrained Ollama call per topic, then merges the results **in Python** into the exact research schema the
cloud path uses — passing through the same FAIR-bound sanitisation. It is self-contained, degrades gracefully
(per-topic safe defaults, retry-once on bad JSON, ~6-minute budget, rate-limit backoff), and never raises into the UI.
The Ollama server stays bound to localhost. The UI shows a badge identifying which engine produced each result.

## Architecture

| Layer | Technology |
|---|---|
| Frontend | Streamlit + custom theme (dark/light, switchable in Settings) |
| Backend | Python 3.11+ |
| Cloud AI | Anthropic Claude / Google Gemini / OpenAI, each with native web search |
| Local AI fallback | Ollama (`llama3.2:1b` default) + `ddgs` + `trafilatura` |
| Database | SQLite via SQLAlchemy 2.0 ORM |
| Risk Model | FAIR with Monte Carlo simulation (`numpy`, PERT via beta distribution) |
| Report Export | `python-docx` (DOCX), `reportlab` (PDF), `matplotlib` (charts) |

> **Model note:** the original spec pinned `claude-sonnet-4-20250514`, which Anthropic deprecated with
> retirement on **2026-06-15**. This build uses the official drop-in replacement `claude-sonnet-4-6`,
> configurable via `CLAUDE_MODEL` in `.env`.

```
vendorfair/
├── app.py                     # Streamlit entry point (5-step flow, register, theming)
├── config.py                  # .env config loader (cloud + Ollama settings)
├── install.sh                 # one-shot installer (clone, venv, deps, Ollama, systemd)
├── .streamlit/
│   └── config.toml            # Streamlit base theme (dark default)
├── database/
│   ├── models.py              # Tenant, Vendor, VendorAssessment, AssessmentHistory
│   └── db.py                  # Engine/session management, default-tenant seeding
├── modules/
│   ├── vendor_intake.py       # Intake persistence
│   ├── ai_researcher.py       # Provider dispatch (cloud + local fallback routing), JSON parse, FAIR sanitize
│   ├── local_researcher.py    # DuckDuckGo + trafilatura + Ollama local research pipeline
│   ├── settings_store.py      # Encrypted API-key store + provider config + UI theme
│   ├── fair_calculator.py     # PERT sampling + Monte Carlo FAIR engine
│   ├── report_generator.py    # DOCX/PDF memos with embedded risk chart
│   └── risk_register.py       # Dashboard queries, trend history, CSV/XLSX export
├── prompts/
│   ├── vendor_research.py     # Research system/user prompts + output schema
│   └── report_writer.py       # Report section prompts + static fallbacks
└── tests/                     # pytest suite (FAIR math, intake DB, research mocks, local fallback, reports)
```

## Appearance & theming

The UI ships with a modern theme — Inter typography, card-style metrics, gradient page
headers, and a fixed (non-collapsible) sidebar nav. It is **dark by default** and can be
switched to **light** under **Settings → Appearance**. The choice is stored app-wide in the
settings database (`ui_theme`) and applied on the next render, so it persists across logins
and restarts. The colours are driven by an injected CSS variable palette in `app.py`; the
Streamlit base theme lives in `.streamlit/config.toml`.

> Note: the theme switch reskins the entire app via CSS. Streamlit's `st.dataframe` grid
> (Risk Register) renders on its own canvas tied to the `config.toml` base theme, so it always
> matches the *default* (dark); switch the `base` in `.streamlit/config.toml` if you run the
> app primarily in light mode.

## FAIR Model

Each parameter is a min / most-likely / max triple sampled from a PERT distribution:

- **Vulnerability** = max(0, TC − CS)
- **LEF** = TEF × Vulnerability
- **LM** = PLM + SLM
- **Risk (ALE)** = LEF × LM

Outputs: P10/P50/P90 ALE, histogram + confidence interval, and a tier:
Low (<$10K) / Moderate ($10K–$100K) / High ($100K–$1M) / Critical (>$1M).

## Tests

```bash
. .venv/bin/activate
python -m pytest tests/ -v
```

**104 tests** cover PERT bounds, percentile consistency (P10 ≤ P50 ≤ P90), vulnerability clipping, sub-3-second
runtime at 10K iterations, intake persistence, encrypted settings, cloud AI-output parsing/sanitisation, the local
research fallback (schema merge, invalid-JSON retry, no-key routing, confidence capping — all mocked, no live calls),
and DOCX/PDF export integrity.

---

# Deploying on any server

This guide deploys VendorFAIR onto a fresh Linux host (bare metal, VM, or container) with both research engines.
It assumes Debian/Ubuntu; adjust the package manager for other distros. Everything runs as a normal service — no
Docker required.

## Quick install (script)

The repo ships an **idempotent** [`install.sh`](install.sh) that clones the project, creates the virtualenv,
installs dependencies, writes a starter `.env`, and (optionally) sets up the local Ollama fallback and a systemd
service. Re-running it updates the checkout/deps and never touches an existing `.env` or `data/`.

```bash
# One-liner — clones into /opt/vendorfair, installs the local LLM, runs as a service:
curl -fsSL https://raw.githubusercontent.com/sneh-p/VendorFAIR/main/install.sh | bash -s -- --with-ollama --service

# …or clone first, then run in place:
git clone https://github.com/sneh-p/VendorFAIR.git
cd VendorFAIR && bash install.sh --with-ollama --service
```

Useful flags (see `bash install.sh --help` for all): `--dir <path>`, `--org "<name>"`, `--port <n>`,
`--model <name>`, `--with-ollama`, `--service`, `--run`. Omit `--with-ollama` to skip the ~1 GB model download
(you can add it later); omit `--service` to just install and get a manual run command.

The manual steps below are the equivalent of what the script automates — use them if you prefer to do it by hand.

## 1. Prerequisites

- A Linux host with **Python 3.11+** and outbound internet (for the local fallback's web search and for pulling the Ollama model).
- ~4 GB RAM and ~6 GB disk if you want the local LLM fallback (`llama3.2:1b`). The app alone needs far less.
- Shell access as root or a sudo user.

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip git curl ca-certificates
python3 --version        # confirm >= 3.11
```

## 2. Get the code and create a virtualenv

```bash
sudo mkdir -p /opt/vendorfair && sudo chown "$USER" /opt/vendorfair
# copy this project into /opt/vendorfair (git clone, scp, rsync, or unpack a tarball), then:
cd /opt/vendorfair
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 3. Configure the environment

```bash
cp .env.example .env
```

Edit `.env`:

| Variable | Purpose | Default |
|---|---|---|
| `ORG_NAME` | Your organisation name (appears on reports) | `Your MSP Name` |
| `APP_TITLE` | Browser/page title | `VendorFAIR` |
| `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY` | Cloud research key(s). **Leave empty to use the local fallback.** | empty |
| `CLAUDE_MODEL` | Claude model id | `claude-sonnet-4-6` |
| `OLLAMA_BASE_URL` | Local Ollama endpoint | `http://127.0.0.1:11434` |
| `OLLAMA_MODEL` | Local fallback model | `llama3.2:1b` |
| `DB_PATH` | SQLite path | `data/vendorfair.db` |
| `REPORT_OUTPUT_DIR` | Generated report folder | `reports/` |
| `DEFAULT_MONTE_CARLO_ITERATIONS` | Simulation iterations | `10000` |

The database and Fernet encryption key are created automatically on first run under `data/` (the key,
`data/.vendorfair.key`, is written `0600` and must never be committed or copied off the host).

## 4. (Optional) Set up the local LLM fallback

Skip this if you only use cloud providers. To enable offline/no-key research:

```bash
# Ollama's installer needs zstd present first on minimal images:
sudo apt-get install -y zstd
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl enable --now ollama          # binds to 127.0.0.1:11434 by default — keep it local
ollama pull llama3.2:1b                       # ~1.3 GB
ollama run llama3.2:1b "say ok"               # quick smoke test
```

In the app's **Settings → Local LLM Fallback**, use **Test local LLM** to confirm reachability and the loaded model.

## 5. Run it

**Foreground (quick check):**

```bash
. .venv/bin/activate
streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
```

**As a systemd service (recommended).** Create `/etc/systemd/system/vendorfair.service`:

```ini
[Unit]
Description=VendorFAIR (Streamlit) third-party risk app
After=network-online.target ollama.service
Wants=network-online.target
# Drop the next line if you are not running the local Ollama fallback:
Requires=ollama.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/vendorfair
# Only needed on networks that drop UDP DNS — forces resolver TCP:
Environment=RES_OPTIONS=use-vc
ExecStart=/opt/vendorfair/.venv/bin/streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true --browser.gatherUsageStats false
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vendorfair
sudo systemctl status vendorfair
```

## 6. Verify

```bash
curl -is http://<server-ip>:8501 | head -1          # expect: HTTP/1.1 200 OK
curl -fsS http://<server-ip>:8501/_stcore/health    # expect: ok
```

Then open `http://<server-ip>:8501`, log in with **`admin` / `ChangeMe123!`**, and **change the password immediately**.

## 7. Security & operational notes

- **Keep Ollama on localhost.** Only port `8501` should face the network; the Ollama port (`11434`) stays bound to `127.0.0.1`.
- **Never copy** `data/vendorfair.db` or `data/.vendorfair.key` between hosts — that would move encrypted secrets and the key that decrypts them together. Configure keys fresh per deployment.
- Cloud API keys entered in **Settings** are stored encrypted (Fernet) in the database; `.env` keys are an alternative for headless installs.
- Local-fallback research is capped at **Medium** confidence — always have an analyst review before relying on it.

## 8. Upgrade the local research model

The default `llama3.2:1b` is a safety net; its extraction is noticeably rougher than a larger model. To improve quality
(needs ~6 GB RAM):

```bash
ollama pull llama3.2:3b
# set OLLAMA_MODEL=llama3.2:3b in /opt/vendorfair/.env
sudo systemctl restart vendorfair
```

## 9. Updating an existing deployment

```bash
cd /opt/vendorfair
# replace the code (git pull / re-copy), keeping your .env and data/ in place, then:
. .venv/bin/activate
pip install -r requirements.txt        # pick up any new dependencies
python -m pytest tests/                 # optional: confirm green
sudo systemctl restart vendorfair
```
