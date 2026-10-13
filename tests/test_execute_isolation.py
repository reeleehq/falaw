"""Partial results, bounded concurrency, and per-call isolation (falaw#20).

Every test here is offline: ``fal_client`` is replaced by a stub module and the
asset transport by ``conftest``'s in-memory one. Nothing in this file may ever
reach fal.
"""

from __future__ import annotations

import json
import sys
import threading
import types
import warnings
from dataclasses import replace
from typing import Optional

import pytest

from falaw import (
    CallOutcome,
    CallPlan,
    ExecutionReport,
    Plan,
    execute_plan,
    execute_plan_isolated,
    plan_dependencies,
)


# --- the stub fal ------------------------------------------------------------


class FakeFal:
    """A stand-in ``fal_client`` whose behaviour is keyed on the application id.

    ``behaviour[app]`` is either a response dict or an exception instance; an
    unregistered app returns a generic image response. Every invocation is
    recorded (thread-safely — these tests run calls in parallel).
    """

    def __init__(self) -> None:
        self.behaviour: dict = {}
        self.calls: list[tuple[str, dict]] = []
        self.keys: list[Optional[str]] = []
        self.events: list[tuple[str, str]] = []
        self.max_in_flight = 0
        self._in_flight = 0
        self._lock = threading.Lock()
        self.before_call = None  # optional hook(app) run inside the call

    # -- registration --
    def responds(self, app: str, response: dict) -> None:
        self.behaviour[app] = response

    def raises(self, app: str, error: BaseException) -> None:
        self.behaviour[app] = error

    # -- the fal_client surface --
    def subscribe(
        self, application, *, arguments, with_logs=True, on_queue_update=None
    ):
        return self._run(application, arguments, key=None)

    def _run(self, application, arguments, *, key):
        with self._lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
            self.calls.append((application, dict(arguments)))
            self.keys.append(key)
            self.events.append(("start", application))
        try:
            if self.before_call is not None:
                self.before_call(application)
            outcome = self.behaviour.get(
                application, {"images": [{"url": f"http://x/{application}.png"}]}
            )
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        finally:
            with self._lock:
                self._in_flight -= 1
                self.events.append(("end", application))

    def module(self) -> types.ModuleType:
        """The object to install as ``sys.modules['fal_client']``."""
        fake = types.SimpleNamespace(
            InProgress=type("InProgress", (), {}),
            subscribe=self.subscribe,
            SyncClient=_sync_client_factory(self),
        )
        return fake  # type: ignore[return-value]

    def apps_called(self) -> list[str]:
        return [app for app, _ in self.calls]

    def count(self, app: str) -> int:
        return self.apps_called().count(app)


def _sync_client_factory(fal: FakeFal):
    class SyncClient:
        def __init__(self, *, key=None):
            self._key = key

        def subscribe(
            self, application, *, arguments, with_logs=True, on_queue_update=None
        ):
            return fal._run(application, arguments, key=self._key)

    return SyncClient


@pytest.fixture
def fal(monkeypatch) -> FakeFal:
    stub = FakeFal()
    monkeypatch.setitem(sys.modules, "fal_client", stub.module())
    return stub


# --- plan builders -----------------------------------------------------------


def _image(app: str, **arguments) -> CallPlan:
    return CallPlan(
        tool="generate_image",
        application=app,
        arguments={"prompt": app, **arguments},
        output_kind="image",
        estimated_cost_usd=0.025,
    )


def _video(app: str, *, source: int) -> CallPlan:
    return CallPlan(
        tool="image_to_video",
        application=app,
        arguments={"image_url": f"<from {source}>"},
        output_kind="video",
        estimated_cost_usd=0.50,
    )


def _acceptance_plan() -> Plan:
    """The plan from falaw#20's acceptance criterion: 5 calls, the 3rd fails.

    Calls 0 and 1 are independent and succeed. Call 2 raises. Calls 3 and 4
    each consume call 2's output, so neither can run.
    """
    return Plan(
        calls=(
            _image("m/ok0"),
            _image("m/ok1"),
            _image("m/boom"),
            _video("m/v3", source=2),
            _video("m/v4", source=2),
        )
    )


