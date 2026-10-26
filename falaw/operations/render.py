"""Beat / shot / scene rendering with caching.

The directorial workflow only works if a single IR edit causes only the
*affected* parts to re-render. Each renderer here:

1. Computes a content hash from the IR (``beat_content_hash`` /
   ``shot_content_hash``) plus the relevant identity anchors.
2. Stores the result in `falaw.cache` keyed by that hash.
3. Returns a small dict with ``url``, ``cache_hit``, and ``hash`` so the
   scene renderer can build a manifest.

Outputs:

* ``render_beat`` --- TTS (using the speaker's voice) → lipsync to the
  speaker's reference image. Returns a video URL.
* ``render_shot`` --- a still or short clip of the visual frame
  (storyboard or i2v depending on quality).
* ``render_scene`` --- orchestrates beats and shots, returns a manifest
  dict that can be persisted next to the Scene file.
"""

from __future__ import annotations

import os
from typing import Optional

from ..cache import _cache_dir, cache_get, cache_put, cached_call_fal
from ._image_args import image_arguments, known_record
from ..registry import pick_model, register_tool
from ..results import parse_response
from ..terms import current_terms_context
from ..scene import (
    Beat,
    Character,
    Environment,
    Scene,
    Shot,
    beat_content_hash,
    shot_content_hash,
)


# --- helpers --------------------------------------------------------------


def _picked_tts_model(character: Character, *, quality: str = "balanced") -> str:
    """Pick the right TTS model. Voice cloning if reference audio present;
    voice id when set; otherwise the default TTS tier."""
    if character.voice and character.voice.model_id:
        return character.voice.model_id
    if character.voice and character.voice.reference_audio_url:
        return pick_model(category="voice_clone", quality_tier="high").id
    return pick_model(category="tts", quality_tier=quality).id


def _tts_arguments(character: Character, line: str) -> dict:
    args: dict = {"text": line}
    if not character.voice:
        return args
    v = character.voice
    if v.reference_audio_url:
        args["reference_audio_url"] = v.reference_audio_url
    if v.voice_id:
        args["voice"] = v.voice_id
    return args


# --- per-beat -------------------------------------------------------------


