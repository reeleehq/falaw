"""Audio operations: text-to-speech and friends."""

from __future__ import annotations

from typing import Optional

from ..core import call_fal
from ..registry import pick_model, register_tool
from ..results import Result, parse_response


@register_tool(
    name="text_to_speech",
    description=(
        "Synthesize speech from text. Picks a TTS model by quality tier; "
        "pass `voice` and `extra` for model-specific knobs. Returns a "
        "falaw.Result whose .first asset is the audio URL."
    ),
    tags=("audio", "tts", "generate"),
    input_schema={
        "type": "object",
        "required": ["text"],
        "properties": {
            "text": {"type": "string"},
            "quality": {
                "type": "string",
                "enum": ["fast", "balanced", "high", "ultra"],
                "default": "balanced",
            },
            "voice": {
                "type": "string",
                "description": "Voice identifier; format depends on the model.",
            },
            "model_id": {"type": "string"},
            "extra": {"type": "object"},
        },
    },
    output_schema={"type": "object", "description": "falaw.Result"},
    examples=(
        {"text": "Hello world", "quality": "balanced"},
        {"text": "Bonjour le monde", "quality": "high", "voice": "fr-FR-female-1"},
    ),
)
def text_to_speech(
    text: str,
    *,
    quality: str = "balanced",
    voice: Optional[str] = None,
    model_id: Optional[str] = None,
    extra: Optional[dict] = None,
) -> Result:
    """Synthesize speech. ``voice`` semantics are model-specific."""
    model = model_id or pick_model(category="tts", quality_tier=quality).id
    arguments: dict = {"text": text}
    if voice:
        arguments["voice"] = voice
    arguments.update(extra or {})
    raw = call_fal(model, arguments)
    return parse_response(raw, application=model, arguments=arguments)


@register_tool(
    name="voice_clone",
    description=(
        "Synthesize speech in a cloned voice. Provide a `reference_audio_url` "
        "(a few seconds of the target voice) and the text to speak. Returns "
        "a falaw.Result whose .first asset is the cloned-voice audio URL."
    ),
    tags=("audio", "voice_clone", "generate"),
    input_schema={
        "type": "object",
        "required": ["reference_audio_url", "text"],
        "properties": {
            "reference_audio_url": {"type": "string"},
            "text": {"type": "string"},
            "model_id": {"type": "string"},
            "extra": {"type": "object"},
        },
    },
    output_schema={"type": "object", "description": "falaw.Result"},
    examples=(
        {
            "reference_audio_url": "https://example.com/me.wav",
            "text": "Hello, this is in my voice.",
        },
    ),
)
def voice_clone(
    reference_audio_url: str,
    text: str,
    *,
    model_id: Optional[str] = None,
    extra: Optional[dict] = None,
) -> Result:
    """Generate speech in a cloned voice."""
    model = model_id or pick_model(category="voice_clone", quality_tier="high").id
    arguments = {
        "reference_audio_url": reference_audio_url,
        "text": text,
        **(extra or {}),
    }
    raw = call_fal(model, arguments)
    return parse_response(raw, application=model, arguments=arguments)


@register_tool(
    name="generate_audio",
    description=(
        "Generate ambient sound, an SFX bed, or music from a text prompt — "
        "the 'city night' / 'rain on a tin roof' bed a cut needs, without "
        "leaving the editor. `kind` picks the model family: 'ambient'/'sfx' "
        "→ Stable Audio 3 SFX (commercially usable), 'music' → Lyria 2. Returns a falaw.Result "
        "whose .first asset is the audio URL."
    ),
    tags=("audio", "ambient", "music", "generate"),
    input_schema={
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "kind": {
                "type": "string",
                "enum": ["ambient", "sfx", "music"],
                "default": "ambient",
            },
            "duration_s": {
                "type": "number",
                "description": "Target seconds (models that take a duration).",
            },
            "model_id": {"type": "string"},
            "extra": {"type": "object"},
        },
    },
    output_schema={"type": "object", "description": "falaw.Result"},
    examples=(
        {"prompt": "city street at night, distant traffic", "kind": "ambient"},
        {"prompt": "gentle acoustic guitar, hopeful", "kind": "music"},
    ),
)
def generate_audio(
    prompt: str,
    *,
    kind: str = "ambient",
    duration_s: Optional[float] = None,
    model_id: Optional[str] = None,
    extra: Optional[dict] = None,
) -> Result:
    """Generate ambient/SFX/music from a prompt. Argument shape mirrors
    :func:`falaw.plan_generate_audio` exactly, so planned and eager calls
    with identical inputs collapse to the same cache entry."""
    from ._plan import resolve_generate_audio

    model, arguments, _ = resolve_generate_audio(
        prompt, kind=kind, duration_s=duration_s, model_id=model_id, extra=extra
    )
    raw = call_fal(model, arguments)
    return parse_response(raw, application=model, arguments=arguments)