# --- all succeed / all fail / mixed ------------------------------------------


def test_all_calls_succeed(fal):
    report = execute_plan_isolated(Plan(calls=(_image("m/a"), _image("m/b"))))

    assert isinstance(report, ExecutionReport)
    assert report.is_complete
    assert [o.status for o in report.outcomes] == ["succeeded", "succeeded"]
    assert [o.index for o in report.outcomes] == [0, 1]
    assert len(report.produced) == 2
    assert all(o.error is None for o in report.outcomes)


def test_all_calls_fail_and_every_exception_is_kept(fal):
    fal.raises("m/a", RuntimeError("filtered a"))
    fal.raises("m/b", RuntimeError("filtered b"))

    report = execute_plan_isolated(Plan(calls=(_image("m/a"), _image("m/b"))))

    assert not report.is_complete
    assert len(report.failed) == 2
    assert report.produced == ()
    assert [str(o.error) for o in report.failed] == ["filtered a", "filtered b"]


def test_mixed_run_keeps_successes_reports_the_failure_and_blocks_dependents(fal):
    """falaw#20's acceptance criterion, verbatim."""
    fal.raises("m/boom", RuntimeError("content filter"))

    report = execute_plan_isolated(_acceptance_plan())

    assert len(report.outcomes) == 5, "one outcome per call, always"
    assert [o.status for o in report.outcomes] == [
        "succeeded",
        "succeeded",
        "failed",
        "blocked",
        "blocked",
    ]
    # The two successes — already paid for — are returned, not discarded.
    assert len(report.produced) == 2
    assert all(a.kind == "image" for a in report.produced)
    # The failure carries its exception, so the caller can classify and retry it.
    (failure,) = report.failed
    assert failure.index == 2
    assert isinstance(failure.error, RuntimeError)
    assert str(failure.error) == "content filter"
    # The dependents are *blocked*, not failed: they must be re-planned.
    assert [o.index for o in report.blocked] == [3, 4]
    assert all(o.blocked_by == (2,) for o in report.blocked)
    assert all(o.error is None for o in report.blocked)
    assert all("re-planned" in o.reason for o in report.blocked)
    # Nothing downstream of the failure was sent to fal.
    assert fal.count("m/v3") == 0 and fal.count("m/v4") == 0


def test_blocking_is_transitive(fal):
    """A consumer of a blocked call is itself blocked, not failed."""
    fal.raises("m/boom", RuntimeError("no"))
    plan = Plan(
        calls=(_image("m/boom"), _video("m/v1", source=0), _video("m/v2", source=1))
    )

    report = execute_plan_isolated(plan)

    assert [o.status for o in report.outcomes] == ["failed", "blocked", "blocked"]
    assert report.outcomes[1].blocked_by == (0,)
    assert report.outcomes[2].blocked_by == (1,)


def test_a_failure_in_one_call_does_not_corrupt_the_others_artifacts(fal):
    """Per-call isolation: the successes are indistinguishable from a clean run."""
    clean = execute_plan_isolated(Plan(calls=(_image("m/ok0"), _image("m/ok1"))))
    fal.raises("m/boom", RuntimeError("boom"))
    mixed = execute_plan_isolated(_acceptance_plan())

    assert [a.asset_id for a in mixed.produced] == [a.asset_id for a in clean.produced]
    assert [a.url for a in mixed.produced] == [a.url for a in clean.produced]


# --- the successes of a mixed run stay cached --------------------------------


def test_a_mixed_runs_successful_calls_are_still_cached(fal):
    """The point of partial results: the paid work is reusable, not thrown away."""
    from falaw.cache import cache_get

    fal.raises("m/boom", RuntimeError("boom"))
    report = execute_plan_isolated(_acceptance_plan())
    assert len(report.succeeded) == 2

    for index in (0, 1):
        call = report.outcomes[index].call
        assert cache_get(call.application, call.arguments) is not None
    # The failed call left no entry behind — a failure must not be cached.
    failed_call = report.outcomes[2].call
    assert cache_get(failed_call.application, failed_call.arguments) is None


