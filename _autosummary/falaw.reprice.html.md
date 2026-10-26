# falaw.reprice

Re-quote a persisted [`falaw.Plan`](falaw.html.md#falaw.Plan) at today’s rates (falaw#60).

A `CallPlan`’s `estimated_cost_usd` is frozen at plan time. That is right —
a quote is a statement about a moment — but rate tables move: falaw 0.0.46
re-quoted every premium LLM call **tenfold upward**, so a preview saved the day
before under-quotes the run it is being used to price. Under-quoting is the one
direction a cost gate must never err in.

Re-quoting cannot be done from `application` and `arguments` alone. The
quantity hints that priced a call — a clip’s duration, a prompt’s token bound —
are estimator-only and deliberately never enter the wire arguments, so they are
not on the serialized call. [`falaw.CostBasis`](falaw.html.md#falaw.CostBasis) is where a `plan_*`
records them, together with which rate table it consulted; this module is what
reads one back:

```pycon
>>> from falaw import plan_generate_image, Plan, reprice_plan
>>> plan = Plan(calls=(plan_generate_image("a tiger", consult_cache=False),))
>>> repriced = reprice_plan(plan)
>>> [c.status for c in repriced.calls]
['unchanged']
>>> repriced.plan.total_cost_usd == plan.total_cost_usd
True
```

Three rules, in order of importance:

- **Pure data.** Nothing here touches the network or a billing API, exactly
  like `plan_*`. Re-pricing reads the committed tables and does arithmetic.
- **A plan with no basis is never assumed current.** Such a call comes back as
  `"no_basis"` with its cost *cleared to* `None`. Keeping the frozen figure
  would be the bug this module exists to fix, dressed as a feature.
- **Unknown is unknown, never free.** A basis whose model has left the
  catalogue, whose pricer is not registered, or whose table no longer prices it
  re-prices to `None` — which lights up
  [`falaw.Plan.has_unknown_costs`](falaw.html.md#falaw.Plan.has_unknown_costs) and forces approval.

The per-call diff says which of those happened, and
[`CallRepricing.basis_changed`](#falaw.reprice.CallRepricing.basis_changed) says whether the *table* moved underneath
the quote — the audit answer the frozen number could never give.

### Module Attributes

| [`RepriceStatus`](#falaw.reprice.RepriceStatus)    | What re-pricing was able to say about one call.                        |
|-------------------------------------------------------------------|------------------------------------------------------------------------|
| [`CATALOGUE_PRICER`](#falaw.reprice.CATALOGUE_PRICER) | `CostBasis.pricer` for a call priced from a `models.json` record.      |
| [`LLM_RATES_PRICER`](#falaw.reprice.LLM_RATES_PRICER) | `CostBasis.pricer` for a routed LLM call priced from `llm_rates.json`. |
| [`DFLT_PRICERS`](#falaw.reprice.DFLT_PRICERS)     | The pricers falaw ships — one per rate table it owns.                  |

### Functions

| [`catalogue_cost_basis`](#falaw.reprice.catalogue_cost_basis)(model_id, \*\*quantities)   | A [`falaw.CostBasis`](falaw.html.md#falaw.CostBasis) for a call priced from `models.json`.             |
|---------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------|
| [`llm_cost_basis`](#falaw.reprice.llm_cost_basis)(routed_model, \*[, ...])          | A [`falaw.CostBasis`](falaw.html.md#falaw.CostBasis) for a routed LLM call priced from the rate table. |
| [`reprice_plan`](#falaw.reprice.reprice_plan)(plan, \*[, pricers])                | Re-quote every call in `plan` against today's rate tables.                                                                           |

### Classes

| [`CallRepricing`](#falaw.reprice.CallRepricing)(\*, index, call, old_cost_usd, ...)   | The before/after for one call in a re-priced plan.                                                               |
|------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------|
| [`Pricer`](#falaw.reprice.Pricer)(\*, quote, table[, version])                 | One pricing rule, and the table that backs it.                                                                   |
| [`RepricedPlan`](#falaw.reprice.RepricedPlan)(\*, plan[, calls])                     | Result of [`reprice_plan()`](#falaw.reprice.reprice_plan) — the new Plan plus the per-call diff. |

### falaw.reprice.CATALOGUE_PRICER *= 'model_catalogue'*

`CostBasis.pricer` for a call priced from a `models.json` record.

### *class* falaw.reprice.CallRepricing(, index, call, old_cost_usd, new_cost_usd, status, reason='', basis_changed=False)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The before/after for one call in a re-priced plan.

#### basis_changed *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True when the rate table’s identity or version moved between the
persisted basis and today’s — the audit answer to “did the price change
because the *table* changed?”. Always `False` for `"no_basis"`, which
has nothing to compare against.

#### call *: [CallPlan](falaw.plan.html.md#falaw.plan.CallPlan)*

The re-priced call — the same call with today’s
`estimated_cost_usd` and a basis stamped with today’s table version.

#### *property* delta_usd *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[float](https://docs.python.org/3/builtins/functions.html#float)]*

`new - old`, or `None` when either side is unknown.

`None` rather than `0.0`: a call that lost or gained its price did
not move by zero, and a caller summing deltas must not be handed a
number that says it did.

#### index *: [int](https://docs.python.org/3/builtins/functions.html#int)*

Position in the original [`falaw.Plan`](falaw.html.md#falaw.Plan).

#### new_cost_usd *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[float](https://docs.python.org/3/builtins/functions.html#float)]*

What today’s rates say, `None` for unknown or no-basis.

#### old_cost_usd *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[float](https://docs.python.org/3/builtins/functions.html#float)]*

What the persisted plan said, `None` if it said unknown.

#### reason *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

Why, when the status is `"unknown"` or `"no_basis"`. Empty otherwise.

#### status *: [Literal](https://docs.python.org/3/library/typing.html#typing.Literal)['unchanged', 'changed', 'unknown', 'no_basis']*

Which of the four cases this call fell into — see [`RepriceStatus`](#falaw.reprice.RepriceStatus).

### falaw.reprice.DFLT_PRICERS *: [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Pricer](#falaw.reprice.Pricer)]* *= {'llm_rates': Pricer(quote=<function \_quote_from_llm_rates>, table='falaw/data/llm_rates.json', version=<functools._lru_cache_wrapper object>), 'model_catalogue': Pricer(quote=<function \_quote_from_catalogue>, table='falaw/data/models.json', version=<functools._lru_cache_wrapper object>)}*

The pricers falaw ships — one per rate table it owns.

Keyed by [`falaw.CostBasis.pricer`](falaw.html.md#falaw.CostBasis.pricer). A basis naming anything else
re-prices as `"unknown"`: an unrecognized rule is a reason to refuse a
number, not to keep the old one.

### falaw.reprice.LLM_RATES_PRICER *= 'llm_rates'*

`CostBasis.pricer` for a routed LLM call priced from `llm_rates.json`.

### *class* falaw.reprice.Pricer(\*, quote, table, version=<function Pricer.<lambda>>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One pricing rule, and the table that backs it.

The seam for a caller with their own numbers: build a `Pricer` closing
over a reconciled rate table and pass `pricers={\*\*DFLT_PRICERS,
LLM_RATES_PRICER: mine}` to [`reprice_plan()`](#falaw.reprice.reprice_plan). The `table` /
`version` pair is stamped onto the re-priced call’s basis, so the next
audit can see which table produced which number.

`table` is also a **gate, not just a label**: a call whose basis names a
different table is reported as `unknown` rather than re-quoted, so a row
priced from your invoice is never silently re-quoted at falaw’s published
rate (or the reverse). Give your `Pricer` the same `table` string the
basis carries — [`falaw.llm_rates.CUSTOM_LLM_RATES_TABLE`](falaw.llm_rates.html.md#falaw.llm_rates.CUSTOM_LLM_RATES_TABLE) for anything
a `plan_*` priced with `llm_rates=`.

#### quote *: [Callable](https://docs.python.org/3/library/typing.html#typing.Callable)[[[CostBasis](falaw.plan.html.md#falaw.plan.CostBasis)], [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[float](https://docs.python.org/3/builtins/functions.html#float)]]*

Price `basis` in USD, or return `None` for *unknown*. May raise; a
raise is reported as `"unknown"` with the exception text as the reason,
so one unpriceable row never aborts a whole plan’s re-quote.

#### table *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

Identity of the table this pricer reads, for the refreshed basis.

#### version *: [Callable](https://docs.python.org/3/library/typing.html#typing.Callable)[[], [str](https://docs.python.org/3/builtins/stdtypes.html#str)]*

Today’s version of that table, for the refreshed basis.

### falaw.reprice.RepriceStatus

What re-pricing was able to say about one call.

- `unchanged`: re-quoted, and today’s rates give the same number.
- `changed`: re-quoted to a different number — the interesting case.
- `unknown`: a basis was present but could not be re-quoted — the model has
  left the catalogue, no pricer is registered under that name, the table no
  longer prices it, or the basis names a **different table** than the pricer
  reads (two sets of books do not re-quote each other). The new cost is
  `None`.
- `no_basis`: the call carries no [`falaw.CostBasis`](falaw.html.md#falaw.CostBasis) at all — it was
  planned before falaw#60, or by something that never recorded one. The new
  cost is `None`, because the honest answer to “what does this cost today?”
  is that nobody can tell.

alias of [`Literal`](https://docs.python.org/3/library/typing.html#typing.Literal)[‘unchanged’, ‘changed’, ‘unknown’, ‘no_basis’]

### *class* falaw.reprice.RepricedPlan(, plan, calls=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Result of [`reprice_plan()`](#falaw.reprice.reprice_plan) — the new Plan plus the per-call diff.

Read [`plan`](#falaw.reprice.RepricedPlan.plan) for the re-quoted plan (it is an ordinary
[`falaw.Plan`](falaw.html.md#falaw.Plan), so `known_cost_usd` / `unknown_call_count` /
`has_unknown_costs` mean what they always mean), and [`calls`](#falaw.reprice.RepricedPlan.calls) for
what changed and why.

#### calls *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[CallRepricing](#falaw.reprice.CallRepricing), ...]*

One entry per call of the input plan, in order.

#### *property* changed *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[CallRepricing](#falaw.reprice.CallRepricing), ...]*

Calls whose price moved — the ones a re-quote exists to surface.

#### *property* known_delta_usd *: [float](https://docs.python.org/3/builtins/functions.html#float)*

Sum of [`CallRepricing.delta_usd`](#falaw.reprice.CallRepricing.delta_usd) over calls priced both times.

The movement you can actually see. It says nothing about the calls in
[`unpriced`](#falaw.reprice.RepricedPlan.unpriced) — read that alongside it, never this alone.

#### plan *: [Plan](falaw.plan.html.md#falaw.plan.Plan)*

The re-priced plan. Structurally identical to the input — same calls,
same order, same arguments, so `plan_hash` is unmoved — with today’s
costs.

#### *property* unpriced *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[CallRepricing](#falaw.reprice.CallRepricing), ...]*

`"unknown"` plus `"no_basis"`.

A budget gate refuses while this is non-empty, the same way it refuses
on [`falaw.Plan.has_unknown_costs`](falaw.html.md#falaw.Plan.has_unknown_costs) — the two are the same
judgement, one made at re-quote time.

* **Type:**
  Calls today’s rates cannot price

### falaw.reprice.catalogue_cost_basis(model_id, \*\*quantities)

A [`falaw.CostBasis`](falaw.html.md#falaw.CostBasis) for a call priced from `models.json`.

`quantities` are [`falaw.estimate_call_cost()`](falaw.html.md#falaw.estimate_call_cost) keywords (`count`,
`seconds`, `megapixels`, `tokens`); `None` values are dropped, so a
hint that was never supplied is recorded as absent rather than as `null`
— the same thing the estimator saw.

```pycon
>>> catalogue_cost_basis("fal-ai/flux/dev", seconds=None).quantities
{}
```

* **Return type:**
  [`CostBasis`](falaw.plan.html.md#falaw.plan.CostBasis)

### falaw.reprice.llm_cost_basis(routed_model, , input_tokens=None, max_output_tokens=None, custom_rates=False)

A [`falaw.CostBasis`](falaw.html.md#falaw.CostBasis) for a routed LLM call priced from the rate table.

`custom_rates=True` records that the quote came from a caller-supplied
`rates=` table rather than the committed one: there is no file to digest,
so the version stays empty and the table names itself
[`falaw.llm_rates.CUSTOM_LLM_RATES_TABLE`](falaw.llm_rates.html.md#falaw.llm_rates.CUSTOM_LLM_RATES_TABLE). [`reprice_plan()`](#falaw.reprice.reprice_plan) then
**refuses** to re-quote it with the committed table, reporting `unknown`
— a caller’s reconciled $0.50 row re-priced at falaw’s published $0.01 is a
50x under-quote, not a price drop. Re-quote it by passing a
[`Pricer`](#falaw.reprice.Pricer) over your table that names that same identity.

* **Return type:**
  [`CostBasis`](falaw.plan.html.md#falaw.plan.CostBasis)

### falaw.reprice.reprice_plan(plan, \*, pricers={'llm_rates': Pricer(quote=<function \_quote_from_llm_rates>, table='falaw/data/llm_rates.json', version=<functools._lru_cache_wrapper object>), 'model_catalogue': Pricer(quote = <function \_quote_from_catalogue>, table='falaw/data/models.json', version=<functools._lru_cache_wrapper object>)})

Re-quote every call in `plan` against today’s rate tables.

Pure data: no network, no billing API, nothing executed. Returns a new
[`RepricedPlan`](#falaw.reprice.RepricedPlan) — the input plan is untouched.

A call carrying a [`falaw.CostBasis`](falaw.html.md#falaw.CostBasis) is re-quoted through the pricer
its basis names, with the exact quantity hints that produced the original
figure, and comes back with a basis re-stamped to today’s table version. A
call carrying no basis is reported as `"no_basis"` and its cost is
**cleared to** `None`: the frozen number is a fact about a past moment,
and silently re-presenting it as a current quote is the failure this
function exists to prevent. That clearing lights up
[`falaw.Plan.has_unknown_costs`](falaw.html.md#falaw.Plan.has_unknown_costs), which is exactly right — nobody can
say what that call costs today.

A basis is only re-quoted by a pricer reading the **same table** it names.
A mismatch is `"unknown"`, not a re-quote: two tables are two sets of
books, and pricing a caller’s reconciled $0.50 row at falaw’s published
$0.01 would be a 50x under-quote wearing the clothes of a price drop. Pass
a [`Pricer`](#falaw.reprice.Pricer) naming that table to re-quote against the same books.

`cache_status` is carried through unchanged. Re-pricing answers “what
would this cost?”, not “is it still cached?”; peeking the cache here would
quietly turn a re-quote into an I/O operation and make a hit look like a
price drop. Re-plan the calls if you want a fresh cache reading.

* **Parameters:**
  * **plan** ([`Plan`](falaw.plan.html.md#falaw.plan.Plan)) – The plan to re-quote, typically just deserialized with
    [`falaw.plan_from_dict()`](falaw.html.md#falaw.plan_from_dict).
  * **pricers** ([`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Pricer`](#falaw.reprice.Pricer)]) – Pricing rules by [`falaw.CostBasis.pricer`](falaw.html.md#falaw.CostBasis.pricer) name. The seam
    for a caller who has reconciled real numbers against their own
    invoice — see [`Pricer`](#falaw.reprice.Pricer).
* **Return type:**
  [`RepricedPlan`](#falaw.reprice.RepricedPlan)

```pycon
>>> from falaw import Plan, CallPlan, reprice_plan
>>> stale = CallPlan(tool="generate_image", application="fal-ai/flux/dev",
...                  arguments={"prompt": "a tiger"}, output_kind="image",
...                  estimated_cost_usd=0.025)
>>> out = reprice_plan(Plan(calls=(stale,)))
>>> out.calls[0].status
'no_basis'
>>> out.plan.calls[0].estimated_cost_usd is None   # unknown, not $0.025
True
>>> out.plan.has_unknown_costs
True
```
