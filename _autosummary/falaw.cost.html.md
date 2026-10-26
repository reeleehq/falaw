# falaw.cost

Cost estimation: ModelRecord.cost_estimate + Scene rollups.

Two surfaces here:

- `estimate_call_cost(record, *, count=1, seconds=None, megapixels=None,
  tokens=None)()` — turn one model’s `CostEstimate` into a USD figure.
- `estimate_scene_cost(scene, *, ...)()` — walk every Shot + Beat in a
  [`falaw.Scene`](falaw.html.md#falaw.Scene) and sum the per-call costs that
  [`falaw.render_scene()`](falaw.html.md#falaw.render_scene) would incur. Returns a structured rollup
  > (per-line + totals) so UIs can show “this render would cost ~$0.42”.

A scene-level estimate is *advisory*. It’s based on the same
`pick_model(category, quality_tier=...)` lookup that the renderer
uses, multiplied by per-line duration / pixel budgets. Real costs vary
with model fluctuations and provider billing rules, but this is good
enough to gate on (e.g. `--budget=1.00`) and to surface in
`muvid status`.

### Module Attributes

| [`DFLT_MEGAPIXELS`](#falaw.cost.DFLT_MEGAPIXELS)       | Pixel budget assumed for a `per_megapixel` call when the caller gives none: a 16:9 canvas 1024 wide (≈0.59 MP), enough for a useful upper-bound estimate.   |
|------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`RESOLUTION_SHORT_SIDE`](#falaw.cost.RESOLUTION_SHORT_SIDE) | The short side, in pixels, of fal's named video resolutions.                                                                                                |
| [`DFLT_VIDEO_ASPECT`](#falaw.cost.DFLT_VIDEO_ASPECT)     | Aspect ratio assumed when none is given or fal derives it (`"auto"`, from the input image): the common case, and 1:1 or 4:3 then over-quote.                |
| [`DFLT_VIDEO_RESOLUTION`](#falaw.cost.DFLT_VIDEO_RESOLUTION) | Resolution assumed for a token-billed video model that records no default.                                                                                  |

### Functions

| [`estimate_call_cost`](#falaw.cost.estimate_call_cost)(record, \*[, count, ...])       | Cost of one fal call against `record`.                                 |
|-----------------------------------------------------------------------------------------------------|------------------------------------------------------------------------|
| [`estimate_scene_cost`](#falaw.cost.estimate_scene_cost)(scene, \*[, tts_quality, ...]) | Estimate the USD cost of a full `render_scene()` invocation.           |
| [`frame_pixels`](#falaw.cost.frame_pixels)(resolution[, aspect_ratio])           | Pixels per frame of a `resolution` at `aspect_ratio` (`"W:H"`).        |
| [`video_call_arguments`](#falaw.cost.video_call_arguments)(record, arguments, \*, ...)   | `(wire arguments, seconds the call bills)` for a video call.           |
| [`video_duration_arg`](#falaw.cost.video_duration_arg)(record, duration_s)             | `duration_s` as the string fal's duration enum wants, or `ValueError`. |
| [`video_price_quantities`](#falaw.cost.video_price_quantities)(record, \*[, seconds, ...]) | The quantity hints that price one video call against `record`.         |

### Classes

| [`CostLine`](#falaw.cost.CostLine)(\*, kind, item_id, model_id, amount, ...)   | One line item in a scene rollup.                                                  |
|-------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------|
| [`CostRollup`](#falaw.cost.CostRollup)(\*, total_amount[, currency, ...])        | Result of [`estimate_scene_cost()`](#falaw.cost.estimate_scene_cost). |

### *class* falaw.cost.CostLine(, kind, item_id, model_id, amount, currency, note='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One line item in a scene rollup.

### *class* falaw.cost.CostRollup(, total_amount, currency='USD', lines=(), skipped=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Result of [`estimate_scene_cost()`](#falaw.cost.estimate_scene_cost).

#### by_kind()

Sum per `kind` for quick inspection.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]

### falaw.cost.DFLT_MEGAPIXELS *= 0.6*

Pixel budget assumed for a `per_megapixel` call when the caller gives none:
a 16:9 canvas 1024 wide (≈0.59 MP), enough for a useful upper-bound estimate.
Exported to the TypeScript twin, which must assume the same.

### falaw.cost.DFLT_VIDEO_ASPECT *= '16:9'*

Aspect ratio assumed when none is given or fal derives it (`"auto"`, from
the input image): the common case, and 1:1 or 4:3 then over-quote.

### falaw.cost.DFLT_VIDEO_RESOLUTION *= '720p'*

Resolution assumed for a token-billed video model that records no default.

### falaw.cost.RESOLUTION_SHORT_SIDE *= {'1080p': 1080, '480p': 480, '4k': 2160, '720p': 720}*

The short side, in pixels, of fal’s named video resolutions. The frame is
that squared times the aspect ratio’s long/short ratio ([`frame_pixels()`](#falaw.cost.frame_pixels)).

### falaw.cost.estimate_call_cost(record, , count=1, seconds=None, megapixels=None, tokens=None)

Cost of one fal call against `record`.

Returns `None` when the cost is **unknown**, so callers can
distinguish “free” from “we can’t say”. That happens when the record
carries no `cost_estimate` at all, or when its pricing is
quantity-based (`per_second` / `per_token`) and the caller did
not supply the quantity — an unpriceable call, not a free one.

Returning `0.0` for a missing quantity would be actively dangerous:
a `per_second` clip is the single most expensive thing fal bills
for, and a caller gating a budget on the answer would read
“$0.00” and spend real money without a prompt. `None` instead
propagates to `CallPlan.estimated_cost_usd` and lights up
`Plan.has_unknown_costs`, which exists for exactly this case.
Callers that know the quantity should pass it; `per_second` callers
can fall back to `record.max_clip_seconds` for an upper bound.

`per_megapixel` is deliberately different: an image’s pixel budget
has a sane house default (below), so it stays priceable.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

### falaw.cost.estimate_scene_cost(scene, , tts_quality='balanced', lipsync_quality='high', shot_quality='balanced', shots_as_video=False, shot_seconds=None)

Estimate the USD cost of a full `render_scene()` invocation.

Walks every shot + beat with the same `pick_model` semantics
the renderer uses, then sums per-call costs. Returns a structured
[`CostRollup`](#falaw.cost.CostRollup) with per-line breakdowns, plus a list of
“skipped” entries the caller should surface (typically: a model
with no `cost_estimate` populated).

`shot_seconds` is the assumed clip length used to price
`shots_as_video`. A `Shot` carries no duration of its own —
screen time comes from the renderer’s per-shot run — and
image-to-video models bill **per second**, so without this the video
lines are genuinely unpriceable and are reported in
`CostRollup.skipped` rather than silently priced at $0.00.
Pass the length you expect (the beat path has the same knob as
`estimated_seconds`).

* **Return type:**
  [`CostRollup`](#falaw.cost.CostRollup)

### falaw.cost.frame_pixels(resolution, aspect_ratio=None)

Pixels per frame of a `resolution` at `aspect_ratio` (`"W:H"`).

An estimate within about a percent of what fal bills (it rounds frame
sides to codec-friendly multiples): `short_side ** 2 * long / short`.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### falaw.cost.video_call_arguments(record, arguments, , duration_s, extra)

`(wire arguments, seconds the call bills)` for a video call.

The one place planned and eager video calls agree. `duration_s` is *sent*
only for a model whose record lists a `duration` parameter (Seedance spells
it as a string enum), validated by [`video_duration_arg()`](#falaw.cost.video_duration_arg); elsewhere it
is estimator-only when planning, since models name that argument
differently. `extra` wins over everything and the billed seconds follow
what it says.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict), [`float`](https://docs.python.org/3/builtins/functions.html#float) | [`None`](https://docs.python.org/3/builtins/constants.html#None)]

### falaw.cost.video_duration_arg(record, duration_s)

`duration_s` as the string fal’s duration enum wants, or `ValueError`.

The one rule the planner (what is sent and quoted) and the scene rollup
share, so neither prices a call fal would reject: whole seconds (halves to
even), and within the record’s `duration` enum when it lists numbers
(`"auto"` aside).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### falaw.cost.video_price_quantities(record, , seconds=None, resolution=None, aspect_ratio=None)

The quantity hints that price one video call against `record`.

`{"tokens": n}` for a model billed per video token (its
`tokens_per_pixel_second` is set), else `{"seconds": s}`; `{}` when
`seconds` is unknown, so the call stays unpriceable rather than free.
`resolution` defaults to the model’s recorded default; `aspect_ratio`
to [`DFLT_VIDEO_ASPECT`](#falaw.cost.DFLT_VIDEO_ASPECT).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
