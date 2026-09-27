import json
from pathlib import Path

import pytest

from openbot.runtime.model_catalog import CATALOG_PROVIDERS, normalize_catalog

SAMPLE = json.loads((Path(__file__).parent / "fixtures" / "models_dev_sample.json").read_text())


def test_normalize_keeps_only_agent_capable_models_of_supported_providers():
    cat = normalize_catalog(SAMPLE)
    assert set(cat) == set(CATALOG_PROVIDERS) == {"openai", "anthropic", "openrouter", "ollama"}
    # deprecated, no tool calling, image output, no/invalid context, non-dict blocks, and the malformed entry are all gone
    assert [m["id"] for m in cat["openai"]] == ["gpt-5.5"]
    # newest first; beta kept; tiny context and no-tools dropped
    assert [m["id"] for m in cat["openrouter"]] == ["z-ai/glm-5.3-flash", "stealth/new-thing"]
    assert [m["id"] for m in cat["ollama"]] == ["kimi-k3", "gpt-oss:20b"]
    assert "xai" not in cat


def test_normalized_record_shape():
    m = next(x for x in normalize_catalog(SAMPLE)["anthropic"] if x["id"] == "claude-opus-5-5")
    assert m == {
        "id": "claude-opus-5-5", "name": "Claude Opus 5.5", "family": "claude-opus", "description": "Most capable Claude",
        "reasoning": True, "effort_levels": ["low", "medium", "high", "xhigh", "max"], "image_input": True,
        "context": 200000, "output": 64000, "cost_input": 5.0, "cost_output": 25.0, "release_date": "2026-03-01", "status": None,
    }


def test_effort_levels_come_only_from_the_effort_option():
    by_id = {m["id"]: m for m in normalize_catalog(SAMPLE)["anthropic"]}
    assert by_id["claude-sonnet-4-5"]["effort_levels"] == []   # budget_tokens only
    assert by_id["claude-haiku-4-5"]["effort_levels"] == []    # toggle only
    assert by_id["claude-opus-5-5"]["reasoning"] is True


def test_beta_is_flagged_and_unknown_cost_and_output_are_null():
    m = next(x for x in normalize_catalog(SAMPLE)["openrouter"] if x["id"] == "stealth/new-thing")
    assert m["status"] == "beta" and m["family"] == "" and m["description"] == ""
    assert m["cost_input"] is None and m["cost_output"] is None and m["output"] is None


def test_missing_provider_or_models_block_yields_empty_list_without_touching_others():
    cat = normalize_catalog({"openai": {"models": SAMPLE["openai"]["models"]}, "anthropic": {"id": "anthropic"}, "openrouter": "garbage"})
    assert [m["id"] for m in cat["openai"]] == ["gpt-5.5"]
    assert cat["anthropic"] == [] and cat["openrouter"] == [] and cat["ollama"] == []


def test_document_must_be_an_object():
    with pytest.raises(ValueError):
        normalize_catalog([])


def test_non_dict_block_inside_an_entry_is_skipped_not_fatal():
    raw = {"openai": {"models": {
        "bad": {"id": "bad", "tool_call": True, "modalities": ["text"], "limit": {"context": 100000}},
        "good": {"id": "good", "tool_call": True, "modalities": {"input": ["text"], "output": ["text"]}, "limit": {"context": 100000}},
    }}}
    assert [m["id"] for m in normalize_catalog(raw)["openai"]] == ["good"]
