"""Mock tests for the local (Ollama) research fallback — no live network calls.

Every external boundary (DuckDuckGo search, page fetch, Ollama generation) is
mocked, so these tests run offline and deterministically.
"""
import json

import pytest

from modules import local_researcher as lr
from prompts.vendor_research import RESEARCH_OUTPUT_SCHEMA

CANONICAL_KEYS = set(json.loads(RESEARCH_OUTPUT_SCHEMA).keys())

# A representative set of per-topic synthesis results.
COMPLIANCE = {
    "certifications_found": ["SOC 2 Type II", "ISO 27001"],
    "security_page_url": "https://acme.example/trust",
    "public_trust_posture": "strong",
    "summary": "Acme advertises SOC 2 and ISO 27001.",
}
BREACH = {
    "breach_history": ["2021 credential-stuffing incident"],
    "last_known_incident": "2021 credential-stuffing incident",
    "incident_severity": "medium",
    "summary": "One historical incident, since remediated.",
}
TRUST = {
    "security_page_url": "https://acme.example/security",
    "public_trust_posture": "moderate",
    "summary": "Public trust center present.",
}


# ---------------------------------------------------------------- merge
class TestMerge:
    def test_merged_matches_canonical_schema(self):
        merged = lr._merge_results(
            "Acme",
            {"compliance": COMPLIANCE, "breach": BREACH, "trust": TRUST},
            ["https://a", "https://a", "https://b"],
        )
        # Every key the cloud schema defines must be present.
        assert CANONICAL_KEYS.issubset(merged.keys())
        assert merged["vendor_name"] == "Acme"
        assert merged["certifications_found"] == ["SOC 2 Type II", "ISO 27001"]
        assert merged["breach_history"] == ["2021 credential-stuffing incident"]
        assert merged["incident_severity"] == "medium"
        # Best of moderate/strong wins.
        assert merged["public_trust_posture"] == "strong"
        # evidence_links de-duplicated, order preserved.
        assert merged["evidence_links"] == ["https://a", "https://b"]
        # Provenance fields present.
        assert merged["research_engine"] == "local"

    def test_fair_inputs_sanitized_and_ordered(self):
        merged = lr._merge_results("Acme", {"breach": BREACH}, [])
        fi = merged["recommended_fair_inputs"]
        for prefix in ("tef", "tc", "cs", "plm"):
            assert fi[f"{prefix}_min"] <= fi[f"{prefix}_ml"] <= fi[f"{prefix}_max"]
        assert 0.0 <= fi["tc_max"] <= 1.0
        assert 0.0 <= fi["cs_max"] <= 1.0
        assert fi["tef_min"] > 0

    def test_no_evidence_yields_low_confidence(self):
        merged = lr._merge_results("Ghost", {}, [])
        assert merged["research_confidence"] == "low"
        assert "little public security information" in merged["research_summary"]

    def test_evidence_yields_capped_medium_confidence(self):
        merged = lr._merge_results("Acme", {"compliance": COMPLIANCE}, ["https://a"])
        assert merged["research_confidence"] == "medium"

    def test_fair_reasoning_present_for_all_params(self):
        merged = lr._merge_results("Acme", {"compliance": COMPLIANCE}, [])
        assert set(merged["fair_input_reasoning"]) == {"tef", "tc", "cs", "plm"}


# ---------------------------------------------------------------- confidence cap
class TestConfidenceCap:
    def test_high_caps_to_medium(self):
        assert lr._cap_confidence("high") == "medium"

    def test_medium_stays_medium(self):
        assert lr._cap_confidence("medium") == "medium"

    def test_low_stays_low(self):
        assert lr._cap_confidence("low") == "low"

    def test_unknown_caps_to_low(self):
        assert lr._cap_confidence("garbage") == "low"


