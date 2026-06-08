"""Local, offline-capable vendor research fallback.

Used when no API key is configured for the selected cloud provider. Instead of
a frontier model with server-side web search, this runs a small agentic pipeline
entirely against local infrastructure:

    DuckDuckGo search (ddgs)  ->  page fetch (requests)  ->  text extraction
    (trafilatura)  ->  per-topic synthesis with a local Ollama model  ->  Python
    merge into the canonical research schema.

Design constraints that shape this module:
- The default model is a 1B parameter model (``llama3.2:1b``). It cannot reason
  over a giant multi-topic prompt, so we make several *small, focused* Ollama
  calls — one per research topic — each asking only for that topic's fields with
  a tight JSON schema and Ollama structured output (``format: "json"``).
- The final merge into the canonical schema (the one in
  ``prompts/vendor_research.py``) happens in plain Python, never via another LLM
  call, so it is deterministic and testable.
- Confidence from a local 1B model is never trustworthy enough to exceed
  "medium"; it is always capped.
- The pipeline must degrade gracefully: a failed search, an unreachable page, a
  malformed Ollama response, DuckDuckGo rate limiting, or the overall time
  budget being exceeded must each fall back to safe defaults for the affected
  topic rather than failing the whole run.

The module is intentionally self-contained; it only borrows the sanitization
helpers from :mod:`modules.ai_researcher` so the FAIR bounds are clamped exactly
the same way as the cloud path.
"""
import json
import logging
import time

import requests

import config
from modules.ai_researcher import FAIR_BOUNDS_DEFAULTS, _extract_json, _sanitize_fair_inputs

logger = logging.getLogger(__name__)

# Network / pipeline tuning ------------------------------------------------
PAGE_FETCH_TIMEOUT = 15           # seconds, per page
PAGE_TEXT_LIMIT = 4000            # chars of extracted text kept per page
RESULTS_PER_TOPIC = 3             # top N search hits fetched per topic
PIPELINE_TIME_BUDGET = 360        # seconds, soft ceiling for the whole run
OLLAMA_TIMEOUT = 120              # seconds, per Ollama generate call
OLLAMA_NUM_CTX = 4096
OLLAMA_TEMPERATURE = 0.2
SEARCH_MAX_RETRIES = 3            # DuckDuckGo rate-limit backoff attempts

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Research topics ----------------------------------------------------------
# Each topic drives exactly one DuckDuckGo query, then one focused Ollama call
# that returns ONLY that topic's fields. Keeping the schemas tiny is essential
# for a 1B model.
TOPICS = [
    {
        "key": "compliance",
        "query": '"{vendor}" SOC 2 OR ISO 27001 certification compliance',
        "schema": {
            "certifications_found": [],
            "security_page_url": "",
            "public_trust_posture": "strong|moderate|weak|unknown",
            "summary": "",
        },
        "instruction": (
            "From the search results below, extract this vendor's security and "
            "compliance certifications (e.g. SOC 2, ISO 27001, PCI DSS, HIPAA, "
            "FedRAMP). List ONLY certifications explicitly mentioned in the text — "
            "never invent any. Capture the vendor's security/trust page URL if one "
            "appears. Judge the public trust posture from the evidence."
        ),
    },
    {
        "key": "breach",
        "query": '"{vendor}" data breach OR security incident',
        "schema": {
            "breach_history": [],
            "last_known_incident": "",
            "incident_severity": "low|medium|high|unknown",
            "summary": "",
        },
        "instruction": (
            "From the search results below, identify any data breaches or security "
            "incidents involving this vendor in the last few years. Each entry in "
            "breach_history should be a one-line description with a year if known. "
            "Set last_known_incident to the most recent one (empty string if none "
            "found). Rate incident_severity overall. If NO incident is mentioned, "
            "return an empty breach_history and incident_severity 'low'."
        ),
    },
    {
        "key": "trust",
        "query": '"{vendor}" security trust center',
        "schema": {
            "security_page_url": "",
            "public_trust_posture": "strong|moderate|weak|unknown",
            "summary": "",
        },
        "instruction": (
            "From the search results below, find the vendor's security trust "
            "center / trust portal URL if one exists, and summarise the overall "
            "public security posture they advertise."
        ),
    },
]