def test_rerunning_a_mixed_plan_does_not_re_bill_the_calls_that_worked(fal):
    fal.raises("m/boom", RuntimeError("boom"))
    execute_plan_isolated(_acceptance_plan())
    calls_after_first_run = fal.count("m/ok0")

    second = execute_plan_isolated(_acceptance_plan())

    assert fal.count("m/ok0") == calls_after_first_run, "the success was re-billed"
    assert second.outcomes[0].cache_hit is True
    assert second.outcomes[0].status == "succeeded"
    # The failing call is retried — a failure is not cached as if it were one.
    assert fal.count("m/boom") == 2


# --- cost accounting ---------------------------------------------------------


def test_cost_accounting_excludes_failed_and_blocked_calls(fal):
    fal.raises("m/boom", RuntimeError("boom"))

    report = execute_plan_isolated(_acceptance_plan())

    # Two image calls at 0.025 each; the $0.50 videos never ran, the failed
    # image is not counted as a success.
    assert report.estimated_spend_usd == pytest.approx(0.05)
    assert report.cache_hit_savings_usd == 0.0


def test_a_cache_hit_is_savings_not_spend(fal):
    plan = Plan(calls=(_image("m/a"),))
    first = execute_plan_isolated(plan)
    assert first.estimated_spend_usd == pytest.approx(0.025)
    assert first.cache_hit_savings_usd == 0.0

    second = execute_plan_isolated(plan)

    assert second.outcomes[0].cache_hit is True
    assert second.estimated_spend_usd == 0.0
    assert second.cache_hit_savings_usd == pytest.approx(0.025)


def test_an_unpriced_call_is_reported_as_unknown_not_as_free(fal):
    """``$0.00`` must never be the answer to "we do not know"."""
    unpriced = CallPlan(
        tool="t", application="m/x", arguments={"prompt": "p"}, output_kind="image"
    )
    assert unpriced.estimated_cost_usd is None

    report = execute_plan_isolated(Plan(calls=(unpriced, _image("m/a"))))

    assert report.estimated_spend_usd == pytest.approx(0.025)
    assert report.has_unknown_costs is True
    # A fully-priced run says so.
    assert (
        execute_plan_isolated(Plan(calls=(_image("m/b"),))).has_unknown_costs is False
    )


def test_an_unpriced_cache_hit_is_not_an_unknown_cost(fal):
    """A cache hit bills nothing, so its missing price is not a missing number."""
    unpriced = CallPlan(
        tool="t", application="m/x", arguments={"prompt": "p"}, output_kind="image"
    )
    plan = Plan(calls=(unpriced,))
    assert execute_plan_isolated(plan).has_unknown_costs is True

    second = execute_plan_isolated(plan)

    assert second.outcomes[0].cache_hit is True
    assert second.has_unknown_costs is False


# --- the per-artifact cost stamp (falaw#26) ----------------------------------


def test_an_artifact_from_a_run_hit_carries_zero_not_the_planned_price(fal):
    """A call planned as a miss that runs as a hit must not carry a price.

    ``Artifact.cost_usd`` used to be the plan-time ``billable_cost_usd`` peek,
    so exactly this case stamped the full price onto a call that cost nothing
    — and nw sums that field into one named ``cost_usd_actual`` (falaw#26).
    """
    plan = Plan(calls=(_image("m/a"),))
    first = execute_plan_isolated(plan)
    assert first.outcomes[0].artifact.cost_usd == pytest.approx(0.025)

    second = execute_plan_isolated(plan)  # the plan still believes "miss"

    assert second.outcomes[0].cache_hit is True
    assert second.outcomes[0].artifact.cost_usd == 0.0  # a known zero


