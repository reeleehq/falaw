# falaw.local

Local utilities: ffmpeg + PIL glue for stitching fal outputs.

The fal calls produce URLs. This module materializes them into local
files and assembles them into watchable scenes (concat, transitions,
thumbnails, etc.). Anything that’s cheap to do locally lives here so
the cloud calls stay focused on generation.

`ffmpeg` is the one external dependency. The functions raise a clear
error if it’s missing.

### Functions

| [`concatenate_clips`](#falaw.local.concatenate_clips)(clip_urls, \*, output_path)   | Materialize each clip and concatenate into one mp4.   |
|--------------------------------------------------------------------------------------------------|-------------------------------------------------------|
| [`extract_thumbnail`](#falaw.local.extract_thumbnail)(clip_url, \*, output_path)    | Save a single frame from a clip as a PNG.             |
| [`has_ffmpeg`](#falaw.local.has_ffmpeg)()                                    | Whether both `ffmpeg` and `ffprobe` are on `PATH`.    |
| [`overlay_audio`](#falaw.local.overlay_audio)(video_url, audio_url, \*, ...)    | Mix an audio track onto a video clip.                 |

### falaw.local.concatenate_clips(clip_urls, , output_path, transition_s=0.0, audio=True)

Materialize each clip and concatenate into one mp4.

* **Parameters:**
  * **clip_urls** ([`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – ordered iterable of fal-served clip URLs (or local paths).
  * **output_path** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – where to write the concatenated mp4.
  * **transition_s** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – crossfade duration in seconds (0 = hard cut).
  * **audio** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – whether to include audio in the output.
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
* **Returns:**
  The output path.

### falaw.local.extract_thumbnail(clip_url, , output_path, at_seconds=1.0)

Save a single frame from a clip as a PNG.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### falaw.local.has_ffmpeg()

Whether both `ffmpeg` and `ffprobe` are on `PATH`.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### falaw.local.overlay_audio(video_url, audio_url, , output_path, replace_audio=True)

Mix an audio track onto a video clip.

With `replace_audio=True` (default) the original audio is dropped.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
