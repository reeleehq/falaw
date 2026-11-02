# falaw.schema_export

Export the Python SSOT as committed JSON for the TypeScript twin (`ts/`).

falaw ships twice: as this Python package and as the npm package `falaw-client`
(`ts/`), which *plans* in the browser and *executes* through a server relay.
The two must agree on the plan and result shapes, the model catalogue and its
prices, the cost rules, the model-picking rules, the response parser, and the
canonical byte-form every hash is taken over. None of that is re-authored on
the TypeScript side: this module writes it out as JSON, the TS build generates
its types from the schemas and reads the catalogue as data, and its parity tests
replay the fixtures below and assert the same output, hash for hash.

What lands in `<out_dir>`:

- `call-plan.schema.json`, `result.schema.json`, `model-record.schema.json`
  — the dataclasses as JSON Schema (via `pydantic.TypeAdapter`), the codegen
  inputs for the Zod types.
- `models.json` — the catalogue, **byte for byte**, so the TS side can compute
  the same `models_table_version` digest a [`falaw.CostBasis`](falaw.html.md#falaw.CostBasis) records.
- `constants.json` — the default backend, the plan dict schema tag, the
  catalogue pricer identity, the tier order, the response-kind keys, and the
  literal vocabularies (`OutputKind`, `CacheStatus`).
- `fixtures/plans.json` — planner inputs → the `CallPlan` dict this package
  builds (cost, basis and all) and its `plan_hash`; plus multi-call plans.
- `fixtures/responses.json` — raw fal responses → the `Result` this package
  parses them into.
- `fixtures/pick_model.json`, `fixtures/cost.json`, `fixtures/canonical.json`
  — model selection, cost estimation, and the canonical blob + SHA-256 for a set
  of payloads (the byte-form parity that makes `plan_hash` agree).
- `fixtures/log_lines.json` — fal’s `logs` arrays, one per status poll, and
  the lines each poll reports once ([`falaw.core.new_log_lines()`](falaw.core.html.md#falaw.core.new_log_lines)).

`tests/test_schema_export.py` pins the committed directory to a fresh export,
so a change here that forgets `python -m falaw export-schema` fails CI on this
side, before the TS side can drift.

```pycon
>>> from falaw.schema_export import PLAN_CASES
>>> PLAN_CASES[0]["tool"]
'generate_image'
```

### Functions

| [`export_schema`](#falaw.schema_export.export_schema)([out_dir])   | Write the JSON contract under `out_dir`; return the paths written.   |
|-----------------------------------------------------------------------------|----------------------------------------------------------------------|

### falaw.schema_export.export_schema(out_dir=None)

Write the JSON contract under `out_dir`; return the paths written.

`out_dir` defaults to the `schema/` directory of *this checkout*. This is
repository tooling: from an installed wheel (no `pyproject.toml` beside the
package) it refuses rather than writing a stray `schema/` wherever the shell
happens to be.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)]