def test_an_artifact_from_a_rebilled_planned_hit_carries_the_price(fal):
    """The other direction of falaw#26: planned ``"hit"``, but the entry is
    gone at run time (evicted since planning), so the call re-bills — the
    artifact must say so instead of the ``None`` the stale plan implied."""
    stale = replace(_image("m/rebill"), cache_status="hit")

    report = execute_plan_isolated(Plan(calls=(stale,)))

    assert report.outcomes[0].cache_hit is False
    assert report.outcomes[0].artifact.cost_usd == pytest.approx(0.025)


def test_an_unpriced_miss_stamps_unknown_never_free(fal):
    """``None`` (no price known) must survive to the artifact — stamping
    ``0.0`` would launder "we do not know" into "it was free"."""
    unpriced = CallPlan(
        tool="t", application="m/x", arguments={"prompt": "p"}, output_kind="image"
    )

    report = execute_plan_isolated(Plan(calls=(unpriced,)))

    assert report.outcomes[0].cache_hit is False
    assert report.outcomes[0].artifact.cost_usd is None


@pytest.mark.parametrize("bad", [-1.0, float("nan")])
def test_a_negative_or_nan_price_is_refused_at_the_callplan(bad):
    """The executor stamps ``estimated_cost_usd`` onto artifacts via
    ``model_copy``, which skips Artifact's ``ge=0`` validation — so the
    refusal must live where the number enters: the CallPlan."""
    with pytest.raises(ValueError, match="non-negative"):
        CallPlan(
            tool="t",
            application="m/bad",
            arguments={},
            output_kind="image",
            estimated_cost_usd=bad,
        )


def test_the_executor_owns_the_cost_stamp_not_the_converter(fal):
    """A converter that invents a price is overwritten: cost is a fact about
    the call's *execution*, which only the executor observes."""

    def opinionated(raw, call):
        from falaw.plan import _artifact_from_response

        artifact = _artifact_from_response(raw, call)
        return artifact.model_copy(update={"cost_usd": 99.0})

    report = execute_plan_isolated(
        Plan(calls=(_image("m/a"),)), artifact_converter=opinionated
    )

    assert report.outcomes[0].artifact.cost_usd == pytest.approx(0.025)


