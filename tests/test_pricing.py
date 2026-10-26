"""Tests for the fal pricing refresh (falaw#18). Fully offline: the HTTP
seam is stubbed; no test may reach fal."""

from __future__ import annotations

import json

import pytest

from falaw import CallPlan, Plan
from falaw.cost import estimate_call_cost
from falaw.base import CostEstimate, ModelRecord
from falaw.pricing import (
    MAX_IDS_PER_REQUEST,
    fetch_model_prices,
    refresh_model_prices,
)


def _stub_http(prices_by_id: dict, calls: list | None = None):
    """An HttpGetJson stub serving canned rows, recording each request."""

    def get(url, params, headers):
        requested = [value for key, value in params if key == "endpoint_id"]
        if calls is not None:
            calls.append(requested)
        assert headers["Authorization"].startswith("Key ")
        return {
            "prices": [
                dict(prices_by_id[i], endpoint_id=i)
                for i in requested
                if i in prices_by_id
            ],
            "next_cursor": None,
            "has_more": False,
        }

    return get


def _catalogue(tmp_path, records):
    path = tmp_path / "models.json"
    path.write_text(json.dumps(records))
    return str(path)


def _record(id_, **extra):
    return {"id": id_, "category": "image", "quality_tier": "balanced", **extra}


class TestRefresh:
    def test_an_api_price_lands_as_a_structured_estimate_with_source_and_date(
        self, tmp_path
    ):
        path = _catalogue(tmp_path, [_record("m/a")])
        http = _stub_http(
            {"m/a": {"unit_price": 0.03, "unit": "image", "currency": "USD"}}
        )

        summary = refresh_model_prices(
            write=True, api_key="k", http_get=http, models_path=path, today="2026-08-15"
        )

        assert summary["newly_priced"] == ["m/a"]
        (rec,) = json.loads(open(path).read())
        assert rec["cost_estimate"] == {
            "kind": "per_image",
            "amount": 0.03,
            "currency": "USD",
            "notes": "fal pricing API, fetched 2026-08-15",
            "source": "api",
        }

    def test_a_moved_rate_flags_the_records_whose_quotes_are_factors_of_it(
        self, tmp_path
    ):
        old = {"kind": "per_second", "amount": 0.1, "source": "api"}
        path = _catalogue(
            tmp_path,
            [
                _record(
                    "m/t",
                    cost_estimate=dict(old),
                    resolution_rate_factors={"4k": 0.5},
                ),
                _record("m/plain", cost_estimate=dict(old)),
            ],
        )
        row = {"unit_price": 0.2, "unit": "video_second"}
        http = _stub_http({"m/t": dict(row), "m/plain": dict(row)})

        summary = refresh_model_prices(api_key="k", http_get=http, models_path=path)

        assert summary["rate_factors_to_review"] == ["m/t"]

    def test_a_kept_empirical_price_does_not_flag_its_factors_but_a_new_one_does(
        self, tmp_path
    ):
        empirical = {"kind": "per_second", "amount": 0.1, "source": "empirical"}
        factors = {"4k": 0.5}
        path = _catalogue(
            tmp_path,
            [
                _record(
                    "m/kept",
                    cost_estimate=empirical,
                    resolution_rate_factors=factors,
                ),
                _record("m/new", resolution_rate_factors=factors),
            ],
        )
        row = {"unit_price": 0.2, "unit": "video_second"}
        http = _stub_http({"m/kept": dict(row), "m/new": dict(row)})

        summary = refresh_model_prices(api_key="k", http_get=http, models_path=path)

        assert summary["rate_factors_to_review"] == ["m/new"]

    def test_an_unmapped_unit_is_recorded_not_guessed_and_keeps_the_old_price(
        self, tmp_path
    ):
        old = {"kind": "per_call", "amount": 0.5, "source": "approximate"}
        path = _catalogue(tmp_path, [_record("m/gpu", cost_estimate=dict(old))])
        http = _stub_http({"m/gpu": {"unit_price": 0.11, "unit": "h100_second"}})

        summary = refresh_model_prices(
            write=True, api_key="k", http_get=http, models_path=path
        )

        assert summary["unmapped_units"] == {"m/gpu": "h100_second"}
        (rec,) = json.loads(open(path).read())
        assert rec["cost_estimate"]["amount"] == 0.5  # untouched
        assert rec["cost_estimate"]["source"] == "approximate"

    def test_a_disagreeing_manual_price_is_overwritten_and_the_delta_reported(
        self, tmp_path
    ):
        path = _catalogue(
            tmp_path,
            [
                _record(
                    "m/a",
                    cost_estimate={
                        "kind": "per_second",
                        "amount": 0.50,
                        "source": "approximate",
                    },
                )
            ],
        )
        http = _stub_http({"m/a": {"unit_price": 0.35, "unit": "video_second"}})

        summary = refresh_model_prices(
            write=True, api_key="k", http_get=http, models_path=path
        )

        (delta,) = summary["price_deltas"]
        assert delta["old"]["amount"] == 0.50 and delta["new"]["amount"] == 0.35
        (rec,) = json.loads(open(path).read())
        assert rec["cost_estimate"]["amount"] == 0.35
        assert rec["cost_estimate"]["source"] == "api"

    def test_an_empirical_price_outranks_the_rate_card_but_the_delta_is_reported(
        self, tmp_path
    ):
        """A measured real bill beats the rate card (which may cover a
        different config tier); the API only outranks 'approximate'/'docs'.
        The disagreement still surfaces as a delta marked kept."""
        path = _catalogue(
            tmp_path,
            [
                _record(
                    "m/e",
                    cost_estimate={
                        "kind": "per_second",
                        "amount": 0.10,
                        "source": "empirical",
                    },
                )
            ],
        )
        http = _stub_http({"m/e": {"unit_price": 0.16, "unit": "seconds"}})

        summary = refresh_model_prices(
            write=True, api_key="k", http_get=http, models_path=path
        )

        (delta,) = summary["price_deltas"]
        assert delta["kept"] == "empirical"
        (rec,) = json.loads(open(path).read())
        assert rec["cost_estimate"]["amount"] == 0.10
        assert rec["cost_estimate"]["source"] == "empirical"

    def test_a_model_the_api_does_not_price_is_reported_and_untouched(self, tmp_path):
        path = _catalogue(tmp_path, [_record("m/a"), _record("m/unknown")])
        http = _stub_http({"m/a": {"unit_price": 0.03, "unit": "image"}})

        summary = refresh_model_prices(api_key="k", http_get=http, models_path=path)

        assert summary["missing_from_api"] == ["m/unknown"]
        # dry-run: the file was not touched at all
        assert "cost_estimate" not in json.loads(open(path).read())[0]

    @pytest.mark.parametrize(
        "row, reason_fragment",
        [
            ({"unit_price": -0.5, "unit": "image"}, "not a positive"),
            ({"unit_price": 0, "unit": "image"}, "not a positive"),
            ({"unit_price": float("nan"), "unit": "image"}, "not a positive"),
            ({"unit": "image"}, "no unit_price"),
            ({"unit_price": 0.1, "unit": "image", "currency": "EUR"}, "not USD"),
        ],
    )
    def test_a_bogus_api_row_is_rejected_loudly_not_stamped(
        self, tmp_path, row, reason_fragment
    ):
        """A negative/NaN price would make every later CallPlan refuse at
        plan time; a zero would plan as known-free through every spend gate;
        non-USD would be summed as USD. None may reach the catalogue."""
        old = {"kind": "per_image", "amount": 0.05, "source": "approximate"}
        path = _catalogue(tmp_path, [_record("m/bogus", cost_estimate=dict(old))])
        http = _stub_http({"m/bogus": row})

        summary = refresh_model_prices(
            write=True, api_key="k", http_get=http, models_path=path
        )

        assert reason_fragment in summary["rejected_rows"]["m/bogus"]
        (rec,) = json.loads(open(path).read())
        assert rec["cost_estimate"] == old  # untouched

    def test_an_equal_price_restamp_is_reported_and_preserves_the_old_note(
        self, tmp_path
    ):
        """Same numbers still means a real write (source, notes, date). It
        must show in the dry-run summary, and a hand-written operational
        note must survive the restamp instead of vanishing."""
        old = {
            "kind": "per_image",
            "amount": 0.03,
            "source": "docs",
            "notes": "KNOWN TO HANG on >4MP inputs",
        }
        path = _catalogue(tmp_path, [_record("m/a", cost_estimate=dict(old))])
        http = _stub_http({"m/a": {"unit_price": 0.03, "unit": "image"}})

        summary = refresh_model_prices(
            write=True, api_key="k", http_get=http, models_path=path, today="2026-08-15"
        )

        assert summary["restamped"] == ["m/a"]
        assert summary["price_deltas"] == []
        (rec,) = json.loads(open(path).read())
        assert rec["cost_estimate"]["source"] == "api"
        assert "KNOWN TO HANG" in rec["cost_estimate"]["notes"]
        assert "2026-08-15" in rec["cost_estimate"]["notes"]

    def test_an_equal_amount_empirical_record_is_left_entirely_alone(self, tmp_path):
        old = {
            "kind": "per_second",
            "amount": 0.10,
            "source": "empirical",
            "notes": "measured 2026-08-01",
        }
        path = _catalogue(tmp_path, [_record("m/e", cost_estimate=dict(old))])
        http = _stub_http({"m/e": {"unit_price": 0.10, "unit": "seconds"}})

        summary = refresh_model_prices(
            write=True, api_key="k", http_get=http, models_path=path
        )

        assert summary["restamped"] == [] and summary["price_deltas"] == []
        (rec,) = json.loads(open(path).read())
        assert rec["cost_estimate"] == old

    def test_dry_run_is_the_default(self, tmp_path):
        path = _catalogue(tmp_path, [_record("m/a")])
        before = open(path).read()
        http = _stub_http({"m/a": {"unit_price": 0.03, "unit": "image"}})

        summary = refresh_model_prices(api_key="k", http_get=http, models_path=path)

        assert summary["write"] is False
        assert open(path).read() == before


