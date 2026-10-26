# falaw.registry

Tool and model registries.

Two registries, both queryable by tags/categories:

* `ToolRegistry` — decorator-populated, holds the agent-facing surface.
* `ModelRegistry` — JSON-backed, catalog of fal models with quality tiers.

Bridges (skill / MCP / HTTP) read the tool registry. Operations call
`pick_model` to map a (category, quality) pair to a concrete fal model id.

### Module Attributes

| [`MODEL_CATALOGUE_TABLE`](#falaw.registry.MODEL_CATALOGUE_TABLE)   | Identity a [`falaw.CostBasis`](falaw.html.md#falaw.CostBasis) records for a catalogue-priced call.   |
|--------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------|

### Functions

| `get_model`(id)                                                                           |                                                                                                                                               |
|-------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| `get_tool`(name)                                                                          |                                                                                                                                               |
| `list_models`(\*[, category, quality_tier])                                               |                                                                                                                                               |
| `list_tools`(\*[, tag])                                                                   |                                                                                                                                               |
| [`model_constraints`](#falaw.registry.model_constraints)(id)                    | The capability/limit fields for a model — the "static reminder of limitations" a shot-list builder surfaces.                                  |
| [`model_params`](#falaw.registry.model_params)(id)                         | Per-model parameters worth knowing before a call, `{name: spec}`.                                                                             |
| [`models_table_version`](#falaw.registry.models_table_version)()                   | The catalogue's version — see [`falaw.base.data_table_version()`](falaw.base.html.md#falaw.base.data_table_version). |
| [`pick_model`](#falaw.registry.pick_model)(\*, category[, quality_tier]) | Pick a sensible fal model for a (category, quality) request.                                                                                  |
| [`register_tool`](#falaw.registry.register_tool)(\*\*spec_kwargs)           | Decorator: register the wrapped function as a falaw tool.                                                                                     |
| [`video_model_constraints`](#falaw.registry.video_model_constraints)()                | `model_constraints` for every video model in the catalog — the data a shot-list builder shows as its model-limits reference.                  |

### falaw.registry.MODEL_CATALOGUE_TABLE *= 'falaw/data/models.json'*

Identity a [`falaw.CostBasis`](falaw.html.md#falaw.CostBasis) records for a catalogue-priced call.

### falaw.registry.model_constraints(id)

The capability/limit fields for a model — the “static reminder of
limitations” a shot-list builder surfaces. Resolves aliases.

Returns a JSON-able dict; `max_clip_seconds` etc. are `None` / empty
when unknown for that model.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### falaw.registry.model_params(id)

Per-model parameters worth knowing before a call, `{name: spec}`.

Each spec is `{"enum": [...], "default": ...}`; resolves aliases. For
`fal-ai/recraft/v3/text-to-image` this shows `style` defaults to
`realistic_image` — a photograph, whatever the prompt describes — and
lists the styles that actually give a woodcut or a linocut. Empty when the
catalogue records none (fal’s OpenAPI schema is the full source).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### falaw.registry.models_table_version()

The catalogue’s version — see [`falaw.base.data_table_version()`](falaw.base.html.md#falaw.base.data_table_version).

Cached per process, like the catalogue itself.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### falaw.registry.pick_model(, category, quality_tier='balanced')

Pick a sensible fal model for a (category, quality) request.

First-match semantics: when several models share a tier, the earlier
entry wins. Curated entries are written first in `data/models.json`,
so they take precedence over corpus-merged additions. If no model
has the exact tier, neighboring tiers are tried. KeyError only when
the category is empty.

* **Return type:**
  [`ModelRecord`](falaw.base.html.md#falaw.base.ModelRecord)

### falaw.registry.register_tool(\*\*spec_kwargs)

Decorator: register the wrapped function as a falaw tool.

```pycon
>>> @register_tool(name='echo', description='echo back', tags=('demo',))
... def _echo(x): return x
>>> get_tool('echo').name
'echo'
```

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)

### falaw.registry.video_model_constraints()

`model_constraints` for every video model in the catalog — the data a
shot-list builder shows as its model-limits reference.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