# ---------------------------------------------------------------- coercion
class TestCoerceTopic:
    def _topic(self, key):
        return next(t for t in lr.TOPICS if t["key"] == key)

    def test_string_coerced_to_list(self):
        out = lr._coerce_topic(self._topic("compliance"),
                               {"certifications_found": "SOC 2"})
        assert out["certifications_found"] == ["SOC 2"]

    def test_invalid_severity_becomes_unknown(self):
        out = lr._coerce_topic(self._topic("breach"),
                               {"incident_severity": "catastrophic"})
        assert out["incident_severity"] == "unknown"

    def test_missing_fields_get_defaults(self):
        out = lr._coerce_topic(self._topic("breach"), {})
        assert out["breach_history"] == []
        assert out["incident_severity"] == "unknown"


# ---------------------------------------------------------------- synthesis retry
class TestSynthesizeRetry:
    def _topic(self):
        return next(t for t in lr.TOPICS if t["key"] == "compliance")

    def test_valid_json_first_try(self, monkeypatch):
        monkeypatch.setattr(lr, "_ollama_generate",
                            lambda *a, **k: json.dumps(COMPLIANCE))
        out = lr._synthesize_topic(self._topic(), "Acme", "ctx", "m", "u")
        assert out["certifications_found"] == ["SOC 2 Type II", "ISO 27001"]

    def test_invalid_then_valid_retries_once(self, monkeypatch):
        calls = {"n": 0}

        def fake_generate(*a, **k):
            calls["n"] += 1
            return "not json" if calls["n"] == 1 else json.dumps(COMPLIANCE)

        monkeypatch.setattr(lr, "_ollama_generate", fake_generate)
        out = lr._synthesize_topic(self._topic(), "Acme", "ctx", "m", "u")
        assert calls["n"] == 2
        assert out["certifications_found"] == ["SOC 2 Type II", "ISO 27001"]

    def test_invalid_twice_falls_back_to_defaults(self, monkeypatch):
        calls = {"n": 0}

        def fake_generate(*a, **k):
            calls["n"] += 1
            return "still not json"

        monkeypatch.setattr(lr, "_ollama_generate", fake_generate)
        out = lr._synthesize_topic(self._topic(), "Acme", "ctx", "m", "u")
        assert calls["n"] == 2
        assert out == lr._topic_defaults(self._topic())

    def test_ollama_error_falls_back_to_defaults(self, monkeypatch):
        import requests

        def boom(*a, **k):
            raise requests.RequestException("connection refused")

        monkeypatch.setattr(lr, "_ollama_generate", boom)
        out = lr._synthesize_topic(self._topic(), "Acme", "ctx", "m", "u")
        assert out == lr._topic_defaults(self._topic())


# ---------------------------------------------------------------- full pipeline
class TestFullPipeline:
    def test_end_to_end_with_mocks(self, monkeypatch):
        monkeypatch.setattr(
            lr, "_gather_topic_context",
            lambda topic, vendor: ("SOURCE: https://x\nsome text", ["https://x"]),
        )

        def fake_synth(topic, vendor, context, model, base_url):
            return {"compliance": COMPLIANCE, "breach": BREACH, "trust": TRUST}[topic["key"]]

        monkeypatch.setattr(lr, "_synthesize_topic", fake_synth)

        result = lr.research_vendor_local(
            "Acme", "https://acme.example", "SaaS",
            ["PII"], "API/SSO", ["SOC2"], model="llama3.2:1b",
        )
        assert CANONICAL_KEYS.issubset(result.keys())
        assert result["research_engine"] == "local"
        assert result["local_model"] == "llama3.2:1b"
        # Local research never exceeds medium confidence.
        assert result["research_confidence"] in ("low", "medium")
        assert result["certifications_found"] == ["SOC 2 Type II", "ISO 27001"]

    def test_time_budget_exhausted_returns_valid_result(self, monkeypatch):
        # A non-positive budget puts the deadline in the past immediately, so
        # every topic short-circuits to defaults without touching the network.
        monkeypatch.setattr(lr, "PIPELINE_TIME_BUDGET", -1)

        def fail_network(*a, **k):
            raise AssertionError("budget-exhausted path must not hit the network")

        monkeypatch.setattr(lr, "_gather_topic_context", fail_network)
        monkeypatch.setattr(lr, "_synthesize_topic", fail_network)
        result = lr.research_vendor_local(
            "Acme", "", "SaaS", [], "", [],
        )
        # Still a valid, schema-complete dict built from topic defaults.
        assert CANONICAL_KEYS.issubset(result.keys())
        assert result["research_engine"] == "local"
        assert result["research_confidence"] == "low"


