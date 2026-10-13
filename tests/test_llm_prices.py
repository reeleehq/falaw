"""First-party LLM prices (falaw#81): one table behind reelee's agent / chat relay and foley."""

import json
import types

import pytest

import falaw
from falaw import llm_call_cost_usd
from falaw.llm_prices import PRICES_FILENAME, load_llm_prices

M = 1_000_000


def test_exported_from_the_package_root():
    for name in ("llm_call_cost_usd", "get_llm_price", "list_llm_prices", "LlmPrice"):
        assert name in falaw.__all__


def test_anthropic_input_and_output():
    assert llm_call_cost_usd("anthropic", "claude-opus-4-7", {"input_tokens": M}) == (
        5.0,
        True,
    )
    assert llm_call_cost_usd("anthropic", "claude-opus-4-7", {"output_tokens": M}) == (
        25.0,
        True,
    )


def test_anthropic_cache_reads_and_writes():
    # reads are 0.1x, 5-minute writes 1.25x the input rate
    usage = {"cache_read_input_tokens": M, "cache_creation_input_tokens": M}
    assert llm_call_cost_usd("anthropic", "claude-sonnet-5-5", usage) == (
        2.0 * 1.35,
        True,
    )


def test_haiku_5_5_long_prompt_rates_apply_past_100k():
    short = llm_call_cost_usd(
        "anthropic", "claude-haiku-5-5", {"input_tokens": 100_000}
    )
    long_ = llm_call_cost_usd(
        "anthropic", "claude-haiku-5-5", {"input_tokens": 100_001}
    )
    assert short == (pytest.approx(0.01), True)  # $0.10 / Mtok
    assert long_ == (pytest.approx(100_001 * 0.5 / M), True)  # $0.50 / Mtok
    # cache tokens count toward the prompt length
    mixed = {"input_tokens": 60_000, "cache_read_input_tokens": 60_000}
    assert llm_call_cost_usd("anthropic", "claude-haiku-5-5", mixed)[
        0
    ] == pytest.approx((0.5 * 60_000 + 0.05 * 60_000) / M)


def test_unlisted_model_is_an_upper_bound_flagged_unknown():
    usd, known = llm_call_cost_usd(
        "anthropic", "claude-unheard-of", {"input_tokens": M}
    )
    assert known is False
    assert usd == max(
        p.rates.input_usd_per_mtok for p in falaw.list_llm_prices("anthropic")
    )


def test_openai_cached_input_is_billed_at_the_cached_rate():
    usage = {
        "input_tokens": 1000,
        "output_tokens": 100,
        "input_tokens_details": {"cached_tokens": 400},
    }
    expected = (600 * 1.25 + 400 * 0.125 + 100 * 10.0) / M
    assert llm_call_cost_usd("openai", "gpt-5", usage) == (
        pytest.approx(expected),
        True,
    )


def test_openai_chat_completions_shape_matches_responses_shape():
    responses = {
        "input_tokens": 900,
        "output_tokens": 50,
        "input_tokens_details": {"cached_tokens": 300},
    }
    chat = {
        "prompt_tokens": 900,
        "completion_tokens": 50,
        "prompt_tokens_details": {"cached_tokens": 300},
    }
    assert llm_call_cost_usd("openai", "gpt-4o", responses) == llm_call_cost_usd(
        "openai", "gpt-4o", chat
    )


def test_openai_dated_snapshot_is_not_priced_as_its_family():
    assert (
        llm_call_cost_usd("openai", "gpt-4o-2024-05-13", {"input_tokens": 1})[1]
        is False
    )


def test_usage_may_be_an_sdk_object():
    usage = types.SimpleNamespace(
        input_tokens=M,
        output_tokens=M,
        cache_read_input_tokens=None,
        cache_creation_input_tokens=None,
    )
    assert llm_call_cost_usd("anthropic", "claude-opus-4-7", usage) == (30.0, True)


@pytest.mark.parametrize(
    "junk",
    [
        None,
        {},
        {"input_tokens": -5},
        {"input_tokens": True},
        {"input_tokens": "abc"},
        {"input_tokens": float("nan")},
    ],
)
def test_junk_usage_costs_zero_not_an_exception(junk):
    assert llm_call_cost_usd("anthropic", "claude-opus-4-7", junk) == (0.0, True)