@pytest.mark.parametrize("concurrency", [1, 2])
def test_a_keyboard_interrupt_aborts_the_run_instead_of_becoming_an_outcome(
    fal, concurrency
):
    """Isolating a Ctrl-C would keep spending after the operator said stop.

    Parametrized because the two execution paths catch it in different places:
    the inline executor never wraps a non-``Exception`` at all, while a thread
    pool always does — so a guard tested at only one of them is a guard tested
    at neither.
    """
    fal.raises("m/ok1", KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        execute_plan_isolated(_acceptance_plan(), concurrency=concurrency)

    assert fal.count("m/v3") == 0


def test_summary_is_json_serializable(fal):
    fal.raises("m/boom", RuntimeError("boom"))
    report = execute_plan_isolated(_acceptance_plan())

    summary = report.summary()

    assert json.loads(json.dumps(summary)) == summary
    assert summary["succeeded"] == 2
    assert summary["failed_indices"] == [2]
    assert summary["blocked_indices"] == [3, 4]


# --- the halt policy (execute_plan) ------------------------------------------


def test_execute_plan_still_raises_the_original_exception_unwrapped(fal):
    """falaw's typed error hierarchy must survive the trip through the executor."""
    from falaw.errors import FalRateLimited

    boom = FalRateLimited("slow down", status_code=429)
    fal.raises("m/boom", boom)

    with pytest.raises(FalRateLimited) as caught:
        execute_plan(_acceptance_plan())

    assert caught.value is boom


def test_halt_stops_submitting_after_the_first_failure(fal):
    """At concurrency=1 the halt policy is exactly the historical behaviour."""
    fal.raises("m/ok1", RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        execute_plan(_acceptance_plan())

    assert fal.apps_called() == ["m/ok0", "m/ok1"], "a call after the failure ran"


def test_isolated_keeps_going_where_halt_stops(fal):
    """The two policies differ on exactly one thing: what happens next."""
    independent = Plan(calls=(_image("m/a"), _image("m/boom"), _image("m/c")))
    fal.raises("m/boom", RuntimeError("boom"))

    report = execute_plan_isolated(independent)

    assert [o.status for o in report.outcomes] == ["succeeded", "failed", "succeeded"]
    assert fal.count("m/c") == 1

    fal.calls.clear()
    with pytest.raises(RuntimeError):
        execute_plan(independent, use_cache=False)
    assert fal.count("m/c") == 0


def test_halt_on_failure_reports_unstarted_calls_as_blocked(fal):
    fal.raises("m/ok1", RuntimeError("boom"))

    report = execute_plan_isolated(_acceptance_plan(), halt_on_failure=True)

    assert [o.status for o in report.outcomes] == [
        "succeeded",
        "failed",
        "blocked",
        "blocked",
        "blocked",
    ]
    assert report.outcomes[2].blocked_by == ()
    assert "halted" in report.outcomes[2].reason


def test_execute_plan_returns_the_same_list_it_always_did(fal):
    artifacts = execute_plan(Plan(calls=(_image("m/a"), _image("m/b"))))

    assert isinstance(artifacts, list)
    assert len(artifacts) == 2
    assert [a.kind for a in artifacts] == ["image", "image"]


def test_artifacts_or_raise_refuses_to_return_a_short_list(fal):
    """A blocked-but-not-failed run has no exception to re-raise, and must not
    quietly hand back fewer artifacts than the plan had calls."""
    report = ExecutionReport(
        outcomes=(
            CallOutcome(index=0, call=_image("m/a"), status="blocked", reason="nope"),
        )
    )
    with pytest.raises(RuntimeError, match="never ran"):
        report.artifacts_or_raise()


# --- bounded concurrency -----------------------------------------------------


def _blocking_hook(barrier: threading.Barrier):
    def hook(application):
        try:
            barrier.wait(timeout=5)
        except threading.BrokenBarrierError:  # pragma: no cover - failure path
            pytest.fail("calls did not run concurrently")

    return hook


def test_independent_calls_run_concurrently(fal):
    """Four independent calls, each of which blocks until all four are in flight."""
    fal.before_call = _blocking_hook(threading.Barrier(4))
    plan = Plan(calls=tuple(_image(f"m/{i}") for i in range(4)))

    report = execute_plan_isolated(plan, concurrency=4)

    assert report.is_complete
    assert fal.max_in_flight == 4


def test_concurrency_is_a_bound_not_a_suggestion(fal):
    """Eight independent calls at concurrency=2 never exceed two in flight."""
    gate = threading.Barrier(2)
    fal.before_call = _blocking_hook(gate)
    plan = Plan(calls=tuple(_image(f"m/{i}") for i in range(8)))

    report = execute_plan_isolated(plan, concurrency=2)

    assert report.is_complete
    assert fal.max_in_flight == 2


def test_the_default_is_sequential(fal):
    plan = Plan(calls=tuple(_image(f"m/{i}") for i in range(4)))

    execute_plan_isolated(plan)

    assert fal.max_in_flight == 1, "concurrency must be opt-in — every call is paid"


def test_a_chained_call_never_runs_beside_its_producer(fal):
    """Concurrency must respect ``<from N>``: a blanket gather corrupts chains."""
    plan = Plan(
        calls=(
            _image("m/i0"),
            _image("m/i1"),
            _video("m/v0", source=0),
            _video("m/v1", source=1),
        )
    )

    report = execute_plan_isolated(plan, concurrency=4)

    assert report.is_complete
    for producer, consumer in (("m/i0", "m/v0"), ("m/i1", "m/v1")):
        assert fal.events.index(("end", producer)) < fal.events.index(
            ("start", consumer)
        ), f"{consumer} started before {producer} finished"
    # The consumers got the producers' URLs, not the literal placeholder.
    sent = dict(fal.calls)
    assert sent["m/v0"]["image_url"] == report.outcomes[0].artifact.url
    assert sent["m/v1"]["image_url"] == report.outcomes[1].artifact.url


def test_a_failure_under_concurrency_still_isolates(fal):
    fal.raises("m/boom", RuntimeError("boom"))

    report = execute_plan_isolated(_acceptance_plan(), concurrency=4)

    assert [o.status for o in report.outcomes] == [
        "succeeded",
        "succeeded",
        "failed",
        "blocked",
        "blocked",
    ]


def test_concurrency_below_one_is_refused(fal):
    with pytest.raises(ValueError, match="at least 1"):
        execute_plan_isolated(Plan(calls=(_image("m/a"),)), concurrency=0)
    assert fal.calls == [], "nothing may be billed before the arguments are checked"


def test_a_bring_your_own_key_survives_into_the_pool(fal):
    """A thread pool does *not* inherit the submitting thread's context.

    ``using_fal_credentials`` binds the caller's fal key to a ContextVar
    (falaw.core), so a concurrent run that forgets to carry the context would
    silently bill the *server's* key instead of the caller's.
    """
    from falaw import using_fal_credentials

    plan = Plan(calls=(_image("m/a"), _image("m/b")))
    with using_fal_credentials("byo-key-123"):
        execute_plan_isolated(plan, concurrency=2)

    assert fal.keys == ["byo-key-123", "byo-key-123"]


# --- plan_dependencies: structural validation, before a cent is spent --------


def test_plan_dependencies_reads_the_dag(fal):
    plan = Plan(calls=(_image("m/a"), _image("m/b"), _video("m/v", source=0)))

    assert plan_dependencies(plan) == (frozenset(), frozenset(), frozenset({0}))


def test_plan_dependencies_finds_refs_nested_in_containers():
    call = CallPlan(
        tool="t",
        application="m",
        arguments={"opts": {"refs": ["<from 0>", "x"]}, "other": ("<from 1>",)},
        output_kind="image",
    )
    plan = Plan(calls=(_image("m/a"), _image("m/b"), call))

    assert plan_dependencies(plan)[2] == frozenset({0, 1})


def test_a_reference_past_the_end_of_the_plan_is_refused(fal):
    plan = Plan(
        calls=(
            _image("m/a"),
            CallPlan(
                tool="t",
                application="m/b",
                arguments={"image_url": "<from 5>"},
                output_kind="video",
            ),
        )
    )

    with pytest.raises(ValueError, match="references artifact index 5"):
        execute_plan(plan, use_cache=False)

    assert fal.calls == [], "a malformed plan must fail before it bills anything"


def test_a_forward_reference_is_refused(fal):
    plan = Plan(calls=(_video("m/v", source=1), _image("m/a")))

    with pytest.raises(ValueError, match="does not run before it"):
        execute_plan_isolated(plan)
    assert fal.calls == []


def test_a_self_reference_is_refused(fal):
    plan = Plan(calls=(_video("m/v", source=0),))

    with pytest.raises(ValueError, match="references nothing|reference nothing"):
        plan_dependencies(plan)


def test_a_non_integer_reference_is_refused():
    call = CallPlan(
        tool="t", application="m", arguments={"x": "<from p1>"}, output_kind="image"
    )
    with pytest.raises(ValueError, match="Bad placeholder"):
        plan_dependencies(Plan(calls=(call,)))


def test_dry_run_does_not_validate_placeholders():
    """``dry_run`` never resolves a placeholder, so it has none to validate.

    Guards a deliberate asymmetry: plans carrying illustrative, non-numeric
    references are dry-run in cost gates today, and making a preview raise
    would be a regression, not a fix.
    """
    call = CallPlan(
        tool="t", application="m", arguments={"x": "<from p1>"}, output_kind="image"
    )
    report = execute_plan_isolated(Plan(calls=(call,)), dry_run=True)

    assert report.is_complete
    assert report.outcomes[0].artifact.url is None


# --- CallOutcome invariants --------------------------------------------------


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"status": "succeeded"}, "an artifact"),
        ({"status": "failed"}, "an error"),
        ({"status": "blocked"}, "a reason"),
        (
            {"status": "failed", "error": ValueError("x"), "artifact": object()},
            "no artifact",
        ),
    ],
)
def test_call_outcome_rejects_a_payload_that_contradicts_its_status(kwargs, expected):
    with pytest.raises(ValueError, match=expected):
        CallOutcome(index=0, call=_image("m/a"), **kwargs)


