"""Video-generation operations: text-to-video and image-to-video."""

from __future__ import annotations

from typing import Optional

from ..core import call_fal
from ..cost import video_call_arguments
from ..registry import get_model, pick_model, register_tool
from ..results import Result, parse_response


def _with_duration(
    model: str, arguments: dict, duration_s: Optional[float], extra: Optional[dict]
) -> tuple[str, dict]:
    """``(application, wire arguments)``, built exactly as the planners build
    them so a planned and an eager call with the same inputs share one cache
    entry: a catalogued alias resolves to its id, and ``duration_s`` is sent as
    the model spells it. Unlike planning, where ``duration_s`` may merely feed
    the estimate, an eager call that cannot send it raises: it would otherwise
    be silently ignored."""
    try:
        record = get_model(model)
    except KeyError:
        record = None
    if duration_s is not None and (
        record is None or "duration" not in record.param_specs
    ):
        raise ValueError(
            f"duration_s is only sent for models whose catalogue record lists a "
            f"'duration' parameter; {model!r} is not one — put its own spelling in extra."
        )
    if record is None:
        return model, {**arguments, **(extra or {})}
    return record.id, video_call_arguments(
        record, arguments, duration_s=duration_s, extra=extra
    )[0]


@register_tool(
    name="text_to_video",
    description=(
        "Generate a video from a text prompt. Picks a tier-appropriate "
        "model (Veo 3 for ultra, Seedance Pro for high). Use `extra` to "
        "pass through model-specific knobs like duration, aspect_ratio, "
        "negative_prompt."
    ),
    tags=("video", "text_to_video", "generate"),
    input_schema={
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "quality": {
                "type": "string",
                "enum": ["fast", "balanced", "high", "ultra"],
                "default": "high",
            },
            "duration_s": {
                "type": "number",
                "description": "Seconds; sent for models that list a 'duration' parameter (Seedance).",
            },
            "model_id": {"type": "string"},
            "extra": {"type": "object"},
        },
    },
    output_schema={"type": "object", "description": "falaw.Result"},
    examples=(
        {"prompt": "A drone shot over a misty pine forest at dawn"},
        {"prompt": "Macro: a single dewdrop on a spider web", "quality": "ultra"},
    ),
)
def text_to_video(
    prompt: str,
    *,
    quality: str = "high",
    duration_s: Optional[float] = None,
    model_id: Optional[str] = None,
    extra: Optional[dict] = None,
) -> Result:
    """Generate a video from a text prompt."""
    model = model_id or pick_model(category="text_to_video", quality_tier=quality).id
    model, arguments = _with_duration(model, {"prompt": prompt}, duration_s, extra)
    raw = call_fal(model, arguments)
    return parse_response(raw, application=model, arguments=arguments)


@register_tool(
    name="image_to_video",
    description=(
        "Animate a still image into a short video. Optional prompt steers "
        "the motion. Picks a tier-appropriate i2v model (Kling Master for "
        "ultra, Seedance for high, Hailuo for balanced)."
    ),
    tags=("video", "image_to_video", "generate"),
    input_schema={
        "type": "object",
        "required": ["image_url"],
        "properties": {
            "image_url": {"type": "string"},
            "prompt": {"type": "string"},
            "quality": {
                "type": "string",
                "enum": ["balanced", "high", "ultra"],
                "default": "high",
            },
            "duration_s": {
                "type": "number",
                "description": "Seconds; sent for models that list a 'duration' parameter (Seedance).",
            },
            "model_id": {"type": "string"},
            "extra": {"type": "object"},
        },
    },
    output_schema={"type": "object", "description": "falaw.Result"},
    examples=(
        {"image_url": "https://...", "prompt": "the camera slowly zooms in"},
        {"image_url": "https://...", "quality": "balanced"},
    ),
)
def image_to_video(
    image_url: str,
    prompt: str = "",
    *,
    quality: str = "high",
    duration_s: Optional[float] = None,
    model_id: Optional[str] = None,
    extra: Optional[dict] = None,
) -> Result:
    """Animate a still image into a video."""
    model = model_id or pick_model(category="image_to_video", quality_tier=quality).id
    base: dict = {"image_url": image_url}
    if prompt:
        base["prompt"] = prompt
    model, arguments = _with_duration(model, base, duration_s, extra)
    raw = call_fal(model, arguments)
    return parse_response(raw, application=model, arguments=arguments)
