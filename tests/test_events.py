"""Progress event emission from call_fal / cached_call_fal."""

from __future__ import annotations

import dataclasses
import pickle
import sys
import types
from typing import Any
from unittest.mock import MagicMock

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


def _install_fake_fal_client(*, in_progress_logs=(), result=None, raises=None):
    """Inject a stub fal_client module that drives on_queue_update."""

    class _InProgress:
        def __init__(self, logs):
            self.logs = logs

    def subscribe(application, *, arguments, with_logs, on_queue_update):
        if raises is not None:
            raise raises
        for batch in in_progress_logs:
            on_queue_update(_InProgress(batch))
        return result if result is not None else {"ok": True}

    fake = types.SimpleNamespace(InProgress=_InProgress, subscribe=subscribe)
    sys.modules["fal_client"] = fake
    return fake


def test_call_fal_emits_queued_then_done(monkeypatch):
    _install_fake_fal_client()
    from falaw import call_fal
    from falaw.events import subscribe

    events = []
    subscribe(events.append)
    call_fal("fal-ai/flux/dev", {"prompt": "p"})
    kinds = [e.kind for e in events]
    assert kinds == ["queued", "done"]
    assert events[0].application == "fal-ai/flux/dev"
    assert events[0].call_id == events[1].call_id


def test_call_fal_emits_log_for_each_message(monkeypatch):
    _install_fake_fal_client(
        in_progress_logs=[
            [{"message": "starting"}],
            [{"message": "halfway"}, {"message": "almost"}],
        ]
    )
    from falaw import call_fal
    from falaw.events import subscribe

    events = []
    subscribe(events.append)
    call_fal("fal-ai/flux/dev", {"prompt": "p"})
    kinds = [e.kind for e in events]
    assert kinds == ["queued", "log", "log", "log", "done"]
    log_messages = [e.message for e in events if e.kind == "log"]
    assert log_messages == ["starting", "halfway", "almost"]


def test_call_fal_emits_progress_when_logs_empty(monkeypatch):
    _install_fake_fal_client(in_progress_logs=[[], []])
    from falaw import call_fal
    from falaw.events import subscribe

    events = []
    subscribe(events.append)
    call_fal("fal-ai/x", {})
    kinds = [e.kind for e in events]
    assert kinds == ["queued", "progress", "progress", "done"]


def test_call_fal_emits_error_then_raises(monkeypatch):
    _install_fake_fal_client(raises=RuntimeError("boom"))
    from falaw import call_fal
    from falaw.events import subscribe

    events = []
    subscribe(events.append)
    with pytest.raises(RuntimeError, match="boom"):
        call_fal("fal-ai/x", {}, journal_errors=False)
    assert events[-1].kind == "error"
    assert "boom" in events[-1].message


def test_per_call_on_event_hook_fires(monkeypatch):
    _install_fake_fal_client()
    from falaw import call_fal

    seen = []
    call_fal("fal-ai/x", {}, on_event=seen.append)
    assert [e.kind for e in seen] == ["queued", "done"]


def test_on_log_still_works_for_backward_compat(monkeypatch):
    _install_fake_fal_client(
        in_progress_logs=[[{"message": "tick"}, {"message": "tock"}]]
    )
    from falaw import call_fal

    captured = []
    call_fal("fal-ai/x", {}, on_log=captured.append)
    assert captured == ["tick", "tock"]


def test_cached_call_fal_emits_cache_hit_when_present(monkeypatch):
    _install_fake_fal_client(result={"r": 1})
    from falaw import cache, cached_call_fal
    from falaw.events import subscribe

    cache.cache_put("fal-ai/x", {"prompt": "p"}, {"r": 1}, note="seed")

    events = []
    subscribe(events.append)
    cached_call_fal("fal-ai/x", {"prompt": "p"})
    kinds = [e.kind for e in events]
    assert kinds == ["cache_hit"]


