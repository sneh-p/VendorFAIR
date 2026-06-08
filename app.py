"""VendorFAIR — Streamlit entry point."""
import json
from datetime import datetime, time
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import config
from database.db import init_db
from modules import audit, auth, risk_register, settings_store, vendor_intake
from modules.fair_calculator import FairInputs, TIER_COLORS, run_simulation
from modules.report_generator import generate_docx, generate_pdf, render_risk_chart

st.set_page_config(page_title=config.APP_TITLE, page_icon="🛡️", layout="wide",
                   initial_sidebar_state="expanded")
init_db()
if auth.seed_default_admin():
    st.session_state["seeded_default_admin"] = True

# ---------------------------------------------------------------- global theme
# Two palettes; the active one is chosen in Settings → Appearance and persisted.
_THEME_PALETTES = {
    "dark": {
        "accent": "#6366F1", "accent_dark": "#4F46E5", "ink": "#E5E7EB",
        "muted": "#94A3B8", "line": "#243049", "surface": "#141C2F",
        "canvas": "#0B1120", "input_bg": "#141C2F",
        "shadow": "0 1px 2px rgba(0,0,0,.35), 0 10px 28px rgba(0,0,0,.45)",
    },
    "light": {
        "accent": "#4F46E5", "accent_dark": "#4338CA", "ink": "#0F172A",
        "muted": "#64748B", "line": "#E2E8F0", "surface": "#FFFFFF",
        "canvas": "#F8FAFC", "input_bg": "#FFFFFF",
        "shadow": "0 1px 2px rgba(15,23,42,.04), 0 8px 24px rgba(15,23,42,.06)",
    },
}

_CSS_BODY = """
html, body, .stApp, [class*="css"] {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}
.stApp { background: var(--vf-canvas); }

/* slim gradient accent bar pinned to the very top */
.vf-topbar {
  position: fixed; top: 0; left: 0; right: 0; height: 4px; z-index: 1000;
  background: linear-gradient(90deg, #4F46E5 0%, #7C3AED 50%, #2563EB 100%);
  pointer-events: none;
}

/* trim Streamlit chrome for an app-like feel (but keep the header so the
   collapsed-sidebar expand control stays available) */
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"] { display: none; }
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 2.4rem; padding-bottom: 3rem; max-width: 1180px; }

/* sidebar stays open — remove the collapse/expand controls entirely */
[data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"],
[data-testid="stExpandSidebarButton"] { display: none !important; }

/* typography */
h1 { font-weight: 800 !important; letter-spacing: -.02em; color: var(--vf-ink); }
h2 { font-weight: 700 !important; letter-spacing: -.01em; color: var(--vf-ink);
     margin-top: 1.4rem !important; }
h3 { font-weight: 600 !important; color: var(--vf-ink); }
[data-testid="stCaptionContainer"] { color: var(--vf-muted); }

/* buttons */
.stButton > button, .stFormSubmitButton > button, .stDownloadButton > button {
  border-radius: 10px; font-weight: 600; padding: .5rem 1.1rem;
  border: 1px solid var(--vf-line); transition: all .15s ease;
}
.stButton > button:hover, .stFormSubmitButton > button:hover,
.stDownloadButton > button:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(79,70,229,.18); border-color: var(--vf-accent);
}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
  background: var(--vf-accent); border-color: var(--vf-accent); color: #fff;
  box-shadow: 0 6px 16px rgba(79,70,229,.25);
}
.stButton > button[kind="primary"]:hover { background: var(--vf-accent-dark); }

/* metrics as cards */
[data-testid="stMetric"] {
  background: var(--vf-surface); border: 1px solid var(--vf-line);
  border-radius: var(--vf-radius); padding: 1rem 1.1rem; box-shadow: var(--vf-shadow);
}
[data-testid="stMetricLabel"] {
  color: var(--vf-muted); font-weight: 600; text-transform: uppercase;
  letter-spacing: .04em; font-size: .72rem;
}
[data-testid="stMetricValue"] { font-weight: 700; color: var(--vf-ink); }

/* text colour + inputs follow the active palette */
[data-testid="stMarkdownContainer"], [data-testid="stWidgetLabel"],
.stRadio label, .stCheckbox label, label, .stApp { color: var(--vf-ink); }
.stTextInput input, .stNumberInput input, .stTextArea textarea,
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="select"] > div {
  background: var(--vf-input-bg) !important; color: var(--vf-ink) !important;
  border-color: var(--vf-line) !important; border-radius: 10px !important;
}
/* dropdown / multiselect popovers (rendered at the document root) */
ul[role="listbox"], [data-baseweb="popover"] [role="listbox"], [data-baseweb="menu"],
ul[role="listbox"] li {
  background: var(--vf-surface) !important; color: var(--vf-ink) !important;
}

/* alerts: softer, rounded, accent rail */
[data-testid="stAlert"] {
  border-radius: 12px; border: 1px solid var(--vf-line);
  box-shadow: var(--vf-shadow);
}

/* expanders */
[data-testid="stExpander"] {
  border: 1px solid var(--vf-line); border-radius: 12px; background: var(--vf-surface);
  box-shadow: var(--vf-shadow); overflow: hidden;
}

/* dataframes / tables */
[data-testid="stDataFrame"], [data-testid="stTable"] {
  border-radius: 12px; overflow: hidden; border: 1px solid var(--vf-line);
}

/* sidebar */
[data-testid="stSidebar"] {
  background: var(--vf-surface); border-right: 1px solid var(--vf-line);
}
[data-testid="stSidebar"] .block-container { padding-top: 1.5rem; }

/* sidebar radio rendered as a vertical nav */
[data-testid="stSidebar"] [role="radiogroup"] { gap: .25rem; }
[data-testid="stSidebar"] [role="radiogroup"] > label {
  display: flex; align-items: center; padding: .5rem .7rem; border-radius: 10px;
  font-weight: 500; cursor: pointer; transition: background .12s ease, color .12s ease;
}
[data-testid="stSidebar"] [role="radiogroup"] > label:hover { background: rgba(99,102,241,.14); }
[data-testid="stSidebar"] [role="radiogroup"] > label:has(input:checked) {
  background: var(--vf-accent); color: #fff;
}
[data-testid="stSidebar"] [role="radiogroup"] > label:has(input:checked) p { color: #fff; }
[data-testid="stSidebar"] [role="radiogroup"] > label > div:first-child { display: none; }

/* VendorFAIR custom components */
.vf-hero {
  background: linear-gradient(135deg, #4F46E5 0%, #6D28D9 100%);
  color: #fff; padding: 1.4rem 1.6rem; border-radius: 16px; margin-bottom: 1.4rem;
  box-shadow: 0 10px 30px rgba(79,70,229,.25);
}
.vf-hero h1 { color: #fff !important; margin: 0; font-size: 1.7rem; }
.vf-hero p { color: rgba(255,255,255,.85); margin: .25rem 0 0; font-size: .95rem; }
.vf-badge {
  display: inline-block; padding: 3px 12px; border-radius: 999px;
  font-size: .75rem; font-weight: 700; letter-spacing: .03em; color: #fff;
}
.vf-brand { display:flex; align-items:center; gap:.55rem; font-weight:800;
  font-size:1.2rem; color:var(--vf-ink); letter-spacing:-.01em; }
.vf-brand .vf-dot { width:30px;height:30px;border-radius:9px;display:grid;
  place-items:center;background:linear-gradient(135deg,#4F46E5,#7C3AED);font-size:1rem; }
"""


