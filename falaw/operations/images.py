"""Image-generation and image-manipulation operations."""

from __future__ import annotations

from typing import Optional

from ..core import call_fal
from ..registry import pick_model, register_tool
from ..results import Result, parse_response
from ..upload import localize_paths, resolve_local_files
from ._image_args import (
    CONTROL_CATEGORY,
    EASYCONTROL_SPATIAL_MODES,
    controlled_image_arguments,
    image_arguments,
    known_record,
)


@register_tool(
    name="generate_image",
    description=(
        "Generate an image from a text prompt. Picks a sensible FLUX model "
        "based on the requested quality tier ('fast', 'balanced', 'high', "
        "'ultra'). Returns a falaw.Result whose .first asset has a URL you "
        "can .download(to=...)."
    ),
    tags=("image", "generate"),
    input_schema={
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "quality": {
                "type": "string",
                "enum": ["fast", "balanced", "high", "ultra"],
                "default": "balanced",
            },
            "image_size": {"type": "string", "default": "landscape_4_3"},
            "model_id": {"type": "string"},
            "extra": {"type": "object"},
        },
    },
    output_schema={"type": "object", "description": "falaw.Result"},
    examples=(
        {"prompt": "A red panda eating bamboo", "quality": "fast"},
        {"prompt": "Cinematic portrait, 35mm film", "quality": "ultra"},
    ),
)
def generate_image(
    prompt: str,
    *,
    quality: str = "balanced",
    image_size: str = "landscape_4_3",
    model_id: Optional[str] = None,
    extra: Optional[dict] = None,
) -> Result:
    """Generate an image from a text prompt.

    ``image_size`` is a fal preset (``landscape_16_9`` …); models that size by
    ``aspect_ratio`` (``nano-banana-pro``) get the equivalent ratio, with
    ``extra={"resolution": "2K"}`` for the pixel tier. A prompt over the
    model's cap raises :class:`falaw.FalPromptTooLong` before any call. Check
    :func:`falaw.model_params` for enums whose default may not be what you
    want (Recraft ``style`` defaults to photoreal).
    """
    model = model_id or pick_model(category="image", quality_tier=quality).id
    arguments = image_arguments(known_record(model), prompt, image_size, extra)
    raw = call_fal(model, arguments)
    return parse_response(raw, application=model, arguments=arguments)


@register_tool(
    name="edit_image",
    description=(
        "Edit an image using a natural-language instruction. Picks a FLUX "
        "Kontext / SeedEdit model by quality tier. Returns a falaw.Result "
        "with the edited image."
    ),
    tags=("image", "edit"),
    input_schema={
        "type": "object",
        "required": ["image_url", "prompt"],
        "properties": {
            "image_url": {"type": "string"},
            "prompt": {"type": "string"},
            "quality": {
                "type": "string",
                "enum": ["fast", "balanced", "high", "ultra"],
                "default": "balanced",
            },
            "model_id": {"type": "string"},
            "extra": {"type": "object"},
        },
    },
    output_schema={"type": "object", "description": "falaw.Result"},
    examples=(
        {"image_url": "https://...", "prompt": "make the sky orange"},
        {
            "image_url": "https://...",
            "prompt": "remove the person on the left",
            "quality": "ultra",
        },
    ),
)
def edit_image(
    image_url: str,
    prompt: str,
    *,
    quality: str = "balanced",
    model_id: Optional[str] = None,
    extra: Optional[dict] = None,
) -> Result:
    """Edit an image with a natural-language instruction."""
    model = model_id or pick_model(category="image_edit", quality_tier=quality).id
    arguments = {"image_url": image_url, "prompt": prompt, **(extra or {})}
    raw = call_fal(model, arguments)
    return parse_response(raw, application=model, arguments=arguments)


@register_tool(
    name="generate_image_with_refs",
    description=(
        "Generate a NEW image from a text prompt while conditioning on one or "
        "more reference images, so a recurring subject (a character's face, a "
        "location, a prop) stays consistent across renders. Unlike "
        "generate_image (pure text-to-image — reference images have no effect), "
        "this routes to a reference-capable image model (Flux Kontext / OmniGen "
        "/ SeedEdit) that actually ingests the references. The first reference "
        "anchors the primary subject; all references are also passed together. "
        "Returns a falaw.Result with the generated image."
    ),
    tags=("image", "generate", "reference", "consistency"),
    input_schema={
        "type": "object",
        "required": ["prompt", "reference_image_urls"],
        "properties": {
            "prompt": {"type": "string"},
            "reference_image_urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "One or more reference image URLs. The first anchors the "
                    "primary subject; subsequent ones add secondary references "
                    "(e.g. environment, second character)."
                ),
            },
            "quality": {
                "type": "string",
                "enum": ["fast", "balanced", "high", "ultra"],
                "default": "balanced",
            },
            "model_id": {"type": "string"},
            "extra": {"type": "object"},
        },
    },
    output_schema={"type": "object", "description": "falaw.Result"},
    examples=(
        {
            "prompt": "Alex looks up at the bell, candlelight on his face",
            "reference_image_urls": ["https://x/alex-modelsheet.png"],
            "quality": "balanced",
        },
    ),
)
def generate_image_with_refs(
    prompt: str,
    reference_image_urls: list[str],
    *,
    quality: str = "balanced",
    model_id: Optional[str] = None,
    extra: Optional[dict] = None,
) -> Result:
    """Generate a new image conditioned on one or more reference images.

    The missing twin of :func:`generate_image`: text-to-image models silently
    ignore reference images, so callers wanting a recurring subject to stay
    consistent (a character's face across storyboard panels) need a model that
    actually ingests references. This routes to the ``image_edit`` category
    (Flux Kontext et al.) and threads the references as ``image_url`` (first)
    + ``image_urls`` (all) — the same wire shape image-edit models understand.

    Pass ``model_id`` to override the picked model.
    """
    refs = [u for u in (reference_image_urls or []) if u]
    if not refs:
        raise ValueError(
            "generate_image_with_refs requires at least one reference URL; "
            "use generate_image for pure text-to-image."
        )
    model = model_id or pick_model(category="image_edit", quality_tier=quality).id
    arguments = _refs_arguments(prompt, refs, extra)
    raw = call_fal(model, arguments)
    return parse_response(raw, application=model, arguments=arguments)


