"""AI vendor research agent with web search.

Supports three providers, each using its native server-side web search:
- anthropic — Claude via the Anthropic SDK (web_search tool)
- gemini    — Google Gemini via google-genai (google_search grounding)
- openai    — OpenAI ChatGPT via the Responses API (web_search tool)
"""
import json
import logging
import re

import anthropic

from modules import settings_store
from prompts.vendor_research import SYSTEM_PROMPT, build_research_prompt

logger = logging.getLogger(__name__)

MAX_CONTINUATIONS = 5

FAIR_BOUNDS_DEFAULTS = {
    "tef_min": 0.1, "tef_ml": 0.5, "tef_max": 2.0,
    "tc_min": 0.3, "tc_ml": 0.6, "tc_max": 0.85,
    "cs_min": 0.4, "cs_ml": 0.65, "cs_max": 0.9,
    "plm_min": 10_000, "plm_ml": 75_000, "plm_max": 500_000,
}


def _extract_json(raw: str) -> dict:
    """Parse the model output into JSON, tolerating markdown fences / preamble."""
    raw = raw.strip()
    # Strip markdown fences if present
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Fall back to the first {...} block in the text
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def _sanitize_fair_inputs(inputs: dict) -> dict:
    """Clamp recommended FAIR inputs to logical bounds and ensure ordering."""
    clean = dict(FAIR_BOUNDS_DEFAULTS)
    for key, default in FAIR_BOUNDS_DEFAULTS.items():
        try:
            clean[key] = float(inputs.get(key, default))
        except (TypeError, ValueError):
            clean[key] = float(default)

    # TEF must be > 0
    for k in ("tef_min", "tef_ml", "tef_max"):
        clean[k] = max(clean[k], 0.001)
    # TC / CS within [0, 1]
    for prefix in ("tc", "cs"):
        for suffix in ("min", "ml", "max"):
            clean[f"{prefix}_{suffix}"] = min(max(clean[f"{prefix}_{suffix}"], 0.0), 1.0)
    # PLM must be >= 0
    for k in ("plm_min", "plm_ml", "plm_max"):
        clean[k] = max(clean[k], 0.0)

    # Enforce min <= ml <= max per parameter
    for prefix in ("tef", "tc", "cs", "plm"):
        lo, ml, hi = sorted(
            [clean[f"{prefix}_min"], clean[f"{prefix}_ml"], clean[f"{prefix}_max"]]
        )
        clean[f"{prefix}_min"], clean[f"{prefix}_ml"], clean[f"{prefix}_max"] = lo, ml, hi

    return clean


def research_vendor(
    vendor_name,
    website,
    category,
    data_types,
    integration_depth,
    regulatory_context,
    client: anthropic.Anthropic | None = None,
    provider: str | None = None,
) -> dict:
    """Run AI-powered vendor research and return the structured result.

    Uses the provider configured in Settings unless `provider` (or an explicit
    Anthropic `client`) is given. Raises the provider SDK's error on API
    failure and ValueError on empty/unparseable output.
    """
    explicit = client is not None or provider is not None
    if client is not None:
        provider = "anthropic"  # an injected Anthropic client pins the provider
    provider = provider or settings_store.get_ai_provider()

    # Local fallback: on the normal app path (provider resolved from settings,
    # no injected client) with no API key available anywhere, route to the local
    # Ollama pipeline instead of failing. An explicitly requested provider/client
    # always uses that provider — behaviour is unchanged when a key exists.
    if not explicit and not settings_store.get_api_key(provider):
        from modules.local_researcher import research_vendor_local

        logger.info("No API key for %s; using local research fallback", provider)
        return research_vendor_local(
            vendor_name, website, category, data_types,
            integration_depth, regulatory_context,
        )

    prompt_text = build_research_prompt(
        vendor_name, website, category, data_types, integration_depth, regulatory_context
    )

    if provider == "anthropic":
        raw = _research_anthropic(prompt_text, client)
    elif provider == "gemini":
        raw = _research_gemini(prompt_text)
    elif provider == "openai":
        raw = _research_openai(prompt_text)
    else:
        raise ValueError(f"Unknown AI provider: {provider}")

    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Model returned no text output")

    result = _extract_json(raw)
    result.setdefault("vendor_name", vendor_name)
    result["recommended_fair_inputs"] = _sanitize_fair_inputs(
        result.get("recommended_fair_inputs", {})
    )
    result.setdefault("research_engine", provider)
    return result


# ---------------------------------------------------------------- providers
def _research_anthropic(prompt_text: str, client: anthropic.Anthropic | None) -> str:
    client = client or anthropic.Anthropic(api_key=settings_store.get_api_key("anthropic"))
    model = settings_store.get_ai_model("anthropic")

    messages = [{"role": "user", "content": prompt_text}]
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 8}]

    response = client.messages.create(
        model=model,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        tools=tools,
        messages=messages,
    )

    # Server-side web search may pause; re-send to let the server resume.
    continuations = 0
    while response.stop_reason == "pause_turn" and continuations < MAX_CONTINUATIONS:
        messages = [
            {"role": "user", "content": prompt_text},
            {"role": "assistant", "content": response.content},
        ]
        response = client.messages.create(
            model=model,
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        )
        continuations += 1

    return "".join(b.text for b in response.content if b.type == "text")


def _research_gemini(prompt_text: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings_store.get_api_key("gemini"))
    response = client.models.generate_content(
        model=settings_store.get_ai_model("gemini"),
        contents=prompt_text,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        ),
    )
    return response.text or ""


def _research_openai(prompt_text: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=settings_store.get_api_key("openai"))
    response = client.responses.create(
        model=settings_store.get_ai_model("openai"),
        instructions=SYSTEM_PROMPT,
        input=prompt_text,
        tools=[{"type": "web_search"}],
    )
    return response.output_text or ""
