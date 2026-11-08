# falaw.operations.images

Image-generation and image-manipulation operations.

### Functions

| [`composite_character_in_environment`](#falaw.operations.images.composite_character_in_environment)(...[, ...])    | Place a character into an environment as one composited still.          |
|----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------|
| [`edit_image`](#falaw.operations.images.edit_image)(image_url, prompt, \*[, quality, ...]) | Edit an image with a natural-language instruction.                      |
| [`generate_image`](#falaw.operations.images.generate_image)(prompt, \*[, quality, ...])        | Generate an image from a text prompt.                                   |
| [`generate_image_with_control`](#falaw.operations.images.generate_image_with_control)(prompt, control, \*)  | Generate an image conditioned on a guide image's structure (falaw#140). |
| [`generate_image_with_refs`](#falaw.operations.images.generate_image_with_refs)(prompt, ...[, ...])      | Generate a new image conditioned on one or more reference images.       |
| [`remove_background`](#falaw.operations.images.remove_background)(image_url, \*[, quality, ...])  | Remove the background from an image.                                    |
| [`upscale_image`](#falaw.operations.images.upscale_image)(image_url, \*[, scale, ...])        | Upscale an image.                                                       |

### falaw.operations.images.composite_character_in_environment(character_image_url, environment_image_url, , prompt='', quality='balanced', model_id=None, extra=None)

Place a character into an environment as one composited still.

The single most user-visible primitive missing from muvid (per
interface_design_plan item E). With this, an agent can produce
“Thor in a bell tower” — the character anchor for a downstream
omnihuman lipsync — without manually compositing in an image editor.

Defaults to `fal-ai/flux-kontext/dev` (image_edit category at
balanced/high tier). Pass `model_id` to override
(e.g. `"fal-ai/flux-pro/kontext/max"` for highest quality, or
`"fal-ai/bytedance/seededit/v3/edit-image"` for SeedEdit).

* **Return type:**
  [`Result`](falaw.results.html.md#falaw.results.Result)

### falaw.operations.images.edit_image(image_url, prompt, , quality='balanced', model_id=None, extra=None)

Edit an image with a natural-language instruction.

* **Return type:**
  [`Result`](falaw.results.html.md#falaw.results.Result)

### falaw.operations.images.generate_image(prompt, , quality='balanced', image_size='landscape_4_3', model_id=None, extra=None, negative_prompt=None)

Generate an image from a text prompt.

`negative_prompt` (what the picture must not contain, named as the thing:
“glasses”, not “no glasses”) reaches a model that accepts one
([`falaw.ModelRecord.accepts_negative_prompt`](falaw.html.md#falaw.ModelRecord.accepts_negative_prompt)) and is dropped for any
other, never joined into `prompt`.

`image_size` is a fal preset (`landscape_16_9` …); models that size by
`aspect_ratio` (`nano-banana-pro`) get the equivalent ratio, with
`extra={"resolution": "2K"}` for the pixel tier. A prompt over the
model’s cap raises [`falaw.FalPromptTooLong`](falaw.html.md#falaw.FalPromptTooLong) before any call. Check
[`falaw.model_params()`](falaw.html.md#falaw.model_params) for enums whose default may not be what you
want (Recraft `style` defaults to photoreal).

* **Return type:**
  [`Result`](falaw.results.html.md#falaw.results.Result)

### falaw.operations.images.generate_image_with_control(prompt, control, , quality='balanced', image_size='landscape_4_3', model_id=None, extra=None, negative_prompt=None)

Generate an image conditioned on a guide image’s structure (falaw#140).

`control` is `[{"mode": "canny" | "depth" | "pose" | ..., "image": url,
"scale": 0.6}]` (`scale` defaults to fal’s 1.0). It is sent as fal’s
`easycontrols`; `controlnet_unions` and the subject-style EasyControl
methods pass through `extra`. A local guide image (a `pathlib.Path`) is
uploaded with [`falaw.upload()`](falaw.html.md#falaw.upload) (swap the transfer with
[`falaw.using_uploader()`](falaw.html.md#falaw.using_uploader)) once the call is known to be well formed. Plan
the call with [`falaw.plan_generate_image_with_control()`](falaw.html.md#falaw.plan_generate_image_with_control) instead to
upload only on a cache miss and key the cache on the file’s bytes.

* **Return type:**
  [`Result`](falaw.results.html.md#falaw.results.Result)

### falaw.operations.images.generate_image_with_refs(prompt, reference_image_urls, , quality='balanced', model_id=None, extra=None, negative_prompt=None)

Generate a new image conditioned on one or more reference images.

The missing twin of [`generate_image()`](#falaw.operations.images.generate_image): text-to-image models silently
ignore reference images, so callers wanting a recurring subject to stay
consistent (a character’s face across storyboard panels) need a model that
actually ingests references. This routes to the `image_edit` category
(Flux Kontext et al.) and threads the references as `image_url` (first)

+ `image_urls` (all) — the same wire shape image-edit models understand.

Pass `model_id` to override the picked model. `negative_prompt` as for
[`generate_image()`](#falaw.operations.images.generate_image).

* **Return type:**
  [`Result`](falaw.results.html.md#falaw.results.Result)

### falaw.operations.images.remove_background(image_url, , quality='high', model_id=None, extra=None)

Remove the background from an image.

* **Return type:**
  [`Result`](falaw.results.html.md#falaw.results.Result)

### falaw.operations.images.upscale_image(image_url, , scale=2.0, model_id=None, extra=None)

Upscale an image.

* **Return type:**
  [`Result`](falaw.results.html.md#falaw.results.Result)
