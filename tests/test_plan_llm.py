"""Tests for plan_llm_complete + text/json artifact materialization."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from falaw import plan_llm_complete
from falaw.plan import CallPlan, Plan, _artifact_from_response, execute


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FALAW_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FALAW_CACHE_DIR", str(tmp_path / "cache"))
    from falaw.events import clear_subscribers
    from falaw.journal import _default_journal

    _default_journal.cache_clear()
    clear_subscribers()
    yield
    clear_subscribers()
    _default_journal.cache_clear()


def _install_fake_fal(monkeypatch, *, response):
    def subscribe(application, *, arguments, with_logs, on_queue_update):
        return response

    fake = types.SimpleNamespace(
        InProgress=type("InProgress", (), {"__init__": lambda self, logs: None}),
        subscribe=subscribe,
    )
    monkeypatch.setitem(sys.modules, "fal_client", fake)
    return fake


# --- plan_llm_complete -----------------------------------------------------


def test_plan_llm_complete_builds_any_llm_callplan():
    cp = plan_llm_complete("Summarize the scene.", system="You are terse.")
    assert isinstance(cp, CallPlan)
    assert cp.tool == "llm_complete"
    assert cp.application == "fal-ai/any-llm"
    assert cp.output_kind == "text"  # default
    assert cp.arguments["prompt"] == "Summarize the scene."
    assert cp.arguments["system_prompt"] == "You are terse."
    assert cp.arguments["model"].startswith("anthropic/")  # default model


def test_plan_llm_complete_has_a_cost_estimate():
    # fal-ai/any-llm now carries an approximate per-call cost, so an LLM plan
    # is budget-gateable rather than has_unknown_costs.
    cp = plan_llm_complete("x", consult_cache=False)
    assert cp.estimated_cost_usd is not None
    assert cp.estimated_cost_usd > 0
    assert Plan(calls=(cp,)).has_unknown_costs is False


def test_plan_llm_complete_output_kind_json():
    cp = plan_llm_complete("Return JSON.", output_kind="json")
    assert cp.output_kind == "json"


def test_plan_llm_complete_arg_shape_matches_eager_llm_complete():
    """Planned and eager calls with the same inputs must share a cache key.

    The cache key is SHA-256 of (application, arguments), so the argument
    dict the planner builds must be byte-identical to the eager wrapper's.
    """
    from falaw.operations.llm import _DEFAULT_LLM, _DEFAULT_MODEL

    cp = plan_llm_complete("hello", system="sys", temperature=0.3, consult_cache=False)
    # This is exactly what eager llm_complete(prompt, system=..., ...) builds:
    expected_args = {
        "model": _DEFAULT_MODEL,
        "prompt": "hello",
        "temperature": 0.3,
        "system_prompt": "sys",
    }
    assert cp.application == _DEFAULT_LLM
    assert cp.arguments == expected_args


def test_plan_llm_complete_extra_args_merge():
    cp = plan_llm_complete("x", extra={"max_tokens": 512}, consult_cache=False)
    assert cp.arguments["max_tokens"] == 512


# --- text/json artifact materialization ------------------------------------


def test_converter_materializes_json_response_to_a_file():
    cp = plan_llm_complete("Return JSON.", output_kind="json", consult_cache=False)
    raw = {"output": '{"logline": "a bell rings at midnight"}'}
    art = _artifact_from_response(raw, cp)

    assert art.kind == "json"
    assert art.url is None
    assert art.path is not None
    content = Path(art.path).read_text(encoding="utf-8")
    assert json.loads(content) == {"logline": "a bell rings at midnight"}
    assert art.bytes_size == len(content.encode("utf-8"))
    assert art.mime == "application/json"


def test_converter_unwraps_a_json_code_fence():
    """``output_kind="json"`` materializes a directly-parseable artifact
    even when the model wraps its answer in a ```json fence."""
    cp = plan_llm_complete("Return JSON.", output_kind="json", consult_cache=False)
    raw = {"output": '```json\n[{"name": "Alex"}]\n```'}
    art = _artifact_from_response(raw, cp)
    content = Path(art.path).read_text(encoding="utf-8")
    # The fence is gone — the artifact parses without any caller-side cleanup.
    assert json.loads(content) == [{"name": "Alex"}]


def test_converter_leaves_a_fence_in_text_output_alone():
    """Only ``output_kind="json"`` is unwrapped — a code block is
    legitimate content in a ``text`` response."""
    cp = plan_llm_complete("Summarize.", output_kind="text", consult_cache=False)
    fenced = "```\nsome code\n```"
    art = _artifact_from_response({"output": fenced}, cp)
    assert Path(art.path).read_text(encoding="utf-8") == fenced


def test_converter_materializes_text_response_to_a_file():
    cp = plan_llm_complete("Summarize.", output_kind="text", consult_cache=False)
    art = _artifact_from_response({"output": "a terse summary"}, cp)
    assert art.kind == "text"
    assert art.path is not None
    assert Path(art.path).read_text(encoding="utf-8") == "a terse summary"
    assert art.mime == "text/plain"


def test_converter_text_materialization_is_content_addressed_and_idempotent():
    cp = plan_llm_complete("x", output_kind="json", consult_cache=False)
    raw = {"output": '{"k": "v"}'}
    a1 = _artifact_from_response(raw, cp)
    a2 = _artifact_from_response(raw, cp)
    assert a1.asset_id == a2.asset_id  # content-addressed
    assert a1.path == a2.path

    # Different content → different asset_id.
    a3 = _artifact_from_response({"output": '{"k": "other"}'}, cp)
    assert a3.asset_id != a1.asset_id


def test_converter_handles_openai_shaped_llm_response():
    cp = plan_llm_complete("x", output_kind="text", consult_cache=False)
    raw = {"choices": [{"message": {"content": "nested content"}}]}
    art = _artifact_from_response(raw, cp)
    assert Path(art.path).read_text(encoding="utf-8") == "nested content"


def test_converter_media_response_without_bytes_keeps_the_url_only():
    """``fetch_bytes=False``: media keeps its URL, gains no path, no content id.

    The id must NOT be the SHA-256 of the URL (falaw#14) — that is what made
    two byte-identical renders look different and put an expiring location in
    downstream cache keys.
    """
    from lacing import hash_bytes

    img_call = CallPlan(
        tool="generate_image",
        application="fal-ai/flux/dev",
        arguments={"prompt": "x"},
        output_kind="image",
    )
    raw = {"images": [{"url": "https://cdn/x.png"}]}
    art = _artifact_from_response(raw, img_call, fetch_bytes=False)
    assert art.kind == "image"
    assert art.url == "https://cdn/x.png"
    assert art.path is None
    assert art.bytes_size == 0
    assert art.asset_id != hash_bytes(b"https://cdn/x.png")


# --- execute() round-trip with a stubbed fal -------------------------------


def test_execute_llm_plan_returns_usable_artifact(monkeypatch):
    _install_fake_fal(monkeypatch, response={"output": '{"tone": "noir"}'})
    cp = plan_llm_complete(
        "Describe the tone.", output_kind="json", consult_cache=False
    )
    [art] = execute(Plan(calls=(cp,)), use_cache=False)
    assert art.kind == "json"
    assert art.path is not None
    assert json.loads(Path(art.path).read_text(encoding="utf-8")) == {"tone": "noir"}
