"""Tests for the llm_rates refresh proposal + staleness check (falaw#56).

Fully offline: both HTTP seams are stubbed from recorded fixture payloads
under ``tests/fixtures/llm_rates/``; no test may reach fal or OpenRouter."""

from __future__ import annotations

import json
import os
import warnings

import pytest

from falaw.llm_rates import (
    DEFAULT_STALENESS_THRESHOLD_DAYS,
    LlmRatesStaleWarning,
    load_llm_rates,
    llm_ceiling_usd,
    warn_if_stale,
)
from falaw.llm_rates_refresh import (
    ANY_LLM_DOC_URL,
    OPENROUTER_MODELS_URL,
    AnyLlmDoc,
    build_proposed_rows,
    diff_llm_rate_tables,
    format_llm_rates_diff,
    parse_any_llm_doc,
    parse_openrouter_long_prompts,
    parse_openrouter_models,
    refresh_llm_rates,
)

_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "llm_rates")


def _any_llm_text() -> str:
    with open(os.path.join(_FIXTURES, "any_llm.txt"), encoding="utf-8") as f:
        return f.read()


def _openrouter_body() -> dict:
    with open(os.path.join(_FIXTURES, "openrouter_models.json"), encoding="utf-8") as f:
        return json.load(f)


def _committed_table_path() -> str:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, "falaw", "data", "llm_rates.json")


def _stub_http(calls: "list[str] | None" = None):
    """A pair of injectable fetchers serving the recorded fixture payloads."""
    text, body = _any_llm_text(), _openrouter_body()

    def get_text(url: str) -> str:
        if calls is not None:
            calls.append(url)
        assert url == ANY_LLM_DOC_URL
        return text

    def get_json(url: str) -> dict:
        if calls is not None:
            calls.append(url)
        assert url == OPENROUTER_MODELS_URL
        return body

    return get_text, get_json


# --- parsers are pure functions ---------------------------------------------


def test_parse_any_llm_doc_reads_the_price_multiple_and_enum():
    doc = parse_any_llm_doc(_any_llm_text())
    assert doc.base_per_call_usd == 0.001
    assert doc.premium_multiple == 10
    assert len(doc.model_enum) == 30
    assert "anthropic/claude-sonnet-4.5" in doc.premium_models
    # On the premium list but not a router `model` option (vision endpoint).
    assert "meta-llama/llama-3.2-90b-vision-instruct" in doc.premium_models
    assert "meta-llama/llama-3.2-90b-vision-instruct" not in doc.model_enum


def test_parse_any_llm_doc_ids_with_periods_do_not_truncate_the_premium_list():
    # openai/gpt-4.1 and anthropic/claude-3.5-sonnet have their own periods;
    # a naive "stop at the first '.'" parse would cut the list off after them.
    doc = parse_any_llm_doc(_any_llm_text())
    assert "openai/gpt-4.1" in doc.premium_models
    assert "deepseek/deepseek-v3.1-terminus" in doc.premium_models  # last in list


@pytest.mark.parametrize(
    "bad_text",
    [
        "no price or model info here",
        "- **Price**: $0.001 per requests\n(no model field)",
    ],
)
def test_parse_any_llm_doc_refuses_a_doc_missing_its_shape(bad_text):
    with pytest.raises(ValueError):
        parse_any_llm_doc(bad_text)


def test_parse_openrouter_models_scales_to_per_million_tokens():
    rates = parse_openrouter_models(_openrouter_body())
    input_rate, output_rate = rates["anthropic/claude-sonnet-4.5"]
    assert input_rate == pytest.approx(3.0)
    assert output_rate == pytest.approx(15.0)


def test_parse_openrouter_models_skips_rows_with_no_positive_price():
    payload = {
        "data": [
            {"id": "a/no-pricing"},
            {"id": "a/zero", "pricing": {"prompt": "0", "completion": "0.001"}},
            {
                "id": "a/bad",
                "pricing": {"prompt": "not-a-number", "completion": "0.001"},
            },
            {
                "id": "a/good",
                "pricing": {"prompt": "0.000001", "completion": "0.000002"},
            },
        ]
    }
    rates = parse_openrouter_models(payload)
    assert set(rates) == {"a/good"}


