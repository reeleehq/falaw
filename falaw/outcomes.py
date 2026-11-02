"""Per-call outcomes of running a :class:`falaw.Plan` — the partial-result type.

A :class:`falaw.Plan` is a fan-out: 200 panels is 200 :class:`~falaw.CallPlan`
entries in one Plan. A ``list[Artifact]`` return has no room to say *"call 7
failed, here are the other 199"*, so the only thing a bare list can do when one
call raises is throw the whole run away — including artifacts that were already
generated and **already billed**.

This module is the vocabulary for saying it properly. Three states, not two:

``succeeded``
    The call ran (or was served from cache) and produced an
    :class:`lacing.Artifact`.
``failed``
    The call raised. The exception is kept, so the caller can classify it
    (:mod:`falaw.errors` distinguishes rate-limiting from a locked account)
    and retry precisely this one call.
``blocked``
    The call never ran, because something it depends on did not succeed — a
    ``"<from N>"`` placeholder pointing at a failed upstream — or because the
    run was halted by an earlier failure.

The third state is what makes a chained plan safe to resume: a blocked call
must be *re-planned*, not retried, and a caller that cannot tell "blocked" from
"failed" will retry a call whose input does not exist.

Examples
--------

>>> from falaw.plan import CallPlan
>>> call = CallPlan(tool="generate_image", application="fal-ai/flux/dev",
...                 arguments={"prompt": "a tiger"}, output_kind="image",
...                 estimated_cost_usd=0.025)
>>> boom = CallOutcome(index=0, call=call, status="failed",
...                    error=RuntimeError("content filter"))
>>> boom.ok
False
>>> report = ExecutionReport(outcomes=(boom,))
>>> report.is_complete
False
>>> report.estimated_spend_usd
0.0
>>> [o.index for o in report.failed]
[0]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from lacing import Artifact

    from .plan import CallPlan


CallStatus = Literal["succeeded", "failed", "blocked"]


def inference_time_s(metrics: Optional[dict]) -> Optional[float]:
    """``metrics["inference_time"]`` as finite, non-negative seconds, or ``None``."""
    from .cost import as_seconds

    return as_seconds((metrics or {}).get("inference_time"))


def billed_cost_usd(
    call: "CallPlan", *, cache_hit: bool, inference_time_s: Optional[float]
) -> Optional[float]:
    """Estimated USD one executed call billed, or ``None`` when unknown.

    ``0.0`` on a cache hit (nothing was billed); else the call's plan-time
    estimate; else, for a model priced per compute second, its rate times the
    run time fal reported (falaw#144). The one rule the executor stamps on the
    artifact and :class:`ExecutionReport` sums, so the two cannot disagree.
    """
    from .cost import compute_time_cost_usd

    if cache_hit:
        return 0.0
    if call.estimated_cost_usd is not None:
        return call.estimated_cost_usd
    return compute_time_cost_usd(call.application, inference_time_s=inference_time_s)


"""What became of one :class:`~falaw.CallPlan` in a run. See the module docstring."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CallOutcome:
    """What happened to one :class:`~falaw.CallPlan`, at its position in the Plan.

    ``index`` is the call's position in ``plan.calls`` and is the identity a
    caller retries or re-plans by — a report always carries exactly one outcome
    per call, in plan order, so ``index`` is also the safe key for zipping a
    Plan against anything the caller built alongside it.
    """

    index: int
    """Position in ``plan.calls``. Stable, and unique within a report."""

    call: "CallPlan"
    """The call this outcome is about — enough to retry it verbatim."""

    status: CallStatus
    """``"succeeded"`` / ``"failed"`` / ``"blocked"``. See the module docstring."""

    artifact: Optional["Artifact"] = None
    """The materialized artifact. Set if and only if ``status == "succeeded"``."""

    error: Optional[BaseException] = None
    """The exception the call raised. Set if and only if ``status == "failed"``.

    Kept as the exception object rather than a string so the caller can use
    falaw's typed hierarchy (:mod:`falaw.errors`) to decide between backing off,
    switching models, and giving up.
    """

    cache_hit: bool = False
    """Whether the result came from the cache **as observed at run time**.

    Not the same thing as :attr:`falaw.CallPlan.cache_status`, which is a
    *prediction* made at plan time and can be wrong in both directions (a
    concurrent run filled the entry; a hit turned out to be unusable and was
    re-executed). Run-level cost accounting reads this one.
    """

    blocked_by: tuple[int, ...] = ()
    """Indices of the calls whose non-success blocked this one. ``()`` when the
    call was blocked for a run-level reason rather than a dependency."""

    reason: str = ""
    """Human-readable explanation. Required for ``blocked``; free otherwise."""

    metrics: Optional[dict[str, Any]] = field(default=None, hash=False)
    """fal's own account of the run that produced the artifact (falaw#127).

    A copy of its final ``Completed.metrics``, as the call's ``done``
    :class:`~falaw.events.ProgressEvent` carried it (e.g.
    ``{"inference_time": 3.2}``), so editing it never touches the event. ``None``
    when nothing ran (a cache hit, a dry run, a call that did not succeed) or fal
    reported none. An *observed* fact about this run, not a price: see
    :attr:`inference_time_s`.
    """

    @property
    def inference_time_s(self) -> Optional[float]:
        """Seconds fal's runner reported spending on this call, or ``None``.

        ``metrics["inference_time"]`` read by :func:`falaw.cost.as_seconds` (a
        finite, non-negative number; a numeric string is not one).
        It is an observed run time: fal does not say it is the billed quantity
        of a per-compute-second endpoint, so a cost derived from it is an
        estimate labelled as such, not a vendor receipt.

        >>> from falaw.plan import CallPlan
        >>> call = CallPlan(tool="t", application="fal-ai/x", arguments={},
        ...                 output_kind="audio")
        >>> CallOutcome(index=0, call=call, status="blocked", reason="r",
        ...             metrics={"inference_time": 3.2}).inference_time_s
        3.2
        >>> CallOutcome(index=0, call=call, status="blocked", reason="r",
        ...             metrics={"inference_time": "3.2"}).inference_time_s is None
        True
        """
        return inference_time_s(self.metrics)

    @property
    def billed_cost_usd(self) -> Optional[float]:
        """Estimated USD this call billed, or ``None`` when unknown.

        See :func:`billed_cost_usd`; a call that did not run (blocked) or did
        not succeed still answers, from its plan-time estimate.
        """
        return billed_cost_usd(
            self.call,
            cache_hit=self.cache_hit,
            inference_time_s=self.inference_time_s,
        )

    def __post_init__(self) -> None:
        """Reject an outcome whose payload contradicts its status.

        A ``"succeeded"`` outcome with no artifact, or a ``"failed"`` one with no
        exception, would be silently useless to every consumer — and the whole
        point of this type is that a caller can trust ``status`` and act on it.
        """
        if self.status == "succeeded":
            self._require(self.artifact is not None, "an artifact")
            self._require(self.error is None, "no error")
        elif self.status == "failed":
            self._require(self.error is not None, "an error")
            self._require(self.artifact is None, "no artifact")
        elif self.status == "blocked":
            self._require(self.artifact is None, "no artifact")
            self._require(self.error is None, "no error")
            self._require(bool(self.reason), "a reason")
        else:
            raise ValueError(
                f"CallOutcome.status must be one of "
                f"'succeeded' / 'failed' / 'blocked', got {self.status!r}."
            )

    def _require(self, condition: bool, expectation: str) -> None:
        if not condition:
            raise ValueError(
                f"CallOutcome(index={self.index}, status={self.status!r}) "
                f"must carry {expectation}."
            )

    @property
    def ok(self) -> bool:
        """Shorthand for ``status == "succeeded"``."""
        return self.status == "succeeded"


@dataclass(frozen=True, slots=True)
class ExecutionReport:
    """The result of running a Plan: one :class:`CallOutcome` per call, in order.

    ``len(report.outcomes) == len(plan.calls)`` **always**, including on a run
    where most calls failed. That invariant is the whole point: a consumer that
    built something per call (nw builds one skeleton annotation per call) can
    zip against :attr:`outcomes` and stay aligned. Zipping against a
    *shorter* list of successes is the silent mis-pairing this type exists to
    prevent.
    """

    outcomes: tuple[CallOutcome, ...] = ()

    def __len__(self) -> int:
        return len(self.outcomes)

    def __iter__(self):
        return iter(self.outcomes)

    def __getitem__(self, idx):
        return self.outcomes[idx]

    @property
    def is_complete(self) -> bool:
        """True when every call succeeded."""
        return all(o.ok for o in self.outcomes)

    @property
    def succeeded(self) -> tuple[CallOutcome, ...]:
        """Outcomes that produced an artifact, in plan order."""
        return tuple(o for o in self.outcomes if o.status == "succeeded")

    @property
    def failed(self) -> tuple[CallOutcome, ...]:
        """Outcomes whose call raised, in plan order."""
        return tuple(o for o in self.outcomes if o.status == "failed")

    @property
    def blocked(self) -> tuple[CallOutcome, ...]:
        """Outcomes whose call never ran, in plan order."""
        return tuple(o for o in self.outcomes if o.status == "blocked")

    @property
    def produced(self) -> tuple["Artifact", ...]:
        """The artifacts that were made, in plan order.

        **Shorter than the Plan when anything failed** — deliberately named so
        it does not read like something to zip a per-call sequence against. Use
        :attr:`outcomes` for anything positional.
        """
        return tuple(o.artifact for o in self.outcomes if o.artifact is not None)

    @property
    def estimated_spend_usd(self) -> float:
        """Estimated USD billed by this run: succeeded calls that were **not** cache hits.

        Estimated, because it sums :attr:`CallOutcome.billed_cost_usd` (the
        plan-time estimate, or for a per-compute-second model its rate times
        fal's reported run time) — falaw does not read fal's invoice. Two
        deliberate exclusions:

        - **Cache hits cost nothing**, and this reads the *observed*
          :attr:`CallOutcome.cache_hit`, not the plan-time prediction.
        - **Failed calls are not counted.** The vendor may or may not have
          billed a call that raised, and falaw cannot know which; adding an
          estimate for it would be inventing a number. Read
          :attr:`failed` to see how many calls are unaccounted for.
        """
        return sum(
            (
                o.billed_cost_usd or 0.0
                for o in self.outcomes
                if o.status == "succeeded" and not o.cache_hit
            ),
            0.0,
        )

    @property
    def has_unknown_costs(self) -> bool:
        """True when a call that may have billed has no price estimate.

        The run-level twin of :attr:`falaw.Plan.has_unknown_costs`, and the
        reason :attr:`estimated_spend_usd` must never be read on its own: an
        unpriced call contributes ``0.0`` to the sum, so a report reading
        ``$0.00`` means *either* "nothing was spent" *or* "we do not know what
        was spent". Those are not the same answer, and a budget gate that
        cannot tell them apart approves the second one.

        "May have billed" is a succeeded call that was not a cache hit, **or a
        failed call** (falaw#141): a call that raised may have been billed
        first (a paid request whose conversion failed, an in-process backend
        that spent before raising), and for an unpriced one there is no
        estimate to put a bound on that. A failed *priced* call is not unknown,
        only excluded from :attr:`estimated_spend_usd` (see there). A blocked
        call never ran and cannot have billed. On a dry run nothing bills, but an
        unpriced call there reads as unknown all the same: the report is a forecast.
        """

        def _may_have_billed(o: CallOutcome) -> bool:
            return o.status == "failed" or (o.status == "succeeded" and not o.cache_hit)

        return any(
            o.billed_cost_usd is None for o in self.outcomes if _may_have_billed(o)
        )

    @property
    def cache_hit_savings_usd(self) -> float:
        """Estimated USD *not* spent because a succeeded call was served from cache.

        The run-time counterpart of :attr:`falaw.Plan.cache_hit_savings_usd`
        (which is a plan-time prediction).
        """
        return sum(
            (
                o.call.estimated_cost_usd or 0.0
                for o in self.outcomes
                if o.status == "succeeded" and o.cache_hit
            ),
            0.0,
        )

    def artifacts_or_raise(self) -> list["Artifact"]:
        """Every artifact in plan order, or re-raise the first failure's exception.

        The bridge back to the plain ``list[Artifact]`` contract of
        :func:`falaw.execute_plan`. The exception raised is the **original** one
        the call raised, unwrapped — falaw's typed error hierarchy
        (:mod:`falaw.errors`) is only useful to a caller if it survives the trip
        through the executor.

        A run with no failures but some blocked calls raises too: the list would
        otherwise be short, and a short list is exactly the silent mis-pairing
        this type exists to prevent.
        """
        failures = self.failed
        if failures:
            raise failures[0].error  # type: ignore[misc]
        blocked = self.blocked
        if blocked:
            first = blocked[0]
            raise RuntimeError(
                f"Plan call {first.index} ({first.call.tool}) never ran: "
                f"{first.reason}. No call failed, so there is no upstream "
                "exception to re-raise; use falaw.execute_plan_isolated to "
                "inspect the full report."
            )
        return [o.artifact for o in self.outcomes]  # type: ignore[misc]

    def summary(self) -> dict:
        """A small JSON-able digest — counts, spend, and which indices failed.

        For logs, telemetry and run records, where the artifacts and exception
        objects themselves are not serializable.
        """
        return {
            "calls": len(self.outcomes),
            "succeeded": len(self.succeeded),
            "failed": len(self.failed),
            "blocked": len(self.blocked),
            "estimated_spend_usd": self.estimated_spend_usd,
            "has_unknown_costs": self.has_unknown_costs,
            "cache_hit_savings_usd": self.cache_hit_savings_usd,
            "failed_indices": [o.index for o in self.failed],
            "blocked_indices": [o.index for o in self.blocked],
        }