def test_cached_call_fal_passes_through_to_call_fal_on_miss(monkeypatch):
    _install_fake_fal_client(result={"r": 2})
    from falaw import cached_call_fal
    from falaw.events import subscribe

    events = []
    subscribe(events.append)
    cached_call_fal("fal-ai/x", {"prompt": "miss"})
    kinds = [e.kind for e in events]
    assert kinds == ["queued", "done"]


def test_global_subscriber_isolated_from_per_call(monkeypatch):
    _install_fake_fal_client()
    from falaw import call_fal
    from falaw.events import subscribe

    global_events = []
    per_call_events = []
    subscribe(global_events.append)

    call_fal("fal-ai/x", {}, on_event=per_call_events.append)

    # Both lists see the same events.
    assert [e.kind for e in global_events] == ["queued", "done"]
    assert [e.kind for e in per_call_events] == ["queued", "done"]


def _install_fake_fal_client_with_queue(updates):
    """A stub whose ``subscribe`` replays ``updates`` (Queued / InProgress objects)."""

    class _Queued:
        def __init__(self, position):
            self.position = position

    class _InProgress:
        def __init__(self, logs=()):
            self.logs = logs

    def subscribe(application, *, arguments, with_logs, on_queue_update):
        for make in updates:
            on_queue_update(make(_Queued, _InProgress))
        return {"ok": True}

    fake = types.SimpleNamespace(
        Queued=_Queued, InProgress=_InProgress, subscribe=subscribe
    )
    sys.modules["fal_client"] = fake
    return fake


def test_the_providers_own_phase_rides_the_events_it_produces():
    """fal's QUEUED carries a position; IN_PROGRESS marks the call as being made.
    Our own ``queued`` (submitted) and ``done`` say nothing about the provider."""
    _install_fake_fal_client_with_queue(
        [
            lambda Q, I: Q(2),
            lambda Q, I: Q(0),
            lambda Q, I: I(),
            lambda Q, I: I([{"message": "step 1"}]),
            lambda Q, I: I([{"level": "info"}]),  # no message: still IN_PROGRESS
        ]
    )
    from falaw import call_fal
    from falaw.events import subscribe

    events = []
    subscribe(events.append)
    call_fal("fal-ai/x", {})
    seen = [(e.kind, e.provider_phase, e.queue_position) for e in events]
    assert seen == [
        ("queued", None, None),
        ("provider_queued", "in_queue", 2),
        ("provider_queued", "in_queue", 0),
        ("progress", "in_progress", None),
        ("log", "in_progress", None),
        ("progress", "in_progress", None),
        ("done", None, None),
    ]


def test_listening_is_scoped_to_its_block_and_its_context():
    from concurrent.futures import ThreadPoolExecutor

    _install_fake_fal_client()
    from falaw import call_fal
    from falaw.events import listening

    mine, other = [], []

    def run(sink):
        with listening(sink.append):
            call_fal("fal-ai/x", {})

    with ThreadPoolExecutor(2) as pool:  # two "jobs", each hears only its own call
        list(pool.map(run, [mine, other]))
    assert [e.kind for e in mine] == ["queued", "done"]
    assert [e.kind for e in other] == ["queued", "done"]

    call_fal("fal-ai/x", {})  # outside the block: nobody is listening
    assert len(mine) == len(other) == 2
    with listening(None):  # a caller with no sink needs no `if`
        call_fal("fal-ai/x", {})
    assert len(mine) == len(other) == 2


def test_a_callback_named_by_several_routes_hears_each_event_once():
    _install_fake_fal_client()
    from falaw import call_fal
    from falaw.events import listening, subscribe

    heard = []
    subscribe(heard.append)
    with listening(heard.append):
        call_fal("fal-ai/x", {}, on_event=heard.append)
    assert [e.kind for e in heard] == ["queued", "done"]


def test_a_queue_that_does_not_move_is_reported_once():
    _install_fake_fal_client_with_queue(
        [lambda Q, I: Q(4)] * 5 + [lambda Q, I: Q(3), lambda Q, I: Q(3)]
    )
    from falaw import call_fal
    from falaw.events import subscribe

    events = []
    subscribe(events.append)
    call_fal("fal-ai/x", {})
    assert [e.queue_position for e in events if e.kind == "provider_queued"] == [4, 3]