# --- the proposed table matches the committed one on the fixtures' date ----


def test_proposed_rows_reproduce_the_committed_table_from_the_same_sources():
    # These fixtures are recordings of the same two sources the committed
    # table cites (fetched the same day) -- so a correct parse regenerates it
    # exactly, field for field, and the diff should be empty.
    doc = parse_any_llm_doc(_any_llm_text())
    body = _openrouter_body()
    proposed_rows = build_proposed_rows(
        doc,
        parse_openrouter_models(body),
        date="2026-10-27",
        long_prompts=parse_openrouter_long_prompts(body),
    )

    with open(_committed_table_path(), encoding="utf-8") as f:
        committed_rows = json.load(f)["rows"]

    diff = diff_llm_rate_tables(committed_rows, proposed_rows)
    assert diff == {"added": [], "removed": [], "changed": [], "unchanged": 30}


# --- diffing: never silently overwritten, always reported -------------------


def test_diff_reports_added_and_removed_models():
    committed = [{"model": "a/old", "tier": "standard", "per_call_usd": 0.001}]
    proposed = [{"model": "a/new", "tier": "standard", "per_call_usd": 0.001}]
    diff = diff_llm_rate_tables(committed, proposed)
    assert diff["added"] == ["a/new"]
    assert diff["removed"] == ["a/old"]
    assert diff["changed"] == []


def test_diff_reports_a_repriced_model_as_a_changed_field():
    committed = [
        {
            "model": "a/m",
            "tier": "standard",
            "per_call_usd": 0.001,
            "input_usd_per_mtok": 1.0,
            "output_usd_per_mtok": 2.0,
            "source": "old source",
            "date": "2026-01-01",
        }
    ]
    proposed = [
        {
            "model": "a/m",
            "tier": "standard",
            "per_call_usd": 0.001,
            "input_usd_per_mtok": 1.5,  # repriced upstream
            "output_usd_per_mtok": 2.0,
            "source": "new source",
            "date": "2026-09-07",
        }
    ]
    diff = diff_llm_rate_tables(committed, proposed)
    assert diff["changed"] == [
        {
            "model": "a/m",
            "field": "input_usd_per_mtok",
            "old": 1.0,
            "new": 1.5,
            "source": "new source",
            "date": "2026-09-07",
        }
    ]


def test_diff_reports_a_tier_move_that_would_otherwise_restore_the_undercharge():
    # falaw#50's bug: a model quietly moved from premium to standard (or vice
    # versa) silently restores the 10x under-quote. The diff must surface it.
    committed = [{"model": "a/m", "tier": "premium", "per_call_usd": 0.01}]
    proposed = [{"model": "a/m", "tier": "standard", "per_call_usd": 0.001}]
    diff = diff_llm_rate_tables(committed, proposed)
    fields = {c["field"] for c in diff["changed"]}
    assert fields == {"tier", "per_call_usd"}


def test_diff_ignores_provenance_fields_that_change_on_every_run():
    committed = [
        {
            "model": "a/m",
            "tier": "standard",
            "per_call_usd": 0.001,
            "date": "2026-01-01",
        }
    ]
    proposed = [
        {
            "model": "a/m",
            "tier": "standard",
            "per_call_usd": 0.001,
            "date": "2026-09-07",
        }
    ]
    diff = diff_llm_rate_tables(committed, proposed)
    assert diff == {"added": [], "removed": [], "changed": [], "unchanged": 1}


