"""fal's run metrics on each plan outcome (falaw#127).

A per-compute-second endpoint is priced by how long fal's runner worked, which
fal reports as ``Completed.metrics["inference_time"]``. ``execute_plan`` records
it on the call's :class:`falaw.CallOutcome`, per call, even when calls run
concurrently. Offline: ``fal_client`` is a stub and the asset transport is the
fake one from ``conftest``.
"""

from __future__ import annotations

import sys
import threading
import types

import pytest

from falaw import CallOutcome, CallPlan, Plan, execute_plan_isolated


class _InProgress:
    def __init__(self, logs=()):
        self.logs = logs


class _Completed:
    def __init__(self, logs, metrics):
        self.logs, self.metrics = logs, metrics


APP = "fal-ai/a"


def _install_fal(monkeypatch, metrics_by_prompt: dict, *, barrier=None):
    """A stub whose ``subscribe`` ends each run with ``Completed(metrics)``,
    the metrics chosen by the call's prompt (one application serves them all)."""

    def subscribe(application, *, arguments, with_logs, on_queue_update):
        if barrier is not None:
            barrier.wait(timeout=5)  # every call in flight at once
        prompt = arguments["prompt"]
        on_queue_update(_InProgress())
        on_queue_update(_Completed(logs=[], metrics=metrics_by_prompt.get(prompt)))
        if barrier is not None:
            barrier.wait(timeout=5)  # every done event emitted before any returns
        return {"images": [{"url": f"http://x/{prompt}.png"}]}

    fake = types.SimpleNamespace(
        InProgress=_InProgress, Completed=_Completed, subscribe=subscribe
    )
    monkeypatch.setitem(sys.modules, "fal_client", fake)


def _image(prompt: str = "p") -> CallPlan:
    return CallPlan(
        tool="generate_image",
        application=APP,
        arguments={"prompt": prompt},
        output_kind="image",
    )


def test_each_outcome_carries_its_own_runs_metrics_even_concurrently(monkeypatch):
    # One application for every call: a capture that heard its neighbours'
    # events (a leak across workers) could not tell them apart by application.
    prompts = ["a", "b", "c"]
    metrics = {p: {"inference_time": float(i + 1)} for i, p in enumerate(prompts)}
    _install_fal(monkeypatch, metrics, barrier=threading.Barrier(len(prompts)))

    report = execute_plan_isolated(
        Plan(calls=tuple(_image(p) for p in prompts)), concurrency=len(prompts)
    )
    assert [o.metrics for o in report.outcomes] == [metrics[p] for p in prompts]
    assert [o.inference_time_s for o in report.outcomes] == [1.0, 2.0, 3.0]


def test_the_outcomes_metrics_are_a_copy_not_the_events_dict(monkeypatch):
    _install_fal(monkeypatch, {"p": {"inference_time": 1.0}})
    events = []
    outcome = execute_plan_isolated(
        Plan(calls=(_image(),)), on_event=events.append
    ).outcomes[0]
    (done,) = [e for e in events if e.kind == "done"]
    assert outcome.metrics == done.metrics and outcome.metrics is not done.metrics


def test_a_cache_hit_has_no_metrics_nothing_ran(monkeypatch):
    _install_fal(monkeypatch, {"p": {"inference_time": 2.5}})
    plan = Plan(calls=(_image(),))

    first = execute_plan_isolated(plan).outcomes[0]
    again = execute_plan_isolated(plan).outcomes[0]
    assert (first.cache_hit, first.inference_time_s) == (False, 2.5)
    assert (again.cache_hit, again.metrics, again.inference_time_s) == (
        True,
        None,
        None,
    )


@pytest.mark.parametrize("reported", [None, {}])
def test_no_reported_metrics_is_none(monkeypatch, reported):
    _install_fal(monkeypatch, {"p": reported})
    outcome = execute_plan_isolated(Plan(calls=(_image(),))).outcomes[0]
    assert (outcome.metrics, outcome.inference_time_s) == (None, None)


def test_the_callers_on_event_still_hears_the_done_event_once(monkeypatch):
    _install_fal(monkeypatch, {"p": {"inference_time": 1.0}})
    events = []
    execute_plan_isolated(Plan(calls=(_image(),)), on_event=events.append)
    done = [e for e in events if e.kind == "done"]
    assert len(done) == 1 and done[0].metrics == {"inference_time": 1.0}


def test_a_dry_run_records_no_metrics(monkeypatch):
    _install_fal(monkeypatch, {})
    outcome = execute_plan_isolated(Plan(calls=(_image(),)), dry_run=True).outcomes[0]
    assert outcome.metrics is None


@pytest.mark.parametrize(
    "seconds", [-1.0, "3", True, float("nan"), float("inf"), 10**400, None]
)
def test_an_inference_time_that_is_not_a_duration_reads_none(seconds):
    outcome = CallOutcome(
        index=0,
        call=_image(),
        status="blocked",
        reason="r",
        metrics={"inference_time": seconds},
    )
    assert outcome.inference_time_s is None


def test_an_integer_inference_time_reads_as_seconds():
    outcome = CallOutcome(
        index=0,
        call=_image(),
        status="blocked",
        reason="r",
        metrics={"inference_time": 4},
    )
    assert outcome.inference_time_s == 4.0