@register_tool(
    name="generate_image_with_control",
    description=(
        "Generate an image whose layout follows a guide image's STRUCTURE: its "
        "edges (canny), depth, pose, HED sketch or segmentation. Use it to make "
        "a subject land where a rig, a sketch or a reference photo puts it "
        "(hands on a wheel at the rig's shoulders) instead of where the model "
        "guesses. Routes to a structural-conditioning model (FLUX.1 [dev] "
        "General with EasyControl). Returns a falaw.Result."
    ),
    tags=("image", "generate", "control", "structure"),
    input_schema={
        "type": "object",
        "required": ["prompt", "control"],
        "properties": {
            "prompt": {"type": "string"},
            "control": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["mode", "image"],
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": list(EASYCONTROL_SPATIAL_MODES),
                        },
                        "image": {
                            "type": "string",
                            "description": "URL of the guide image.",
                        },
                        "scale": {"type": "number", "default": 1.0},
                    },
                },
            },
            "quality": {
                "type": "string",
                "enum": ["fast", "balanced", "high", "ultra"],
                "default": "balanced",
            },
            "image_size": {"type": "string", "default": "landscape_4_3"},
            "model_id": {"type": "string"},
            "extra": {"type": "object"},
        },
    },
    output_schema={"type": "object", "description": "falaw.Result"},
    examples=(
        {
            "prompt": "a driver's hands on a steering wheel, cel-shaded",
            "control": [
                {"mode": "pose", "image": "https://x/rig-pose.png", "scale": 0.7}
            ],
        },
    ),
)
def generate_image_with_control(
    prompt: str,
    control: list[dict],
    *,
    quality: str = "balanced",
    image_size: str = "landscape_4_3",
    model_id: Optional[str] = None,
    extra: Optional[dict] = None,
) -> Result:
    """Generate an image conditioned on a guide image's structure (falaw#140).

    ``control`` is ``[{"mode": "canny" | "depth" | "pose" | ..., "image": url,
    "scale": 0.6}]`` (``scale`` defaults to fal's 1.0). It is sent as fal's
    ``easycontrols``; ``controlnet_unions`` and the subject-style EasyControl
    methods pass through ``extra``. A local guide image (a ``pathlib.Path``) is
    uploaded with :func:`falaw.upload` (swap the transfer with
    :func:`falaw.using_uploader`) once the call is known to be well formed. Plan
    the call with :func:`falaw.plan_generate_image_with_control` instead to
    upload only on a cache miss and key the cache on the file's bytes.
    """
    model = model_id or pick_model(category=CONTROL_CATEGORY, quality_tier=quality).id
    arguments, local_files = localize_paths(
        controlled_image_arguments(
            known_record(model), prompt, image_size, control, extra
        )
    )
    arguments = resolve_local_files(arguments, local_files, mode="wire")
    raw = call_fal(model, arguments)
    return parse_response(raw, application=model, arguments=arguments)


def _refs_arguments(prompt: str, refs: list[str], extra: Optional[dict]) -> dict:
    """Build the argument dict for a reference-conditioned image call.

    Image-edit models disagree on the parameter name — some read ``image_url``
    (singular), others ``image_urls`` (plural). Passing both lets the receiving
    model use whichever it understands; ``image_url`` carries the primary
    (first) reference. Shared by the eager op and its ``plan_*`` sibling so an
    eager call and a planned call with identical inputs collapse to one cache
    entry.
    """
    return {
        "image_url": refs[0],
        "image_urls": list(refs),
        "prompt": prompt,
        **(extra or {}),
    }