def test_format_llm_rates_diff_reads_as_a_report():
    diff = {
        "added": ["a/new"],
        "removed": [],
        "changed": [
            {
                "model": "a/m",
                "field": "per_call_usd",
                "old": 0.001,
                "new": 0.002,
                "source": "OpenRouter (https://openrouter.ai/api/v1/models)",
                "date": "2026-09-07",
            }
        ],
        "unchanged": 5,
    }
    text = format_llm_rates_diff(diff)
    assert "a/new" in text
    assert "per_call_usd" in text
    assert "0.001" in text and "0.002" in text
    # The diff report carries provenance for a changed row, not just the number.
    assert "2026-09-07" in text
    assert "openrouter.ai" in text


def test_format_llm_rates_diff_says_no_date_or_source_when_missing():
    diff = {
        "added": [],
        "removed": [],
        "changed": [
            {"model": "a/m", "field": "per_call_usd", "old": 0.001, "new": 0.002}
        ],
        "unchanged": 0,
    }
    text = format_llm_rates_diff(diff)
    assert "no date" in text
    assert "no source" in text


def test_format_llm_rates_diff_says_so_when_nothing_changed():
    diff = {"added": [], "removed": [], "changed": [], "unchanged": 30}
    assert format_llm_rates_diff(diff) == "No changes (30 rows unchanged)."


# --- refresh_llm_rates: the committed table is never written ----------------


def test_refresh_dry_run_touches_no_file():
    get_text, get_json = _stub_http()
    committed_path = _committed_table_path()
    before = open(committed_path, encoding="utf-8").read()

    summary = refresh_llm_rates(
        write=False,
        http_get_any_llm_doc=get_text,
        http_get_openrouter_models=get_json,
        today="2026-10-27",
    )

    assert open(committed_path, encoding="utf-8").read() == before
    assert summary["write"] is False
    assert summary["proposed_path"] is None
    assert summary["diff_path"] is None
    assert summary["diff"]["added"] == []
    assert summary["diff"]["changed"] == []


def test_refresh_write_writes_a_proposal_and_diff_but_never_the_committed_file(
    tmp_path,
):
    get_text, get_json = _stub_http()
    committed_path = _committed_table_path()
    before = open(committed_path, encoding="utf-8").read()
    proposed_path = str(tmp_path / "llm_rates.proposed.json")
    diff_path = str(tmp_path / "llm_rates.diff.txt")

    summary = refresh_llm_rates(
        write=True,
        http_get_any_llm_doc=get_text,
        http_get_openrouter_models=get_json,
        proposed_path=proposed_path,
        diff_path=diff_path,
        today="2026-10-27",
    )

    # The committed table -- the one a test pins the premium set against --
    # is never touched by a write=True refresh.
    assert open(committed_path, encoding="utf-8").read() == before
    assert summary["proposed_path"] == proposed_path
    assert summary["diff_path"] == diff_path

    proposed = json.loads(open(proposed_path, encoding="utf-8").read())
    assert len(proposed["rows"]) == 30
    diff_text = open(diff_path, encoding="utf-8").read()
    assert "No changes" in diff_text


def test_refresh_uses_the_injected_fetchers_not_the_network():
    calls: list[str] = []
    get_text, get_json = _stub_http(calls)
    refresh_llm_rates(
        write=False,
        http_get_any_llm_doc=get_text,
        http_get_openrouter_models=get_json,
        today="2026-10-27",
    )
    assert calls == [ANY_LLM_DOC_URL, OPENROUTER_MODELS_URL]


def test_refresh_dry_run_reports_a_price_change_without_writing_anything(tmp_path):
    # A deliberately stale committed table: one row's per-token rate does not
    # match the (fixture-recorded) live sources any more.
    stale_table = json.loads(open(_committed_table_path(), encoding="utf-8").read())
    for row in stale_table["rows"]:
        if row["model"] == "anthropic/claude-sonnet-4.5":
            row["input_usd_per_mtok"] = 1.0  # was 3.0
    rates_path = tmp_path / "llm_rates.json"
    rates_path.write_text(json.dumps(stale_table))

    get_text, get_json = _stub_http()
    summary = refresh_llm_rates(
        write=False,
        http_get_any_llm_doc=get_text,
        http_get_openrouter_models=get_json,
        rates_path=str(rates_path),
        today="2026-10-27",
    )

    assert rates_path.read_text() == json.dumps(stale_table)  # untouched
    changed = summary["diff"]["changed"]
    (entry,) = [
        c
        for c in changed
        if c["model"] == "anthropic/claude-sonnet-4.5"
        and c["field"] == "input_usd_per_mtok"
    ]
    assert entry["old"] == 1.0
    assert entry["new"] == 3.0
    # The diff carries where the proposed number came from, not just the
    # number, so a human reviewing it doesn't have to open the proposed file.
    assert entry["date"] == "2026-10-27"
    assert "openrouter.ai" in entry["source"]


