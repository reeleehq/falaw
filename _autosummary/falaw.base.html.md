# falaw.base

Core types: ToolSpec and ModelRecord.

These dataclasses are the single source of truth from which every external
surface (Claude skill, MCP server, HTTP service, UI) is derived.

### Module Attributes

| [`TABLE_VERSION_CHARS`](#falaw.base.TABLE_VERSION_CHARS)   | Hex characters of the digest [`data_table_version()`](#falaw.base.data_table_version) returns.   |
|------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------|

### Functions

| [`data_table_version`](#falaw.base.data_table_version)(path)   | Short content digest naming the version of a committed data table.   |
|-----------------------------------------------------------------------------|----------------------------------------------------------------------|

### Classes

| [`CostEstimate`](#falaw.base.CostEstimate)(\*, kind, amount[, currency, ...])   | Quantitative cost of one fal call against this model.   |
|----------------------------------------------------------------------------------------------------|---------------------------------------------------------|
| [`ModelRecord`](#falaw.base.ModelRecord)(\*, id, category[, description, ...]) | One entry in the fal model catalog.                     |
| [`ToolSpec`](#falaw.base.ToolSpec)(\*, name, description, func[, ...])      | Single source of truth for a tool exposed by falaw.     |

### *class* falaw.base.CostEstimate(, kind, amount, currency='USD', notes='', source='approximate')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Quantitative cost of one fal call against this model.

#### kind

How the price scales. `per_call` is the simplest:
constant per invocation regardless of size. `per_second`
applies to video / TTS where output length matters.
`per_image` covers batch image gen. `per_megapixel`
covers high-res image generation. `per_token` covers
LLM-style endpoints.

* **Type:**
  [`Literal`](https://docs.python.org/3/library/typing.html#typing.Literal)[`'per_call'`, `'per_image'`, `'per_second'`, `'per_token'`, `'per_megapixel'`]

#### amount

USD (or `currency`) per unit defined by `kind`.

* **Type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### currency

ISO 4217 code. `"USD"` is the only supported value
today; the field exists so we can extend without a schema
migration.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### notes

Free-form caveats — “rounded up to next second”, etc.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### source

How the estimate was obtained — `"docs"`,
`"empirical"`, `"approximate"`. Lets us flag stale or
unverified entries in audits.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### *class* falaw.base.ModelRecord(, id, category, description='', aliases=(), quality_tier='', cost_hint='', cost_estimate=None, docs_url='', max_clip_seconds=None, single_character_recommended=False, supported_resolutions=(), default_negative_prompt='', max_prompt_chars=None, size_param='image_size', param_specs=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One entry in the fal model catalog.

#### default_negative_prompt *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

Quality/realism negatives worth appending by default (e.g. to avoid the
plastic-skin look). Empty when none.

#### max_clip_seconds *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[float](https://docs.python.org/3/builtins/functions.html#float)]*

Practical max length of a single generated clip, in seconds (e.g. ~10
for Seedance). Drives the “this shot is too long, split it” warning.

#### max_prompt_chars *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[int](https://docs.python.org/3/builtins/functions.html#int)]*

Hard cap on `prompt` length, from the model’s OpenAPI schema. Calls
over it fail at fal with an HTTP 422 after queueing; falaw raises first.

#### param_specs *: [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Any](https://docs.python.org/3/library/typing.html#typing.Any)]]*

Discoverable per-model parameters that matter for choosing well, as
`{name: {"enum": [...], "default": ...}}` — e.g. Recraft’s `style`,
whose photoreal default silently overrides a woodcut prompt. See
[`falaw.model_params()`](falaw.html.md#falaw.model_params).

#### single_character_recommended *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True when the model handles a single character per shot far better than
multiple interacting ones — drives the “two characters, consider
shot/reverse-shot” warning.

#### size_param *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

`"image_size"` (fal’s named
presets, the default) or `"aspect_ratio"` (+ `resolution`).

* **Type:**
  Which argument carries the output size

#### supported_resolutions *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]*

Resolutions the model offers, cheap→expensive (e.g. (“720p”, “1080p”)).

### falaw.base.TABLE_VERSION_CHARS *= 12*

Hex characters of the digest [`data_table_version()`](#falaw.base.data_table_version) returns.

### *class* falaw.base.ToolSpec(, name, description, func, input_schema=dict(), output_schema=dict(), tags=(), examples=(), version='0.0.1')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Single source of truth for a tool exposed by falaw.

A ToolSpec is what the registry stores. Bridges read it to produce
Claude-skill instructions, MCP tool descriptors, HTTP endpoints, etc.

### falaw.base.data_table_version(path)

Short content digest naming the version of a committed data table.

The one definition for every table falaw ships (`models.json`,
`llm_rates.json`), so a [`falaw.CostBasis`](falaw.html.md#falaw.CostBasis) stamped by one is
comparable with a basis stamped by another.

Deliberately the *bytes*, not a declared `version` field: 0.0.46 moved
every premium LLM row’s price tenfold without touching one, and that drift
is exactly what a persisted quote must be able to detect. A digest cannot
forget to be bumped.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
