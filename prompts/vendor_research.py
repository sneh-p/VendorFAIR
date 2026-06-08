"""System and user prompt templates for the vendor research agent."""
import json

RESEARCH_OUTPUT_SCHEMA = json.dumps(
    {
        "vendor_name": "",
        "security_page_url": "",
        "certifications_found": [],
        "breach_history": [],
        "last_known_incident": "",
        "incident_severity": "low|medium|high|unknown",
        "public_trust_posture": "strong|moderate|weak|unknown",
        "evidence_links": [],
        "research_confidence": "high|medium|low",
        "research_summary": "",
        "fair_input_reasoning": {
            "tef": "plain-English reasoning for the TEF range",
            "tc": "plain-English reasoning for the TC range",
            "cs": "plain-English reasoning for the CS range",
            "plm": "plain-English reasoning for the PLM range",
        },
        "recommended_fair_inputs": {
            "tef_min": 0.1,
            "tef_ml": 0.5,
            "tef_max": 2.0,
            "tc_min": 0.3,
            "tc_ml": 0.6,
            "tc_max": 0.85,
            "cs_min": 0.4,
            "cs_ml": 0.65,
            "cs_max": 0.9,
            "plm_min": 10000,
            "plm_ml": 75000,
            "plm_max": 500000,
        },
    },
    indent=2,
)

SYSTEM_PROMPT = """
You are a senior vendor risk analyst with expertise in third-party security assessment.
Your job is to research a vendor's security posture using publicly available information.

You MUST:
- Use the web_search tool to gather real, current evidence before making any claims
- Return ONLY a valid JSON object matching the schema provided — no preamble, no markdown fences
- Recommend FAIR input ranges grounded in your research findings
- Explain your reasoning for each recommended FAIR input in plain English in the
  fair_input_reasoning field
- Express uncertainty clearly in research_confidence and research_summary fields
- Flag if a vendor has NO public security information (this itself is a risk signal)

You MUST NOT:
- Fabricate certifications or breach history
- Return ranges outside the logical FAIR bounds (TEF > 0, TC/CS between 0 and 1)
- Skip the web search step
"""


def build_research_prompt(
    vendor_name,
    website,
    category,
    data_types,
    integration_depth,
    regulatory_context,
):
    return f"""
Research the following vendor for a third-party risk assessment:

Vendor Name: {vendor_name}
Website: {website}
Category: {category}
Data Types Accessed: {', '.join(data_types)}
Integration Depth: {integration_depth}
Regulatory Context: {', '.join(regulatory_context)}

Search for:
1. Security/trust page at {website}
2. "{vendor_name} data breach" OR "{vendor_name} security incident" (last 3 years)
3. "{vendor_name} SOC2" OR "{vendor_name} ISO 27001" certifications
4. "{vendor_name} vulnerability" OR "{vendor_name} CVE" recent findings
5. Any regulatory enforcement actions involving {vendor_name}

Return your findings as a JSON object matching this exact schema:
{RESEARCH_OUTPUT_SCHEMA}
"""