@register_tool(
    name="render_beat",
    description=(
        "Render one Beat: TTS (using the speaker's Voice) → lipsync to "
        "the speaker's reference image. Cached by content hash --- "
        "re-rendering an unchanged Beat is a no-op. Returns "
        "{url, cache_hit, hash, audio_url}."
    ),
    tags=("render", "beat", "video"),
    input_schema={
        "type": "object",
        "required": ["beat", "character"],
        "properties": {
            "beat": {"type": "object", "description": "falaw.Beat"},
            "character": {"type": "object", "description": "falaw.Character"},
            "tts_quality": {"type": "string", "default": "balanced"},
            "lipsync_quality": {"type": "string", "default": "high"},
            "force": {
                "type": "boolean",
                "default": False,
                "description": "Bypass cache and re-render.",
            },
        },
    },
    output_schema={"type": "object"},
    examples=(),
)
def render_beat(
    beat: Beat,
    character: Character,
    *,
    tts_quality: str = "balanced",
    lipsync_quality: str = "high",
    tts_model_id: Optional[str] = None,
    avatar_model_id: Optional[str] = None,
    force: bool = False,
) -> dict:
    """Render one Beat to a lipsynced video. Returns a small manifest dict.

    Args:
        tts_model_id: Override the TTS model. When provided, takes precedence
            over the character's voice.model_id and over ``tts_quality``-based
            ``pick_model``. Use this to force a specific TTS engine for one
            beat (e.g. eleven-v3 for emotional delivery, multilingual-v2 for
            consistency).
        avatar_model_id: Override the avatar/lipsync model (e.g.
            ``"fal-ai/bytedance/omnihuman/v1.5"`` to bypass the default
            ``ai-avatar`` which is known to hang).
    """
    if not beat.line and not beat.action:
        return {
            "url": "",
            "cache_hit": False,
            "hash": "",
            "skipped": "empty beat (no line, no action)",
        }

    h = beat_content_hash(beat, character=character)
    cache_app = "falaw.render_beat"
    cache_args = {"hash": h}

    # Under a terms context a composite hit cannot show which models made it, so
    # it is a miss: the per-call caches underneath are checked (falaw#110).
    if not force and current_terms_context() is None:
        hit = cache_get(cache_app, cache_args)
        if hit is not None:
            return {**hit, "cache_hit": True}

    audio_url = ""
    video_url = ""

    if beat.line:
        tts_model = tts_model_id or _picked_tts_model(character, quality=tts_quality)
        tts_args = _tts_arguments(character, beat.line)
        tts_raw = cached_call_fal(tts_model, tts_args, refresh=force)
        tts_result = parse_response(tts_raw, application=tts_model, arguments=tts_args)
        if not tts_result.first:
            raise RuntimeError(
                f"render_beat: TTS produced no asset for beat {beat.id!r}"
            )
        audio_url = tts_result.first.url

    if beat.line and character.reference_image_url:
        # `avatar` category = image+audio → talking video (the right primitive
        # for "still face speaks line"). `lipsync` category requires an
        # existing video, which we don't have here.
        av_model = (
            avatar_model_id
            or pick_model(category="avatar", quality_tier=lipsync_quality).id
        )
        # ai-avatar requires a non-empty `prompt`; omnihuman accepts one.
        # Use beat.emotion / beat.action as the directorial hint; fall back
        # to a neutral default so the schema is satisfied.
        av_prompt = beat.emotion or beat.action or "natural delivery"
        av_args = {
            "image_url": character.reference_image_url,
            "audio_url": audio_url,
            "prompt": av_prompt,
        }
        av_raw = cached_call_fal(av_model, av_args, refresh=force)
        av_result = parse_response(av_raw, application=av_model, arguments=av_args)
        if av_result.first:
            video_url = av_result.first.url

    manifest = {
        "url": video_url or audio_url,
        "video_url": video_url,
        "audio_url": audio_url,
        "hash": h,
        "beat_id": beat.id,
        "speaker": beat.speaker,
        "cache_hit": False,
    }
    cache_put(cache_app, cache_args, manifest, note=f"beat:{beat.id}")
    return manifest


# --- per-shot -------------------------------------------------------------


