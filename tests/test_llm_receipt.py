"""Tests for falaw#50 option B — the eager LLM path finally keeps a record.

What these pin:

* the receipt reports measured chars, best-effort tokens (OpenAI and
  Anthropic usage shapes; None — never zero — when the response carries no
  usage block);
* a cache hit is a $0.00 receipt with ``cost_source="cache_hit"``; a fresh
  call is priced for the *routed* model against the rate table, falling back
  to the registry (named in ``cost_source``) only for a model no table prices;
* ``llm_complete`` delegates to the receipt variant — one
  argument-construction site, so the two spellings share one cache entry
  (proved by a cross-spelling cache hit);
* the receipt variant is library surface only, NOT a registered tool.
"""

from __future__ import annotations

import sys
import types

import pytest


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
    captured: list[dict] = []

    def subscribe(application, *, arguments, with_logs, on_queue_update):
        captured.append({"application": application, "arguments": dict(arguments)})
        return response

    fake = types.SimpleNamespace(
        InProgress=type("InProgress", (), {"__init__": lambda self, logs: None}),
        subscribe=subscribe,
    )
    monkeypatch.setitem(sys.modules, "fal_client", fake)
    return captured


OPENAI_SHAPED = {
    "choices": [{"message": {"content": "A terse summary."}}],
    "usage": {"prompt_tokens": 42, "completion_tokens": 7},
}

ANTHROPIC_SHAPED = {
    "output": "Another answer.",
    "usage": {"input_tokens": 10, "output_tokens": 3},
}

NO_USAGE = {"output": "Bare answer."}


def test_receipt_measures_chars_and_reads_openai_usage(monkeypatch):
    _install_fake_fal(monkeypatch, response=OPENAI_SHAPED)
    from falaw import llm_complete_with_receipt

    text, r = llm_complete_with_receipt("Summarize.", system="Be terse.")
    assert text == "A terse summary."
    assert r.chars_in == len("Summarize.") + len("Be terse.")
    assert r.chars_out == len(text)
    assert (r.tokens_in, r.tokens_out) == (42, 7)
    assert r.cache_hit is False
    assert r.application == "fal-ai/any-llm"
    assert r.model.startswith("anthropic/")  # the default routed model


def test_receipt_reads_anthropic_usage_shape(monkeypatch):
    _install_fake_fal(monkeypatch, response=ANTHROPIC_SHAPED)
    from falaw import llm_complete_with_receipt

    _, r = llm_complete_with_receipt("q")
    assert (r.tokens_in, r.tokens_out) == (10, 3)


def test_receipt_reports_none_tokens_when_unrecorded(monkeypatch):
    """None means the provider recorded nothing — never invent a zero."""
    _install_fake_fal(monkeypatch, response=NO_USAGE)
    from falaw import llm_complete_with_receipt

    _, r = llm_complete_with_receipt("q")
    assert (r.tokens_in, r.tokens_out) == (None, None)


def test_fresh_call_is_priced_for_the_routed_model(monkeypatch):
    # Was pinned to the fal-ai/any-llm record. That record carries fal's
    # *standard* request tier, and the default routed model is on fal's
    # published premium list at 10x — so this used to under-report every
    # premium turn tenfold in the ledger a consumer sums (falaw#55).
    _install_fake_fal(monkeypatch, response=NO_USAGE)
    from falaw import llm_complete_with_receipt, llm_ceiling_usd
    from falaw.operations.llm import _DEFAULT_MODEL

    _, r = llm_complete_with_receipt("q")
    assert r.estimated_cost_usd == pytest.approx(llm_ceiling_usd(_DEFAULT_MODEL))
    assert r.cost_source == "rate_table:per_call"


def test_a_premium_routed_model_is_not_priced_at_the_router_rate(monkeypatch):
    _install_fake_fal(monkeypatch, response=NO_USAGE)
    from falaw import llm_complete_with_receipt
    from falaw.registry import get_model

    _, r = llm_complete_with_receipt("q")
    router_flat = get_model("fal-ai/any-llm").cost_estimate.amount
    assert r.estimated_cost_usd > router_flat


def test_a_model_the_table_does_not_price_falls_back_to_the_registry(monkeypatch):
    # A receipt records money already spent, so an unpriced routed model keeps
    # the router's approximate number rather than dropping to None — with
    # cost_source saying so, unlike a plan-time quote which must go unknown.
    _install_fake_fal(monkeypatch, response=NO_USAGE)
    from falaw import llm_complete_with_receipt
    from falaw.registry import get_model

    _, r = llm_complete_with_receipt("q", model="some/model-nobody-priced")
    record = get_model("fal-ai/any-llm")
    assert r.estimated_cost_usd == pytest.approx(record.cost_estimate.amount)
    assert r.cost_source == f"registry:{record.cost_estimate.kind}"


def test_cache_hit_is_a_zero_dollar_receipt(monkeypatch):
    _install_fake_fal(monkeypatch, response=NO_USAGE)
    from falaw import llm_complete_with_receipt

    _, first = llm_complete_with_receipt("same question")
    assert first.cache_hit is False
    _, second = llm_complete_with_receipt("same question")
    assert second.cache_hit is True
    assert second.estimated_cost_usd == 0.0
    assert second.cost_source == "cache_hit"


def test_llm_complete_and_receipt_variant_share_one_cache_entry(monkeypatch):
    """The delegation is what guarantees one argument-construction site:
    a plain llm_complete call must HIT the cache entry the receipt variant
    wrote, and vice versa — two spellings, one call identity."""
    captured = _install_fake_fal(monkeypatch, response=NO_USAGE)
    from falaw import llm_complete, llm_complete_with_receipt

    llm_complete_with_receipt("shared", system="s")
    assert len(captured) == 1
    out = llm_complete("shared", system="s")
    assert out == "Bare answer."
    assert len(captured) == 1, "the plain spelling hit the receipt call's entry"