def test_call_outcome_rejects_an_unknown_status():
    with pytest.raises(ValueError, match="must be one of"):
        CallOutcome(index=0, call=_image("m/a"), status="skipped")  # type: ignore[arg-type]


# --- per-call isolation of falaw's own warnings ------------------------------


def test_deferred_degrade_warnings_collects_instead_of_emitting(fal):
    """The mechanism, in isolation: inside the sink, nothing reaches ``warnings``."""
    import urllib.error

    from falaw.content import using_url_fetcher
    from falaw.plan import _content_ref_or_none, _deferred_degrade_warnings

    def dead(url, *, chunk_size=1 << 16):
        raise urllib.error.HTTPError(url, 404, "gone", {}, None)  # type: ignore[arg-type]
        yield b""  # pragma: no cover - generator marker

    with using_url_fetcher(dead), warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        with _deferred_degrade_warnings() as sink:
            ref, _ = _content_ref_or_none("http://x/dead.png", None, None)
        assert ref is None
        assert len(sink) == 1 and "dead.png" in sink[0]
        assert recorded == [], "a deferred warning must not also be emitted"

        # ...and outside the sink it is emitted normally.
        _content_ref_or_none("http://x/dead.png", None, None)
        assert len(recorded) == 1


def test_a_speculative_cache_probe_does_not_swallow_a_concurrent_warning(fal):
    """The reason the sink is a ContextVar and not ``warnings.catch_warnings``.

    ``catch_warnings`` replaces process-global state, so under concurrency one
    call's *discarded* cache probe would eat another call's genuine warning at
    random. Here the two calls are forced to interleave: call B is inside its
    probe (whose result is about to be thrown away) at the moment call A warns.
    """
    import time
    import urllib.error

    from falaw.cache import cache_put
    from falaw.content import using_url_fetcher

    dead_a, dead_b = "http://x/dead-a.png", "http://x/dead-b.png"
    probe_started = threading.Event()
    recorded: list = []

    def chunks(url, *, chunk_size=1 << 16):
        if url == dead_b:
            probe_started.set()
            deadline = time.time() + 2.0
            while time.time() < deadline and not _mentions(recorded, "dead-a"):
                time.sleep(0.005)
            raise urllib.error.HTTPError(url, 404, "gone", {}, None)  # type: ignore[arg-type]
        if url == dead_a:
            # Warn only once B is inside its probe window.
            probe_started.wait(timeout=2.0)
            raise urllib.error.HTTPError(url, 404, "gone", {}, None)  # type: ignore[arg-type]
        yield b"good bytes"

    probe_call = _image("m/probe")
    # Seed a cache entry whose asset is gone: converting it degrades, the
    # degraded artifact is unusable, and the probe's complaints are discarded.
    cache_put("m/probe", probe_call.arguments, {"images": [{"url": dead_b}]})
    fal.responds("m/probe", {"images": [{"url": "http://x/alive.png"}]})
    fal.responds("m/fresh", {"images": [{"url": dead_a}]})

    plan = Plan(calls=(_image("m/fresh"), probe_call))
    # ``using_url_fetcher`` is a plain module global precisely so it reaches the
    # pool threads this test runs the plan on.
    with using_url_fetcher(chunks), warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        recorded = captured
        report = execute_plan_isolated(plan, concurrency=2)

    assert report.is_complete
    assert _mentions(captured, "dead-a"), (
        "the fresh call's degrade warning was swallowed by the other call's "
        "discarded cache probe"
    )
    assert _mentions(captured, "Dropping the falaw cache entry")