_POSTURE_RANK = {"strong": 3, "moderate": 2, "weak": 1, "unknown": 0}
_SEVERITY_VALUES = {"low", "medium", "high", "unknown"}
_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}


# ---------------------------------------------------------------- Ollama I/O
def ollama_available(base_url: str | None = None, timeout: float = 2.0) -> bool:
    """Return True if an Ollama server answers at ``/api/tags``."""
    base_url = base_url or config.OLLAMA_BASE_URL
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=timeout)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def list_models(base_url: str | None = None, timeout: float = 2.0) -> list[str]:
    """Return the names of models the local Ollama server has pulled."""
    base_url = base_url or config.OLLAMA_BASE_URL
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=timeout)
        resp.raise_for_status()
        return [m.get("name", "") for m in resp.json().get("models", [])]
    except (requests.RequestException, ValueError):
        return []


def test_local_llm(base_url: str | None = None, model: str | None = None) -> dict:
    """Quick health check for the Settings page 'Test local LLM' button.

    Returns a dict describing reachability, installed models, whether the
    configured model is loaded, and the result of a tiny generation — never
    raises, so the UI can render the outcome directly.
    """
    base_url = base_url or config.OLLAMA_BASE_URL
    model = model or config.OLLAMA_MODEL
    started = time.monotonic()
    result = {
        "reachable": False,
        "models": [],
        "model_loaded": False,
        "generation_ok": False,
        "detail": "",
        "elapsed": 0.0,
        "model": model,
        "base_url": base_url,
    }

    if not ollama_available(base_url):
        result["detail"] = f"No Ollama server reachable at {base_url}."
        result["elapsed"] = round(time.monotonic() - started, 2)
        return result

    result["reachable"] = True
    result["models"] = list_models(base_url)
    # Ollama tags include the tag suffix (e.g. "llama3.2:1b"); match loosely.
    result["model_loaded"] = any(
        m == model or m.split(":")[0] == model.split(":")[0] for m in result["models"]
    )

    try:
        text = _ollama_generate(
            "Reply with the single word: ok",
            system="You are a health check. Reply with one word.",
            model=model,
            base_url=base_url,
            as_json=False,
            timeout=30,
        )
        result["generation_ok"] = bool(text.strip())
        result["detail"] = (
            f"Model responded ({text.strip()[:40]})." if result["generation_ok"]
            else "Model returned an empty response."
        )
    except requests.RequestException as exc:
        result["detail"] = f"Generation failed: {exc}"

    result["elapsed"] = round(time.monotonic() - started, 2)
    return result


def _ollama_generate(
    prompt: str,
    system: str,
    model: str,
    base_url: str,
    as_json: bool = True,
    timeout: int = OLLAMA_TIMEOUT,
) -> str:
    """Call Ollama's /api/generate (non-streaming) and return the response text."""
    payload = {
        "model": model,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {"num_ctx": OLLAMA_NUM_CTX, "temperature": OLLAMA_TEMPERATURE},
    }
    if as_json:
        payload["format"] = "json"
    resp = requests.post(
        f"{base_url.rstrip('/')}/api/generate", json=payload, timeout=timeout
    )
    resp.raise_for_status()
    return resp.json().get("response", "")


