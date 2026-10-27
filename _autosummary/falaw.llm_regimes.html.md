# falaw.llm_regimes

Token-rate regimes: the one vocabulary both falaw LLM rate tables price in (falaw#128).

[`falaw.llm_prices`](falaw.llm_prices.html.md#module-falaw.llm_prices) (first-party calls) and [`falaw.llm_rates`](falaw.llm_rates.html.md#module-falaw.llm_rates) (calls routed
through fal’s any-llm) both bill a model’s tokens at a set of per-million rates, and
some models switch to a dearer set once a prompt passes a length threshold. This module
owns that shape ([`LlmPriceRates`](#falaw.llm_regimes.LlmPriceRates)), how a table row spells it ([`rates_from_row()`](#falaw.llm_regimes.rates_from_row),
[`parse_long_prompt()`](#falaw.llm_regimes.parse_long_prompt)) and which set a prompt is billed at ([`rates_for_prompt()`](#falaw.llm_regimes.rates_for_prompt)),
so neither table keeps its own copy.

```pycon
>>> base = LlmPriceRates(input_usd_per_mtok=1.0, output_usd_per_mtok=2.0)
>>> long = LlmPriceRates(input_usd_per_mtok=3.0, output_usd_per_mtok=4.0)
>>> rates_for_prompt(base, 100, long_prompt_over_tokens=100, long_prompt_rates=long) is base
True
>>> rates_for_prompt(base, 101, long_prompt_over_tokens=100, long_prompt_rates=long) is long
True
```

### Functions

| [`parse_long_prompt`](#falaw.llm_regimes.parse_long_prompt)(row)                         | `(over_input_tokens, rates)` from a row's `long_prompt` block, or `(None, None)`.                         |
|-------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------|
| [`rates_for_prompt`](#falaw.llm_regimes.rates_for_prompt)(rates, input_tokens, \*, ...) | The rates a prompt of `input_tokens` is billed at: the long-prompt tier past its threshold, else `rates`. |
| [`rates_from_row`](#falaw.llm_regimes.rates_from_row)(row)                            | The `*_usd_per_mtok` columns of a table row (or a `long_prompt` block).                                   |

### Classes

| [`LlmPriceRates`](#falaw.llm_regimes.LlmPriceRates)(\*, input_usd_per_mtok, ...[, ...])   | USD per million tokens for one prompt-length regime of one model.   |
|------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------|

### *class* falaw.llm_regimes.LlmPriceRates(, input_usd_per_mtok, output_usd_per_mtok, cache_read_usd_per_mtok=None, cache_write_usd_per_mtok=None, cache_write_1h_usd_per_mtok=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

USD per million tokens for one prompt-length regime of one model.

### falaw.llm_regimes.parse_long_prompt(row)

`(over_input_tokens, rates)` from a row’s `long_prompt` block, or `(None, None)`.

The rates replace the row’s own once a prompt exceeds `over_input_tokens`.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)], [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`LlmPriceRates`](#falaw.llm_regimes.LlmPriceRates)]]

### falaw.llm_regimes.rates_for_prompt(rates, input_tokens, , long_prompt_over_tokens, long_prompt_rates)

The rates a prompt of `input_tokens` is billed at: the long-prompt tier
past its threshold, else `rates`.

* **Return type:**
  [`LlmPriceRates`](#falaw.llm_regimes.LlmPriceRates)

### falaw.llm_regimes.rates_from_row(row)

The `*_usd_per_mtok` columns of a table row (or a `long_prompt` block).

* **Return type:**
  [`LlmPriceRates`](#falaw.llm_regimes.LlmPriceRates)
