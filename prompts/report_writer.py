"""Prompt templates for AI-written report sections (executive summary, controls)."""

EXEC_SUMMARY_PROMPT = """
Write a 2-3 sentence non-technical executive summary of a vendor risk assessment with these facts:

Vendor: {vendor_name} ({category})
Client tenant: {tenant_name}
Annualized loss exposure (median): ${ale_p50:,.0f}
Risk tier: {risk_tier}
Public trust posture: {public_trust_posture}
Key research finding: {research_summary}

Audience: a client executive with no security background. Plain language, no jargon.
Return only the summary text.
"""

CONTROLS_PROMPT = """
A vendor risk assessment produced the following result:

Vendor: {vendor_name} ({category})
Risk tier: {risk_tier}
Data types accessed: {data_types}
Integration depth: {integration_depth}
Regulatory context: {regulatory_context}
Research summary: {research_summary}

List 4-6 required security controls or contractual clauses appropriate for this
risk tier and regulatory context. Return each on its own line, starting with "- ".
Return only the list.
"""

# Static fallbacks used when no API key is configured.
FALLBACK_CONTROLS = {
    "Low": [
        "- Annual security attestation questionnaire",
        "- Standard data-protection clause in contract",
        "- Notification of material security incidents within 30 days",
    ],
    "Moderate": [
        "- SOC 2 Type II report (or equivalent) reviewed annually",
        "- Breach notification within 72 hours, contractually required",
        "- Data encryption in transit and at rest",
        "- Right-to-audit clause",
    ],
    "High": [
        "- SOC 2 Type II + penetration test summary reviewed before signature",
        "- Breach notification within 24 hours, contractually required",
        "- MFA / SSO enforcement for all vendor access to client systems",
        "- Cyber-liability insurance minimum coverage clause",
        "- Data residency and deletion-on-termination clauses",
    ],
    "Critical": [
        "- Independent security assessment before contract signature",
        "- Continuous monitoring / quarterly review cadence",
        "- Breach notification within 24 hours plus incident-response cooperation clause",
        "- Cyber-liability insurance with minimum coverage matched to P90 exposure",
        "- Escrow / exit plan and verified data destruction on termination",
        "- Executive sign-off required before proceeding (consider Avoid/Transfer)",
    ],
}

RECOMMENDATION_BY_TIER = {
    "Low": "Accept",
    "Moderate": "Accept with mitigations",
    "High": "Mitigate",
    "Critical": "Transfer or Avoid",
}