@register_tool(
    name="composite_character_in_environment",
    description=(
        "Place a specific character into a specific environment as a single "
        "still image, preserving the character's identity. Uses an image-edit "
        "model that accepts multiple reference images (Flux Kontext, OmniGen v2, "
        "SeedEdit). The character image anchors identity; the environment image "
        "anchors location, lighting, and palette. Returns a falaw.Result with "
        "the composited still."
    ),
    tags=("image", "edit", "composite"),
    input_schema={
        "type": "object",
        "required": ["character_image_url", "environment_image_url"],
        "properties": {
            "character_image_url": {"type": "string"},
            "environment_image_url": {"type": "string"},
            "prompt": {
                "type": "string",
                "description": (
                    "Optional directorial addendum: framing, action, mood. "
                    "If omitted, a sensible default is used."
                ),
            },
            "quality": {
                "type": "string",
                "enum": ["fast", "balanced", "high", "ultra"],
                "default": "balanced",
            },
            "model_id": {"type": "string"},
            "extra": {"type": "object"},
        },
    },
    output_schema={"type": "object", "description": "falaw.Result"},
    examples=(
        {
            "character_image_url": "https://x/thor.png",
            "environment_image_url": "https://x/bell_tower.png",
            "prompt": "Thor stands in the bell tower, contemplative gaze, candlelight on his face",
            "quality": "high",
        },
    ),
)
def composite_character_in_environment(
    character_image_url: str,
    environment_image_url: str,
    *,
    prompt: str = "",
    quality: str = "balanced",
    model_id: Optional[str] = None,
    extra: Optional[dict] = None,
) -> Result:
    """Place a character into an environment as one composited still.

    The single most user-visible primitive missing from muvid (per
    interface_design_plan item E). With this, an agent can produce
    "Thor in a bell tower" — the character anchor for a downstream
    omnihuman lipsync — without manually compositing in an image editor.

    Defaults to ``fal-ai/flux-kontext/dev`` (image_edit category at
    balanced/high tier). Pass ``model_id`` to override
    (e.g. ``"fal-ai/flux-pro/kontext/max"`` for highest quality, or
    ``"fal-ai/bytedance/seededit/v3/edit-image"`` for SeedEdit).
    """
    model = model_id or pick_model(category="image_edit", quality_tier=quality).id

    if not prompt:
        prompt = (
            "Place the person from the first image into the scene from the "
            "second image. Preserve the person's identity exactly (face, hair, "
            "build, age, clothing). Match the environment's lighting, palette, "
            "and atmosphere. Photorealistic composition; the person looks like "
            "they belong there."
        )

    arguments = {
        # Multi-reference argument — Flux Kontext, OmniGen v2 accept
        # `image_urls` (plural). Some models use `image_url` for primary.
        # Pass both for compatibility; the receiving model will use what it
        # understands.
        "image_url": character_image_url,
        "image_urls": [character_image_url, environment_image_url],
        "prompt": prompt,
        **(extra or {}),
    }
    raw = call_fal(model, arguments)
    return parse_response(raw, application=model, arguments=arguments)


@register_tool(
    name="upscale_image",
    description=(
        "Upscale an image to higher resolution while preserving fidelity. "
        "Defaults to clarity-upscaler. Returns a falaw.Result with the "
        "upscaled image."
    ),
    tags=("image", "upscale"),
    input_schema={
        "type": "object",
        "required": ["image_url"],
        "properties": {
            "image_url": {"type": "string"},
            "scale": {"type": "number", "default": 2.0},
            "model_id": {"type": "string"},
            "extra": {"type": "object"},
        },
    },
    output_schema={"type": "object", "description": "falaw.Result"},
    examples=(
        {"image_url": "https://...", "scale": 2.0},
        {"image_url": "https://...", "scale": 4.0, "extra": {"creativity": 0.35}},
    ),
)
def upscale_image(
    image_url: str,
    *,
    scale: float = 2.0,
    model_id: Optional[str] = None,
    extra: Optional[dict] = None,
) -> Result:
    """Upscale an image."""
    model = model_id or pick_model(category="upscale", quality_tier="high").id
    arguments = {"image_url": image_url, "scale": scale, **(extra or {})}
    raw = call_fal(model, arguments)
    return parse_response(raw, application=model, arguments=arguments)


@register_tool(
    name="remove_background",
    description=(
        "Remove the background from an image, returning a transparent PNG. "
        "Defaults to BiRefNet v2 (quality='high') or Bria (quality='balanced'). "
        "Returns a falaw.Result."
    ),
    tags=("image", "background_removal"),
    input_schema={
        "type": "object",
        "required": ["image_url"],
        "properties": {
            "image_url": {"type": "string"},
            "quality": {
                "type": "string",
                "enum": ["balanced", "high"],
                "default": "high",
            },
            "model_id": {"type": "string"},
            "extra": {"type": "object"},
        },
    },
    output_schema={"type": "object", "description": "falaw.Result"},
    examples=({"image_url": "https://example.com/photo.jpg"},),
)
def remove_background(
    image_url: str,
    *,
    quality: str = "high",
    model_id: Optional[str] = None,
    extra: Optional[dict] = None,
) -> Result:
    """Remove the background from an image."""
    model = (
        model_id or pick_model(category="background_removal", quality_tier=quality).id
    )
    arguments = {"image_url": image_url, **(extra or {})}
    raw = call_fal(model, arguments)
    return parse_response(raw, application=model, arguments=arguments)