# ---------------------------------------------------------------- search/scrape
def _search(query: str, max_results: int = RESULTS_PER_TOPIC) -> list[dict]:
    """Run a DuckDuckGo text search with backoff on rate limiting.

    Returns a list of ``{"url", "title", "snippet"}`` dicts (possibly empty).
    Never raises — search failure degrades to no results for that topic.
    """
    from ddgs import DDGS

    delay = 2.0
    for attempt in range(1, SEARCH_MAX_RETRIES + 1):
        try:
            with DDGS() as ddgs:
                hits = list(ddgs.text(query, max_results=max_results))
            results = []
            for h in hits:
                url = h.get("href") or h.get("url") or h.get("link") or ""
                if not url:
                    continue
                results.append({
                    "url": url,
                    "title": h.get("title", ""),
                    "snippet": h.get("body") or h.get("snippet") or "",
                })
            return results
        except Exception as exc:  # noqa: BLE001 — ddgs raises a variety of errors
            msg = str(exc).lower()
            rate_limited = "rate" in msg or "429" in msg or "limit" in msg
            if attempt >= SEARCH_MAX_RETRIES:
                logger.warning("DuckDuckGo search failed for %r: %s", query, exc)
                return []
            wait = delay * attempt if rate_limited else delay
            logger.info(
                "Search attempt %d/%d failed (%s); backing off %.1fs",
                attempt, SEARCH_MAX_RETRIES, exc, wait,
            )
            time.sleep(wait)
    return []


def _fetch_and_extract(url: str) -> str:
    """Fetch a page and return readable text (truncated), or '' on any failure."""
    import trafilatura

    try:
        resp = requests.get(
            url, timeout=PAGE_FETCH_TIMEOUT, headers={"User-Agent": _BROWSER_UA}
        )
        if resp.status_code != 200 or not resp.text:
            return ""
        text = trafilatura.extract(resp.text) or ""
        return text[:PAGE_TEXT_LIMIT]
    except requests.RequestException as exc:
        logger.info("Fetch failed for %s: %s", url, exc)
        return ""
    except Exception as exc:  # noqa: BLE001 — trafilatura can raise on odd input
        logger.info("Extraction failed for %s: %s", url, exc)
        return ""


def _gather_topic_context(topic: dict, vendor_name: str) -> tuple[str, list[str]]:
    """Search + scrape for one topic. Returns (joined_text, source_urls)."""
    query = topic["query"].format(vendor=vendor_name)
    hits = _search(query)
    blocks: list[str] = []
    sources: list[str] = []
    for hit in hits[:RESULTS_PER_TOPIC]:
        text = _fetch_and_extract(hit["url"])
        sources.append(hit["url"])
        body = text or hit.get("snippet", "")
        if body:
            blocks.append(f"SOURCE: {hit['url']}\n{body}")
    return "\n\n---\n\n".join(blocks), sources


# ---------------------------------------------------------------- synthesis
def _topic_defaults(topic: dict) -> dict:
    """Safe default values for a topic whose synthesis failed."""
    defaults = {}
    for field, spec in topic["schema"].items():
        if isinstance(spec, list):
            defaults[field] = []
        elif "unknown" in str(spec):
            defaults[field] = "unknown"
        else:
            defaults[field] = ""
    return defaults


def _build_topic_prompt(topic: dict, vendor_name: str, context: str) -> str:
    schema_str = json.dumps(topic["schema"], indent=2)
    context = context or "(no search results were retrieved)"
    return (
        f"Vendor: {vendor_name}\n\n"
        f"{topic['instruction']}\n\n"
        f"Return ONLY a JSON object with exactly these keys:\n{schema_str}\n\n"
        f"Search results:\n{context}\n"
    )


def _synthesize_topic(topic: dict, vendor_name: str, context: str,
                      model: str, base_url: str) -> dict:
    """One focused Ollama call for a topic, with a single error-correction retry.

    Falls back to this topic's safe defaults (never raising) so one bad topic
    cannot sink the whole pipeline.
    """
    system = (
        "You are a vendor security analyst. You extract facts from search "
        "results and respond with ONLY a valid JSON object matching the "
        "requested schema. Never fabricate certifications or incidents. If the "
        "evidence is missing, use empty values or 'unknown'."
    )
    prompt = _build_topic_prompt(topic, vendor_name, context)

    for attempt in range(2):
        try:
            raw = _ollama_generate(prompt, system, model, base_url)
        except requests.RequestException as exc:
            logger.warning("Ollama call failed for topic %s: %s", topic["key"], exc)
            return _topic_defaults(topic)
        try:
            parsed = _extract_json(raw)
            return _coerce_topic(topic, parsed)
        except (json.JSONDecodeError, ValueError) as exc:
            if attempt == 0:
                logger.info("Invalid JSON for topic %s; retrying once", topic["key"])
                prompt = (
                    f"{prompt}\n\nYour previous reply was not valid JSON "
                    f"({exc}). Respond with ONLY the JSON object, nothing else."
                )
                continue
            logger.warning("Topic %s failed JSON twice; using defaults", topic["key"])
            return _topic_defaults(topic)
    return _topic_defaults(topic)