@register_tool(
    name="render_shot",
    description=(
        "Render a Shot: a still (storyboard) or short clip if "
        "`as_video=True` (image-to-video). Cached by content hash. "
        "Returns {url, cache_hit, hash, kind}."
    ),
    tags=("render", "shot"),
    input_schema={
        "type": "object",
        "required": ["shot"],
        "properties": {
            "shot": {"type": "object", "description": "falaw.Shot"},
            "environment": {"type": "object", "description": "falaw.Environment"},
            "characters": {"type": "array", "description": "list of falaw.Character"},
            "style": {"type": "string"},
            "as_video": {"type": "boolean", "default": False},
            "quality": {"type": "string", "default": "balanced"},
            "force": {"type": "boolean", "default": False},
        },
    },
    output_schema={"type": "object"},
    examples=(),
)
def render_shot(
    shot: Shot,
    *,
    environment: Optional[Environment] = None,
    characters: tuple = (),
    style: str = "",
    as_video: bool = False,
    quality: str = "balanced",
    image_model_id: Optional[str] = None,
    image_to_video_model_id: Optional[str] = None,
    force: bool = False,
) -> dict:
    """Render a Shot as a still (default) or a short clip.

    Args:
        image_model_id: Override the image-gen model used for the storyboard
            still (defaults to ``pick_model(category="image", …)``).
        image_to_video_model_id: Override the image-to-video model used when
            ``as_video=True`` (e.g. ``"fal-ai/minimax/hailuo-02/pro/image-to-video"``).
    """
    h = shot_content_hash(shot, environment=environment) + ("-v" if as_video else "-i")
    cache_app = "falaw.render_shot"
    cache_args = {"hash": h, "quality": quality}

    # Under a terms context a composite hit cannot show which models made it, so
    # it is a miss: the per-call caches underneath are checked (falaw#110).
    if not force and current_terms_context() is None:
        hit = cache_get(cache_app, cache_args)
        if hit is not None:
            return {**hit, "cache_hit": True}

    parts = [shot.description or "shot", f"framing: {shot.framing}"]
    if environment is not None:
        parts.append(f"location: {environment.description}")
        if environment.time_of_day:
            parts.append(f"time: {environment.time_of_day}")
    for c in characters:
        if c.description:
            parts.append(f"{c.name}: {c.description}")
    if shot.camera:
        parts.append(f"camera: {shot.camera}")
    if style:
        parts.append(f"style: {style}")
    prompt = " | ".join(parts)

    img_model = image_model_id or pick_model(category="image", quality_tier=quality).id
    img_raw = cached_call_fal(
        img_model,
        image_arguments(known_record(img_model), prompt, "landscape_16_9", None),
        refresh=force,
    )
    img_result = parse_response(
        img_raw, application=img_model, arguments={"prompt": prompt}
    )
    if not img_result.first:
        raise RuntimeError(
            f"render_shot: image generation produced no asset for {shot.id!r}"
        )
    still_url = img_result.first.url

    if not as_video:
        manifest = {
            "url": still_url,
            "kind": "image",
            "hash": h,
            "shot_id": shot.id,
            "cache_hit": False,
        }
        cache_put(cache_app, cache_args, manifest, note=f"shot:{shot.id}")
        return manifest

    # image -> video
    i2v_model = (
        image_to_video_model_id
        or pick_model(category="image_to_video", quality_tier=quality).id
    )
    i2v_args: dict = {"image_url": still_url}
    if shot.camera:
        i2v_args["prompt"] = shot.camera
    i2v_raw = cached_call_fal(i2v_model, i2v_args, refresh=force)
    i2v_result = parse_response(i2v_raw, application=i2v_model, arguments=i2v_args)
    video_url = i2v_result.first.url if i2v_result.first else ""
    manifest = {
        "url": video_url or still_url,
        "kind": "video",
        "still_url": still_url,
        "video_url": video_url,
        "hash": h,
        "shot_id": shot.id,
        "cache_hit": False,
    }
    cache_put(cache_app, cache_args, manifest, note=f"shot:{shot.id}")
    return manifest


# --- whole-scene orchestration --------------------------------------------


@register_tool(
    name="render_scene",
    description=(
        "Render an entire Scene: every Shot + every Beat, with caching "
        "so unchanged units are no-ops. Returns a manifest dict with "
        "per-beat and per-shot results, plus aggregate counts. Pass "
        "`force=True` to bypass the cache."
    ),
    tags=("render", "scene"),
    input_schema={
        "type": "object",
        "required": ["scene"],
        "properties": {
            "scene": {"type": "object", "description": "falaw.Scene"},
            "tts_quality": {"type": "string", "default": "balanced"},
            "lipsync_quality": {"type": "string", "default": "high"},
            "shot_quality": {"type": "string", "default": "balanced"},
            "shots_as_video": {"type": "boolean", "default": False},
            "force": {"type": "boolean", "default": False},
        },
    },
    output_schema={"type": "object"},
    examples=(),
)
def render_scene(
    scene: Scene,
    *,
    tts_quality: str = "balanced",
    lipsync_quality: str = "high",
    shot_quality: str = "balanced",
    shots_as_video: bool = False,
    force: bool = False,
    concurrency: int = 1,
) -> dict:
    """Render every shot and beat. Returns a manifest dict.

    ``concurrency`` controls how many shots/beats run in parallel
    against fal. The work is HTTP-bound, so a thread pool is enough.
    Default ``1`` preserves serial behavior. Use
    :func:`iter_render_scene` instead if you want results yielded as
    each unit completes (for live UI updates).
    """
    iterator = iter_render_scene(
        scene,
        tts_quality=tts_quality,
        lipsync_quality=lipsync_quality,
        shot_quality=shot_quality,
        shots_as_video=shots_as_video,
        force=force,
        concurrency=concurrency,
    )
    shot_results: list[dict] = []
    beat_results: list[dict] = []
    for kind, result in iterator:
        if kind == "shot":
            shot_results.append(result)
        else:
            beat_results.append(result)

    cache_hits = sum(
        int(r.get("cache_hit", False)) for r in shot_results + beat_results
    )
    return {
        "title": scene.title,
        "style": scene.style,
        "shot_count": len(shot_results),
        "beat_count": len(beat_results),
        "cache_hits": cache_hits,
        "shots": shot_results,
        "beats": beat_results,
    }


