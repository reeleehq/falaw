"""Per-compute-second pricing from fal's reported run time (falaw#144).

A ``per_compute_second`` model bills the runner's machine time, which only the
finished run knows (``Completed.metrics["inference_time"]``, recorded on the
outcome by falaw#127). A plan leaves it unknown; the run prices it, and the
artifact's stamp and the report's sums read the same number. Offline: the fal
client is a stub, the asset transport is ``conftest``'s fake.
"""

from __future__ import annotations

import sys
import types

import pytest

from falaw import CallPlan, Plan, execute_plan_isolated
from falaw.base import CostEstimate, ModelRecord
from falaw.cost import compute_time_cost_usd, estimate_call_cost

APP = "fal-ai/compute-billed"
RATE = 0.0005  # USD per compute second


@pytest.fixture(autouse=True)
def _compute_billed_model(monkeypatch):
    """A catalogue that also prices ``APP`` per compute second."""
    import falaw.registry as registry

    record = ModelRecord(
        id=APP,
        category="audio",
        cost_estimate=CostEstimate(kind="per_compute_second", amount=RATE),
    )
    real = registry.get_model
    monkeypatch.setattr(
        registry, "get_model", lambda id: record if id == APP else real(id)
    )
    return record


class _InProgress:
    def __init__(self, logs=()):
        self.logs = logs


class _Completed:
    def __init__(self, logs, metrics):
        self.logs, self.metrics = logs, metrics


def _install_fal(monkeypatch, metrics):
    calls = []

    def subscribe(application, *, arguments, with_logs, on_queue_update):
        calls.append(application)
        on_queue_update(_InProgress())
        on_queue_update(_Completed(logs=[], metrics=metrics))
        return {"audio": {"url": f"http://x/{arguments['prompt']}.wav"}}

    fake = types.SimpleNamespace(
        InProgress=_InProgress, Completed=_Completed, subscribe=subscribe
    )
    monkeypatch.setitem(sys.modules, "fal_client", fake)
    return calls


def _call(prompt="p") -> CallPlan:
    return CallPlan(
        tool="generate_audio",
        application=APP,
        arguments={"prompt": prompt},
        output_kind="audio",
        estimated_cost_usd=None,  # what a plan can say about machine time
    )


def test_a_plan_cannot_price_machine_time(_compute_billed_model):
    assert estimate_call_cost(_compute_billed_model) is None
    assert Plan(calls=(_call(),)).has_unknown_costs is True


def test_the_run_prices_it_from_the_reported_inference_time(monkeypatch):
    _install_fal(monkeypatch, {"inference_time": 4.0})
    report = execute_plan_isolated(Plan(calls=(_call(),)))
    outcome = report.outcomes[0]
    assert outcome.billed_cost_usd == pytest.approx(4.0 * RATE)
    assert outcome.artifact.cost_usd == pytest.approx(4.0 * RATE)  # one rule
    assert report.estimated_spend_usd == pytest.approx(4.0 * RATE)
    assert report.has_unknown_costs is False


@pytest.mark.parametrize("metrics", [None, {}, {"inference_time": "4"}])
def test_no_usable_run_time_stays_unknown_never_free(monkeypatch, metrics):
    _install_fal(monkeypatch, metrics)
    report = execute_plan_isolated(Plan(calls=(_call(),)))
    assert report.outcomes[0].artifact.cost_usd is None
    assert report.has_unknown_costs is True
    assert report.estimated_spend_usd == 0.0


def test_a_cache_hit_bills_nothing(monkeypatch):
    calls = _install_fal(monkeypatch, {"inference_time": 4.0})
    plan = Plan(calls=(_call(),))
    execute_plan_isolated(plan)
    again = execute_plan_isolated(plan)
    assert calls == [APP]
    assert again.outcomes[0].cache_hit
    assert again.outcomes[0].artifact.cost_usd == 0.0
    assert again.has_unknown_costs is False


def test_a_dry_run_has_no_run_time_so_stays_unknown(monkeypatch):
    _install_fal(monkeypatch, {"inference_time": 4.0})
    report = execute_plan_isolated(Plan(calls=(_call(),)), dry_run=True)
    assert report.has_unknown_costs is True


def test_a_plan_time_estimate_wins_over_the_run_time():
    from falaw.outcomes import billed_cost_usd

    priced = CallPlan(
        tool="t",
        application=APP,
        arguments={},
        output_kind="audio",
        estimated_cost_usd=0.02,
    )
    assert billed_cost_usd(priced, cache_hit=False, inference_time_s=100.0) == 0.02


def test_only_a_per_compute_second_model_is_priced_from_run_time():
    assert compute_time_cost_usd(APP, inference_time_s=2.0) == pytest.approx(2 * RATE)
    assert compute_time_cost_usd(APP, inference_time_s=None) is None
    assert compute_time_cost_usd("fal-ai/flux/dev", inference_time_s=2.0) is None
    assert compute_time_cost_usd("fal-ai/not-catalogued", inference_time_s=2.0) is None