def _theme_css(theme: str) -> str:
    """Build the full stylesheet for the chosen palette (dark/light)."""
    p = _THEME_PALETTES.get(theme, _THEME_PALETTES["dark"])
    root = (
        ":root {"
        f"--vf-accent:{p['accent']};--vf-accent-dark:{p['accent_dark']};"
        f"--vf-ink:{p['ink']};--vf-muted:{p['muted']};--vf-line:{p['line']};"
        f"--vf-surface:{p['surface']};--vf-canvas:{p['canvas']};"
        f"--vf-input-bg:{p['input_bg']};--vf-radius:14px;--vf-shadow:{p['shadow']};"
        "}"
    )
    font_import = (
        "@import url('https://fonts.googleapis.com/css2?"
        "family=Inter:wght@400;500;600;700;800&display=swap');"
    )
    return (
        f"<style>{font_import}{root}{_CSS_BODY}</style>"
        "<div class='vf-topbar'></div>"
    )


st.markdown(_theme_css(settings_store.get_ui_theme()), unsafe_allow_html=True)


# ---------------------------------------------------------------- helpers
def fair_results_from_state():
    """Re-run the simulation from FAIR inputs stored in session state."""
    inputs = FairInputs(**st.session_state["fair_inputs"])
    return run_simulation(inputs)


def tier_badge(tier: str) -> str:
    color = TIER_COLORS.get(tier, "#95a5a6")
    return f"<span class='vf-badge' style='background:{color}'>{tier}</span>"


def page_header(title: str, subtitle: str = "") -> None:
    """Render a modern gradient hero header for a page."""
    sub = f"<p>{subtitle}</p>" if subtitle else ""
    st.markdown(
        f"<div class='vf-hero'><h1>{title}</h1>{sub}</div>", unsafe_allow_html=True
    )


# The 15 FAIR PERT input columns shared between assessments and session state
FAIR_FIELDS = [f"{p}_{s}" for p in ("tef", "tc", "cs", "plm", "slm") for s in ("min", "ml", "max")]


def clear_assessment_state():
    """Drop all assessment-scoped session state, including FAIR widget keys."""
    for key in ("assessment_id", "vendor_id", "research", "fair_inputs",
                "has_results", "reeval_from"):
        st.session_state.pop(key, None)
    for field in FAIR_FIELDS:
        st.session_state.pop(field, None)


