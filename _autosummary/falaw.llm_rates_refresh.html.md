# falaw.llm_rates_refresh

Refresh proposals for the LLM rate table, never a silent overwrite (falaw#56).

`falaw/data/llm_rates.json` was assembled by hand from two live sources and
has no refresh job, so it ages without saying so (falaw#50 option A found
this). Both sources move on their own schedule:

1. fal’s own any-llm endpoint doc (`ANY_LLM_DOC_URL`) — the `model` enum,
   the flat per-request price, and the verbatim premium list.
2. OpenRouter’s public catalogue (`OPENROUTER_MODELS_URL`) — the upstream
   `pricing.prompt` / `pricing.completion` any-llm resells.

[`refresh_llm_rates()`](#falaw.llm_rates_refresh.refresh_llm_rates) fetches both through an injectable seam, parses them
with pure functions ([`parse_any_llm_doc()`](#falaw.llm_rates_refresh.parse_any_llm_doc), [`parse_openrouter_models()`](#falaw.llm_rates_refresh.parse_openrouter_models)),
and diffs the result against the committed table. A price change is a
decision, not something this module gets to make on your behalf — the
committed `llm_rates.json` a test pins the premium set against is **never**
written here. `write=True` persists a *proposed* table plus a
human-readable diff alongside it; promoting the proposal over the committed
file is a separate, human step.

```pycon
>>> from falaw.llm_rates_refresh import parse_any_llm_doc
>>> doc = parse_any_llm_doc(
...     '- **Price**: $0.001 per requests\n'
...     '- **`model`** (`ModelEnum`, _optional_):\n'
...     '  Name of the model to use. Premium models are charged at 10x the '
...     'rate of standard models, they include: a/b, c/d. Default value: `"a/b"`\n'
...     '  - Options: `"a/b"`, `"c/d"`, `"e/f"`\n'
... )
>>> doc.base_per_call_usd
0.001
>>> doc.premium_multiple
10
>>> sorted(doc.premium_models)
['a/b', 'c/d']
>>> doc.model_enum
('a/b', 'c/d', 'e/f')
```

### Module Attributes

| [`ANY_LLM_DOC_URL`](#falaw.llm_rates_refresh.ANY_LLM_DOC_URL)         | model enum, flat price, premium list.                                    |
|--------------------------------------------------------------------------|--------------------------------------------------------------------------|
| [`OPENROUTER_MODELS_URL`](#falaw.llm_rates_refresh.OPENROUTER_MODELS_URL)   | upstream per-token list prices.                                          |
| [`PROPOSED_RATES_FILENAME`](#falaw.llm_rates_refresh.PROPOSED_RATES_FILENAME) | Basename of the proposed table a refresh writes under `falaw/data`.      |
| [`RATES_DIFF_FILENAME`](#falaw.llm_rates_refresh.RATES_DIFF_FILENAME)     | Basename of the human-readable diff a refresh writes under `falaw/data`. |
| [`TOKEN_RATE_PRECISION`](#falaw.llm_rates_refresh.TOKEN_RATE_PRECISION)    | Decimal places kept for a converted `*_usd_per_mtok` rate.               |

### Functions

| [`build_proposed_rows`](#falaw.llm_rates_refresh.build_proposed_rows)(any_llm, ...)         | One rate-table row per id in `any_llm.model_enum`, freshly derived.                                                 |
|--------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------|
| [`diff_llm_rate_tables`](#falaw.llm_rates_refresh.diff_llm_rate_tables)(committed_rows, ...) | Compare two `rows` lists (as loaded from the table JSON) by model id.                                               |
| [`format_llm_rates_diff`](#falaw.llm_rates_refresh.format_llm_rates_diff)(diff)               | Render [`diff_llm_rate_tables()`](#falaw.llm_rates_refresh.diff_llm_rate_tables)'s result as a human-readable report. |
| [`parse_any_llm_doc`](#falaw.llm_rates_refresh.parse_any_llm_doc)(text)                   | Pure parse of fal's any-llm `llms.txt` into [`AnyLlmDoc`](#falaw.llm_rates_refresh.AnyLlmDoc).             |
| [`parse_openrouter_models`](#falaw.llm_rates_refresh.parse_openrouter_models)(payload)          | `{model_id: (input_usd_per_mtok, output_usd_per_mtok)}` from OpenRouter.                                            |
| [`refresh_llm_rates`](#falaw.llm_rates_refresh.refresh_llm_rates)(\*[, write, ...])       | Fetch both sources, propose a fresh table, diff it — never overwrite.                                               |

### Classes

| [`AnyLlmDoc`](#falaw.llm_rates_refresh.AnyLlmDoc)(\*, base_per_call_usd, ...)   | The pricing-relevant facts parsed out of fal's any-llm doc.   |
|------------------------------------------------------------------------------------------|---------------------------------------------------------------|

### falaw.llm_rates_refresh.ANY_LLM_DOC_URL *= 'https://fal.ai/models/fal-ai/any-llm/llms.txt'*

model enum, flat price, premium list.

* **Type:**
  fal’s any-llm endpoint doc

### *class* falaw.llm_rates_refresh.AnyLlmDoc(, base_per_call_usd, premium_multiple, premium_models, model_enum)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The pricing-relevant facts parsed out of fal’s any-llm doc.

#### base_per_call_usd

The flat per-request price fal publishes for the
standard tier.

* **Type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### premium_multiple

How many times the base price a premium-tier
request costs.

* **Type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

#### premium_models

The routed-model ids fal’s doc lists as premium,
verbatim (a model here that is not in `model_enum` belongs to a
different endpoint, e.g. a vision-only variant, and is not a rate
table row).

* **Type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### model_enum

Every routed-model id the `model` argument accepts, in
the doc’s own order.

* **Type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

### falaw.llm_rates_refresh.OPENROUTER_MODELS_URL *= 'https://openrouter.ai/api/v1/models'*

upstream per-token list prices.

* **Type:**
  OpenRouter’s public model catalogue

### falaw.llm_rates_refresh.PROPOSED_RATES_FILENAME *= 'llm_rates.proposed.json'*

Basename of the proposed table a refresh writes under `falaw/data`.

### falaw.llm_rates_refresh.RATES_DIFF_FILENAME *= 'llm_rates.diff.txt'*

Basename of the human-readable diff a refresh writes under `falaw/data`.

### falaw.llm_rates_refresh.TOKEN_RATE_PRECISION *= 6*

Decimal places kept for a converted `*_usd_per_mtok` rate.

### falaw.llm_rates_refresh.build_proposed_rows(any_llm, openrouter_rates, , date)

One rate-table row per id in `any_llm.model_enum`, freshly derived.

The whole table is regenerated from the two sources every run — there is
no merge with the committed file here. The committed file only changes
when a human promotes a proposal, so there is nothing stale to carry
forward into it.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### falaw.llm_rates_refresh.diff_llm_rate_tables(committed_rows, proposed_rows)

Compare two `rows` lists (as loaded from the table JSON) by model id.

Returns `{"added", "removed", "changed", "unchanged"}`: `added`/
`removed` are sorted model-id lists; `changed` is a list of
`{"model", "field", "old", "new", "source", "date"}` for every
`_DIFFED_FIELDS` value that moved (`source`/`date` themselves
are provenance, not a price fact, so they never appear as a \*diffed
field\* even though every row gets a fresh stamp — but the *proposed*
row’s own `source`/`date` ride along on every change entry, so the
human-readable diff carries where the new number came from, not just
what it is); `unchanged` is a count.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### falaw.llm_rates_refresh.format_llm_rates_diff(diff)

Render [`diff_llm_rate_tables()`](#falaw.llm_rates_refresh.diff_llm_rate_tables)’s result as a human-readable report.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### falaw.llm_rates_refresh.parse_any_llm_doc(text)

Pure parse of fal’s any-llm `llms.txt` into [`AnyLlmDoc`](#falaw.llm_rates_refresh.AnyLlmDoc).

* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – the doc is missing the price line, the `model` field,
      its premium sentence, or its options list — any of which means
      fal changed the doc’s shape and a human should look, not that the
      refresh should guess.
* **Return type:**
  [`AnyLlmDoc`](#falaw.llm_rates_refresh.AnyLlmDoc)

### falaw.llm_rates_refresh.parse_openrouter_models(payload)

`{model_id: (input_usd_per_mtok, output_usd_per_mtok)}` from OpenRouter.

Pure parse of the `GET /api/v1/models` body. OpenRouter quotes
`pricing.prompt`/`pricing.completion` as USD-per-token strings; this
scales them to the table’s per-million-token unit. A model with a
missing, non-numeric, or non-positive prompt/completion price is left out
— unknown, never a guessed zero.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

### falaw.llm_rates_refresh.refresh_llm_rates(, write=False, http_get_any_llm_doc=None, http_get_openrouter_models=None, rates_path=None, proposed_path=None, diff_path=None, today=None)

Fetch both sources, propose a fresh table, diff it — never overwrite.

`rates_path` (default: the committed `llm_rates.json`) is read only,
never written: this function has no code path that touches the committed
table, by design — a repriced or retiered model is a decision for a human
to promote, not something a refresh job gets to make silently. With
`write=True`, the freshly-derived table is written to `proposed_path`
(default: `llm_rates.proposed.json` next to the committed file) and the
diff report to `diff_path` (default: `llm_rates.diff.txt`).

Returns a summary dict: `{"fetched_at", "committed_models",
"proposed_models", "diff", "write", "proposed_path", "diff_path"}`. The
two path keys are `None` when `write=False`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
