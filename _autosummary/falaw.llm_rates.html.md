# falaw.llm_rates

Per-routed-model LLM rates: the data behind a *ceiling* quote (falaw#50, option A).

`fal-ai/any-llm` is one registry record that routes thirty different models,
so a single record-level `cost_estimate` cannot express what a call actually
costs. Until now every planned LLM call quoted that one record’s flat
$0.001 — which under-quotes in the one direction a cost gate must never err.
Two facts, both read off the vendor’s own documentation, say by how much:

1. **fal bills the router per request, at two tiers.** Its endpoint doc says
   “$0.001 per requests” and “Premium models are charged at 10x the rate of
   standard models”, followed by the verbatim premium list. falaw’s default
   model — `anthropic/claude-sonnet-4.5` — is on that list, so *every*
   planned LLM call has been quoting a tenth of the published price.
2. **The routed model has an upstream per-token rate.** any-llm is “powered by
   OpenRouter” and shares its model-id namespace, so OpenRouter’s published
   prompt/completion rates are what fal resells. A reseller cannot durably
   charge less than its own cost, which makes those rates a floor on the true
   price of a long prompt on a big model.

Neither basis dominates the other: the flat request price wins on a short
prompt, the token rates win on a long one. So the ceiling is the \*\*maximum
over every basis known for that model\*\* ([`llm_ceiling_usd()`](#falaw.llm_rates.llm_ceiling_usd)) — the only
composition that cannot under-quote either way, and monotone non-decreasing in
both token hints.

The table itself is data, not code: [`RATES_FILENAME`](#falaw.llm_rates.RATES_FILENAME) under `falaw/data`,
versioned, one row per routed model, each row carrying its own `source` and
`date`. Nothing here touches the network — planning stays free.

```pycon
>>> rate = get_llm_rate('anthropic/claude-sonnet-4.5')
>>> rate.tier
'premium'
>>> rate.per_call_usd
0.01
```

A model the table does not know is **unknown, not free** — the estimator
returns `None` so the plan lights up `has_unknown_costs` and forces
approval, rather than falling back to the router’s flat price:

```pycon
>>> get_llm_rate('some/model-fal-never-heard-of') is None
True
>>> llm_ceiling_usd('some/model-fal-never-heard-of') is None
True
```

### Module Attributes

| [`RATES_FILENAME`](#falaw.llm_rates.RATES_FILENAME)                   | Basename of the rate table under `falaw/data`.                                                                              |
|-----------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------|
| [`TOKENS_PER_RATE_UNIT`](#falaw.llm_rates.TOKENS_PER_RATE_UNIT)             | Token count the table's `*_per_mtok` columns are quoted per.                                                                |
| [`DEFAULT_STALENESS_THRESHOLD_DAYS`](#falaw.llm_rates.DEFAULT_STALENESS_THRESHOLD_DAYS) | Warn once a priced row's `date` is this many days old.                                                                      |
| [`LLM_RATES_TABLE`](#falaw.llm_rates.LLM_RATES_TABLE)                  | Identity a [`falaw.CostBasis`](falaw.html.md#falaw.CostBasis) records for an LLM-priced call. |
| [`CUSTOM_LLM_RATES_TABLE`](#falaw.llm_rates.CUSTOM_LLM_RATES_TABLE)           | What a basis records when the caller quoted against their own `rates=` table.                                               |

### Functions

| [`get_llm_rate`](#falaw.llm_rates.get_llm_rate)(model, \*[, rates])                 | The row for `model`, or `None` when the table does not price it.                                                                               |
|---------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------|
| [`list_llm_rates`](#falaw.llm_rates.list_llm_rates)(\*[, rates])                      | Every row in the table, in file order — the catalogue view.                                                                                    |
| [`llm_ceiling_usd`](#falaw.llm_rates.llm_ceiling_usd)(model, \*[, input_tokens, ...])  | Ceiling cost in USD of `count` calls routing `model`, or `None`.                                                                               |
| [`llm_rates_table_version`](#falaw.llm_rates.llm_rates_table_version)()                        | The rate table's version — see [`falaw.base.data_table_version()`](falaw.base.html.md#falaw.base.data_table_version). |
| [`load_llm_rates`](#falaw.llm_rates.load_llm_rates)()                                 | The committed rate table, keyed by routed-model id.                                                                                            |
| [`warn_if_stale`](#falaw.llm_rates.warn_if_stale)(rate, \*[, threshold_days, today]) | Warn (never raise) when `rate` is older than `threshold_days`.                                                                                 |

### Classes

| [`LlmRate`](#falaw.llm_rates.LlmRate)(\*, model, tier, per_call_usd[, ...])   | What one routed model costs, on every basis the table knows.   |
|--------------------------------------------------------------------------------------------------|----------------------------------------------------------------|

### Exceptions

| [`LlmRatesStaleWarning`](#falaw.llm_rates.LlmRatesStaleWarning)   | A quote was served from a rate row older than the staleness threshold.   |
|-------------------------------------------------------------------------|--------------------------------------------------------------------------|

### falaw.llm_rates.CUSTOM_LLM_RATES_TABLE *= 'caller-supplied'*

What a basis records when the caller quoted against their own `rates=` table.

It has no file to digest, so its `table_version` stays empty — and, more
importantly, **the committed table must never re-price it**. Two tables are two
sets of books: re-quoting a $0.50 row from a caller’s reconciled invoice against
falaw’s $0.01 published rate is a 50x *under-quote* wearing the clothes of a
price drop. [`falaw.reprice_plan()`](falaw.html.md#falaw.reprice_plan) therefore refuses a basis whose `table`
does not match the pricer’s, reporting it as unknown; a caller who wants their
own numbers re-quoted passes a [`falaw.Pricer`](falaw.html.md#falaw.Pricer) that names this table.

### falaw.llm_rates.DEFAULT_STALENESS_THRESHOLD_DAYS *= 90*

Warn once a priced row’s `date` is this many days old.

`llm_rates.json` has no refresh job that runs itself (falaw#56): a
repriced or retiered model does not fail any test, so a quote can go stale
silently. This is the default threshold [`llm_ceiling_usd()`](#falaw.llm_rates.llm_ceiling_usd) checks a
row’s `date` against before returning a quote.

### falaw.llm_rates.LLM_RATES_TABLE *= 'falaw/data/llm_rates.json'*

Identity a [`falaw.CostBasis`](falaw.html.md#falaw.CostBasis) records for an LLM-priced call.

### *class* falaw.llm_rates.LlmRate(, model, tier, per_call_usd, input_usd_per_mtok=None, output_usd_per_mtok=None, long_prompt_over_tokens=None, long_prompt_rates=None, source='', date='', notes='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What one routed model costs, on every basis the table knows.

#### model

The `model` argument value this row prices, e.g.
`"anthropic/claude-sonnet-4.5"`.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### tier

fal’s billing tier for the router — `"standard"` or
`"premium"`. Informational; `per_call_usd` is already
materialized, so no multiplier arithmetic happens in code.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### per_call_usd

What fal bills per request when this model is routed.

* **Type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### input_usd_per_mtok

Upstream list price per
[`TOKENS_PER_RATE_UNIT`](#falaw.llm_rates.TOKENS_PER_RATE_UNIT) prompt tokens, or `None` when no
upstream rate is published for this id — unknown, never zero.

* **Type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

#### output_usd_per_mtok

The same for completion tokens.

* **Type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

#### long_prompt_over_tokens

Prompt length past which the upstream bills
`long_prompt_rates` instead (OpenRouter’s `pricing.overrides`,
falaw#124), or `None` when the model has one regime.

* **Type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]

#### long_prompt_rates

The token rates that replace the row’s own past
`long_prompt_over_tokens`.

* **Type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`LlmPriceRates`](falaw.llm_prices.html.md#falaw.llm_prices.LlmPriceRates)]

#### source

Where these numbers came from.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### date

ISO date they were read on. Rates move; a quote is only as
fresh as its row.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### notes

Free-form caveats.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### *property* has_token_rates *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True when both token columns are populated, so a token quote is possible.

### *exception* falaw.llm_rates.LlmRatesStaleWarning

Bases: [`UserWarning`](https://docs.python.org/3/builtins/exceptions.html#UserWarning)

A quote was served from a rate row older than the staleness threshold.

### falaw.llm_rates.RATES_FILENAME *= 'llm_rates.json'*

Basename of the rate table under `falaw/data`.

### falaw.llm_rates.TOKENS_PER_RATE_UNIT *= 1000000*

Token count the table’s `*_per_mtok` columns are quoted per.

### falaw.llm_rates.get_llm_rate(model, , rates=None)

The row for `model`, or `None` when the table does not price it.

`None` is the load-bearing answer: it means *unknown*, and every caller
must propagate it as unknown rather than substituting the router’s flat
price for a model nobody has priced.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`LlmRate`](#falaw.llm_rates.LlmRate)]

### falaw.llm_rates.list_llm_rates(, rates=None)

Every row in the table, in file order — the catalogue view.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`LlmRate`](#falaw.llm_rates.LlmRate)]

### falaw.llm_rates.llm_ceiling_usd(model, , input_tokens=None, max_output_tokens=None, count=1, rates=None)

Ceiling cost in USD of `count` calls routing `model`, or `None`.

Two modes, decided by whether the caller passes a token hint at all.

**No hints** — quote fal’s published per-request price for the routed
model. That is a known vendor fact, and for the premium tier it is ten
times what the router’s flat record said:

```pycon
>>> flat = llm_ceiling_usd('anthropic/claude-sonnet-4.5')
>>> flat
0.01
```

**Both hints** — quote the **maximum** of that request price and
`input_tokens` in plus `max_output_tokens` out at the routed model’s
upstream rates. Taking the max is what makes it a ceiling: the flat price
binds a short prompt, the token sum binds a long one, and quoting either
alone under-quotes the other case.

```pycon
>>> long_prompt = llm_ceiling_usd(
...     'anthropic/claude-sonnet-4.5', input_tokens=20_000, max_output_tokens=4_000
... )
>>> round(long_prompt, 4)
0.12
>>> long_prompt > flat        # length raises the quote; the flat rate is a floor
True
```

Monotone in both hints, so a bigger hint never quotes less:

```pycon
>>> a = llm_ceiling_usd('openai/gpt-4o', input_tokens=1_000, max_output_tokens=100)
>>> b = llm_ceiling_usd('openai/gpt-4o', input_tokens=9_000, max_output_tokens=100)
>>> b >= a
True
```

Past a row’s long-prompt threshold the upstream bills higher rates for the
whole call (falaw#124), and the quote uses them. Claude Haiku 5.5 costs five
times as much per token above 100,000 prompt tokens:

```pycon
>>> haiku = 'anthropic/claude-haiku-5.5'
>>> below = llm_ceiling_usd(haiku, input_tokens=99_999, max_output_tokens=0)
>>> above = llm_ceiling_usd(haiku, input_tokens=100_000, max_output_tokens=0)
>>> round(below, 6), round(above, 6)
(0.01, 0.05)
```

Both hints are upper bounds the *caller* holds at plan time: the prompt is
already written, and `max_tokens` caps the response. Real output length
is unknowable before the call, which is exactly why this quotes the cap and
never a midpoint guess.

A token quote is therefore **all or nothing**. Asking for one that cannot
be bounded yields `None` — unknown, which forces approval — rather than a
number that looks like a ceiling and is not. That covers one hint without
the other (an uncapped response has no bound to quote):

```pycon
>>> llm_ceiling_usd('anthropic/claude-sonnet-4.5', input_tokens=50_000) is None
True
```

and a row with no published upstream token rates (the request price alone
is not a ceiling on a token bill nobody has priced):

```pycon
>>> llm_ceiling_usd(
...     'google/gemini-flash-1.5', input_tokens=50_000, max_output_tokens=1_000
... ) is None
True
```

* **Parameters:**
  * **model** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The `model` argument the call will send to the router.
  * **input_tokens** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Upper bound on prompt tokens. `None` together with
    `max_output_tokens` selects the per-request basis alone.
  * **max_output_tokens** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – The response cap (any-llm’s `max_tokens`).
  * **count** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Number of identical calls.
  * **rates** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`LlmRate`](#falaw.llm_rates.LlmRate)]]) – Override table, for a caller who has reconciled real rates
    against their own billing.
* **Raises:**
  * [**TypeError**](https://docs.python.org/3/builtins/exceptions.html#TypeError) – a token hint or `count` that is not a plain `int`.
        A `bool` and a `float` both do the arithmetic silently —
        `True` prices one token, `1.5e4` prices a fractional one —
        so a caller who passed the wrong thing would get a number rather
        than a complaint.
  * [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – a negative token hint or `count`, which would make the
        token basis *lower* the ceiling — silently, and in the one
        direction a spend gate must never err.
* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

### falaw.llm_rates.llm_rates_table_version()

The rate table’s version — see [`falaw.base.data_table_version()`](falaw.base.html.md#falaw.base.data_table_version).

Cached per process, like the table itself.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### falaw.llm_rates.load_llm_rates()

The committed rate table, keyed by routed-model id.

Cached: the file is read once per process. Tests and callers with their
own reconciled numbers pass a mapping to `rates=` instead of mutating
this one.

* **Return type:**
  [`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`LlmRate`](#falaw.llm_rates.LlmRate)]

### falaw.llm_rates.warn_if_stale(rate, , threshold_days=90, today=None)

Warn (never raise) when `rate` is older than `threshold_days`.

Safe to call at import time or on every quote: it only ever calls
[`warnings.warn()`](https://docs.python.org/3/library/warnings.html#warnings.warn), so a stale table degrades a quote’s trustworthiness
without ever breaking a caller. Returns the warning message when one was
issued, else `None` (handy for tests, which can assert on it without
a `pytest.warns` context).

`stacklevel=2` attributes the warning to [`llm_ceiling_usd()`](#falaw.llm_rates.llm_ceiling_usd)’s call
site here rather than to every external caller of *that* — a fixed
location, not one that moves with the caller. That matters because
Python’s default warning filter only dedups a repeated warning by its
exact `(message, category, module, lineno)`: a fixed location plus a
message keyed on `(model, date)` means a caller quoting the same stale
row in a loop (including a blank/unknown `date`, which always reads as
stale) sees the warning once per process, not once per call.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