# ---------------------------------------------------------------- login gate
if "user" not in st.session_state:
    _left, _mid, _right = st.columns([1, 1.15, 1])
    with _mid:
        st.markdown(
            f"<div class='vf-hero' style='text-align:center'>"
            f"<h1>🛡️ {config.APP_TITLE}</h1>"
            f"<p>FAIR-based third-party risk intake &amp; quantification</p></div>",
            unsafe_allow_html=True,
        )
        if st.session_state.get("seeded_default_admin"):
            st.info(
                f"First run: sign in as **{auth.DEFAULT_ADMIN_USERNAME}** / "
                f"`{auth.DEFAULT_ADMIN_PASSWORD}`, then change the password under User Management."
            )
        with st.form("login_form"):
            l_username = st.text_input("Username")
            l_password = st.text_input("Password", type="password")
            if st.form_submit_button("Sign In", use_container_width=True, type="primary"):
                session_user = auth.authenticate(l_username, l_password)
                if session_user:
                    st.session_state["user"] = session_user
                    audit.log_event(session_user["username"], "login_success",
                                    role=session_user["role"])
                    st.rerun()
                else:
                    audit.log_event(l_username or "(blank)", "login_failed")
                    st.error("Invalid username or password.")
    st.stop()

user = st.session_state["user"]


def can(permission: str) -> bool:
    return auth.has_permission(user["role"], permission)


# ---------------------------------------------------------------- sidebar
st.sidebar.markdown(
    f"<div class='vf-brand'><span class='vf-dot'>🛡️</span>{config.APP_TITLE}</div>",
    unsafe_allow_html=True,
)
st.sidebar.caption(f"Signed in as **{user['full_name'] or user['username']}** · {user['role']}")
if st.sidebar.button("🚪 Log out"):
    audit.log_event(user["username"], "logout", role=user["role"])
    st.session_state.clear()
    st.rerun()

tenants = vendor_intake.list_tenants()
tenant_names = {t.name: t.id for t in tenants}
selected_tenant_name = st.sidebar.selectbox("Client Tenant", list(tenant_names))
selected_tenant_id = tenant_names[selected_tenant_name]

# Reset assessment-scoped state when the tenant changes so pages reload dynamically
if st.session_state.get("active_tenant_id") != selected_tenant_id:
    st.session_state["active_tenant_id"] = selected_tenant_id
    st.session_state.pop("register_tenant_filter", None)
    clear_assessment_state()

NAV = [
    ("New Assessment", "new_assessment"),
    ("Risk Register", "view_register"),
    ("Assessment History", "view_history"),
    ("Audit Log", "view_audit"),
    ("User Management", "manage_users"),
    ("Settings", "manage_settings"),
]
# Apply a navigation request from the previous run (must happen before the
# radio is instantiated — widget state can't be modified afterwards).
if pending_nav := st.session_state.pop("pending_nav", None):
    st.session_state["nav"] = pending_nav
page = st.sidebar.radio("Navigate", [name for name, perm in NAV if can(perm)], key="nav")

active_provider = settings_store.get_ai_provider()
ai_key_available = bool(settings_store.get_api_key(active_provider))
# When no cloud key is set, AI research falls back to the local Ollama pipeline.
local_research_ready = False
if not ai_key_available:
    from modules import local_researcher

    local_research_ready = local_researcher.ollama_available()
    if local_research_ready:
        st.sidebar.info(
            f"No API key for {settings_store.PROVIDERS[active_provider]} — AI "
            f"research will use the local LLM fallback ({config.OLLAMA_MODEL})."
        )
    else:
        st.sidebar.warning(
            f"No API key configured for {settings_store.PROVIDERS[active_provider]} "
            f"and no local LLM reachable at {config.OLLAMA_BASE_URL} — AI research "
            "is disabled. Set a key under Settings or start Ollama."
        )