# ---------------------------------------------------------------- routing
class TestFallbackRouting:
    def test_no_key_routes_to_local(self, monkeypatch):
        import modules.ai_researcher as ai
        from modules import settings_store

        monkeypatch.setattr(settings_store, "get_ai_provider", lambda: "anthropic")
        monkeypatch.setattr(settings_store, "get_api_key", lambda provider: "")

        sentinel = {"research_engine": "local", "vendor_name": "Acme"}
        monkeypatch.setattr(lr, "research_vendor_local",
                            lambda *a, **k: sentinel)

        result = ai.research_vendor(
            vendor_name="Acme", website="", category="SaaS",
            data_types=[], integration_depth="", regulatory_context=[],
        )
        assert result is sentinel

    def test_key_present_does_not_route_to_local(self, monkeypatch):
        import modules.ai_researcher as ai
        from modules import settings_store

        monkeypatch.setattr(settings_store, "get_ai_provider", lambda: "anthropic")
        monkeypatch.setattr(settings_store, "get_api_key", lambda provider: "sk-present")

        def fail_local(*a, **k):
            raise AssertionError("should not use local fallback when a key exists")

        monkeypatch.setattr(lr, "research_vendor_local", fail_local)
        monkeypatch.setattr(ai, "_research_anthropic",
                            lambda prompt, client: json.dumps({"vendor_name": "Acme"}))

        result = ai.research_vendor(
            vendor_name="Acme", website="", category="SaaS",
            data_types=[], integration_depth="", regulatory_context=[],
        )
        assert result["research_engine"] == "anthropic"

    def test_explicit_provider_skips_local_fallback(self, monkeypatch):
        import modules.ai_researcher as ai
        from modules import settings_store

        # No key anywhere, but an explicit provider must still use that provider.
        monkeypatch.setattr(settings_store, "get_api_key", lambda provider: "")
        monkeypatch.setattr(ai, "_research_gemini",
                            lambda prompt: json.dumps({"vendor_name": "Acme"}))

        def fail_local(*a, **k):
            raise AssertionError("explicit provider should not fall back to local")

        monkeypatch.setattr(lr, "research_vendor_local", fail_local)
        result = ai.research_vendor(
            vendor_name="Acme", website="", category="SaaS",
            data_types=[], integration_depth="", regulatory_context=[],
            provider="gemini",
        )
        assert result["vendor_name"] == "Acme"


# ---------------------------------------------------------------- health check
class TestHealthCheck:
    def test_ollama_available_true(self, monkeypatch):
        class R:
            status_code = 200

        monkeypatch.setattr(lr.requests, "get", lambda *a, **k: R())
        assert lr.ollama_available() is True

    def test_ollama_available_false_on_error(self, monkeypatch):
        def boom(*a, **k):
            raise lr.requests.ConnectionError("nope")

        monkeypatch.setattr(lr.requests, "get", boom)
        assert lr.ollama_available() is False

    def test_test_local_llm_unreachable(self, monkeypatch):
        monkeypatch.setattr(lr, "ollama_available", lambda *a, **k: False)
        out = lr.test_local_llm()
        assert out["reachable"] is False
        assert out["generation_ok"] is False
        assert "Ollama" in out["detail"]

    def test_test_local_llm_happy_path(self, monkeypatch):
        monkeypatch.setattr(lr, "ollama_available", lambda *a, **k: True)
        monkeypatch.setattr(lr, "list_models", lambda *a, **k: ["llama3.2:1b"])
        monkeypatch.setattr(lr, "_ollama_generate", lambda *a, **k: "ok")
        out = lr.test_local_llm(model="llama3.2:1b")
        assert out["reachable"] is True
        assert out["model_loaded"] is True
        assert out["generation_ok"] is True
