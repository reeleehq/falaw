# falaw.outcomes

Per-call outcomes of running a [`falaw.Plan`](falaw.html.md#falaw.Plan) — the partial-result type.

A [`falaw.Plan`](falaw.html.md#falaw.Plan) is a fan-out: 200 panels is 200 [`CallPlan`](falaw.html.md#falaw.CallPlan)
entries in one Plan. A `list[Artifact]` return has no room to say  *“call 7
failed, here are the other 199”*, so the only thing a bare list can do when one
call raises is throw the whole run away — including artifacts that were already
generated and **already billed**.

This module is the vocabulary for saying it properly. Three states, not two:

`succeeded`
: The call ran (or was served from cache) and produced an
  `lacing.Artifact`.

`failed`
: The call raised. The exception is kept, so the caller can classify it
  ([`falaw.errors`](falaw.errors.html.md#module-falaw.errors) distinguishes rate-limiting from a locked account)
  and retry precisely this one call.

`blocked`
: The call never ran, because something it depends on did not succeed — a
  `"<from N>"` placeholder pointing at a failed upstream — or because the
  run was halted by an earlier failure.

The third state is what makes a chained plan safe to resume: a blocked call
must be *re-planned*, not retried, and a caller that cannot tell “blocked” from
“failed” will retry a call whose input does not exist.

### Examples

```pycon
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
```

### Module Attributes

| [`CallStatus`](#falaw.outcomes.CallStatus)   | What became of one [`CallPlan`](falaw.html.md#falaw.CallPlan) in a run.   |
|---------------------------------------------------------------|---------------------------------------------------------------------------------------------------------|

### Classes

| [`CallOutcome`](#falaw.outcomes.CallOutcome)(\*, index, call, status[, ...])   | What happened to one [`CallPlan`](falaw.html.md#falaw.CallPlan), at its position in the Plan.   |
|------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------|
| [`ExecutionReport`](#falaw.outcomes.ExecutionReport)([outcomes])                   | The result of running a Plan: one [`CallOutcome`](#falaw.outcomes.CallOutcome) per call, in order.            |

### *class* falaw.outcomes.CallOutcome(, index, call, status, artifact=None, error=None, cache_hit=False, blocked_by=(), reason='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What happened to one [`CallPlan`](falaw.html.md#falaw.CallPlan), at its position in the Plan.

`index` is the call’s position in `plan.calls` and is the identity a
caller retries or re-plans by — a report always carries exactly one outcome
per call, in plan order, so `index` is also the safe key for zipping a
Plan against anything the caller built alongside it.

#### artifact *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[Artifact]*

The materialized artifact. Set if and only if `status == "succeeded"`.

#### blocked_by *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[int](https://docs.python.org/3/builtins/functions.html#int), ...]*

Indices of the calls whose non-success blocked this one. `()` when the
call was blocked for a run-level reason rather than a dependency.

#### cache_hit *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

Whether the result came from the cache **as observed at run time**.

Not the same thing as [`falaw.CallPlan.cache_status`](falaw.html.md#falaw.CallPlan.cache_status), which is a
*prediction* made at plan time and can be wrong in both directions (a
concurrent run filled the entry; a hit turned out to be unusable and was
re-executed). Run-level cost accounting reads this one.

#### call *: [CallPlan](falaw.plan.html.md#falaw.plan.CallPlan)*

The call this outcome is about — enough to retry it verbatim.

#### error *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[BaseException](https://docs.python.org/3/builtins/exceptions.html#BaseException)]*

The exception the call raised. Set if and only if `status == "failed"`.

Kept as the exception object rather than a string so the caller can use
falaw’s typed hierarchy ([`falaw.errors`](falaw.errors.html.md#module-falaw.errors)) to decide between backing off,
switching models, and giving up.

#### index *: [int](https://docs.python.org/3/builtins/functions.html#int)*

Position in `plan.calls`. Stable, and unique within a report.

#### *property* ok *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

Shorthand for `status == "succeeded"`.

#### reason *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

Human-readable explanation. Required for `blocked`; free otherwise.

#### status *: [Literal](https://docs.python.org/3/library/typing.html#typing.Literal)['succeeded', 'failed', 'blocked']*

`"succeeded"` / `"failed"` / `"blocked"`. See the module docstring.

### falaw.outcomes.CallStatus

What became of one [`CallPlan`](falaw.html.md#falaw.CallPlan) in a run. See the module docstring.

alias of [`Literal`](https://docs.python.org/3/library/typing.html#typing.Literal)[‘succeeded’, ‘failed’, ‘blocked’]

### *class* falaw.outcomes.ExecutionReport(outcomes=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The result of running a Plan: one [`CallOutcome`](#falaw.outcomes.CallOutcome) per call, in order.

`len(report.outcomes) == len(plan.calls)` **always**, including on a run
where most calls failed. That invariant is the whole point: a consumer that
built something per call (nw builds one skeleton annotation per call) can
zip against `outcomes` and stay aligned. Zipping against a
*shorter* list of successes is the silent mis-pairing this type exists to
prevent.

#### artifacts_or_raise()

Every artifact in plan order, or re-raise the first failure’s exception.

The bridge back to the plain `list[Artifact]` contract of
[`falaw.execute_plan()`](falaw.html.md#falaw.execute_plan). The exception raised is the **original** one
the call raised, unwrapped — falaw’s typed error hierarchy
([`falaw.errors`](falaw.errors.html.md#module-falaw.errors)) is only useful to a caller if it survives the trip
through the executor.

A run with no failures but some blocked calls raises too: the list would
otherwise be short, and a short list is exactly the silent mis-pairing
this type exists to prevent.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[`Artifact`]

#### *property* blocked *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[CallOutcome](#falaw.outcomes.CallOutcome), ...]*

Outcomes whose call never ran, in plan order.

#### *property* cache_hit_savings_usd *: [float](https://docs.python.org/3/builtins/functions.html#float)*

Estimated USD *not* spent because a succeeded call was served from cache.

The run-time counterpart of [`falaw.Plan.cache_hit_savings_usd`](falaw.html.md#falaw.Plan.cache_hit_savings_usd)
(which is a plan-time prediction).

#### *property* estimated_spend_usd *: [float](https://docs.python.org/3/builtins/functions.html#float)*

succeeded calls that were **not** cache hits.

Estimated, because it sums [`falaw.CallPlan.estimated_cost_usd`](falaw.html.md#falaw.CallPlan.estimated_cost_usd) —
falaw does not read fal’s invoice. Two deliberate exclusions:

- **Cache hits cost nothing**, and this reads the *observed*
  [`CallOutcome.cache_hit`](#falaw.outcomes.CallOutcome.cache_hit), not the plan-time prediction.
- **Failed calls are not counted.** The vendor may or may not have
  billed a call that raised, and falaw cannot know which; adding an
  estimate for it would be inventing a number. Read
  [`failed`](#falaw.outcomes.ExecutionReport.failed) to see how many calls are unaccounted for.

* **Type:**
  Estimated USD billed by this run

#### *property* failed *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[CallOutcome](#falaw.outcomes.CallOutcome), ...]*

Outcomes whose call raised, in plan order.

#### *property* has_unknown_costs *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True when a call that actually billed has no price estimate.

The run-level twin of [`falaw.Plan.has_unknown_costs`](falaw.html.md#falaw.Plan.has_unknown_costs), and the
reason [`estimated_spend_usd`](#falaw.outcomes.ExecutionReport.estimated_spend_usd) must never be read on its own: an
unpriced call contributes `0.0` to the sum, so a report reading
`$0.00` means *either* “nothing was spent” *or* “we do not know what
was spent”. Those are not the same answer, and a budget gate that
cannot tell them apart approves the second one.

#### *property* is_complete *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True when every call succeeded.

#### *property* produced *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[Artifact, ...]*

The artifacts that were made, in plan order.

**Shorter than the Plan when anything failed** — deliberately named so
it does not read like something to zip a per-call sequence against. Use
`outcomes` for anything positional.

#### *property* succeeded *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[CallOutcome](#falaw.outcomes.CallOutcome), ...]*

Outcomes that produced an artifact, in plan order.

#### summary()

A small JSON-able digest — counts, spend, and which indices failed.

For logs, telemetry and run records, where the artifacts and exception
objects themselves are not serializable.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
