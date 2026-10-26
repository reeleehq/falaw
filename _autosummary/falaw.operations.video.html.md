# falaw.operations.video

Video-generation operations: text-to-video and image-to-video.

### Functions

| [`image_to_video`](#falaw.operations.video.image_to_video)(image_url[, prompt, quality, ...])   | Animate a still image into a video.   |
|------------------------------------------------------------------------------------------------------|---------------------------------------|
| [`text_to_video`](#falaw.operations.video.text_to_video)(prompt, \*[, quality, ...])           | Generate a video from a text prompt.  |

### falaw.operations.video.image_to_video(image_url, prompt='', , quality='high', duration_s=None, model_id=None, extra=None)

Animate a still image into a video.

* **Return type:**
  [`Result`](falaw.results.html.md#falaw.results.Result)

### falaw.operations.video.text_to_video(prompt, , quality='high', duration_s=None, model_id=None, extra=None)

Generate a video from a text prompt.

* **Return type:**
  [`Result`](falaw.results.html.md#falaw.results.Result)