class TestFetch:
    def test_requests_are_batched_at_the_endpoint_cap(self):
        ids = [f"m/{i}" for i in range(7)]
        calls: list = []
        http = _stub_http(
            {i: {"unit_price": 0.01, "unit": "image"} for i in ids}, calls
        )

        prices = fetch_model_prices(ids, api_key="k", http_get=http, batch_size=3)

        assert [len(c) for c in calls] == [3, 3, 1]
        assert set(prices) == set(ids)
        assert MAX_IDS_PER_REQUEST == 50  # the default cap is the documented one

    def test_the_live_apis_plural_units_map_and_gpu_units_do_not(self):
        from falaw.pricing import _cost_rule_for_unit

        assert _cost_rule_for_unit("megapixels") == ("per_megapixel", 1.0)
        assert _cost_rule_for_unit("seconds") == ("per_second", 1.0)
        assert _cost_rule_for_unit("image") == ("per_image", 1.0)
        assert _cost_rule_for_unit("h100_seconds") is None

    def test_scaled_units_convert_the_price_not_just_the_kind(self):
        """$6/minute is $0.10/s; '$0.30 per 10 seconds' is $0.03/s; ambiguous
        units (GPU time, 'units', characters) stay unmapped."""
        from falaw.pricing import _cost_rule_for_unit

        kind, mult = _cost_rule_for_unit("minutes")
        assert kind == "per_second" and 6.0 * mult == pytest.approx(0.10)
        kind, mult = _cost_rule_for_unit("10 seconds")
        assert kind == "per_second" and 0.30 * mult == pytest.approx(0.03)
        # "1m tokens" on video models means *video tokens* (resolution x
        # duration), which falaw cannot supply at plan time — mapping it
        # would make those calls unpriceable. Deliberately unmapped.
        assert _cost_rule_for_unit("1m tokens") is None
        assert _cost_rule_for_unit("compute seconds") is None
        assert _cost_rule_for_unit("units") is None
        assert _cost_rule_for_unit("1000 characters") is None

    def test_pagination_is_followed(self):
        pages = [
            {
                "prices": [{"endpoint_id": "m/a", "unit_price": 0.1, "unit": "image"}],
                "next_cursor": "c1",
                "has_more": True,
            },
            {
                "prices": [{"endpoint_id": "m/b", "unit_price": 0.2, "unit": "image"}],
                "next_cursor": None,
                "has_more": False,
            },
        ]
        seen_cursors = []

        def get(url, params, headers):
            seen_cursors.append([v for k, v in params if k == "cursor"])
            return pages.pop(0)

        prices = fetch_model_prices(["m/a", "m/b"], api_key="k", http_get=get)

        assert set(prices) == {"m/a", "m/b"}
        assert seen_cursors == [[], ["c1"]]

    def test_one_unknown_id_does_not_sink_the_batch(self):
        """The live API 404s a whole batch over one unknown id; the fetcher
        must bisect around it and still price everything it can."""
        known = {f"m/{i}": {"unit_price": 0.01, "unit": "image"} for i in range(5)}
        calls: list = []

        def get(url, params, headers):
            requested = [v for k, v in params if k == "endpoint_id"]
            calls.append(requested)
            if any(r not in known for r in requested):
                return None  # the API's blanket 404
            return {
                "prices": [dict(known[i], endpoint_id=i) for i in requested],
                "next_cursor": None,
                "has_more": False,
            }

        ids = list(known) + ["m/unknown"]
        prices = fetch_model_prices(ids, api_key="k", http_get=get)

        assert set(prices) == set(known)
        assert "m/unknown" not in prices

    def test_a_missing_key_is_a_loud_refusal(self, monkeypatch):
        monkeypatch.delenv("FAL_KEY", raising=False)
        monkeypatch.delenv("FAL_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="FAL_KEY"):
            fetch_model_prices(["m/a"], http_get=_stub_http({}))


class TestDisciplineSurvives:
    def test_an_api_priced_per_second_model_without_seconds_is_still_unpriceable(self):
        """The None-not-0.0 rule must survive the new price source."""
        record = ModelRecord(
            id="m/v",
            category="video",
            description="",
            cost_estimate=CostEstimate(kind="per_second", amount=0.35, source="api"),
        )
        assert estimate_call_cost(record) is None
        assert estimate_call_cost(record, seconds=10) == pytest.approx(3.5)


class TestPlanSplit:
    def test_known_cost_and_unknown_count_split_the_total(self):
        priced = CallPlan(
            tool="t",
            application="m/a",
            arguments={},
            output_kind="image",
            estimated_cost_usd=0.25,
        )
        unpriced = CallPlan(
            tool="t",
            application="m/b",
            arguments={},
            output_kind="video",
        )
        hit = CallPlan(
            tool="t",
            application="m/c",
            arguments={},
            output_kind="image",
            estimated_cost_usd=0.10,
            cache_status="hit",
        )
        plan = Plan(calls=(priced, unpriced, hit))

        assert plan.total_cost_usd == pytest.approx(0.25)
        assert plan.known_cost_usd == pytest.approx(0.25)
        assert plan.unknown_call_count == 1
        assert plan.has_unknown_costs is True

    def test_a_fully_priced_plan_has_no_unknowns(self):
        call = CallPlan(
            tool="t",
            application="m/a",
            arguments={},
            output_kind="image",
            estimated_cost_usd=0.25,
        )
        plan = Plan(calls=(call,))

        assert plan.known_cost_usd == plan.total_cost_usd
        assert plan.unknown_call_count == 0