def _mentions(recorded, needle: str) -> bool:
    return any(needle in str(w.message) for w in list(recorded))


# --- cache isolation under concurrency ---------------------------------------


def test_a_failed_cache_write_leaves_no_entry_behind():
    """A half-written manifest is worse than none: it fails every future read."""
    import os

    from falaw.cache import _entry_dir, _key, _manifest_path, cache_get, cache_put

    circular: dict = {"pad": "x" * 4096}
    circular["self"] = circular  # json.dump writes, then raises

    with pytest.raises(ValueError):
        cache_put("m/a", {"prompt": "p"}, circular)

    key = _key("m/a", {"prompt": "p"})
    assert not os.path.exists(_manifest_path(key))
    assert cache_get("m/a", {"prompt": "p"}) is None
    assert [f for f in os.listdir(_entry_dir(key)) if f.endswith(".part")] == []


def test_a_reader_never_observes_a_half_written_manifest():
    """The invariant that makes concurrent writers to one key safe.

    Two structurally identical calls of one Plan land on the same cache key, so
    ``concurrency > 1`` really can have one writer mid-write while another
    reader looks. Rather than race threads and hope to catch the window — a
    guard that only *sometimes* fires is not a guard — this observes the file
    from *inside* the write: ``json.dump`` calls ``default=str`` on an
    unserializable value, so the probe below runs with the dump half-finished.
    """
    from falaw.cache import cache_get, cache_put

    arguments = {"prompt": "p"}
    original = {"images": [{"url": "http://x/original.png"}]}
    cache_put("m/a", arguments, original)

    observed: list = []

    class Probe:
        """``str()``-ed by ``json.dump`` partway through writing the manifest."""

        def __str__(self) -> str:
            try:
                observed.append(cache_get("m/a", arguments))
            except Exception as e:  # noqa: BLE001 — a corrupt read is the finding
                observed.append(e)
            return "probe"

    cache_put("m/a", arguments, {"pad": "z" * 100_000, "probe": Probe()})

    assert observed == [original], (
        "mid-write, the cache served something other than the previous complete "
        f"entry: {observed!r}"
    )
    assert cache_get("m/a", arguments)["probe"] == "probe", "the new entry landed"