def _coerce_topic(topic: dict, parsed: dict) -> dict:
    """Coerce a parsed Ollama object to the topic schema's shape/types."""
    out = _topic_defaults(topic)
    for field, spec in topic["schema"].items():
        if field not in parsed:
            continue
        value = parsed[field]
        if isinstance(spec, list):
            if isinstance(value, list):
                out[field] = [str(v).strip() for v in value if str(v).strip()]
            elif value:
                out[field] = [str(value).strip()]
        elif field == "incident_severity":
            sev = str(value).strip().lower()
            out[field] = sev if sev in _SEVERITY_VALUES else "unknown"
        elif field == "public_trust_posture":
            post = str(value).strip().lower()
            out[field] = post if post in _POSTURE_RANK else "unknown"
        else:
            out[field] = str(value).strip()
    return out


# ---------------------------------------------------------------- FAIR derivation
def _derive_fair_inputs(severity: str, posture: str, certifications: list) -> tuple[dict, dict]:
    """Heuristically derive FAIR ranges + reasoning from the qualitative findings.

    A 1B model is not reliable at producing 12 calibrated numbers, so we anchor
    on the project defaults and nudge them by the two qualitative signals we DID
    extract (incident severity and trust posture). The result is still passed
    through the shared sanitizer, so ordering/bounds are guaranteed.
    """
    fair = dict(FAIR_BOUNDS_DEFAULTS)
    has_certs = bool(certifications)

    # Threat Event Frequency / loss magnitude rise with a worse incident history.
    if severity == "high":
        fair["tef_ml"], fair["tef_max"] = 0.9, 3.0
        fair["plm_ml"], fair["plm_max"] = 120_000, 750_000
    elif severity == "medium":
        fair["tef_ml"], fair["tef_max"] = 0.6, 2.2
        fair["plm_ml"], fair["plm_max"] = 90_000, 600_000

    # Control strength rises with strong posture / certifications, falls with weak.
    if posture == "strong" or has_certs:
        fair["cs_min"], fair["cs_ml"], fair["cs_max"] = 0.55, 0.75, 0.95
        fair["tc_max"] = min(fair["tc_max"], 0.75)
    elif posture == "weak":
        fair["cs_min"], fair["cs_ml"], fair["cs_max"] = 0.25, 0.45, 0.7
        fair["tc_ml"], fair["tc_max"] = 0.65, 0.9

    reasoning = {
        "tef": (
            f"Anchored on baseline frequency and adjusted for an incident severity "
            f"signal of '{severity}'. Local-model research cannot fully enumerate "
            f"threat activity, so the range stays wide."
        ),
        "tc": (
            "Threat capability left near baseline; local research surfaces little "
            "attacker-specific intelligence."
        ),
        "cs": (
            f"Control strength reflects a public trust posture of '{posture}'"
            + (f" and {len(certifications)} certification(s) found" if has_certs
               else " with no certifications surfaced")
            + ". Derived heuristically from limited local evidence."
        ),
        "plm": (
            f"Primary loss magnitude scaled to the '{severity}' incident-severity "
            f"signal; treat as a rough prior pending analyst review."
        ),
    }
    return fair, reasoning


# ---------------------------------------------------------------- confidence
def _cap_confidence(confidence: str, ceiling: str = "medium") -> str:
    rank = _CONFIDENCE_RANK
    cap = rank.get(ceiling, 2)
    cur = rank.get(str(confidence).strip().lower(), 1)
    capped = min(cur, cap)
    for name, value in rank.items():
        if value == capped:
            return name
    return "low"