def test_receipt_variant_is_not_a_registered_tool():
    """Library surface only — the tool surface keeps the one
    string-returning llm_complete (no CONTRACT 7 / snapshot movement)."""
    import falaw.operations.llm  # noqa: F401 — ensure registration ran
    from falaw.registry import list_tools

    names = {t.name for t in list_tools()}
    assert "llm_complete" in names
    assert "llm_complete_with_receipt" not in names


def test_a_long_prompt_is_recorded_at_its_token_cost_not_the_request_price(monkeypatch):
    """falaw#130: the receipt used the per-call price even when usage reported a
    prompt whose upstream token cost (long-prompt tier included) is far above it."""
    from falaw import llm_ceiling_usd, llm_complete_with_receipt

    model = "anthropic/claude-haiku-5.5"
    usage = {"prompt_tokens": 150_000, "completion_tokens": 2_000}
    _install_fake_fal(monkeypatch, response={"output": "ok", "usage": usage})
    _, r = llm_complete_with_receipt("q", model=model)
    expected = llm_ceiling_usd(model, input_tokens=150_000, max_output_tokens=2_000)
    assert expected > llm_ceiling_usd(
        model
    )  # the long tier binds, not the request price
    assert r.estimated_cost_usd == pytest.approx(expected)
    assert r.cost_source == "rate_table:upstream_tokens"


def test_a_short_prompt_still_records_the_request_price(monkeypatch):
    from falaw import llm_ceiling_usd, llm_complete_with_receipt
    from falaw.operations.llm import _DEFAULT_MODEL

    _install_fake_fal(monkeypatch, response=OPENAI_SHAPED)  # 42 in, 7 out
    _, r = llm_complete_with_receipt("q")
    assert r.estimated_cost_usd == pytest.approx(llm_ceiling_usd(_DEFAULT_MODEL))
    assert r.cost_source == "rate_table:per_call"


@pytest.mark.parametrize(
    "usage",
    [
        {"prompt_tokens": 150_000},  # no output count: no token bound
        {"prompt_tokens": -5, "completion_tokens": 7},  # nonsense count is unrecorded
    ],
)
def test_incomplete_or_nonsense_usage_falls_back_to_the_request_price(
    monkeypatch, usage
):
    from falaw import llm_ceiling_usd, llm_complete_with_receipt
    from falaw.operations.llm import _DEFAULT_MODEL

    _install_fake_fal(monkeypatch, response={"output": "ok", "usage": usage})
    _, r = llm_complete_with_receipt("q")
    assert r.estimated_cost_usd == pytest.approx(llm_ceiling_usd(_DEFAULT_MODEL))
    assert r.cost_source == "rate_table:per_call"


def test_anthropic_cache_tokens_count_toward_the_long_prompt_tier(monkeypatch):
    """Anthropic's input_tokens excludes cache reads and writes; the prompt the
    upstream bills is their sum, so the long-prompt threshold must see it."""
    from falaw import llm_ceiling_usd, llm_complete_with_receipt

    model = "anthropic/claude-haiku-5.5"
    usage = {
        "input_tokens": 1_000,
        "cache_read_input_tokens": 120_000,
        "cache_creation_input_tokens": 30_000,
        "output_tokens": 2_000,
    }
    _install_fake_fal(monkeypatch, response={"output": "ok", "usage": usage})
    _, r = llm_complete_with_receipt("q", model=model)
    assert (r.tokens_in, r.tokens_out) == (151_000, 2_000)
    expected = llm_ceiling_usd(model, input_tokens=151_000, max_output_tokens=2_000)
    assert r.estimated_cost_usd == pytest.approx(expected)
    assert r.cost_source == "rate_table:upstream_tokens"


def test_reported_usage_on_a_model_without_token_rates_records_the_request_price(
    monkeypatch,
):
    from falaw import llm_ceiling_usd, llm_complete_with_receipt
    from falaw.llm_rates import get_llm_rate

    model = "google/gemini-flash-1.5"
    assert not get_llm_rate(model).has_token_rates
    usage = {"prompt_tokens": 150_000, "completion_tokens": 2_000}
    _install_fake_fal(monkeypatch, response={"output": "ok", "usage": usage})
    _, r = llm_complete_with_receipt("q", model=model)
    assert (r.tokens_in, r.tokens_out) == (150_000, 2_000)
    assert r.estimated_cost_usd == pytest.approx(llm_ceiling_usd(model))
    assert r.cost_source == "rate_table:per_call"


def test_a_negative_count_reads_as_unrecorded_not_zero(monkeypatch):
    from falaw import llm_complete_with_receipt

    usage = {"prompt_tokens": -5, "completion_tokens": 7}
    _install_fake_fal(monkeypatch, response={"output": "ok", "usage": usage})
    _, r = llm_complete_with_receipt("q")
    assert (r.tokens_in, r.tokens_out) == (None, 7)


@pytest.mark.parametrize(
    "usage, expected",
    [
        ({"prompt_tokens": 100, "output_tokens": 50}, (100, 50)),  # mixed shapes
        (
            {"prompt_tokens": 10, "prompt_tokens_details": {"cached_tokens": 50}},
            (10, None),  # cached is a subset of prompt_tokens: never above it
        ),
    ],
)
def test_usage_counts_are_read_per_side_and_never_invented(usage, expected):
    from falaw.operations.llm import _extract_llm_usage

    assert _extract_llm_usage({"usage": usage}) == expected