# --- staleness: warns, never raises, surfaced at quote time -----------------


def test_check_staleness_is_silent_when_fresh():
    from falaw.llm_rates import LlmRate

    fresh = LlmRate(model="a/m", tier="standard", per_call_usd=0.001, date="2026-09-01")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert (
            warn_if_stale(fresh, today=__import__("datetime").date(2026, 9, 7)) is None
        )


def test_check_staleness_warns_but_does_not_raise_when_old():
    import datetime

    from falaw.llm_rates import LlmRate

    old = LlmRate(model="a/m", tier="standard", per_call_usd=0.001, date="2020-01-01")
    with pytest.warns(LlmRatesStaleWarning):
        message = warn_if_stale(old, today=datetime.date(2026, 9, 7))
    assert "a/m" in message
    assert "2020-01-01" in message


def test_check_staleness_warns_on_a_missing_or_malformed_date():
    import datetime

    from falaw.llm_rates import LlmRate

    blank = LlmRate(model="a/m", tier="standard", per_call_usd=0.001, date="")
    with pytest.warns(LlmRatesStaleWarning):
        warn_if_stale(blank, today=datetime.date(2026, 9, 7))


def test_check_staleness_respects_a_custom_threshold():
    import datetime

    from falaw.llm_rates import LlmRate

    rate = LlmRate(model="a/m", tier="standard", per_call_usd=0.001, date="2026-08-01")
    today = datetime.date(2026, 9, 7)  # 37 days later
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert warn_if_stale(rate, threshold_days=90, today=today) is None
    with pytest.warns(LlmRatesStaleWarning):
        warn_if_stale(rate, threshold_days=10, today=today)


def test_llm_ceiling_usd_warns_when_the_committed_table_is_stale(monkeypatch):
    import datetime

    from falaw.llm_rates import get_llm_rate

    # Push "today" far enough past the committed row's date (read, not pinned,
    # so a refresh does not break this test) that it reads as stale.
    committed = get_llm_rate("anthropic/claude-sonnet-4.5").date
    far_future = datetime.date.fromisoformat(committed) + datetime.timedelta(
        days=DEFAULT_STALENESS_THRESHOLD_DAYS + 1
    )

    class _FixedDate(datetime.date):
        @classmethod
        def today(cls):
            return far_future

    monkeypatch.setattr("falaw.llm_rates.datetime.date", _FixedDate)
    with pytest.warns(LlmRatesStaleWarning):
        llm_ceiling_usd("anthropic/claude-sonnet-4.5")


def test_llm_ceiling_usd_does_not_warn_for_a_fresh_override_table():
    from falaw.llm_rates import LlmRate

    fresh = {
        "my/model": LlmRate(
            model="my/model",
            tier="standard",
            per_call_usd=0.5,
            date="2026-09-07",
        )
    }
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        llm_ceiling_usd("my/model", rates=fresh)


def test_load_llm_rates_itself_never_warns_or_raises_on_import():
    # Importing/loading the table must never blow up, whatever its date --
    # the staleness check is opt-in at the quote call, not at load time.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        load_llm_rates()


