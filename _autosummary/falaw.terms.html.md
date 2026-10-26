# falaw.terms

The terms ledger: may this `(model, backend)` be used for *this* job? (falaw#16)

falaw is the only layer that knows which vendor model a job will actually
call, so it is the layer that can know whether that call is permitted.
Copyleft is the famous perimeter; vendor terms of service are the one that
binds a commercial product. This module owns a per-`(model, backend)` ledger
(`falaw/data/model_terms.json`) and the plan-time check over it.

Rows are keyed on `CallPlan.application` — the *resolved* model id, never an
alias — and `CallPlan.backend`. A self-hosted backend must therefore plan
its calls under the catalogue model id the ledger row names.

The key is `(model, backend)`, not `model`: the backend decides whether an
upstream weights licence flows through to us. Through a hosted API the host
holds the weights licence (`license_binds_us="no"`); the same weights
self-hosted bind us directly (`"yes"`). Same model id, different position.

**Fail closed.** `unknown` is a refusal, not a warning — the discipline
[`falaw.Plan.has_unknown_costs`](falaw.html.md#falaw.Plan.has_unknown_costs) applies to money, applied to licences. A
`(model, backend)` with no row at all is `unknown` too, so a model nobody
has reviewed is refused rather than waved through. The check is opt-in per
call: `plan_*(..., terms_context=TermsContext(...))`. With no context
(the default, for local/internal use) nothing is checked.

This is an implementation of what the terms *say*, not legal advice; it
refuses when unsure and does not adjudicate. The *context* (is this job
serving a third party? will its output be C2PA-stamped?) is the caller’s (an argument, or
scoped to a block by [`using_terms_context()`](#falaw.terms.using_terms_context)), never process-global; the ledger is data, the check is falaw’s.

```pycon
>>> ctx = TermsContext(third_party=True)
>>> check_terms("fal-ai/flux/schnell", "comfyui", ctx)   # Apache-2.0, ours to serve
>>> check_terms("fal-ai/flux/dev", "comfyui", ctx)
Traceback (most recent call last):
    ...
falaw.errors.FalTermsViolation: ...
```

### Module Attributes

| [`TERMS_PATH`](#falaw.terms.TERMS_PATH)   | The ledger — separate from `models.json` so it refreshes on its own cadence and is reviewed as a legal artifact.   |
|---------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------|

### Functions

| [`check_terms`](#falaw.terms.check_terms)(model_id, backend, context, \*[, ...])   | Raise `FalTermsViolation` unless `(model_id, backend)` is usable for *context*.                                                                                                                                    |
|-------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`clearance`](#falaw.terms.clearance)(application, backend, context[, ...])      | The descriptive record a plan carries once [`check_terms()`](#falaw.terms.check_terms) passed: what was cleared, where, for which job.                                                          |
| [`current_terms_context`](#falaw.terms.current_terms_context)()                              | The context bound by [`using_terms_context()`](#falaw.terms.using_terms_context), else `None`.                                                                                                          |
| [`effective_terms_context`](#falaw.terms.effective_terms_context)(explicit)                    | The context a check runs under: an explicit `terms_context=` argument wins; otherwise the one scoped by [`using_terms_context()`](#falaw.terms.using_terms_context).                                    |
| [`get_terms`](#falaw.terms.get_terms)(model_id, backend, \*[, ledger])           | The row for `(model_id, backend)`, or `None` when nobody reviewed it.                                                                                                                                              |
| [`is_cleared`](#falaw.terms.is_cleared)(call, context)                            | (Describes what the stamp says, not the ledger's later edits.) Whether *call* (a `CallPlan`) carries a clearance that still describes it: same model and backend as now, for exactly *context*.                    |
| [`load_terms`](#falaw.terms.load_terms)([path])                                   | The ledger as `{(model_id, backend): ModelTerms}` (cached per path).                                                                                                                                               |
| [`terms_subject`](#falaw.terms.terms_subject)(application[, arguments])              | The model id the ledger judges for this call: the routed model for a router such as `fal-ai/any-llm`, else *application* itself.                                                                                   |
| [`third_party_tenancy_ok`](#falaw.terms.third_party_tenancy_ok)(model_id, backend, \*)        | The routing-visible projection: may a router send third-party work to `(model_id, backend)` without consulting the full ledger? `False` when unsure — the cheap 80%, so a router can drop an incompatible backend. |
| [`unreviewed_models`](#falaw.terms.unreviewed_models)(\*[, ledger, backend])             | Catalogue models with no ledger row on *backend* — what still needs a human read of the terms (each is refused under a strict context).                                                                            |
| [`using_terms_context`](#falaw.terms.using_terms_context)(context)                         | Scope *context* over every call made inside the block, eager or planned.                                                                                                                                           |

### Classes

| [`ModelTerms`](#falaw.terms.ModelTerms)(\*, model_id, backend[, license, ...])   | One ledger row.                                                                                                                                                                                          |
|------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`TermsContext`](#falaw.terms.TermsContext)(\*[, commercial, third_party, c2pa])   | What the job needs from the terms — supplied by the caller, never process-global (an explicit argument, or scoped to a block by [`using_terms_context()`](#falaw.terms.using_terms_context)). |

### *class* falaw.terms.ModelTerms(, model_id, backend, license='unknown', license_binds_us='unknown', commercial_use='unknown', third_party_tenancy='unknown', c2pa_compatible='unknown', provenance_constraint='', notes='', source_url='', observed_on='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One ledger row. A field left `unknown` is a refusal when it matters.

### falaw.terms.TERMS_PATH *= PosixPath('/home/runner/work/falaw/falaw/falaw/data/model_terms.json')*

The ledger — separate from `models.json` so it refreshes on its own
cadence and is reviewed as a legal artifact.

### *class* falaw.terms.TermsContext(, commercial=True, third_party=False, c2pa=False)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What the job needs from the terms — supplied by the caller, never process-global
(an explicit argument, or scoped to a block by [`using_terms_context()`](#falaw.terms.using_terms_context)).

The defaults describe the strictest ordinary use (commercial) without
claiming anything extra; `third_party` and `c2pa` are opt-in because
they are the facts only the deployment knows.

### falaw.terms.check_terms(model_id, backend, context, , ledger=None, arguments=None)

Raise `FalTermsViolation` unless `(model_id, backend)` is
usable for *context*. `context=None` (the default everywhere) checks
nothing: the strict path is opt-in per deployment. Pass the call’s
`arguments` so a router is judged by the model it routes to
([`terms_subject()`](#falaw.terms.terms_subject)).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### falaw.terms.clearance(application, backend, context, arguments=None)

The descriptive record a plan carries once [`check_terms()`](#falaw.terms.check_terms) passed:
what was cleared, where, for which job. Lives in `CallPlan.metadata`
(never hashed), so a persisted plan can show it was cleared.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### falaw.terms.current_terms_context()

The context bound by [`using_terms_context()`](#falaw.terms.using_terms_context), else `None`.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`TermsContext`](#falaw.terms.TermsContext)]

### falaw.terms.effective_terms_context(explicit)

The context a check runs under: an explicit `terms_context=` argument
wins; otherwise the one scoped by [`using_terms_context()`](#falaw.terms.using_terms_context). (Entry
points that take no argument still enforce the scoped one at the call
chokepoints, so the strictest applicable check always runs.)

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`TermsContext`](#falaw.terms.TermsContext)]

### falaw.terms.get_terms(model_id, backend, , ledger=None)

The row for `(model_id, backend)`, or `None` when nobody reviewed it.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`ModelTerms`](#falaw.terms.ModelTerms)]

### falaw.terms.is_cleared(call, context)

(Describes what the stamp says, not the ledger’s later edits.) Whether *call* (a `CallPlan`) carries a clearance that still describes
it: same model and backend as now, for exactly *context*. A call re-targeted
after planning (`dataclasses.replace(call, backend=...)`, a replayed or
repriced plan) fails this, so it must be re-checked, never trusted.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### falaw.terms.load_terms(path=None)

The ledger as `{(model_id, backend): ModelTerms}` (cached per path).

* **Return type:**
  [`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ModelTerms`](#falaw.terms.ModelTerms)]

### falaw.terms.terms_subject(application, arguments=None)

The model id the ledger judges for this call: the routed model for a
router such as `fal-ai/any-llm`, else *application* itself.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### falaw.terms.third_party_tenancy_ok(model_id, backend, , ledger=None)

The routing-visible projection: may a router send third-party work to
`(model_id, backend)` without consulting the full ledger? `False` when
unsure — the cheap 80%, so a router can drop an incompatible backend.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### falaw.terms.unreviewed_models(, ledger=None, backend='fal')

Catalogue models with no ledger row on *backend* — what still needs a
human read of the terms (each is refused under a strict context).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### falaw.terms.using_terms_context(context)

Scope *context* over every call made inside the block, eager or planned.

The eager verbs (`generate_image`, `render_scene`, …) take no
`terms_context`; this is the one seam that covers all of them, enforced
where every call passes ([`falaw.cache.cached_call_fal()`](falaw.cache.html.md#falaw.cache.cached_call_fal),
[`falaw.core.call_fal()`](falaw.core.html.md#falaw.core.call_fal)). Scoped to the block (and its threads/tasks),
never process-global: the deployment decides, per job.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`None`](https://docs.python.org/3/builtins/constants.html#None)]
