# falaw.refresh

Refresh fal.ai docs locally with conditional GETs.

Three layers, cheapest first:

* `is_stale(source)` — HEAD with `If-None-Match`; near-zero cost.
* `fetch_if_changed(source)` — conditional GET; saves and snapshots if changed.
* `refresh_llms()` / `refresh_full_docs()` — coordinate fetches across
  the doc set, save previous-version snapshots for diffing, journal results.

State (per-source ETag and Last-Modified) is kept under
`$FALAW_DATA_DIR/refresh/state.json` (default `~/.config/falaw/refresh/`);
previous-version snapshots live alongside as `<source>.prev` so a successful
refresh can be diffed against the prior content.

For scheduled / remote runs, set `FALAW_DATA_DIR` to a path *inside* the
repo (e.g. `misc/falaw_state`) so journal entries and refresh state are
committed back to the repo on each run.

### Functions

| [`default_sources`](#falaw.refresh.default_sources)(\*[, docs_dir])                | The default documentation sources to refresh, rooted at `docs_dir`.   |
|-------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------|
| [`diff_against_previous`](#falaw.refresh.diff_against_previous)(source, \*[, n_context]) | Unified diff: previous snapshot vs current local file.                |
| [`fetch_if_changed`](#falaw.refresh.fetch_if_changed)(source, \*[, save_snapshot])  | Conditional GET.                                                      |
| [`is_stale`](#falaw.refresh.is_stale)(source, \*[, state])                  | Cheap HEAD: True iff the upstream ETag differs from saved state.      |
| [`refresh_full_docs`](#falaw.refresh.refresh_full_docs)(\*[, docs_dir, ...])         | Re-crawl per-page docs and rebuild `fal_ai_docs_full.md`.             |
| [`refresh_llms`](#falaw.refresh.refresh_llms)(\*[, docs_dir, journal])          | Refresh `llms.txt` and `llms-full.txt`; return a summary dict.        |
| [`refresh_state`](#falaw.refresh.refresh_state)()                                | Return the saved per-source refresh state (etags, last fetch times).  |

### Classes

| [`DocSource`](#falaw.refresh.DocSource)(\*, name, url, local_path)   | A single document mirrored locally.   |
|-----------------------------------------------------------------------------------------|---------------------------------------|

### *class* falaw.refresh.DocSource(, name, url, local_path)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A single document mirrored locally.

### falaw.refresh.default_sources(, docs_dir=None)

The default documentation sources to refresh, rooted at `docs_dir`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`DocSource`](#falaw.refresh.DocSource)]

### falaw.refresh.diff_against_previous(source, , n_context=3)

Unified diff: previous snapshot vs current local file.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### falaw.refresh.fetch_if_changed(source, , save_snapshot=True)

Conditional GET. Updates the local file and saved state on a real change.

Returns `(changed, body)`: `changed` is False on 304 (or any non-200);
`body` is the new text only when changed.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### falaw.refresh.is_stale(source, , state=None)

Cheap HEAD: True iff the upstream ETag differs from saved state.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### falaw.refresh.refresh_full_docs(, docs_dir=None, max_workers=16, force=False, journal=True)

Re-crawl per-page docs and rebuild `fal_ai_docs_full.md`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### falaw.refresh.refresh_llms(, docs_dir=None, journal=True)

Refresh `llms.txt` and `llms-full.txt`; return a summary dict.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### falaw.refresh.refresh_state()

Return the saved per-source refresh state (etags, last fetch times).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
