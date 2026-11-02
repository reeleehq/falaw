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

import contextlib
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
    assert (r.rates_table_version, r.rate_date) == ("", "")  # not the table's


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


# --- falaw#135: rate-table provenance, and an observed cost as one more basis


def test_a_table_priced_receipt_records_the_table_version_and_row_date(monkeypatch):
    from falaw import llm_complete_with_receipt
    from falaw.llm_rates import get_llm_rate, llm_rates_table_version
    from falaw.operations.llm import _DEFAULT_MODEL

    _install_fake_fal(monkeypatch, response=OPENAI_SHAPED)
    _, r = llm_complete_with_receipt("q")
    assert r.cost_source == "rate_table:per_call"
    assert r.rates_table_version == llm_rates_table_version() != ""
    assert r.rate_date == get_llm_rate(_DEFAULT_MODEL).date != ""


def test_a_token_priced_receipt_records_the_table_version_and_row_date(monkeypatch):
    from falaw import llm_complete_with_receipt
    from falaw.llm_rates import get_llm_rate, llm_rates_table_version

    model = "anthropic/claude-haiku-5.5"
    usage = {"prompt_tokens": 150_000, "completion_tokens": 2_000}
    _install_fake_fal(monkeypatch, response={"output": "ok", "usage": usage})
    _, r = llm_complete_with_receipt("q", model=model)
    assert r.cost_source == "rate_table:upstream_tokens"
    assert r.rates_table_version == llm_rates_table_version()
    assert r.rate_date == get_llm_rate(model).date


def test_custom_rates_record_no_table_version():
    # A caller's rates= table has no file to digest (as reprice.llm_cost_basis).
    from falaw.llm_rates import LlmRate, llm_cost_bases, llm_rates_table_version

    mine = {
        "my/model": LlmRate(
            model="my/model",
            tier="standard",
            per_call_usd=0.5,
            source="reconciled against my invoice",
            date="2026-09-07",
        )
    }
    custom = llm_cost_bases("my/model", rates=mine)
    assert (custom.table_version, custom.rate_date) == ("", "2026-09-07")
    committed = llm_cost_bases("anthropic/claude-haiku-5.5")
    assert committed.table_version == llm_rates_table_version() != ""


# fal's docs show openrouter/router returning usage.cost 0.0005595: the upstream
# cost, ~18x below fal's flat any-llm request price. An observed cost is a basis
# in the max (falaw#130), never an override that lowers the receipt.
UPSTREAM_USAGE_COST = 0.0005595


def test_an_observed_cost_below_the_request_price_does_not_lower_it(monkeypatch):
    from falaw import llm_ceiling_usd, llm_complete_with_receipt
    from falaw.llm_rates import llm_rates_table_version
    from falaw.operations.llm import _DEFAULT_MODEL

    usage = {"prompt_tokens": 42, "completion_tokens": 7, "cost": UPSTREAM_USAGE_COST}
    _install_fake_fal(monkeypatch, response={"output": "ok", "usage": usage})
    _, r = llm_complete_with_receipt("q")
    assert r.estimated_cost_usd == llm_ceiling_usd(_DEFAULT_MODEL) > UPSTREAM_USAGE_COST
    assert r.cost_source == "rate_table:per_call"
    assert r.rates_table_version == llm_rates_table_version()
    assert (r.tokens_in, r.tokens_out) == (42, 7)


def test_a_reported_zero_usage_cost_does_not_zero_the_receipt(monkeypatch):
    from falaw import llm_complete_with_receipt

    _install_fake_fal(monkeypatch, response={"output": "ok", "usage": {"cost": 0}})
    _, r = llm_complete_with_receipt("q")
    assert r.estimated_cost_usd > 0
    assert r.cost_source == "rate_table:per_call"


def test_an_observed_cost_above_the_estimate_binds(monkeypatch):
    from falaw import llm_ceiling_usd, llm_complete_with_receipt
    from falaw.operations.llm import _DEFAULT_MODEL

    observed = 100 * llm_ceiling_usd(_DEFAULT_MODEL)
    usage = {"cost": observed}
    _install_fake_fal(monkeypatch, response={"output": "ok", "usage": usage})
    _, r = llm_complete_with_receipt("q")
    assert (r.estimated_cost_usd, r.cost_source) == (observed, "observed:usage_cost")
    assert (r.rates_table_version, r.rate_date) == ("", "")  # not the table's


