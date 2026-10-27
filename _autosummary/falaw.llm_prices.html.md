# falaw.llm_prices

One first-party LLM price table: what a direct Anthropic / OpenAI call costs (falaw#81).

[`falaw.llm_rates`](falaw.llm_rates.html.md#module-falaw.llm_rates) prices LLMs *routed through fal* (`fal-ai/any-llm`).
This module prices calls made straight to the model vendor, the way reelee’s
agent loop and chat relay and foley’s rungs make them. Those three used to keep
a private copy of the same numbers and drifted; this is the one home.

```pycon
>>> llm_call_cost_usd("anthropic", "claude-opus-4-7",
...                   {"input_tokens": 1_000_000, "output_tokens": 0})
(5.0, True)
```

The answer is `(usd, known)`. A model the table does not list is \*\*unknown,
not free\*\*: it is priced at the dearest rates listed for that provider and
`known` is `False`. The cost is then a *floor on a guess*, not a ceiling: an
unlisted model can cost more than the dearest listed one (an older, pricier
model). A spend cap can count it; a caller that must never under-count should
refuse an unpriced model by testing `known`:

```pycon
>>> usd, known = llm_call_cost_usd("anthropic", "claude-from-the-future",
...                                {"input_tokens": 1_000_000})
>>> known, usd > 0
(False, True)
```

`usage` is the vendor’s own reported usage, a mapping or an object with
attributes, in either of OpenAI’s two shapes (Responses or Chat Completions):

```pycon
>>> llm_call_cost_usd("openai", "gpt-5", {"prompt_tokens": 1000,
...     "completion_tokens": 100, "prompt_tokens_details": {"cached_tokens": 1000}})
(0.001125, True)
```

The table is data, not code: [`PRICES_FILENAME`](#falaw.llm_prices.PRICES_FILENAME) under `falaw/data`, one
row per model, each row carrying its own `source` and `date`. Nothing here
touches the network. Model ids are matched **exactly**: a dated snapshot is not
priced as its family, because older snapshots can cost more.

### Module Attributes

| [`PRICES_FILENAME`](#falaw.llm_prices.PRICES_FILENAME)       | Basename of the price table under `falaw/data`.                        |
|------------------------------------------------------------------------|------------------------------------------------------------------------|
| [`TOKENS_PER_PRICE_UNIT`](#falaw.llm_prices.TOKENS_PER_PRICE_UNIT) | Token count the table's `*_usd_per_mtok` columns are quoted per.       |
| [`COST_DECIMALS`](#falaw.llm_prices.COST_DECIMALS)         | Digits the returned USD is rounded to, which only removes float noise. |
| [`PROVIDERS`](#falaw.llm_prices.PROVIDERS)             | First-party providers the table prices.                                |

### Functions

| [`get_llm_price`](#falaw.llm_prices.get_llm_price)(provider, model, \*[, prices])   | The row for `model` (exact id), or `None` when the table does not list it.                                                                                                                                        |
|-------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`list_llm_prices`](#falaw.llm_prices.list_llm_prices)([provider, prices])            | Every row, or the rows of one `provider`.                                                                                                                                                                         |
| [`llm_call_cost_usd`](#falaw.llm_prices.llm_call_cost_usd)(provider, model, usage, \*)  | `(USD, known)` for one first-party call from the vendor's reported `usage`.                                                                                                                                       |
| [`llm_prices_table_version`](#falaw.llm_prices.llm_prices_table_version)()                     | The table's version, a digest of its bytes (see [`falaw.base.data_table_version()`](falaw.base.html.md#falaw.base.data_table_version)).                                                  |
| [`llm_token_counts`](#falaw.llm_prices.llm_token_counts)(provider, usage)              | The [`LlmTokenCounts`](#falaw.llm_prices.LlmTokenCounts) of a vendor `usage`, in the shapes [`llm_call_cost_usd()`](#falaw.llm_prices.llm_call_cost_usd) accepts (a mapping or an SDK object). |
| [`load_llm_prices`](#falaw.llm_prices.load_llm_prices)()                              | The committed table, keyed by `(provider, model)`.                                                                                                                                                                |

### Classes

| [`LlmPrice`](#falaw.llm_prices.LlmPrice)(\*, provider, model, rates[, ...])        | One row of the first-party table: a model's rates and where they came from.                                                                                                                                                                                         |
|-----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`LlmTokenCounts`](#falaw.llm_prices.LlmTokenCounts)(\*[, fresh_input, cache_read, ...]) | The token counts a first-party call's `usage` reports, normalized across providers: the very counts [`llm_call_cost_usd()`](#falaw.llm_prices.llm_call_cost_usd) prices, so a caller that records them next to the cost cannot disagree with it (falaw#89). |

### falaw.llm_prices.COST_DECIMALS *= 9*

Digits the returned USD is rounded to, which only removes float noise.

### *class* falaw.llm_prices.LlmPrice(, provider, model, rates, long_prompt_over_tokens=None, long_prompt_rates=None, source='', date='', notes='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One row of the first-party table: a model’s rates and where they came from.

### *class* falaw.llm_prices.LlmTokenCounts(, fresh_input=0, cache_read=0, cache_write=0, cache_write_1h=0, output=0, reasoning=0)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The token counts a first-party call’s `usage` reports, normalized across
providers: the very counts [`llm_call_cost_usd()`](#falaw.llm_prices.llm_call_cost_usd) prices, so a caller that
records them next to the cost cannot disagree with it (falaw#89).

`fresh_input` is billed at the input rate, `cache_read` and
`cache_write` at their own; `cache_write_1h` is the part of
`cache_write` on the 1-hour tier (already included in it: do not add the two). `reasoning` is informational: it is
already inside `output`.

#### *property* input *: [int](https://docs.python.org/3/builtins/functions.html#int)*

Every prompt token, cached or not.

### falaw.llm_prices.PRICES_FILENAME *= 'first_party_llm_prices.json'*

Basename of the price table under `falaw/data`.

### falaw.llm_prices.PROVIDERS *= ('anthropic', 'openai')*

First-party providers the table prices.

### falaw.llm_prices.TOKENS_PER_PRICE_UNIT *= 1000000*

Token count the table’s `*_usd_per_mtok` columns are quoted per.

### falaw.llm_prices.get_llm_price(provider, model, , prices=None)

The row for `model` (exact id), or `None` when the table does not list it.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`LlmPrice`](#falaw.llm_prices.LlmPrice)]

### falaw.llm_prices.list_llm_prices(provider=None, , prices=None)

Every row, or the rows of one `provider`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`LlmPrice`](#falaw.llm_prices.LlmPrice)]

### falaw.llm_prices.llm_call_cost_usd(provider, model, usage, , prices=None)

`(USD, known)` for one first-party call from the vendor’s reported `usage`.

- `provider="anthropic"`: `input_tokens` (uncached), `output_tokens`,
  `cache_read_input_tokens`, `cache_creation_input_tokens`.
- `provider="openai"`: Responses (`input_tokens` / `output_tokens` /
  `input_tokens_details.cached_tokens`) or Chat Completions
  (`prompt_tokens` / `completion_tokens` /
  `prompt_tokens_details.cached_tokens`). Input includes the cached part,
  which is billed at the cached rate; reasoning tokens are already in output.

`known` is `False` when the model is not in the table; the cost is then
priced at the provider’s dearest listed rates, which is not a ceiling for a
model pricier than any listed (see the module docstring). `prices=` swaps in the caller’s
own table, e.g. one reconciled against an invoice.

* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – `provider` is not one of [`PROVIDERS`](#falaw.llm_prices.PROVIDERS).
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]

### falaw.llm_prices.llm_prices_table_version()

The table’s version, a digest of its bytes (see [`falaw.base.data_table_version()`](falaw.base.html.md#falaw.base.data_table_version)).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### falaw.llm_prices.llm_token_counts(provider, usage)

The [`LlmTokenCounts`](#falaw.llm_prices.LlmTokenCounts) of a vendor `usage`, in the shapes
[`llm_call_cost_usd()`](#falaw.llm_prices.llm_call_cost_usd) accepts (a mapping or an SDK object).

```pycon
>>> llm_token_counts("openai", {"prompt_tokens": 1000, "completion_tokens": 100,
...     "prompt_tokens_details": {"cached_tokens": 400}})
LlmTokenCounts(fresh_input=600, cache_read=400, cache_write=0, cache_write_1h=0, output=100, reasoning=0)
```

A key that is present but `None` falls through to the next shape’s key
(`{"input_tokens": None, "prompt_tokens": 7}` counts 7).

* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – `provider` is not one of [`PROVIDERS`](#falaw.llm_prices.PROVIDERS).
* **Return type:**
  [`LlmTokenCounts`](#falaw.llm_prices.LlmTokenCounts)

### falaw.llm_prices.load_llm_prices()

The committed table, keyed by `(provider, model)`. Read once per process.

* **Return type:**
  [`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`LlmPrice`](#falaw.llm_prices.LlmPrice)]