def _install_fake_fal_client_completing(monkeypatch, metrics, *, completed_cls=None):
    """A stub whose ``subscribe`` ends with fal's ``Completed(logs, metrics)``."""

    class _InProgress:
        def __init__(self, logs=()):
            self.logs = logs

    class _Completed:
        def __init__(self, logs, metrics):
            self.logs, self.metrics = logs, metrics

    completed_cls = completed_cls or _Completed

    def subscribe(application, *, arguments, with_logs, on_queue_update):
        on_queue_update(_InProgress())
        on_queue_update(completed_cls(logs=[], metrics=metrics))
        return {"video": {"url": "u"}}

    fake = types.SimpleNamespace(
        InProgress=_InProgress, Completed=completed_cls, subscribe=subscribe
    )
    monkeypatch.setitem(sys.modules, "fal_client", fake)


def test_completed_metrics_ride_the_done_event_not_the_response(monkeypatch):
    _install_fake_fal_client_completing(monkeypatch, {"inference_time": 3.25})
    from falaw import call_fal

    events = []
    response = call_fal("fal-ai/x", {}, on_event=events.append)
    assert response == {"video": {"url": "u"}}  # the model's output, untouched
    done = events[-1]
    assert done.kind == "done" and done.metrics == {"inference_time": 3.25}
    assert all(e.metrics is None for e in events[:-1])
    # Sinks serialise events (nw's job record uses ``asdict``): keep that working.
    assert dataclasses.asdict(done)["metrics"] == {"inference_time": 3.25}
    assert pickle.loads(pickle.dumps(done)) == done
    hash(done)  # events stay hashable


def test_the_real_fal_client_completed_status_is_recognised(monkeypatch):
    # Other tests leave a stub in sys.modules["fal_client"]: reach the real one.
    monkeypatch.delitem(sys.modules, "fal_client", raising=False)
    fal_client = pytest.importorskip("fal_client.client")
    _install_fake_fal_client_completing(
        monkeypatch, {"inference_time": 2.0}, completed_cls=fal_client.Completed
    )
    from falaw import call_fal

    events = []
    call_fal("fal-ai/x", {}, on_event=events.append)
    assert events[-1].metrics == {"inference_time": 2.0}


@pytest.mark.parametrize("metrics", [{}, None])
def test_no_completed_metrics_is_none_not_empty(monkeypatch, metrics):
    _install_fake_fal_client_completing(monkeypatch, metrics)
    from falaw import call_fal

    events = []
    call_fal("fal-ai/x", {}, on_event=events.append)
    assert events[-1].kind == "done" and events[-1].metrics is None


def test_malformed_metrics_degrade_and_never_lose_the_billed_result(monkeypatch):
    _install_fake_fal_client_completing(monkeypatch, "oops")
    from falaw import call_fal
    from falaw.degrade import deferred_degrade_warnings

    events = []
    with deferred_degrade_warnings() as complaints:
        response = call_fal("fal-ai/x", {}, on_event=events.append)
    assert response == {"video": {"url": "u"}}
    assert events[-1].kind == "done" and events[-1].metrics is None
    assert any("non-mapping metrics" in c for c in complaints)


def test_cached_call_fal_reports_metrics_on_a_run_and_none_on_a_hit(monkeypatch):
    _install_fake_fal_client_completing(monkeypatch, {"inference_time": 1.5})
    from falaw import cached_call_fal

    ran, hit = [], []
    cached_call_fal("fal-ai/x", {"prompt": "p"}, on_event=ran.append)
    cached_call_fal("fal-ai/x", {"prompt": "p"}, on_event=hit.append)
    assert ran[-1].metrics == {"inference_time": 1.5}
    assert [e.kind for e in hit] == ["cache_hit"] and hit[0].metrics is None