@pytest.mark.parametrize("above", [True, False])
def test_an_observed_cost_against_the_registry_fallback(monkeypatch, above):
    from falaw import llm_complete_with_receipt
    from falaw.registry import get_model

    record = get_model("fal-ai/any-llm")
    registry_usd = record.cost_estimate.amount
    observed = registry_usd * (2 if above else 0.5)
    _install_fake_fal(
        monkeypatch, response={"output": "ok", "usage": {"cost": observed}}
    )
    _, r = llm_complete_with_receipt("q", model="some/model-nobody-priced")
    if above:
        assert (r.estimated_cost_usd, r.cost_source) == (
            observed,
            "observed:usage_cost",
        )
    else:
        assert r.estimated_cost_usd == pytest.approx(registry_usd)
        assert r.cost_source == f"registry:{record.cost_estimate.kind}"
    assert (r.rates_table_version, r.rate_date) == ("", "")


def test_an_observed_cost_binds_when_nothing_else_prices_the_call(monkeypatch):
    from falaw import llm_complete_with_receipt
    import falaw.operations.llm as llm_ops

    monkeypatch.setattr(llm_ops, "estimate_call_cost", lambda *a, **k: None)
    usage = {"cost": UPSTREAM_USAGE_COST}
    _install_fake_fal(monkeypatch, response={"output": "ok", "usage": usage})
    _, r = llm_complete_with_receipt("q", model="some/model-nobody-priced")
    assert (r.estimated_cost_usd, r.cost_source) == (
        UPSTREAM_USAGE_COST,
        "observed:usage_cost",
    )


def test_a_cache_hit_beats_a_reported_usage_cost(monkeypatch):
    from falaw import llm_complete_with_receipt

    usage = {"cost": 0.5}
    _install_fake_fal(monkeypatch, response={"output": "ok", "usage": usage})
    llm_complete_with_receipt("same prompt")
    _, r = llm_complete_with_receipt("same prompt")
    assert r.cache_hit
    assert (r.estimated_cost_usd, r.cost_source) == (0.0, "cache_hit")
    assert (r.rates_table_version, r.rate_date) == ("", "")


_UNCACHEABLE = "could not cache the response"
"""falaw's warning when a response carrying a non-finite float cannot be cached."""


@pytest.mark.parametrize(
    "cost, uncacheable",
    [
        (-0.01, False),
        ("0.01", False),
        (True, False),
        (float("nan"), True),
        (float("inf"), True),
        (10**400, False),  # an int too large for a float: OverflowError
        (None, False),
        ([0.01], False),
    ],
)
def test_a_nonsense_usage_cost_is_not_a_cost(monkeypatch, cost, uncacheable):
    from falaw import llm_complete_with_receipt
    from falaw.operations.llm import _extract_usage_cost

    assert _extract_usage_cost({"usage": {"cost": cost}}) is None
    usage = {"prompt_tokens": 42, "completion_tokens": 7, "cost": cost}
    _install_fake_fal(monkeypatch, response={"output": "ok", "usage": usage})
    warns = (
        pytest.warns(UserWarning, match=_UNCACHEABLE)
        if uncacheable
        else contextlib.nullcontext()
    )
    with warns:
        _, r = llm_complete_with_receipt("q")
    assert r.cost_source == "rate_table:per_call"


def test_a_negative_zero_usage_cost_reads_as_zero():
    import math

    from falaw.operations.llm import _extract_usage_cost

    usd = _extract_usage_cost({"usage": {"cost": -0.0}})
    assert usd == 0.0 and math.copysign(1.0, usd) == 1.0


def test_an_observed_cost_equal_to_the_estimate_reads_as_the_estimate(monkeypatch):
    """Strictly above binds; a tie keeps the table's source and provenance."""
    from falaw import llm_ceiling_usd, llm_complete_with_receipt
    from falaw.operations.llm import _DEFAULT_MODEL

    tie = llm_ceiling_usd(_DEFAULT_MODEL)
    _install_fake_fal(monkeypatch, response={"output": "ok", "usage": {"cost": tie}})
    _, r = llm_complete_with_receipt("q")
    assert (r.estimated_cost_usd, r.cost_source) == (tie, "rate_table:per_call")
    assert r.rates_table_version and r.rate_date