# --- the module's own examples must run --------------------------------------


def test_new_modules_doctests_pass():
    import doctest

    import falaw.outcomes
    import falaw.plan

    for module in (falaw.plan, falaw.outcomes):
        result = doctest.testmod(
            module,
            optionflags=doctest.NORMALIZE_WHITESPACE | doctest.ELLIPSIS,
        )
        assert result.attempted > 0, f"{module.__name__} has no examples to run"
        assert result.failed == 0, f"{module.__name__} has failing examples"


# --- artifact lineage (lacing#14 / D5) ---------------------------------------


def test_a_chained_artifact_records_its_upstream_asset_ids(fal):
    """The D5 payoff: was_derived_from carries the consumed artifacts'
    content-addressed asset_ids, read off the plan DAG by the executor."""
    plan = Plan(calls=(_image("m/a"), _video("m/v", source=0)))

    report = execute_plan_isolated(plan)

    image, video = (o.artifact for o in report.outcomes)
    assert list(image.provenance.was_derived_from) == []
    assert list(video.provenance.was_derived_from) == [image.asset_id]


def test_a_multi_dependency_call_records_every_upstream(fal):
    lipsync = CallPlan(
        tool="lipsync",
        application="m/l",
        arguments={"video_url": "<from 0>", "audio_url": "<from 1>"},
        output_kind="video",
        estimated_cost_usd=0.1,
    )
    plan = Plan(calls=(_image("m/a"), _image("m/b"), lipsync))

    report = execute_plan_isolated(plan)

    a, b, lip = (o.artifact for o in report.outcomes)
    assert list(lip.provenance.was_derived_from) == [a.asset_id, b.asset_id]


def test_cache_hits_are_stamped_too(fal):
    """A hit's artifact is re-converted from the cached raw each run; its
    lineage is this run's upstream slots, stamped the same way."""
    plan = Plan(calls=(_image("m/a"), _video("m/v", source=0)))
    execute_plan_isolated(plan)

    second = execute_plan_isolated(plan)

    image, video = (o.artifact for o in second.outcomes)
    assert second.outcomes[1].cache_hit is True
    assert list(video.provenance.was_derived_from) == [image.asset_id]
