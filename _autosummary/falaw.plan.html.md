# falaw.plan

Plan / Execute primitives — separate planning (data) from execution (effects).

Today every falaw operation is eager: `generate_image(prompt)` makes the
API call immediately. That means:

- A budget gate has to predict cost from outside the call and *hope* the
  prediction matches what the operation will actually do.
- Tests need a fake fal_client to exercise any code that touches an
  operation, even when the test is about composition or cost.
- A UI can’t show “you’re about to spend $4.12, click confirm” without
  a separate, parallel cost-prediction code path.

The fix is to give every operation two surfaces:

1. `plan_X(...) -> CallPlan`: pure data describing the call that *would*
   happen — model_id, arguments, predicted cost, cache status. No API contact.
2. `execute(plan, ...) -> list[Artifact]`: turns a Plan (one or more
   CallPlans) into materialized Artifacts. The eager wrappers
   (`generate_image`, etc.) are now thin: `execute(plan_X(...))[0]`.

A higher-level orchestrator (a music-video render, a storyboard generation)
builds a Plan by composing CallPlans across multiple operations. The Plan
gets a typed `total_cost_usd`, can be inspected, edited, dry-run, or
serialized — all without the network.

### Examples

```pycon
>>> from falaw.plan import CallPlan, Plan
>>> p1 = CallPlan(
...     tool="generate_image",
...     application="fal-ai/flux/dev",
...     arguments={"prompt": "a tiger", "image_size": "landscape_4_3"},
...     output_kind="image",
...     estimated_cost_usd=0.025,
...     cache_status="miss",
... )
>>> p2 = CallPlan(
...     tool="image_to_video",
...     application="fal-ai/minimax/hailuo-02/pro/image-to-video",
...     arguments={"image_url": "<from p1>"},
...     output_kind="video",
...     estimated_cost_usd=0.50,
...     cache_status="miss",
... )
>>> plan = Plan(calls=(p1, p2))
>>> plan.total_cost_usd
0.525
>>> plan.cache_hit_savings_usd
0.0
>>> [c.tool for c in plan.calls]
['generate_image', 'image_to_video']
```

Plans concatenate, so an orchestrator can build one shot’s Plan and then
append it to a scene-level Plan:

```pycon
>>> shot_plan = Plan(calls=(p1,))
>>> scene_plan = Plan(calls=()) + shot_plan + Plan(calls=(p2,))
>>> len(scene_plan.calls)
2
```

### Module Attributes