# ---------------------------------------------------------------- New Assessment
if page == "New Assessment":
    page_header("New Vendor Assessment",
                "Intake → AI research → FAIR quantification → report, in five guided steps.")

    # ---- Step 1: intake form
    st.header("Step 1 — Vendor Intake")
    with st.form("intake_form"):
        col1, col2 = st.columns(2)
        with col1:
            v_name = st.text_input("Vendor name *")
            v_website = st.text_input("Website", placeholder="https://vendor.example.com")
            v_category = st.selectbox("Category", vendor_intake.VENDOR_CATEGORIES)
            v_contract = st.selectbox("Contract status", vendor_intake.CONTRACT_STATUSES)
        with col2:
            v_data_types = st.multiselect("Data types accessed", vendor_intake.DATA_TYPES)
            v_integration = st.selectbox("Integration depth", vendor_intake.INTEGRATION_DEPTHS)
            v_regulatory = st.multiselect("Regulatory context", vendor_intake.REGULATORY_OPTIONS)
            v_assessor = st.text_input("Assessor", value=user["full_name"] or user["username"])
        submitted = st.form_submit_button("Save Intake")

    if submitted:
        if not v_name.strip():
            st.error("Vendor name is required.")
        else:
            vendor_id, assessment_id = vendor_intake.save_vendor_intake(
                tenant_id=selected_tenant_id,
                name=v_name,
                website=v_website,
                category=v_category,
                contract_status=v_contract,
                data_types=v_data_types,
                integration_depth=v_integration,
                regulatory_context=v_regulatory,
                assessor=v_assessor,
            )
            st.session_state["assessment_id"] = assessment_id
            st.session_state["vendor_id"] = vendor_id
            st.session_state.pop("research", None)
            st.session_state["fair_inputs"] = {
                k: getattr(FairInputs(), k) for k in FairInputs.__dataclass_fields__
            }
            audit.log_event(user["username"], "intake_saved", role=user["role"],
                            entity_type="assessment", entity_id=assessment_id,
                            tenant_id=selected_tenant_id, details={"vendor": v_name})
            st.success(f"Saved intake for {v_name} (assessment #{assessment_id}).")

    if "assessment_id" not in st.session_state:
        st.info("Save the intake form to continue.")
        st.stop()

    assessment = vendor_intake.get_assessment(st.session_state["assessment_id"])

    reeval = st.session_state.get("reeval_from")
    if reeval and reeval.get("assessment_id") == assessment.id:
        st.info(
            f"🔄 Re-evaluating **{assessment.vendor.name}** — intake and FAIR inputs "
            f"pre-filled from assessment #{reeval['previous_id']} "
            f"({reeval['previous_date']}, tier: {reeval['previous_tier']}). "
            f"Steps 2–5 below run against new assessment #{assessment.id}."
        )

    # ---- Step 2: AI research
    st.header("Step 2 — Auto-Research Vendor")
    if ai_key_available:
        st.caption(f"Provider: {settings_store.PROVIDERS[active_provider]} "
                   f"({settings_store.get_ai_model(active_provider)})")
        spinner_msg = "Researching vendor security posture (web search)…"
    else:
        st.caption(f"No API key for {settings_store.PROVIDERS[active_provider]} — "
                   f"using local LLM fallback ({config.OLLAMA_MODEL}). Slower; "
                   "confidence is capped at Medium.")
        spinner_msg = ("Researching locally (DuckDuckGo + Ollama) — this can take "
                       "several minutes on CPU…")
    research_enabled = ai_key_available or local_research_ready
    if st.button("🔍 Auto-Research Vendor", disabled=not research_enabled, type="primary"):
        from modules.ai_researcher import research_vendor

        with st.spinner(spinner_msg):
            try:
                research = research_vendor(
                    vendor_name=assessment.vendor.name,
                    website=assessment.vendor.website,
                    category=assessment.vendor.category,
                    data_types=[s.strip() for s in assessment.data_types_accessed.split(",") if s.strip()],
                    integration_depth=assessment.integration_depth,
                    regulatory_context=[s.strip() for s in assessment.regulatory_context.split(",") if s.strip()],
                )
                st.session_state["research"] = research
                vendor_intake.update_assessment_research(
                    assessment.id, research, json.dumps(research, indent=2)
                )
                # Pre-populate FAIR inputs from the recommendation
                for k, v in research["recommended_fair_inputs"].items():
                    if k in st.session_state["fair_inputs"]:
                        st.session_state["fair_inputs"][k] = float(v)
                audit.log_event(user["username"], "research_run", role=user["role"],
                                entity_type="assessment", entity_id=assessment.id,
                                tenant_id=selected_tenant_id,
                                details={"vendor": assessment.vendor.name})
                st.success("Research complete — FAIR inputs pre-populated below.")
            except Exception as exc:  # noqa: BLE001 — surface any API failure to the UI
                st.error(f"Research failed: {exc}")

    if research := st.session_state.get("research"):
        if research.get("research_engine") == "local":
            st.info(
                f"🖥️ Researched via Local LLM ({research.get('local_model', 'local')}) "
                "— confidence capped at Medium. Review findings before relying on them."
            )
        col1, col2, col3 = st.columns(3)
        col1.metric("Trust posture", research.get("public_trust_posture", "unknown"))
        col2.metric("Incident severity", research.get("incident_severity", "unknown"))
        col3.metric("Research confidence", research.get("research_confidence", "unknown"))
        st.write(research.get("research_summary", ""))
        with st.expander("FAIR input reasoning"):
            for param, reasoning in (research.get("fair_input_reasoning") or {}).items():
                st.markdown(f"**{param.upper()}** — {reasoning}")
        with st.expander("Full research JSON"):
            st.json(research)

    # ---- Step 3: FAIR inputs
    st.header("Step 3 — FAIR Inputs")
    fi = st.session_state.setdefault(
        "fair_inputs", {k: getattr(FairInputs(), k) for k in FairInputs.__dataclass_fields__}
    )

    def triple(label, prefix, fmt="%.3f", step=0.01):
        c1, c2, c3 = st.columns(3)
        fi[f"{prefix}_min"] = c1.number_input(f"{label} min", value=float(fi[f"{prefix}_min"]), format=fmt, step=step, key=f"{prefix}_min")
        fi[f"{prefix}_ml"] = c2.number_input(f"{label} most likely", value=float(fi[f"{prefix}_ml"]), format=fmt, step=step, key=f"{prefix}_ml")
        fi[f"{prefix}_max"] = c3.number_input(f"{label} max", value=float(fi[f"{prefix}_max"]), format=fmt, step=step, key=f"{prefix}_max")

    triple("TEF — Threat Event Frequency (events/yr)", "tef")
    triple("TC — Threat Capability (0–1)", "tc")
    triple("CS — Control Strength (0–1)", "cs")
    triple("PLM — Primary Loss Magnitude ($)", "plm", fmt="%.0f", step=1000.0)
    triple("SLM — Secondary Loss Magnitude ($)", "slm", fmt="%.0f", step=1000.0)

    # ---- Step 4: simulation
    st.header("Step 4 — Run Simulation")
    if st.button("▶️ Run Monte Carlo Simulation", type="primary"):
        try:
            results = run_simulation(FairInputs(**fi))
            st.session_state["has_results"] = True
            vendor_intake.update_assessment_fair(
                assessment.id, fi, results.percentiles, results.risk_tier
            )
            audit.log_event(user["username"], "simulation_run", role=user["role"],
                            entity_type="assessment", entity_id=assessment.id,
                            tenant_id=selected_tenant_id,
                            details={"risk_tier": results.risk_tier,
                                     "ale_p50": round(results.p50)})

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("ALE P10", f"${results.p10:,.0f}")
            c2.metric("ALE P50", f"${results.p50:,.0f}")
            c3.metric("ALE P90", f"${results.p90:,.0f}")
            c4.markdown(f"### {tier_badge(results.risk_tier)}", unsafe_allow_html=True)

            fig = px.histogram(
                x=results.ale_samples, nbins=60,
                labels={"x": "Annualized Loss Exposure ($)"},
                title=f"Simulated Annual Loss Distribution ({len(results.ale_samples):,} iterations)",
            )
            for label, value, color in (("P10", results.p10, "green"), ("P50", results.p50, "orange"), ("P90", results.p90, "red")):
                fig.add_vline(x=value, line_dash="dash", line_color=color, annotation_text=f"{label}: ${value:,.0f}")
            st.plotly_chart(fig, use_container_width=True)

            # Confidence interval visualization
            ci = go.Figure()
            ci.add_trace(go.Scatter(
                x=[results.p10, results.p50, results.p90], y=["ALE"] * 3,
                mode="markers+lines", marker=dict(size=[10, 16, 10], color=["green", "orange", "red"]),
            ))
            ci.update_layout(title="80% Confidence Interval (P10 – P90)", height=180, xaxis_title="$ / year")
            st.plotly_chart(ci, use_container_width=True)
        except ValueError as exc:
            st.error(f"Invalid FAIR inputs: {exc}")

    # ---- Step 5: report
    st.header("Step 5 — Generate Report")
    if not st.session_state.get("has_results"):
        st.info("Run the simulation first.")
    else:
        assessment = vendor_intake.get_assessment(st.session_state["assessment_id"])
        results = fair_results_from_state()
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📄 Generate DOCX"):
                with st.spinner("Building DOCX memo…"):
                    path = generate_docx(assessment.vendor, assessment.vendor.tenant, assessment, results)
                audit.log_event(user["username"], "report_generated", role=user["role"],
                                entity_type="assessment", entity_id=assessment.id,
                                tenant_id=selected_tenant_id,
                                details={"format": "docx", "file": Path(path).name})
                st.download_button("⬇️ Download DOCX", data=Path(path).read_bytes(),
                                   file_name=Path(path).name,
                                   mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        with col2:
            if st.button("📕 Generate PDF"):
                with st.spinner("Building PDF memo…"):
                    path = generate_pdf(assessment.vendor, assessment.vendor.tenant, assessment, results)
                audit.log_event(user["username"], "report_generated", role=user["role"],
                                entity_type="assessment", entity_id=assessment.id,
                                tenant_id=selected_tenant_id,
                                details={"format": "pdf", "file": Path(path).name})
                st.download_button("⬇️ Download PDF", data=Path(path).read_bytes(),
                                   file_name=Path(path).name, mime="application/pdf")


# ---------------------------------------------------------------- Risk Register
elif page == "Risk Register":
    page_header("Vendor Risk Register",
                "Portfolio view of assessed vendors with risk tiers, exposure, and trends.")

    fcol1, fcol2, fcol3, fcol4 = st.columns(4)
    tenant_options = ["All"] + list(tenant_names)
    f_tenant = fcol1.selectbox(
        "Tenant filter", tenant_options,
        index=tenant_options.index(selected_tenant_name),
        key="register_tenant_filter",
    )
    f_tiers = fcol2.multiselect("Risk tier", ["Low", "Moderate", "High", "Critical"])
    f_contract = fcol3.multiselect("Contract status", vendor_intake.CONTRACT_STATUSES)
    f_certified = fcol4.checkbox("Certified vendors only")
    f_latest = fcol4.checkbox("Latest assessment per vendor", value=True)

    df = risk_register.load_register(
        tenant_id=None if f_tenant == "All" else tenant_names[f_tenant],
        risk_tiers=f_tiers or None,
        contract_statuses=f_contract or None,
        certified_only=f_certified,
        latest_only=f_latest,
    )

    if df.empty:
        st.info("No assessments match the current filters.")
    else:
        def color_tier(val):
            return f"background-color: {risk_register.tier_color(val)}; color: white" if val in TIER_COLORS else ""

        st.dataframe(
            df.style.map(color_tier, subset=["Risk Tier"]),
            use_container_width=True, hide_index=True,
        )
        if can("export_register"):
            col1, col2 = st.columns(2)
            if col1.download_button("⬇️ Export CSV", risk_register.export_csv(df),
                                    "vendorfair_register.csv", "text/csv"):
                audit.log_event(user["username"], "register_exported", role=user["role"],
                                details={"format": "csv", "rows": len(df), "tenant_filter": f_tenant})
            if col2.download_button("⬇️ Export XLSX", risk_register.export_xlsx(df),
                                    "vendorfair_register.xlsx",
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"):
                audit.log_event(user["username"], "register_exported", role=user["role"],
                                details={"format": "xlsx", "rows": len(df), "tenant_filter": f_tenant})

    # ---- Re-evaluate an existing vendor
    if can("new_assessment"):
        st.divider()
        st.subheader("🔄 Re-evaluate a Vendor")
        st.caption(
            "Starts a fresh assessment for the vendor, pre-filled with its previous "
            "intake and FAIR inputs. The prior assessment is kept for the risk trend."
        )
        reeval_vendors = risk_register.list_vendors(
            None if f_tenant == "All" else tenant_names[f_tenant]
        )
        if not reeval_vendors:
            st.caption("No vendors available to re-evaluate.")
        else:
            tenant_by_id = {tid: name for name, tid in tenant_names.items()}
            vendor_labels = {
                f"{v.name} ({tenant_by_id.get(v.tenant_id, '?')})": v for v in reeval_vendors
            }
            rcol1, rcol2 = st.columns([3, 1])
            sel_label = rcol1.selectbox("Vendor", list(vendor_labels))
            rcol2.write("")  # vertical alignment with the selectbox
            if rcol2.button("Start Re-evaluation"):
                vendor = vendor_labels[sel_label]
                previous = vendor_intake.get_latest_assessment(vendor.id)
                try:
                    new_id = vendor_intake.create_reassessment(
                        vendor.id, assessor=user["full_name"] or user["username"]
                    )
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    new_assessment = vendor_intake.get_assessment(new_id)
                    clear_assessment_state()
                    st.session_state["assessment_id"] = new_id
                    st.session_state["vendor_id"] = vendor.id
                    fi = {k: getattr(FairInputs(), k) for k in FairInputs.__dataclass_fields__}
                    for field in FAIR_FIELDS:
                        fi[field] = float(getattr(new_assessment, field))
                    st.session_state["fair_inputs"] = fi
                    st.session_state["reeval_from"] = {
                        "assessment_id": new_id,
                        "previous_id": previous.id,
                        "previous_date": previous.updated_at.date().isoformat(),
                        "previous_tier": previous.risk_tier or "—",
                    }
                    audit.log_event(
                        user["username"], "reassessment_started", role=user["role"],
                        entity_type="assessment", entity_id=new_id,
                        tenant_id=vendor.tenant_id,
                        details={"vendor": vendor.name,
                                 "previous_assessment_id": previous.id},
                    )
                    st.session_state["pending_nav"] = "New Assessment"
                    st.rerun()


# ---------------------------------------------------------------- History
elif page == "Assessment History":
    page_header("Assessment History",
                "Risk-tier and exposure trends across vendor reassessments.")
    vendors = risk_register.list_vendors(selected_tenant_id)
    if not vendors:
        st.info("No vendors for this tenant yet.")
    else:
        vendor_map = {v.name: v.id for v in vendors}
        sel = st.selectbox("Vendor", list(vendor_map))
        trend = risk_register.load_trend(vendor_map[sel])
        if trend.empty:
            st.info("No completed assessments for this vendor yet.")
        else:
            fig = px.line(trend, x="Date", y="ALE P50 ($)", markers=True,
                          title=f"Risk trend — {sel}")
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(trend, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------- Audit Log
elif page == "Audit Log":
    page_header("Audit Log", "Immutable record of user and system actions.")

    fcol1, fcol2, fcol3, fcol4 = st.columns(4)
    a_user = fcol1.selectbox("User", ["All"] + [u.username for u in auth.list_users()])
    a_action = fcol2.selectbox("Action", ["All"] + audit.list_actions())
    a_start = fcol3.date_input("From", value=None)
    a_end = fcol4.date_input("To", value=None)

    df = audit.load_audit(
        start=datetime.combine(a_start, time.min) if a_start else None,
        end=datetime.combine(a_end, time.max) if a_end else None,
        username=None if a_user == "All" else a_user,
        action=None if a_action == "All" else a_action,
    )

    if df.empty:
        st.info("No audit events match the current filters.")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.download_button("⬇️ Export CSV", audit.export_csv(df),
                           "vendorfair_audit_log.csv", "text/csv")


# ---------------------------------------------------------------- User Management
elif page == "User Management":
    page_header("User Management", "Accounts, roles, and access control.")

    if flash := st.session_state.pop("user_flash", None):
        st.success(flash)

    with st.expander("Role / feature matrix"):
        matrix = pd.DataFrame(
            [[("✅" if auth.has_permission(role, perm) else "—") for role in auth.ROLES]
             for perm in auth.PERMISSIONS],
            index=[auth.PERMISSIONS[p] for p in auth.PERMISSIONS],
            columns=auth.ROLES,
        )
        st.dataframe(matrix, use_container_width=True)

    users = auth.list_users()
    st.header("Users")
    st.dataframe(pd.DataFrame([{
        "Username": u.username, "Full name": u.full_name, "Email": u.email,
        "Role": u.role, "Active": "✅" if u.is_active else "❌",
        "Last login (UTC)": u.last_login,
    } for u in users]), use_container_width=True, hide_index=True)

    st.header("Create User")
    with st.form("create_user_form"):
        col1, col2 = st.columns(2)
        with col1:
            nu_username = st.text_input("Username *")
            nu_fullname = st.text_input("Full name")
            nu_email = st.text_input("Email")
        with col2:
            nu_role = st.selectbox("Role", auth.ROLES,
                                   help="\n\n".join(f"**{r}** — {d}" for r, d in auth.ROLE_DESCRIPTIONS.items()))
            nu_password = st.text_input("Temporary password * (min 8 chars)", type="password")
        if st.form_submit_button("Create User"):
            try:
                new_id = auth.create_user(nu_username, nu_password, nu_role,
                                          full_name=nu_fullname, email=nu_email)
                audit.log_event(user["username"], "user_created", role=user["role"],
                                entity_type="user", entity_id=new_id,
                                details={"username": nu_username, "role": nu_role})
                st.session_state["user_flash"] = f"User '{nu_username}' created."
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    st.header("Manage Existing User")
    target_name = st.selectbox("User", [u.username for u in users])
    target = next(u for u in users if u.username == target_name)
    mcol1, mcol2, mcol3 = st.columns(3)

    with mcol1:
        new_role = st.selectbox("Role", auth.ROLES, index=auth.ROLES.index(target.role),
                                key="manage_role")
        if st.button("Update Role"):
            try:
                auth.set_user_role(target_name, new_role)
                audit.log_event(user["username"], "user_role_changed", role=user["role"],
                                entity_type="user", entity_id=target.id,
                                details={"username": target_name,
                                         "from": target.role, "to": new_role})
                st.session_state["user_flash"] = f"Role for '{target_name}' set to {new_role}."
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    with mcol2:
        st.write("")  # vertical alignment
        toggle_label = "Deactivate" if target.is_active else "Activate"
        if st.button(f"{toggle_label} Account"):
            if target_name == user["username"]:
                st.error("You cannot deactivate your own account.")
            else:
                try:
                    auth.set_user_active(target_name, not target.is_active)
                    audit.log_event(user["username"], "user_active_changed", role=user["role"],
                                    entity_type="user", entity_id=target.id,
                                    details={"username": target_name,
                                             "active": not target.is_active})
                    st.session_state["user_flash"] = f"Account '{target_name}' {toggle_label.lower()}d."
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

    with mcol3:
        new_pw = st.text_input("New password (min 8 chars)", type="password", key="reset_pw")
        if st.button("Reset Password"):
            try:
                auth.reset_password(target_name, new_pw)
                audit.log_event(user["username"], "password_reset", role=user["role"],
                                entity_type="user", entity_id=target.id,
                                details={"username": target_name})
                st.session_state["user_flash"] = f"Password reset for '{target_name}'."
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


# ---------------------------------------------------------------- Settings
elif page == "Settings":
    page_header("Settings",
                "Appearance, organization branding, AI research providers, and data controls.")

    st.header("Appearance")
    _current_theme = settings_store.get_ui_theme()
    _theme_labels = {"dark": "🌙 Dark", "light": "☀️ Light"}
    _theme_choice = st.radio(
        "Theme", ["dark", "light"],
        index=0 if _current_theme == "dark" else 1,
        format_func=lambda t: _theme_labels[t], horizontal=True,
        help="Applies to the whole app for all users; saved instantly.",
    )
    if _theme_choice != _current_theme:
        settings_store.set_ui_theme(_theme_choice)
        audit.log_event(user["username"], "ui_theme_updated", role=user["role"],
                        details={"theme": _theme_choice})
        st.rerun()

    st.header("Tenants")
    if flash := st.session_state.pop("tenant_flash", None):
        st.success(flash)
    with st.form("tenant_form"):
        t_name = st.text_input("New tenant name")
        t_desc = st.text_input("Description")
        if st.form_submit_button("Add Tenant") and t_name.strip():
            try:
                vendor_intake.create_tenant(t_name, t_desc)
                audit.log_event(user["username"], "tenant_created", role=user["role"],
                                entity_type="tenant", details={"name": t_name})
                st.session_state["tenant_flash"] = f"Tenant '{t_name}' created."
                st.rerun()
            except Exception as exc:  # noqa: BLE001 — duplicate names etc.
                st.error(f"Could not create tenant: {exc}")

    st.header("Organization")
    st.text_input("Org name (set via ORG_NAME in .env)", value=config.ORG_NAME, disabled=True)
    logo = st.file_uploader("Upload report logo (PNG)", type=["png"])
    if logo:
        logo_path = Path(__file__).parent / "assets" / "logo.png"
        logo_path.parent.mkdir(exist_ok=True)
        logo_path.write_bytes(logo.read())
        audit.log_event(user["username"], "logo_updated", role=user["role"],
                        details={"file": logo.name})
        st.success("Logo saved to assets/logo.png")

    st.header("AI Research Provider")
    if flash := st.session_state.pop("ai_flash", None):
        st.success(flash)

    provider_ids = list(settings_store.PROVIDERS)
    sel_provider = st.selectbox(
        "Provider", provider_ids,
        format_func=lambda p: settings_store.PROVIDERS[p],
        index=provider_ids.index(settings_store.get_ai_provider()),
    )
    sel_model = st.text_input(
        "Model", value=settings_store.get_ai_model(sel_provider),
        help=f"Default: {settings_store.DEFAULT_MODELS[sel_provider]}",
    )
    st.text_input(
        "Current API key", value=settings_store.api_key_hint(sel_provider), disabled=True,
        help="Keys are stored encrypted (Fernet) in the database; the encryption key "
             "lives in data/.vendorfair.key with 0600 permissions. Keys are never displayed.",
    )
    new_key = st.text_input(f"New {settings_store.PROVIDERS[sel_provider]} API key",
                            type="password", placeholder="paste key to replace")
    acol1, acol2 = st.columns(2)
    with acol1:
        if st.button("💾 Save Provider Settings"):
            settings_store.set_ai_provider(sel_provider)
            settings_store.set_ai_model(sel_provider, sel_model or settings_store.DEFAULT_MODELS[sel_provider])
            details = {"provider": sel_provider, "model": sel_model}
            if new_key.strip():
                settings_store.set_api_key(sel_provider, new_key)
                audit.log_event(user["username"], "api_key_updated", role=user["role"],
                                details={"provider": sel_provider})
                details["api_key"] = "updated"
            audit.log_event(user["username"], "ai_provider_updated", role=user["role"],
                            details=details)
            st.session_state["ai_flash"] = f"AI provider set to {settings_store.PROVIDERS[sel_provider]}."
            st.rerun()
    with acol2:
        if st.button("🗑️ Clear Stored API Key"):
            settings_store.clear_api_key(sel_provider)
            audit.log_event(user["username"], "api_key_cleared", role=user["role"],
                            details={"provider": sel_provider})
            st.session_state["ai_flash"] = f"Stored API key for {settings_store.PROVIDERS[sel_provider]} cleared."
            st.rerun()

    st.header("Local LLM Fallback")
    st.caption(
        "When no API key is configured for the selected provider, VendorFAIR "
        "researches vendors locally with DuckDuckGo + an Ollama model "
        f"(`{config.OLLAMA_MODEL}` at `{config.OLLAMA_BASE_URL}`). Confidence is "
        "always capped at Medium for local research."
    )
    from modules import local_researcher

    if local_researcher.ollama_available():
        models = local_researcher.list_models()
        loaded = any(
            m == config.OLLAMA_MODEL or m.split(":")[0] == config.OLLAMA_MODEL.split(":")[0]
            for m in models
        )
        st.success(f"Ollama reachable at {config.OLLAMA_BASE_URL}.")
        if loaded:
            st.caption(f"Configured model `{config.OLLAMA_MODEL}` is installed.")
        else:
            st.warning(
                f"Configured model `{config.OLLAMA_MODEL}` is NOT installed. "
                f"Installed: {', '.join(models) or 'none'}. Run "
                f"`ollama pull {config.OLLAMA_MODEL}`."
            )
    else:
        st.warning(f"No Ollama server reachable at {config.OLLAMA_BASE_URL}.")

    if st.button("🧪 Test local LLM"):
        with st.spinner("Pinging local Ollama model…"):
            check = local_researcher.test_local_llm()
        if check["generation_ok"]:
            st.success(
                f"Local LLM OK — model `{check['model']}` responded in "
                f"{check['elapsed']}s. {check['detail']}"
            )
        elif check["reachable"]:
            st.error(
                f"Ollama is reachable but the test generation failed. {check['detail']} "
                f"Installed models: {', '.join(check['models']) or 'none'}."
            )
        else:
            st.error(check["detail"])

    st.header("⚠️ Reset Data")
    st.caption(
        "Permanently deletes vendors, assessments, and history snapshots. "
        "Tenants, user accounts, settings, and the audit log are preserved."
    )
    reset_scope = st.radio(
        "Scope", [f"Current tenant only ({selected_tenant_name})", "All tenants"],
        key="reset_scope",
    )
    reset_confirm = st.text_input("Type RESET to confirm", key="reset_confirm")
    if st.button("🗑️ Delete Assessment Data"):
        if reset_confirm.strip() != "RESET":
            st.error("Confirmation text does not match. Type RESET to proceed.")
        else:
            all_tenants = reset_scope == "All tenants"
            counts = vendor_intake.reset_data(None if all_tenants else selected_tenant_id)
            audit.log_event(user["username"], "data_reset", role=user["role"],
                            tenant_id=None if all_tenants else selected_tenant_id,
                            details={**counts, "scope": "all" if all_tenants else selected_tenant_name})
            clear_assessment_state()
            st.success(
                f"Deleted {counts['vendors']} vendors, {counts['assessments']} assessments, "
                f"and {counts['history']} history snapshots."
            )