def _best_posture(*postures: str) -> str:
    best = "unknown"
    for p in postures:
        if _POSTURE_RANK.get(p, 0) > _POSTURE_RANK.get(best, 0):
            best = p
    return best


# ---------------------------------------------------------------- merge
def _merge_results(vendor_name: str, topics: dict, sources: list[str]) -> dict:
    """Merge per-topic synthesis dicts into the canonical research schema.

    Pure Python — no LLM involved — so the shape is deterministic and testable.
    """
    compliance = topics.get("compliance", {})
    breach = topics.get("breach", {})
    trust = topics.get("trust", {})

    certifications = list(dict.fromkeys(compliance.get("certifications_found", [])))
    breach_history = breach.get("breach_history", [])
    severity = breach.get("incident_severity", "unknown") or "unknown"
    posture = _best_posture(
        compliance.get("public_trust_posture", "unknown"),
        trust.get("public_trust_posture", "unknown"),
    )
    security_page_url = (
        compliance.get("security_page_url")
        or trust.get("security_page_url")
        or ""
    )
    evidence_links = list(dict.fromkeys(u for u in sources if u))

    # Build a human summary from whatever topic summaries we got.
    summary_parts = [
        s for s in (
            compliance.get("summary"),
            breach.get("summary"),
            trust.get("summary"),
        ) if s
    ]
    if certifications:
        summary_parts.insert(0, f"Certifications found: {', '.join(certifications)}.")
    if not summary_parts:
        summary_parts.append(
            "Local research surfaced little public security information for this "
            "vendor — itself a mild risk signal."
        )
    research_summary = " ".join(summary_parts)

    fair, fair_reasoning = _derive_fair_inputs(severity, posture, certifications)

    # Confidence: medium when we found real evidence, low when we found nothing.
    found_anything = bool(
        certifications or breach_history or security_page_url or evidence_links
    )
    confidence = _cap_confidence("medium" if found_anything else "low")

    merged = {
        "vendor_name": vendor_name,
        "security_page_url": security_page_url,
        "certifications_found": certifications,
        "breach_history": breach_history,
        "last_known_incident": breach.get("last_known_incident", ""),
        "incident_severity": severity if severity in _SEVERITY_VALUES else "unknown",
        "public_trust_posture": posture,
        "evidence_links": evidence_links,
        "research_confidence": confidence,
        "research_summary": research_summary,
        "fair_input_reasoning": fair_reasoning,
        "recommended_fair_inputs": _sanitize_fair_inputs(fair),
        # Provenance — surfaced as a badge in the UI.
        "research_engine": "local",
        "local_model": "",  # filled in by research_vendor_local
    }
    return merged


# ---------------------------------------------------------------- entry point
def research_vendor_local(
    vendor_name,
    website,
    category,
    data_types,
    integration_depth,
    regulatory_context,
    model: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Run the local research pipeline and return the canonical research dict.

    Signature mirrors :func:`modules.ai_researcher.research_vendor` so the
    dispatcher can call either interchangeably. Always returns a valid result —
    individual topic failures degrade to safe defaults rather than raising.
    """
    model = model or config.OLLAMA_MODEL
    base_url = base_url or config.OLLAMA_BASE_URL
    deadline = time.monotonic() + PIPELINE_TIME_BUDGET

    topic_results: dict[str, dict] = {}
    all_sources: list[str] = []

    for topic in TOPICS:
        if time.monotonic() >= deadline:
            logger.warning("Pipeline time budget exhausted before topic %s", topic["key"])
            topic_results[topic["key"]] = _topic_defaults(topic)
            continue
        context, sources = _gather_topic_context(topic, vendor_name)
        all_sources.extend(sources)
        if time.monotonic() >= deadline:
            logger.warning("Time budget exhausted before synthesising %s", topic["key"])
            topic_results[topic["key"]] = _topic_defaults(topic)
            continue
        topic_results[topic["key"]] = _synthesize_topic(
            topic, vendor_name, context, model, base_url
        )

    merged = _merge_results(vendor_name, topic_results, all_sources)
    merged["local_model"] = model
    return merged