| [`CacheStatus`](#falaw.plan.CacheStatus)        | Whether the cache will short-circuit this call.                                                                                                                        |
|---------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`OutputKind`](#falaw.plan.OutputKind)         | Coarse class of what this call produces.                                                                                                                               |
| [`PLAN_DICT_SCHEMA`](#falaw.plan.PLAN_DICT_SCHEMA)   | The `schema` tag [`plan_to_dict()`](#falaw.plan.plan_to_dict) writes and [`plan_from_dict()`](#falaw.plan.plan_from_dict) expects. |
| [`DFLT_FETCH_BYTES`](#falaw.plan.DFLT_FETCH_BYTES)   | Whether [`execute()`](#falaw.plan.execute) downloads media results to content-address them.                                                    |
| [`FETCH_BYTES_ENVVAR`](#falaw.plan.FETCH_BYTES_ENVVAR) | Env var overriding [`DFLT_FETCH_BYTES`](#falaw.plan.DFLT_FETCH_BYTES) process-wide.                                                                     |
| [`DFLT_CONCURRENCY`](#falaw.plan.DFLT_CONCURRENCY)   | How many calls of a Plan run at once by default.                                                                                                                       |
| [`CONTENT_REF_PREFIX`](#falaw.plan.CONTENT_REF_PREFIX) | Prefix marking a content hash where a cache key would otherwise hold a URL.                                                                                            |

### Functions

| [`call_plan_from_dict`](#falaw.plan.call_plan_from_dict)(d)                            | Rebuild a [`CallPlan`](#falaw.plan.CallPlan) from a [`call_plan_to_dict()`](#falaw.plan.call_plan_to_dict) dict.   |
|----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`call_plan_to_dict`](#falaw.plan.call_plan_to_dict)(call)                           | Convert a [`CallPlan`](#falaw.plan.CallPlan) to a plain JSON-serializable dict.                                                  |
| [`cost_basis_from_dict`](#falaw.plan.cost_basis_from_dict)(d)                           | Rebuild a [`CostBasis`](#falaw.plan.CostBasis) from a [`cost_basis_to_dict()`](#falaw.plan.cost_basis_to_dict) dict. |
| [`cost_basis_to_dict`](#falaw.plan.cost_basis_to_dict)(basis)                         | Convert a [`CostBasis`](#falaw.plan.CostBasis) to a plain JSON-serializable dict.                                                 |
| [`execute`](#falaw.plan.execute)(plan, \*[, on_event, dry_run, ...])       | Execute a Plan, returning a list of materialized :class:<br/><br/>```<br/>`<br/>```<br/><br/>lacing.Artifact\`s.                                        |
| [`execute_isolated`](#falaw.plan.execute_isolated)(plan, \*[, on_event, ...])       | Execute a Plan with **per-call failure isolation**, returning a report.                                                                                 |
| [`extract_first_url`](#falaw.plan.extract_first_url)(raw)                            | Find the first asset URL in a fal response, regardless of shape.                                                                                        |
| [`make_call_plan`](#falaw.plan.make_call_plan)(\*, tool, application, ...[, ...]) | Build a [`CallPlan`](#falaw.plan.CallPlan) and (optionally) check the cache.                                                     |
| [`plan_dependencies`](#falaw.plan.plan_dependencies)(plan)                           | Per-call set of the call indices it references via `"<from N>"`.                                                                                        |
| [`plan_from_dict`](#falaw.plan.plan_from_dict)(d)                                 | Rebuild a [`Plan`](#falaw.plan.Plan) from a [`plan_to_dict()`](#falaw.plan.plan_to_dict) dict.            |
| [`plan_hash`](#falaw.plan.plan_hash)(plan)                                   | Stable, plan-scoped **structural idempotency key** for a whole [`Plan`](#falaw.plan.Plan).                                   |
| [`plan_to_dict`](#falaw.plan.plan_to_dict)(plan)                                | Convert a [`Plan`](#falaw.plan.Plan) to a plain JSON-serializable dict.                                                      |

### Classes

| [`CallPlan`](#falaw.plan.CallPlan)(\*, tool, application[, backend, ...])   | A single planned fal call.                                                                                    |
|----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------|
| [`CostBasis`](#falaw.plan.CostBasis)(\*, pricer, priced[, quantities, ...])  | How a [`CallPlan.estimated_cost_usd`](#falaw.plan.CallPlan.estimated_cost_usd) was arrived at (falaw#60). |
| [`Plan`](#falaw.plan.Plan)([calls])                                     | An ordered sequence of [`CallPlan`](#falaw.plan.CallPlan) — a render plan, in essence. |

### falaw.plan.CONTENT_REF_PREFIX *= 'sha256:'*

Prefix marking a content hash where a cache key would otherwise hold a URL.

Self-describing on purpose: a reader of a cache manifest can tell at a glance
that an argument was keyed on *what the upstream produced* rather than \*where
it was served from\*, and the prefixed form can never be confused with a
literal URL argument.

### falaw.plan.CacheStatus

Whether the cache will short-circuit this call.

- `hit`: A cached response exists and will be returned without an API call.
- `miss`: No cache entry; the call will hit fal.
- `stale`: An entry exists but is expected to be invalidated (e.g. a
  `force=True` re-render asked for it). Today we don’t distinguish stale
  from miss for cost — both are billed.
- `unknown`: Plan was built without consulting the cache.

alias of [`Literal`](https://docs.python.org/3/library/typing.html#typing.Literal)[‘hit’, ‘miss’, ‘stale’, ‘unknown’]

### *class* falaw.plan.CallPlan(, tool, application, backend='fal', arguments, output_kind, estimated_cost_usd=None, cache_status='unknown', expected_duration_s=None, metadata=dict(), key_extra=dict(), local_files=(), cost_basis=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A single planned fal call. Pure data — no API contact yet.

`application` and `arguments` are the *exact* tuple
`cached_call_fal(application, arguments)` would take, so a Plan can be
cache-checked, executed, or replayed without ambiguity.

#### application *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The fal model id that will be invoked (e.g. `"fal-ai/flux/dev"`).
Backend-scoped: what it names depends on [`backend`](#falaw.plan.CallPlan.backend).

#### arguments *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)*

Keyword arguments to pass to fal. Will be JSON-canonicalized for
cache key computation; should be JSON-serializable.

#### backend *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

Which execution backend `execute_plan()` dispatches this call to
(falaw#15) — see [`falaw.backends`](falaw.backends.html.md#module-falaw.backends). Defaults to
[`falaw.canonical.DFLT_BACKEND`](falaw.canonical.html.md#falaw.canonical.DFLT_BACKEND) (`"fal"`), the only backend until a
second one lands. Enters the per-call cache key and `plan_hash` only
when it is **not** the default, so every call falaw has ever planned or
cached keeps its exact pre-#15 digest — see [`falaw.canonical`](falaw.canonical.html.md#module-falaw.canonical).

#### *property* billable_cost_usd *: [float](https://docs.python.org/3/builtins/functions.html#float)*

Cost that will actually be billed (0 on cache hit, estimate otherwise).

Returns `0.0` (not `None`) on cache hit or unknown estimate so
sums are well-defined; use [`estimated_cost_usd`](#falaw.plan.CallPlan.estimated_cost_usd) `is None` to
check unknown status explicitly.

#### cache_status *: [Literal](https://docs.python.org/3/library/typing.html#typing.Literal)['hit', 'miss', 'stale', 'unknown']*

Whether the cache will short-circuit this call. `"hit"` means
`execute` won’t bill, so [`Plan.total_cost_usd`](#falaw.plan.Plan.total_cost_usd) and
[`Plan.cache_hit_savings_usd`](#falaw.plan.Plan.cache_hit_savings_usd) reflect that.

#### cost_basis *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[CostBasis](#falaw.plan.CostBasis)]*

How [`estimated_cost_usd`](#falaw.plan.CallPlan.estimated_cost_usd) was computed, or `None` when nothing
recorded it (falaw#60). Present, the quote can be re-run against today’s
rate table by [`falaw.reprice_plan()`](falaw.html.md#falaw.reprice_plan); absent, that function reports the
call as `"no_basis"` and clears its cost to unknown rather than passing a
stale figure off as current. Purely descriptive — it stays out of
[`plan_hash()`](#falaw.plan.plan_hash) and the per-call cache key, and out of the serialized
dict entirely when unset, so every plan falaw has ever hashed or persisted
is unmoved.

#### estimated_cost_usd *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[float](https://docs.python.org/3/builtins/functions.html#float)]*

Predicted cost in USD. `None` when the model has no `cost_estimate`
populated (callers can distinguish “free” from “unknown”).

#### expected_duration_s *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[float](https://docs.python.org/3/builtins/functions.html#float), [float](https://docs.python.org/3/builtins/functions.html#float)]]*

`(min, max)` duration the model can produce, or `None` if no
duration contract is known. Plan-level validators can check that the
requested duration fits this range and raise `FalDurationOutOfRange`
*before* the call instead of letting it silently truncate.

#### key_extra *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)*

Identity beyond the wire arguments — entries that change what the call
*produces* without appearing in `arguments`. Participates in the
per-call cache key AND `plan_hash`, under omit-if-empty (an empty dict
leaves every existing key byte-identical). Unlike `metadata`, which is
deliberately identity-free labelling, putting something here says “a
cached result minted without this value must not be reused”. First
customer: nw’s Transform `impl_version` (nw#27) — “same interface,
changed behaviour” must miss the cache without renaming anything.

#### local_files *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)*

one pointer
(a tuple of dict keys / list indices) per `os.PathLike` the caller passed.
Only these are resolved at execute time (uploaded on a cache miss, keyed on
the file’s sha256), so a string that merely looks like a marker is inert.
Omit-when-empty on the wire (like `cost_basis`): a plan with no local
file serializes to the bytes it did before the field existed; absent reads
as empty.

* **Type:**
  Where [`arguments`](#falaw.plan.CallPlan.arguments) holds local-file markers (falaw#92)

#### metadata *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)*

Free-form labels for downstream consumers. Conventional keys:
`shot_id`, `beat_id`, `character_name`, `strategy`.

#### output_kind *: [Literal](https://docs.python.org/3/library/typing.html#typing.Literal)['image', 'video', 'audio', 'json', 'text', 'binary']*

What kind of Artifact this call will produce.

#### tool *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

High-level tool name — `"generate_image"`, `"image_to_video"`, etc.
Distinct from `application` because one tool may dispatch to several
fal models depending on quality tier.

### *class* falaw.plan.CostBasis(, pricer, priced, quantities=dict(), table='', table_version='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

How a [`CallPlan.estimated_cost_usd`](#falaw.plan.CallPlan.estimated_cost_usd) was arrived at (falaw#60).

A frozen quote goes stale the moment the rate table moves — 0.0.46 moved
falaw’s LLM prices tenfold — and a persisted plan cannot be re-quoted from
`application` and `arguments` alone: the quantity hints that priced it
(the clip’s duration, the prompt’s token bound) are estimator-only and
never enter the wire arguments. This records them, plus *which* table
priced them, so a saved plan can be re-quoted faithfully
([`falaw.reprice_plan()`](falaw.html.md#falaw.reprice_plan)) and audited after the fact.

Pure data. Nothing here reaches the network, and nothing here enters
[`plan_hash()`](#falaw.plan.plan_hash) or the per-call cache key: a basis says what a call
*cost*, never what it *produces*, so stamping one leaves every existing
digest byte-identical.

#### priced *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

a `falaw.ModelRecord.id` for the
catalogue pricer, the routed `model` argument for the LLM pricer.
Distinct from [`CallPlan.application`](#falaw.plan.CallPlan.application), which for `fal-ai/any-llm`
names the router rather than the model that sets the price.

* **Type:**
  The entity that was priced

#### pricer *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

Which pricing rule produced the figure — a key into
[`falaw.reprice.DFLT_PRICERS`](falaw.reprice.html.md#falaw.reprice.DFLT_PRICERS). `"model_catalogue"` for a record
priced out of `models.json`, `"llm_rates"` for a routed LLM priced out
of `llm_rates.json`. An unrecognized name re-prices as *unknown*, never
as the old number.

#### quantities *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)*

The estimator-only shape hints fed to the pricer, by keyword —
`{"seconds": 6.0}`, `{"input_tokens": 20000, "max_output_tokens": 4000}`.
Absent keys mean the hint was not supplied, which is what made a
quantity-priced call unpriceable in the first place. Omit-when-unset: a
hint that was `None` at plan time is left out rather than written as
`null`.

#### table *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

Identity of the rate table consulted, e.g.
`"falaw/data/llm_rates.json"`. Free-form so a caller’s own reconciled
table can name itself.

#### table_version *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The version of that table at plan time — falaw stamps a short content
digest, so a table whose numbers moved gets a different value even when
its declared version did not. Empty means unversioned/unknown.

### falaw.plan.DFLT_CONCURRENCY *= 1*

How many calls of a Plan run at once by default.

One — a Plan executes sequentially unless the caller asks otherwise. Every call
is a paid vendor request, so parallelism is opt-in: it is the caller who knows
their rate limit, their budget, and whether they want 200 renders started at
once. ([`falaw.render_scene()`](falaw.html.md#falaw.render_scene) makes the same choice for the same reason.)

### falaw.plan.DFLT_FETCH_BYTES *= True*

Whether [`execute()`](#falaw.plan.execute) downloads media results to content-address them.

True — an artifact whose `asset_id` is not the SHA-256 of its bytes breaks
`lacing.Artifact`’s contract and puts an expiring location into every
downstream cache key.

### falaw.plan.FETCH_BYTES_ENVVAR *= 'FALAW_FETCH_ARTIFACT_BYTES'*

Env var overriding [`DFLT_FETCH_BYTES`](#falaw.plan.DFLT_FETCH_BYTES) process-wide.

Not a production setting — see the `fetch_bytes` argument of [`execute()`](#falaw.plan.execute)
for what opting out costs. Read at call time, so it can be set after import.

**Do not reach for this to make a test suite offline.** It works, and that is
the trap: it silences the network by turning content addressing **off**, so the
suite becomes hermetic and simultaneously stops exercising the feature. Every
`asset_id` becomes a digest of the response rather than the SHA-256 of the
bytes, chained calls key on URLs, and no test then covers the path production
actually takes. Install a fake transport instead —
[`falaw.testing.fake_assets()`](falaw.testing.html.md#falaw.testing.fake_assets) is one line in a `conftest.py` — and the
suite stays offline *with* content addressing under test, on bytes it controls.
Both consumers that hit this chose the fake for exactly that reason
(thorwhalen/falaw#27).

### falaw.plan.OutputKind

Coarse class of what this call produces. Mirrors `lacing.Artifact.kind`
so the producer knows what shape of Artifact to materialize.

alias of [`Literal`](https://docs.python.org/3/library/typing.html#typing.Literal)[‘image’, ‘video’, ‘audio’, ‘json’, ‘text’, ‘binary’]

### falaw.plan.PLAN_DICT_SCHEMA *= 'falaw.plan/v1'*

The `schema` tag [`plan_to_dict()`](#falaw.plan.plan_to_dict) writes and [`plan_from_dict()`](#falaw.plan.plan_from_dict)
expects. Bumped only on a breaking change to the dict shape.

### *class* falaw.plan.Plan(calls=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

An ordered sequence of [`CallPlan`](#falaw.plan.CallPlan) — a render plan, in essence.

Plans compose: `a + b` returns a new Plan with `a.calls` followed by
`b.calls`. `Plan(calls=())` is the identity. Plans are frozen, so
edits return new Plans (use [`with_call_replaced()`](#falaw.plan.Plan.with_call_replaced) for in-place-feel).

#### *property* cache_hit_savings_usd *: [float](https://docs.python.org/3/builtins/functions.html#float)*

USD that would have been spent without the cache.

Equal to `sum(c.estimated_cost_usd for c in calls if c.cache_status == "hit"
and c.estimated_cost_usd is not None)`.

#### *property* has_unknown_costs *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True if any non-cache-hit call has no cost estimate.

Use this to refuse to gate on a budget when the estimate is incomplete.

#### *property* known_cost_usd *: [float](https://docs.python.org/3/builtins/functions.html#float)*

The priced part of [`total_cost_usd`](#falaw.plan.Plan.total_cost_usd) — same number today,
but honest by construction.

`total_cost_usd` coerces unpriced calls to `$0.00` so sums stay
well-defined; a cumulative budget gate that reads it alone will
under-quote (400 unpriceable video calls total $0.00). Read this
together with [`unknown_call_count`](#falaw.plan.Plan.unknown_call_count): the true cost is
`known_cost_usd` *plus an unknown amount* spread over that many
calls, and a correct gate refuses when the count is nonzero rather
than pretending the unknown part is free (falaw#18).

#### *property* total_cost_usd *: [float](https://docs.python.org/3/builtins/functions.html#float)*

Sum of [`CallPlan.billable_cost_usd`](#falaw.plan.CallPlan.billable_cost_usd) across all calls.

#### *property* unknown_call_count *: [int](https://docs.python.org/3/builtins/functions.html#int)*

How many billable calls carry no price at all.

The countable form of [`has_unknown_costs`](#falaw.plan.Plan.has_unknown_costs) — see
[`known_cost_usd`](#falaw.plan.Plan.known_cost_usd) for the budget-gate arithmetic it enables.

#### with_call_replaced(index, new_call)

Return a new Plan with `calls[index]` replaced.

* **Return type:**
  [`Plan`](#falaw.plan.Plan)

### falaw.plan.call_plan_from_dict(d)

Rebuild a [`CallPlan`](#falaw.plan.CallPlan) from a [`call_plan_to_dict()`](#falaw.plan.call_plan_to_dict) dict.

`arguments` / `metadata` are copied (a deserialized plan owns its own
data); `expected_duration_s` is re-tupled. `backend` defaults to
`DFLT_BACKEND` when absent — a dict written before falaw#15 names no
backend, and it always meant `"fal"`.

`cost_basis` is absent on any plan written before falaw#60 and on any
call nothing stamped; it comes back as `None`, which
[`falaw.reprice_plan()`](falaw.html.md#falaw.reprice_plan) reports as `"no_basis"` — never as a quote
that is still current.

* **Return type:**
  [`CallPlan`](#falaw.plan.CallPlan)

### falaw.plan.call_plan_to_dict(call)

Convert a [`CallPlan`](#falaw.plan.CallPlan) to a plain JSON-serializable dict.

The inverse of [`call_plan_from_dict()`](#falaw.plan.call_plan_from_dict). `expected_duration_s` (a
`tuple`) becomes a 2-element list since JSON has no tuple type;
everything else is already JSON-native.

`backend` (falaw#15) is a **tolerated-default addition**, not a
[`PLAN_DICT_SCHEMA`](#falaw.plan.PLAN_DICT_SCHEMA) bump: it is always written, but
[`call_plan_from_dict()`](#falaw.plan.call_plan_from_dict) defaults it to `DFLT_BACKEND` when
absent, so a dict from before this field existed still parses, and a
dict written by this version still parses under older falaw (the extra
key is simply never read there). No migration needed either direction.

`cost_basis` (falaw#60) is the same kind of addition under a stricter
rule — **omit-when-unset**: the key is written only when a basis exists, so
a plan built without one serializes to the exact bytes it did before the
field existed, and every stored plan, fixture and cassette is unmoved.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### falaw.plan.cost_basis_from_dict(d)

Rebuild a [`CostBasis`](#falaw.plan.CostBasis) from a [`cost_basis_to_dict()`](#falaw.plan.cost_basis_to_dict) dict.

* **Return type:**
  [`CostBasis`](#falaw.plan.CostBasis)

### falaw.plan.cost_basis_to_dict(basis)

Convert a [`CostBasis`](#falaw.plan.CostBasis) to a plain JSON-serializable dict.

`table` / `table_version` are omitted when empty, matching the
omit-when-unset discipline the rest of the wire shape follows — a basis
that names no table writes no key rather than a pair of `""`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### falaw.plan.execute(plan, , on_event=None, dry_run=False, use_cache=True, refresh=False, artifact_converter=None, content_store=None, fetch_bytes=None, asset_fetcher=None, concurrency=1)

Execute a Plan, returning a list of materialized :class:

```
`
```

lacing.Artifact\`s.

This is the **halt** policy: the first call that raises ends the run, and its
exception propagates unchanged (falaw’s typed hierarchy — see
[`falaw.errors`](falaw.errors.html.md#module-falaw.errors) — is what a caller classifies on, so it is never
wrapped). Use [`execute_isolated()`](#falaw.plan.execute_isolated) when one bad call must not discard
the rest of a fan-out; it returns an [`ExecutionReport`](falaw.html.md#falaw.ExecutionReport) with one
outcome per call instead of raising.

* **Parameters:**
  * **plan** ([`Plan`](#falaw.plan.Plan)) – The Plan to execute.
  * **on_event** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)]) – Optional per-call event subscriber (passed to `call_fal`).
  * **dry_run** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – When True, no fal calls are made; synthetic Artifacts are
    returned with placeholder `asset_id` and `url=None`. Useful
    for exercising downstream composition without an API key.
  * **use_cache** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – When True (default), executes via `cached_call_fal` so
    cache hits skip the network. When False, the cache is not touched
    **at all** — neither read nor written. That is the historical
    meaning and it is unchanged: a caller who genuinely wants no cache
    interaction still has it. To re-run a plan and *keep* what the
    re-run paid for, leave `use_cache=True` and pass `refresh`.
  * **refresh** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – When True, skip the cache **read** and keep the cache
    **write** — the third mode (falaw#49). Every call executes fresh,
    and every fresh result is stored under the key it would have been
    read from, so the next run (or a downstream consumer) hits it.
    Requires `use_cache=True`, since there is no key to write under
    when the cache is off; the contradictory combination raises rather
    than silently picking one. This is the mode to reach for behind a
    `force` / “re-verify this” switch: without it, forcing a re-run
    discards the result it just paid for and guarantees the next
    consumer re-bills.
  * **artifact_converter** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict), [`CallPlan`](#falaw.plan.CallPlan)], Artifact]]) – Per-CallPlan converter from raw fal response to
    `lacing.Artifact`. When `None` (default), a built-in
    converter handles the common shapes (`{images: [{url}]}`,
    `{video: {url}}`, `{audio: {url}}`). Mutually exclusive with
    `content_store` / `fetch_bytes` / `asset_fetcher`, which
    configure the built-in converter only — passing both raises, rather
    than silently ignoring the ones a custom converter cannot honour.
    Converters do not own `cost_usd`: the executor stamps it from
    the observed run outcome after conversion, overwriting whatever
    the converter set (falaw#26).
  * **content_store** – Injected `lacing.ArtifactStore` that media bytes
    are materialized into. Defaults to
    [`falaw.content.default_content_store()`](falaw.content.html.md#falaw.content.default_content_store) (a directory store
    rooted in the falaw cache). Point this at an S3-backed store to
    share content — and therefore cache hits — across machines.
  * **fetch_bytes** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool)]) – Whether to download each media result so its `asset_id`
    is the SHA-256 of its bytes. Defaults to [`DFLT_FETCH_BYTES`](#falaw.plan.DFLT_FETCH_BYTES)
    (true), overridable process-wide via [`FETCH_BYTES_ENVVAR`](#falaw.plan.FETCH_BYTES_ENVVAR).
    **Opting out forfeits caching for chained calls**: without bytes
    there is no content hash, so downstream calls fall back to keying
    on the upstream URL — which fal mints fresh per upload, so the
    downstream entry can never be reused across runs or machines. It
    also means `asset_id` is *not* a content hash, in violation of
    `lacing.Artifact`’s contract. Use it only when you genuinely
    want URL-only artifacts and no reuse.
  * **asset_fetcher** – Injected byte source (`url -> Iterable[bytes]`) used to
    read media results; defaults to
    [`falaw.content.default_url_fetcher()`](falaw.content.html.md#falaw.content.default_url_fetcher). This is the per-call
    transport seam. A **hermetic test suite** usually wants the
    process-wide one instead — [`falaw.testing.fake_assets()`](falaw.testing.html.md#falaw.testing.fake_assets), built
    on [`falaw.content.using_url_fetcher()`](falaw.content.html.md#falaw.content.using_url_fetcher) — because a suite
    reaching falaw *through* its own public API has no `execute`
    call site to pass this to. Passing it here still wins over any
    installed default. (`$FALAW_FETCH_ARTIFACT_BYTES=0` also silences
    the network, but by turning content addressing off — see
    [`FETCH_BYTES_ENVVAR`](#falaw.plan.FETCH_BYTES_ENVVAR).)
  * **concurrency** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – How many calls may be in flight at once. `1`
    ([`DFLT_CONCURRENCY`](#falaw.plan.DFLT_CONCURRENCY)) runs the Plan sequentially, on the
    calling thread, exactly as it always has. Above 1, independent calls
    run on a thread pool bounded by this number — a Plan is I/O-bound
    (an HTTP request that fal takes tens of seconds to answer), so
    threads are the right tool and the bound is what keeps a 200-call
    fan-out from becoming 200 simultaneous paid requests. \*\*Chained
    calls are never parallelised with their producers\*\*: a call holding
    a `"<from N>"` placeholder waits for call `N`. Two things to
    weigh before raising it: the vendor’s rate limit, and memory —
    materializing a media result peaks at roughly twice the asset’s size
    (thorwhalen/lacing#25), so `concurrency` multiplies the peak.
* **Return type:**
  [*list*](https://docs.python.org/3/builtins/stdtypes.html#list)

## Failure handling — a paid result is never discarded

Two different things can go wrong when reading a result’s bytes, and they
get two different answers:

- **A fresh call whose bytes cannot be fetched.** fal has already run — and
  billed — the generation. Raising would throw away a result we paid for,
  typically over a transient network failure. So the artifact **degrades**:
  `url` is kept, `bytes_size` stays 0, `asset_id` is a digest of the
  response and is *not* claimed to be a content hash, and a
  [`UserWarning`](https://docs.python.org/3/builtins/exceptions.html#UserWarning) is emitted. Downstream key resolution reads
  > `bytes_size == 0` and falls back to the URL — a guaranteed cache
  > *miss*, never a wrong hit.
- **A cache hit that cannot be materialized** — fal deleted the URL and the
  bytes are not in the content store. The entry is unusable, so it is
  treated as a **miss**: it is invalidated and the call re-executed once.
  A cache must never become a trap whose only escape is re-billing the
  whole plan with `use_cache=False`.

## Placeholder resolution — the wire/key split

Any string argument equal to `"<from N>"` (for an integer `N`) is
rewritten *just before* the call is made — so a multi-step plan (e.g.
generate_image → image_to_video) can reference the upstream output without
the planner needing to know its URL. The rewrite happens after the upstream
call has executed; planning itself is unaffected.

It happens **twice**, into two different argument sets, because the same
value cannot serve both jobs:

- the **wire** arguments get `artifacts[N].url` — what fal needs in order
  to fetch the input;
- the **key** arguments get `sha256:<artifacts[N].asset_id>` — the
  upstream’s content hash, so a byte-identical upstream regeneration
  produces a downstream cache *hit* instead of re-billing the expensive
  call. Keying on the URL instead is the defect this split exists to fix
  (falaw#14): fal mints a unique URL per upload, so a URL-keyed downstream
  entry is unreachable the moment the upstream genuinely re-runs.

An upstream artifact with no materialized bytes has no content hash, so its
key ref falls back to the URL — a guaranteed miss, never a wrong hit.

* **rtype:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)
* **returns:**
  One `lacing.Artifact` per [`CallPlan`](#falaw.plan.CallPlan) in `plan.calls`,
  in the same order.

### falaw.plan.execute_isolated(plan, , on_event=None, dry_run=False, use_cache=True, refresh=False, artifact_converter=None, content_store=None, fetch_bytes=None, asset_fetcher=None, concurrency=1, halt_on_failure=False)

Execute a Plan with **per-call failure isolation**, returning a report.

The fan-out counterpart of [`execute()`](#falaw.plan.execute). Where `execute` raises on the
first failure — discarding every artifact produced before it, each of which
fal has already billed — this returns an [`ExecutionReport`](falaw.html.md#falaw.ExecutionReport)
carrying one [`CallOutcome`](falaw.html.md#falaw.CallOutcome) per call: the successes with their
artifacts, the failures with their exceptions, and the calls that never ran
with the reason why.

`len(report.outcomes) == len(plan.calls)` always, so a caller that built
something per call can zip against `report.outcomes` and stay aligned.

* **Parameters:**
  **halt_on_failure** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – When True, stop *submitting* work as soon as any call
  fails; everything not yet started is reported `blocked` with a
  run-level reason. This is what [`execute()`](#falaw.plan.execute) uses, and at
  `concurrency=1` it reproduces the historical sequential
  behaviour exactly. Note that at `concurrency > 1` calls already
  in flight are **not** cancelled — a fal request cannot be recalled
  once made, and pretending otherwise would discard results that were
  billed anyway.
* **Return type:**
  [`ExecutionReport`](falaw.outcomes.html.md#falaw.outcomes.ExecutionReport)

:param All other arguments are as [`execute()`](#falaw.plan.execute).:

## Three outcome states, not two

`failed` and `blocked` are different questions for the caller. A failed
call can be retried verbatim. A blocked one cannot: its input does not
exist, so it has to be re-planned after its producer succeeds. Any call
holding a `"<from N>"` placeholder whose call `N` did not succeed is
blocked, transitively.

### Examples

```pycon
>>> from falaw import CallPlan, Plan, execute_plan_isolated
>>> plan = Plan(calls=(CallPlan(tool="t", application="m",
...                             arguments={}, output_kind="image"),))
>>> report = execute_plan_isolated(plan, dry_run=True)
>>> report.is_complete, len(report.outcomes)
(True, 1)
```

### falaw.plan.extract_first_url(raw)

Find the first asset URL in a fal response, regardless of shape.

Public (no underscore) because it is now used from [`falaw.prune`](falaw.prune.html.md#module-falaw.prune) as
well: deciding whether pruning a blob makes a cache entry unmaterializable
is the *same* question this answers for `execute`, and the two must not
drift into two opinions about what a response’s asset is.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### falaw.plan.make_call_plan(, tool, application, arguments, output_kind, backend='fal', estimated_cost_usd=None, expected_duration_s=None, metadata=None, consult_cache=True, cost_basis=None)

Build a [`CallPlan`](#falaw.plan.CallPlan) and (optionally) check the cache.

When `consult_cache=True` (the default), the cache is peeked using the
same key the eventual call would produce; `cache_status` is set to
`"hit"` if a cached entry exists, `"miss"` otherwise. This makes
`Plan.total_cost_usd` honest: a fully-cached Plan reports $0.

When `consult_cache=False` (e.g. for unit tests or “what would a fresh
run cost?” reporting), `cache_status` is `"unknown"`.

A **chained call** — arguments still holding a `"<from N>"` placeholder,
because the upstream call has not executed yet — is never peeked
(falaw#15, D2): its resolved key is not knowable at plan time, and the
unresolved key is never written by anything ([`execute()`](#falaw.plan.execute) always keys
on the resolved form), so peeking it can only ever report a false
`"miss"` — never a real `"hit"`. That silently over-quotes cost and
under-reports the plan’s `cache_hit_savings_usd` on every chained call,
which under prepaid billing (a quote that may be *deducted*) is a billing
bug. `cache_status` is `"unknown"` here instead, exactly the case
[`CacheStatus`](#falaw.plan.CacheStatus) documents it for.

`cost_basis` records how `estimated_cost_usd` was arrived at so the
quote can be re-run later (falaw#60). It is descriptive only: it never
reaches the cache key or [`plan_hash()`](#falaw.plan.plan_hash), and a plan built without one
is byte-identical to one built before the field existed.

* **Raises:**
  [**FalNonCanonicalArgument**](falaw.errors.html.md#falaw.errors.FalNonCanonicalArgument) – an argument cannot be hashed
      faithfully (non-JSON object, non-finite float, non-string mapping
      key). Raised here — while planning is still free — rather than at
      key-composition time on the way to the network (falaw#17).
* **Return type:**
  [`CallPlan`](#falaw.plan.CallPlan)

### falaw.plan.plan_dependencies(plan)

Per-call set of the call indices it references via `"<from N>"`.

The Plan’s dependency DAG, read straight off the placeholders — one
`frozenset` per call, in plan order, so `deps[3] == {1}` means call 3
consumes call 1’s output. An empty set means the call is **independent** and
may run concurrently with any other independent call, which is what
[`execute_isolated()`](#falaw.plan.execute_isolated) schedules on.

Also the plan’s structural validator, and it runs \*\*before a cent is
spent\*\*: a malformed reference used to surface only when execution reached
the offending call, i.e. after every call before it had been billed.

* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – a placeholder that is not `"<from N>"` for an integer
      `N`; an `N` outside the plan; or an `N` that does not run
      *before* the referencing call (including a self-reference) — the
      output would not exist yet, so it can only ever be a bug.
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)[[`int`](https://docs.python.org/3/builtins/functions.html#int)], [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

```pycon
>>> a = CallPlan(tool="t", application="m", arguments={}, output_kind="image")
>>> b = CallPlan(tool="t", application="m",
...              arguments={"image_url": "<from 0>"}, output_kind="video")
>>> plan_dependencies(Plan(calls=(a, b)))
(frozenset(), frozenset({0}))
>>> plan_dependencies(Plan(calls=(b,)))
Traceback (most recent call last):
    ...
ValueError: Placeholder '<from 0>' in call 0 references call 0, which does not run before it. ...
```

### falaw.plan.plan_from_dict(d)

Rebuild a [`Plan`](#falaw.plan.Plan) from a [`plan_to_dict()`](#falaw.plan.plan_to_dict) dict.

Raises `ValueError` if `d` carries an unrecognized `schema` tag — a
plan written by an incompatible future version should fail loudly, not
silently lose calls. A missing `schema` is tolerated (treated as v1) so
hand-written plans stay easy.

* **Return type:**
  [`Plan`](#falaw.plan.Plan)

### falaw.plan.plan_hash(plan)

Stable, plan-scoped **structural idempotency key** for a whole [`Plan`](#falaw.plan.Plan).

Answers “does this whole plan match one I already ran?” — the handle a job
manager (its first customer, `nw.jobs`) uses to dedup double-submits and
to replay a resumed render for free. It is computed *before* execution and
with `<from N>` placeholders intact, so it is stable across re-plans of the
same structural request.

The digest canonicalizes each call over `{app, args, tool}`
([`falaw.canonical.plan_identity_payload()`](falaw.canonical.html.md#falaw.canonical.plan_identity_payload)) — matching
`_synthetic_artifact()`’s canonicalization, and deliberately **not** the
per-call content-addressed cache key (`falaw.cache._key()`, which keys on
`{app, args}` with no `tool`). `plan_hash` and the per-call cache key
therefore key on *different* bytes and must not be assumed to agree
call-for-call. Both projections live side by side in [`falaw.canonical`](falaw.canonical.html.md#module-falaw.canonical)
with one shared byte-form ([`falaw.canonical.canonical_blob()`](falaw.canonical.html.md#falaw.canonical.canonical_blob) — sorted
keys, **no** `default=str` fallback, no NaN), so an argument the form
cannot represent faithfully raises
[`falaw.errors.FalNonCanonicalArgument`](falaw.errors.html.md#falaw.errors.FalNonCanonicalArgument) instead of colliding, and a
new identity-bearing field is an explicit decision about both hashes.

Two structurally-identical plans hash equal; changing any call’s `app`,
`args`, or `tool` — or the *order* of calls — changes the hash.

```pycon
>>> a = CallPlan(tool="generate_image", application="fal-ai/flux/dev",
...              arguments={"prompt": "a tiger"}, output_kind="image")
>>> b = CallPlan(tool="image_to_video", application="fal-ai/svd",
...              arguments={"image_url": "<from 0>"}, output_kind="video")
>>> plan_hash(Plan(calls=(a, b))) == plan_hash(Plan(calls=(a, b)))
True
>>> plan_hash(Plan(calls=(a, b))) == plan_hash(Plan(calls=(b, a)))
False
```

`backend` (falaw#15) joins the hashed payload too, so a plan built for
one backend never dedups against the structurally-identical plan for
another — and, since it is included only when non-default, every plan
made of today’s (all-`"fal"`) calls hashes exactly as it did before:

```pycon
>>> comfy = CallPlan(tool="generate_image", application="fal-ai/flux/dev",
...                   arguments={"prompt": "a tiger"}, output_kind="image",
...                   backend="comfyui")
>>> plan_hash(Plan(calls=(a,))) == plan_hash(Plan(calls=(comfy,)))
False
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### falaw.plan.plan_to_dict(plan)

Convert a [`Plan`](#falaw.plan.Plan) to a plain JSON-serializable dict.

The result round-trips through [`plan_from_dict()`](#falaw.plan.plan_from_dict). This is the
substrate primitive a consumer (a persistence layer, an MCP transport, a
plan-diff tool) builds on — falaw owns the wire shape of its own Plan so
every consumer agrees on it. Carries a `schema` tag ([`PLAN_DICT_SCHEMA`](#falaw.plan.PLAN_DICT_SCHEMA))
so a future breaking change is detectable.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
