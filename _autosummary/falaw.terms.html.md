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
serving a third party? will its output be C2PA-stamped?) is the caller’s, never
read from a global; the ledger is data, the check is falaw’s.

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
| [`get_terms`](#falaw.terms.get_terms)(model_id, backend, \*[, ledger])           | The row for `(model_id, backend)`, or `None` when nobody reviewed it.                                                                                                                                              |
| [`load_terms`](#falaw.terms.load_terms)([path])                                   | The ledger as `{(model_id, backend): ModelTerms}` (cached per path).                                                                                                                                               |
| [`third_party_tenancy_ok`](#falaw.terms.third_party_tenancy_ok)(model_id, backend, \*)        | The routing-visible projection: may a router send third-party work to `(model_id, backend)` without consulting the full ledger? `False` when unsure — the cheap 80%, so a router can drop an incompatible backend. |
| [`unreviewed_models`](#falaw.terms.unreviewed_models)(\*[, ledger, backend])             | Catalogue models with no ledger row on *backend* — what still needs a human read of the terms (each is refused under a strict context).                                                                            |

### Classes

| [`ModelTerms`](#falaw.terms.ModelTerms)(\*, model_id, backend[, license, ...])   | One ledger row.                                                           |
|------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------|
| [`TermsContext`](#falaw.terms.TermsContext)(\*[, commercial, third_party, c2pa])   | What the job needs from the terms — supplied by the caller, never global. |

### *class* falaw.terms.ModelTerms(, model_id, backend, license='unknown', license_binds_us='unknown', commercial_use='unknown', third_party_tenancy='unknown', c2pa_compatible='unknown', provenance_constraint='', notes='', source_url='', observed_on='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One ledger row. A field left `unknown` is a refusal when it matters.

### falaw.terms.TERMS_PATH *= PosixPath('/home/runner/work/falaw/falaw/falaw/data/model_terms.json')*

The ledger — separate from `models.json` so it refreshes on its own
cadence and is reviewed as a legal artifact.

### *class* falaw.terms.TermsContext(, commercial=True, third_party=False, c2pa=False)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What the job needs from the terms — supplied by the caller, never global.

The defaults describe the strictest ordinary use (commercial) without
claiming anything extra; `third_party` and `c2pa` are opt-in because
they are the facts only the deployment knows.

### falaw.terms.check_terms(model_id, backend, context, , ledger=None)

Raise `FalTermsViolation` unless `(model_id, backend)` is
usable for *context*. `context=None` (the default everywhere) checks
nothing: the strict path is opt-in per deployment.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### falaw.terms.get_terms(model_id, backend, , ledger=None)

The row for `(model_id, backend)`, or `None` when nobody reviewed it.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`ModelTerms`](#falaw.terms.ModelTerms)]

### falaw.terms.load_terms(path=None)

The ledger as `{(model_id, backend): ModelTerms}` (cached per path).

* **Return type:**
  [`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ModelTerms`](#falaw.terms.ModelTerms)]

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
