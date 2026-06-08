"""Mock tests for the AI research module (no live API calls)."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from modules.ai_researcher import (
    _extract_json,
    _sanitize_fair_inputs,
    research_vendor,
)


VALID_RESEARCH = {
    "vendor_name": "Acme SaaS",
    "security_page_url": "https://acme.example/trust",
    "certifications_found": ["SOC 2 Type II"],
    "breach_history": [],
    "last_known_incident": "",
    "incident_severity": "low",
    "public_trust_posture": "strong",
    "evidence_links": ["https://acme.example/trust"],
    "research_confidence": "high",
    "research_summary": "Strong public security posture.",
    "recommended_fair_inputs": {
        "tef_min": 0.1, "tef_ml": 0.4, "tef_max": 1.5,
        "tc_min": 0.3, "tc_ml": 0.5, "tc_max": 0.8,
        "cs_min": 0.5, "cs_ml": 0.7, "cs_max": 0.9,
        "plm_min": 5000, "plm_ml": 50000, "plm_max": 300000,
    },
}


def _mock_client(text: str, stop_reason: str = "end_turn"):
    client = MagicMock()
    block = SimpleNamespace(type="text", text=text)
    client.messages.create.return_value = SimpleNamespace(
        content=[block], stop_reason=stop_reason
    )
    return client


class TestExtractJson:
    def test_plain_json(self):
        assert _extract_json(json.dumps(VALID_RESEARCH))["vendor_name"] == "Acme SaaS"

    def test_fenced_json(self):
        raw = "```json\n" + json.dumps(VALID_RESEARCH) + "\n```"
        assert _extract_json(raw)["research_confidence"] == "high"

    def test_json_with_preamble(self):
        raw = "Here are my findings:\n" + json.dumps(VALID_RESEARCH)
        assert _extract_json(raw)["public_trust_posture"] == "strong"

    def test_garbage_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _extract_json("not json at all")


class TestSanitizeFairInputs:
    def test_clamps_tc_cs_to_unit_interval(self):
        out = _sanitize_fair_inputs({"tc_max": 1.7, "cs_min": -0.2})
        assert out["tc_max"] <= 1.0
        assert out["cs_min"] >= 0.0

    def test_tef_positive(self):
        out = _sanitize_fair_inputs({"tef_min": -5})
        assert out["tef_min"] > 0

    def test_reorders_min_ml_max(self):
        out = _sanitize_fair_inputs({"plm_min": 900000, "plm_ml": 50000, "plm_max": 10000})
        assert out["plm_min"] <= out["plm_ml"] <= out["plm_max"]

    def test_non_numeric_falls_back_to_default(self):
        out = _sanitize_fair_inputs({"tef_ml": "lots"})
        assert isinstance(out["tef_ml"], float)


class TestResearchVendor:
    def _call(self, client):
        return research_vendor(
            vendor_name="Acme SaaS",
            website="https://acme.example",
            category="SaaS",
            data_types=["PII"],
            integration_depth="API/SSO",
            regulatory_context=["SOC2"],
            client=client,
        )

    def test_returns_parsed_result(self):
        result = self._call(_mock_client(json.dumps(VALID_RESEARCH)))
        assert result["vendor_name"] == "Acme SaaS"
        assert result["recommended_fair_inputs"]["tc_max"] <= 1.0

    def test_handles_fenced_output(self):
        raw = "```json\n" + json.dumps(VALID_RESEARCH) + "\n```"
        result = self._call(_mock_client(raw))
        assert result["research_confidence"] == "high"

    def test_empty_output_raises(self):
        with pytest.raises(ValueError):
            self._call(_mock_client(""))

    def test_uses_web_search_tool(self):
        client = _mock_client(json.dumps(VALID_RESEARCH))
        self._call(client)
        kwargs = client.messages.create.call_args.kwargs
        assert any(t.get("name") == "web_search" for t in kwargs["tools"])


class TestProviderDispatch:
    def _call(self, provider):
        return research_vendor(
            vendor_name="Acme SaaS",
            website="https://acme.example",
            category="SaaS",
            data_types=["PII"],
            integration_depth="API/SSO",
            regulatory_context=["SOC2"],
            provider=provider,
        )

    def test_gemini_dispatch(self, monkeypatch):
        import modules.ai_researcher as ai

        monkeypatch.setattr(ai, "_research_gemini", lambda prompt: json.dumps(VALID_RESEARCH))
        result = self._call("gemini")
        assert result["vendor_name"] == "Acme SaaS"

    def test_openai_dispatch(self, monkeypatch):
        import modules.ai_researcher as ai

        monkeypatch.setattr(ai, "_research_openai", lambda prompt: json.dumps(VALID_RESEARCH))
        result = self._call("openai")
        assert result["research_confidence"] == "high"

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown AI provider"):
            self._call("llama")

    def test_injected_client_pins_anthropic(self, monkeypatch):
        import modules.ai_researcher as ai
        from modules import settings_store

        # Even if settings say gemini, an explicit Anthropic client wins
        monkeypatch.setattr(settings_store, "get_ai_provider", lambda: "gemini")
        client = _mock_client(json.dumps(VALID_RESEARCH))
        result = research_vendor(
            vendor_name="Acme SaaS", website="", category="SaaS",
            data_types=[], integration_depth="", regulatory_context=[],
            client=client,
        )
        assert client.messages.create.called
        assert result["vendor_name"] == "Acme SaaS"
