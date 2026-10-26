# falaw.results

Result wrapper: parse fal responses into typed assets, lazy download.

### Functions

| [`parse_response`](#falaw.results.parse_response)(raw, \*, application, arguments)   | Best-effort parser over the common fal response shapes.      |
|----------------------------------------------------------------------------------------------------|--------------------------------------------------------------|
| [`sniff_extension`](#falaw.results.sniff_extension)(data)                             | Extension implied by the leading bytes ('' if unrecognised). |

### Classes

| [`Asset`](#falaw.results.Asset)(url, kind[, content_type, width, ...])   | A single piece of generated media.                                  |
|-------------------------------------------------------------------------------------------------|---------------------------------------------------------------------|
| [`Result`](#falaw.results.Result)([assets, raw, application, arguments])  | A fal call result with parsed assets and the original raw response. |

### *class* falaw.results.Asset(url, kind, content_type='', width=0, height=0, duration_s=0.0, metadata=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A single piece of generated media.

Holds the URL plus minimal typed metadata. `download` materializes it.

#### download(, to=None, fix_suffix=False)

Download the asset to a file. Returns the local path.

The bytes are sniffed: some models return a different format than the
usual one (Recraft’s `vector_illustration/*` styles return SVG, not
PNG). If the suffix of `to` contradicts the content, a
`UserWarning` is issued; with `fix_suffix=True` the suffix is
corrected instead (so the returned path may differ from `to`).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### *class* falaw.results.Result(assets=list(), raw=dict(), application='', arguments=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A fal call result with parsed assets and the original raw response.

The raw response is kept so callers can inspect provider-specific fields
(timings, seed, has_nsfw_concepts, …) that we do not normalize.

### falaw.results.parse_response(raw, , application, arguments)

Best-effort parser over the common fal response shapes.

fal models return a variety of layouts (lists, single objects, bare URLs).
We normalize each into Asset(url, kind, …). Unknown shapes pass through
as `raw` only — callers can read `result.raw` for anything we miss.

* **Return type:**
  [`Result`](#falaw.results.Result)

### falaw.results.sniff_extension(data)

Extension implied by the leading bytes (’’ if unrecognised).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