@pytest.mark.parametrize("count", [1e6, "1000000", 1_000_000.0])
def test_counts_that_are_not_python_ints_are_still_priced(count):
    assert llm_call_cost_usd(
        "anthropic", "claude-opus-4-7", {"input_tokens": count}
    ) == (5.0, True)
    assert llm_call_cost_usd("openai", "gpt-4o", {"prompt_tokens": count}) == (
        2.5,
        True,
    )


def test_one_hour_cache_writes_cost_twice_the_input_rate():
    usage = {
        "cache_creation_input_tokens": M,
        "cache_creation": {"ephemeral_1h_input_tokens": M},
    }
    assert llm_call_cost_usd("anthropic", "claude-opus-4-7", usage) == (10.0, True)
    half = {
        "cache_creation_input_tokens": M,
        "cache_creation": {"ephemeral_1h_input_tokens": M // 2},
    }
    assert llm_call_cost_usd("anthropic", "claude-opus-4-7", half) == (8.125, True)


def test_unknown_model_bound_covers_long_prompt_rates_of_a_caller_table():
    rates = falaw.llm_prices.LlmPriceRates
    table = {
        ("anthropic", "m"): falaw.LlmPrice(
            provider="anthropic",
            model="m",
            rates=rates(input_usd_per_mtok=1.0, output_usd_per_mtok=1.0),
            long_prompt_over_tokens=10,
            long_prompt_rates=rates(
                input_usd_per_mtok=100.0, output_usd_per_mtok=100.0
            ),
        )
    }
    usage = {"input_tokens": 11}
    known = llm_call_cost_usd("anthropic", "m", usage, prices=table)
    unknown = llm_call_cost_usd("anthropic", "other", usage, prices=table)
    assert unknown[1] is False and unknown[0] >= known[0]


def test_openai_cached_beyond_input_is_not_priced_lower():
    usage = {"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": 1000}}
    assert llm_call_cost_usd("openai", "gpt-4o", usage)[0] == pytest.approx(
        1000 * 1.25 / M
    )


def test_loaded_table_is_read_only():
    with pytest.raises(TypeError):
        load_llm_prices()[("openai", "x")] = None


def test_non_string_model_is_unknown_not_a_crash():
    assert llm_call_cost_usd("openai", 5, {"input_tokens": 1})[1] is False


def test_unknown_provider_is_an_informative_error():
    with pytest.raises(ValueError, match="anthropic, openai"):
        llm_call_cost_usd("mistral", "x", {})


def test_caller_supplied_table():
    table = {
        ("openai", "mine"): falaw.LlmPrice(
            provider="openai",
            model="mine",
            rates=falaw.llm_prices.LlmPriceRates(
                input_usd_per_mtok=1.0, output_usd_per_mtok=2.0
            ),
        )
    }
    assert llm_call_cost_usd("openai", "mine", {"input_tokens": M}, prices=table) == (
        1.0,
        True,
    )


def test_every_row_is_dated_and_sourced():
    for p in falaw.list_llm_prices():
        assert p.date and p.source, p.model
    assert falaw.get_llm_price("openai", "gpt-5").date == "2026-09-28"


def test_table_covers_every_model_the_three_copies_priced():
    """The union of reelee's two tables and foley's subset (falaw#81)."""
    anthropic = {
        "claude-fable-5-1",
        "claude-fable-5",
        "claude-opus-5-5",
        "claude-opus-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-sonnet-5-5",
        "claude-sonnet-5",
        "claude-sonnet-4-6",
        "claude-haiku-5-5",
        "claude-haiku-4-5",
    }
    openai = {
        "gpt-5.1",
        "gpt-5",
        "gpt-5-mini",
        "gpt-5-nano",
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4o",
        "gpt-4o-mini",
    }
    listed = {(p.provider, p.model) for p in load_llm_prices().values()}
    assert listed >= {("anthropic", m) for m in anthropic} | {
        ("openai", m) for m in openai
    }


def test_table_file_is_valid_json_with_rows():
    import os

    path = os.path.join(os.path.dirname(falaw.__file__), "data", PRICES_FILENAME)
    assert json.load(open(path))["rows"]