def test_repeated_quotes_of_the_same_stale_row_warn_once_not_per_call():
    # A blank date always reads as stale. Without dedup, a caller quoting the
    # same override row in a loop would get one LlmRatesStaleWarning per
    # call -- noisy enough to bury a real signal. Python's default warning
    # filter dedups by (message, category, module, lineno); a fixed
    # `stacklevel` inside `llm_ceiling_usd` is what makes that collapse work.
    from falaw.llm_rates import LlmRate

    blank = {
        "my/blank-date-model": LlmRate(
            model="my/blank-date-model", tier="standard", per_call_usd=0.001, date=""
        )
    }
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for _ in range(5):
            llm_ceiling_usd("my/blank-date-model", rates=blank)
        assert len(caught) == 5  # "always" bypasses dedup, by design, to see this

    with warnings.catch_warnings(record=True) as caught:
        warnings.resetwarnings()  # restore the default (deduping) filter
        for _ in range(5):
            llm_ceiling_usd("my/blank-date-model", rates=blank)
        assert len(caught) == 1


# --- long-prompt tiers from pricing.overrides (falaw#124) -------------------


def test_overrides_become_a_long_prompt_block_starting_at_the_threshold():
    blocks = parse_openrouter_long_prompts(_openrouter_body())
    assert blocks["anthropic/claude-haiku-5.5"] == {
        "over_input_tokens": 99_999,  # min_prompt_tokens 100,000 is billed long
        "input_usd_per_mtok": 0.5,
        "output_usd_per_mtok": 2.5,
    }
    assert set(blocks) == {
        "anthropic/claude-haiku-5.5",
        "anthropic/claude-sonnet-4.5",
        "google/gemini-2.5-pro",
    }


def test_several_overrides_collapse_to_one_block_that_never_under_quotes():
    payload = {
        "data": [
            {
                "id": "a/m",
                "pricing": {
                    "overrides": [
                        {
                            "min_prompt_tokens": 500,
                            "prompt": "0.000004",
                            "completion": "0.000001",
                        },
                        {
                            "min_prompt_tokens": 100,
                            "prompt": "0.000002",
                            "completion": "0.000003",
                        },
                    ]
                },
            }
        ]
    }
    assert parse_openrouter_long_prompts(payload)["a/m"] == {
        "over_input_tokens": 99,
        "input_usd_per_mtok": 4.0,
        "output_usd_per_mtok": 3.0,
    }


@pytest.mark.parametrize(
    "override",
    [
        {"prompt": "0.000002", "completion": "0.000003"},  # no threshold
        {"min_prompt_tokens": "100", "prompt": "0.000002", "completion": "0.000003"},
        {"min_prompt_tokens": 0, "prompt": "0.000002", "completion": "0.000003"},
        {"min_prompt_tokens": 100, "prompt": "0", "completion": "0.000003"},
        {"min_prompt_tokens": 100, "completion": "0.000003"},
    ],
)
def test_an_unparseable_override_yields_no_block(override):
    payload = {"data": [{"id": "a/m", "pricing": {"overrides": [override]}}]}
    assert parse_openrouter_long_prompts(payload) == {}


def test_proposed_rows_carry_the_block_and_the_diff_reports_a_change_to_it():
    doc = parse_any_llm_doc(_any_llm_text())
    body = _openrouter_body()
    rows = build_proposed_rows(
        doc,
        parse_openrouter_models(body),
        date="2026-10-27",
        long_prompts=parse_openrouter_long_prompts(body),
    )
    by_model = {r["model"]: r for r in rows}
    assert (
        by_model["anthropic/claude-sonnet-4.5"]["long_prompt"]["over_input_tokens"]
        == 199_999
    )
    assert "long_prompt" not in by_model["openai/gpt-4o"]

    without = build_proposed_rows(doc, parse_openrouter_models(body), date="2026-10-27")
    changed = diff_llm_rate_tables(rows, without)["changed"]
    assert {(c["model"], c["field"]) for c in changed} == {
        ("anthropic/claude-haiku-5.5", "long_prompt"),
        ("anthropic/claude-sonnet-4.5", "long_prompt"),
        ("google/gemini-2.5-pro", "long_prompt"),
    }