def iter_render_scene(
    scene: Scene,
    *,
    tts_quality: str = "balanced",
    lipsync_quality: str = "high",
    shot_quality: str = "balanced",
    shots_as_video: bool = False,
    force: bool = False,
    concurrency: int = 1,
):
    """Yield ``(kind, result)`` pairs as each shot/beat finishes.

    ``kind`` ∈ ``{"shot", "beat"}``. With ``concurrency=1`` results
    arrive in submission order (shots before beats). With
    ``concurrency > 1`` they arrive in completion order (use the
    ``"shot_id"`` / ``"beat_id"`` keys to re-key by identity).

    Cache hits are immediate: a fully-cached scene yields all results
    in close succession even at ``concurrency=1``.
    """
    chars_by_name = {c.name: c for c in scene.characters}
    envs_by_name = {e.name: e for e in scene.environments}

    def _one_shot(shot: Shot) -> dict:
        env = envs_by_name.get(shot.environment)
        chars = tuple(
            chars_by_name[name] for name in shot.characters if name in chars_by_name
        )
        return render_shot(
            shot,
            environment=env,
            characters=chars,
            style=scene.style,
            as_video=shots_as_video,
            quality=shot_quality,
            force=force,
        )

    def _one_beat(beat: Beat) -> dict:
        speaker = chars_by_name.get(beat.speaker)
        if speaker is None:
            return {
                "beat_id": beat.id,
                "skipped": "no character",
                "speaker": beat.speaker,
                "cache_hit": False,
            }
        return render_beat(
            beat,
            speaker,
            tts_quality=tts_quality,
            lipsync_quality=lipsync_quality,
            force=force,
        )

    if concurrency <= 1:
        for shot in scene.shots:
            yield "shot", _one_shot(shot)
        for beat in scene.beats:
            yield "beat", _one_beat(beat)
        return

    from concurrent.futures import ThreadPoolExecutor, as_completed
    from contextvars import copy_context

    # A pool worker does not inherit the submitting thread's context, so a BYO
    # key bound with ``using_fal_credentials`` would vanish and the calls would
    # bill the operator's env key. Run each task in its own copy of the context
    # (one copy per task: a Context cannot be entered by two threads at once).
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = {}
        for shot in scene.shots:
            fut = ex.submit(copy_context().run, _one_shot, shot)
            futures[fut] = "shot"
        for beat in scene.beats:
            fut = ex.submit(copy_context().run, _one_beat, beat)
            futures[fut] = "beat"
        for fut in as_completed(futures):
            yield futures[fut], fut.result()


def manifest_path_for(scene: Scene, *, dir: Optional[str] = None) -> str:
    """Return where `render_scene`'s manifest would be saved by default."""
    base = dir or os.path.join(_cache_dir(), "scenes")
    safe = scene.title.replace(" ", "_").replace("/", "_") or "scene"
    return os.path.join(base, f"{safe}.manifest.json")
