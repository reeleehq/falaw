"""``plan_*`` siblings of the eager operations.

Every eager op in ``falaw.operations`` does the same dance:

1. Resolve a model id from ``(category, quality_tier)``.
2. Build the ``arguments`` dict.
3. Hand off to ``call_fal``.

The eager wrapper does all three. The ``plan_*`` sibling does steps 1 and 2,
then returns a :class:`falaw.plan.CallPlan` describing what *would* happen.
A planner can compose many ``plan_*`` results into a :class:`falaw.plan.Plan`,
inspect the cost, swap models, and only then call ``execute(plan)``.

The five ops covered here are the ones nw needs first:
``generate_image``, ``edit_image``, ``image_to_video``, ``animate_face``,
``lipsync``. Other ops can be ported later — the eager wrappers continue
to work in the meantime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

from ..cost import estimate_call_cost, video_call_arguments, video_price_quantities
from ..llm_rates import LlmRateTable, llm_ceiling_usd
from ..plan import CallPlan, CostBasis, make_call_plan
from ..registry import get_model, pick_model
from ._image_args import image_arguments
from ..reprice import catalogue_cost_basis, llm_cost_basis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_model_id_and_record(
    *, model_id: Optional[str], category: str, quality_tier: str
):
    """Mirror the eager-op model-resolution pattern; return ``(id, ModelRecord)``.

    Eager ops do ``model = model_id or pick_model(category, quality_tier).id``.
    For planning we need the full :class:`ModelRecord` (to read ``cost_estimate``
    and any future duration contracts), so this resolves both at once.
    """
    if model_id:
        # Allow alias resolution via get_model.
        record = get_model(model_id)
        return record.id, record
    record = pick_model(category=category, quality_tier=quality_tier)
    return record.id, record


def _catalogue_price(
    record,
    *,
    seconds: Optional[float] = None,
    megapixels: Optional[float] = None,
    tokens: Optional[int] = None,
) -> tuple[Optional[float], CostBasis]:
    """``(estimated_cost_usd, cost_basis)`` for a catalogue-priced call.

    Both come out of one call site on purpose (falaw#60): the basis is the
    recipe for reproducing the figure, so computing them apart is how the two
    drift and a re-quote silently stops matching the quote it replaces. Hints
    left ``None`` are dropped rather than recorded as ``null`` — absent is what
    :func:`estimate_call_cost` actually saw, and what makes a quantity-priced
    record unpriceable.
    """
    supplied = {
        k: v
        for k, v in (
            ("seconds", seconds),
            ("megapixels", megapixels),
            ("tokens", tokens),
        )
        if v is not None
    }
    return (
        estimate_call_cost(record, count=1, **supplied),
        catalogue_cost_basis(record.id, **supplied),
    )


# ---------------------------------------------------------------------------
# generate_image
# ---------------------------------------------------------------------------


def plan_generate_image(
    prompt: str,
    *,
    quality: str = "balanced",
    image_size: str = "landscape_4_3",
    model_id: Optional[str] = None,
    extra: Optional[dict] = None,
    metadata: Optional[dict] = None,
    consult_cache: bool = True,
) -> CallPlan:
    """Plan a :func:`falaw.generate_image` call without executing it."""
    application, record = _resolve_model_id_and_record(
        model_id=model_id, category="image", quality_tier=quality
    )
    arguments = image_arguments(record, prompt, image_size, extra)
    cost, basis = _catalogue_price(record)
    return make_call_plan(
        tool="generate_image",
        application=application,
        arguments=arguments,
        output_kind="image",
        estimated_cost_usd=cost,
        metadata=metadata,
        consult_cache=consult_cache,
        cost_basis=basis,
    )


# ---------------------------------------------------------------------------
# edit_image
# ---------------------------------------------------------------------------


def plan_edit_image(
    image_url: str,
    prompt: str,
    *,
    quality: str = "balanced",
    model_id: Optional[str] = None,
    extra: Optional[dict] = None,
    metadata: Optional[dict] = None,
    consult_cache: bool = True,
) -> CallPlan:
    """Plan a :func:`falaw.edit_image` call (Flux Kontext / SeedEdit / OmniGen)."""
    application, record = _resolve_model_id_and_record(
        model_id=model_id, category="image_edit", quality_tier=quality
    )
    arguments = {"image_url": image_url, "prompt": prompt, **(extra or {})}
    cost, basis = _catalogue_price(record)
    return make_call_plan(
        tool="edit_image",
        application=application,
        arguments=arguments,
        output_kind="image",
        estimated_cost_usd=cost,
        metadata=metadata,
        consult_cache=consult_cache,
        cost_basis=basis,
    )


# ---------------------------------------------------------------------------
# generate_image_with_refs (reference-conditioned image generation)
# ---------------------------------------------------------------------------


def plan_generate_image_with_refs(
    prompt: str,
    reference_image_urls: list[str],
    *,
    quality: str = "balanced",
    model_id: Optional[str] = None,
    extra: Optional[dict] = None,
    metadata: Optional[dict] = None,
    consult_cache: bool = True,
) -> CallPlan:
    """Plan a :func:`falaw.generate_image_with_refs` call.

    The planning sibling of the eager op: text-to-image models ignore
    reference images, so a caller wanting a recurring subject to stay
    consistent must route to a reference-capable model. This picks the
    ``image_edit`` category (Flux Kontext et al.) and threads the references
    as ``image_url`` (first) + ``image_urls`` (all), the same wire shape the
    eager op uses — so a planned and an eager call with identical inputs
    collapse to one cache entry.
    """
    from .images import _refs_arguments

    refs = [u for u in (reference_image_urls or []) if u]
    if not refs:
        raise ValueError(
            "plan_generate_image_with_refs requires at least one reference "
            "URL; use plan_generate_image for pure text-to-image."
        )
    application, record = _resolve_model_id_and_record(
        model_id=model_id, category="image_edit", quality_tier=quality
    )
    arguments = _refs_arguments(prompt, refs, extra)
    cost, basis = _catalogue_price(record)
    return make_call_plan(
        tool="generate_image_with_refs",
        application=application,
        arguments=arguments,
        output_kind="image",
        estimated_cost_usd=cost,
        metadata=metadata,
        consult_cache=consult_cache,
        cost_basis=basis,
    )


# ---------------------------------------------------------------------------
# composite_character_in_environment (multi-reference image edit)
# ---------------------------------------------------------------------------


_DEFAULT_COMPOSITE_PROMPT = (
    "Place the person from the first image into the scene from the second image. "
    "Preserve the person's identity exactly (face, hair, build, age, clothing). "
    "Match the environment's lighting, palette, and atmosphere. Photorealistic "
    "composition; the person looks like they belong there."
)


def plan_composite_character_in_environment(
    character_image_url: str,
    environment_image_url: str,
    *,
    prompt: str = "",
    quality: str = "balanced",
    model_id: Optional[str] = None,
    extra: Optional[dict] = None,
    metadata: Optional[dict] = None,
    consult_cache: bool = True,
) -> CallPlan:
    """Plan a :func:`falaw.composite_character_in_environment` call.

    The character image anchors identity; the environment image anchors
    location, lighting, palette. The default model is Flux Kontext dev.
    """
    application, record = _resolve_model_id_and_record(
        model_id=model_id, category="image_edit", quality_tier=quality
    )
    arguments: dict = {
        "image_url": character_image_url,
        "image_urls": [character_image_url, environment_image_url],
        "prompt": prompt or _DEFAULT_COMPOSITE_PROMPT,
        **(extra or {}),
    }
    cost, basis = _catalogue_price(record)
    return make_call_plan(
        tool="composite_character_in_environment",
        application=application,
        arguments=arguments,
        output_kind="image",
        estimated_cost_usd=cost,
        metadata=metadata,
        consult_cache=consult_cache,
        cost_basis=basis,
    )


# ---------------------------------------------------------------------------
# image_to_video
# ---------------------------------------------------------------------------


def _plan_video(
    tool: str,
    category: str,
    arguments: dict,
    *,
    quality: str,
    model_id: Optional[str],
    duration_s: Optional[float],
    extra: Optional[dict],
    metadata: Optional[dict],
    consult_cache: bool,
) -> CallPlan:
    """The planning body shared by the video verbs (see
    :func:`video_call_arguments` for the duration rules)."""
    application, record = _resolve_model_id_and_record(
        model_id=model_id, category=category, quality_tier=quality
    )
    arguments, seconds = video_call_arguments(
        record, arguments, duration_s=duration_s, extra=extra
    )
    cost, basis = _catalogue_price(
        record,
        **video_price_quantities(
            record,
            seconds=seconds,
            resolution=arguments.get("resolution"),
            aspect_ratio=arguments.get("aspect_ratio"),
        ),
    )
    return make_call_plan(
        tool=tool,
        application=application,
        arguments=arguments,
        output_kind="video",
        estimated_cost_usd=cost,
        metadata=metadata,
        consult_cache=consult_cache,
        cost_basis=basis,
    )


def plan_image_to_video(
    image_url: str,
    prompt: str = "",
    *,
    quality: str = "high",
    model_id: Optional[str] = None,
    duration_s: Optional[float] = None,
    extra: Optional[dict] = None,
    metadata: Optional[dict] = None,
    consult_cache: bool = True,
) -> CallPlan:
    """Plan a :func:`falaw.image_to_video` call.

    ``duration_s`` is used for cost estimation (``per_second`` and
    ``per_token`` models); it reaches fal only for models whose catalogue
    record lists a ``duration`` parameter (see :func:`_plan_video`), else only
    if the caller puts it in ``extra``.
    """
    arguments: dict = {"image_url": image_url}
    if prompt:
        arguments["prompt"] = prompt
    return _plan_video(
        "image_to_video",
        "image_to_video",
        arguments,
        quality=quality,
        model_id=model_id,
        duration_s=duration_s,
        extra=extra,
        metadata=metadata,
        consult_cache=consult_cache,
    )


def plan_text_to_video(
    prompt: str,
    *,
    quality: str = "high",
    model_id: Optional[str] = None,
    duration_s: Optional[float] = None,
    extra: Optional[dict] = None,
    metadata: Optional[dict] = None,
    consult_cache: bool = True,
) -> CallPlan:
    """Plan a :func:`falaw.text_to_video` call — the sibling of
    :func:`plan_image_to_video` (same duration and cost rules)."""
    return _plan_video(
        "text_to_video",
        "text_to_video",
        {"prompt": prompt},
        quality=quality,
        model_id=model_id,
        duration_s=duration_s,
        extra=extra,
        metadata=metadata,
        consult_cache=consult_cache,
    )


def plan_reference_to_video(
    prompt: str,
    *,
    image_urls: Sequence[str] = (),
    video_urls: Sequence[str] = (),
    audio_urls: Sequence[str] = (),
    quality: str = "high",
    model_id: Optional[str] = None,
    duration_s: Optional[float] = None,
    extra: Optional[dict] = None,
    metadata: Optional[dict] = None,
    consult_cache: bool = True,
) -> CallPlan:
    """Plan a reference-to-video call (Seedance 2.0): a prompt steered by
    reference images, videos and audio.

    The counts are checked against the model's recorded limits
    (``model_constraints(id)["max_references"]``) by :func:`make_call_plan`, while
    planning is free, whatever route (``extra`` included) they arrive by. The
    quote is the standard rate, a ceiling: fal bills about 0.6x when video
    references are supplied.
    """
    refs = {
        "image_urls": image_urls,
        "video_urls": video_urls,
        "audio_urls": audio_urls,
    }
    for name, urls in refs.items():
        if isinstance(urls, str):
            raise TypeError(f"{name} must be a list of URLs, not one string")
    wanted = {name: list(urls) for name, urls in refs.items() if urls}
    return _plan_video(
        "reference_to_video",
        "reference_to_video",
        {"prompt": prompt, **wanted},
        quality=quality,
        model_id=model_id,
        duration_s=duration_s,
        extra=extra,
        metadata=metadata,
        consult_cache=consult_cache,
    )


# ---------------------------------------------------------------------------
# animate_face (avatar from image + audio)
# ---------------------------------------------------------------------------


def plan_animate_face(
    image_url: str,
    audio_url: str,
    *,
    prompt: str = "",
    quality: str = "balanced",
    model_id: Optional[str] = None,
    duration_s: Optional[float] = None,
    extra: Optional[dict] = None,
    metadata: Optional[dict] = None,
    consult_cache: bool = True,
) -> CallPlan:
    """Plan a :func:`falaw.animate_face` call (image + audio → talking video).

    Note: the default avatar model is known to hang. For production-grade
    behavior, callers should pass ``model_id="fal-ai/bytedance/omnihuman/v1.5"``
    or set ``quality="high"`` (which picks omnihuman).
    """
    application, record = _resolve_model_id_and_record(
        model_id=model_id, category="avatar", quality_tier=quality
    )
    arguments: dict = {"image_url": image_url, "audio_url": audio_url}
    if prompt:
        arguments["prompt"] = prompt
    elif "ai-avatar" in application:
        # ai-avatar requires non-empty prompt by contract.
        arguments["prompt"] = "natural delivery"
    if extra:
        arguments.update(extra)
    cost, basis = _catalogue_price(record, seconds=duration_s)
    return make_call_plan(
        tool="animate_face",
        application=application,
        arguments=arguments,
        output_kind="video",
        estimated_cost_usd=cost,
        metadata=metadata,
        consult_cache=consult_cache,
        cost_basis=basis,
    )


# ---------------------------------------------------------------------------
# lipsync (re-sync existing video to new audio)
# ---------------------------------------------------------------------------


def plan_lipsync(
    video_url: str,
    audio_url: str,
    *,
    quality: str = "high",
    model_id: Optional[str] = None,
    duration_s: Optional[float] = None,
    extra: Optional[dict] = None,
    metadata: Optional[dict] = None,
    consult_cache: bool = True,
) -> CallPlan:
    """Plan a :func:`falaw.lipsync` call (existing video + new audio → re-synced video)."""
    application, record = _resolve_model_id_and_record(
        model_id=model_id, category="lipsync", quality_tier=quality
    )
    arguments = {"video_url": video_url, "audio_url": audio_url, **(extra or {})}
    cost, basis = _catalogue_price(record, seconds=duration_s)
    return make_call_plan(
        tool="lipsync",
        application=application,
        arguments=arguments,
        output_kind="video",
        estimated_cost_usd=cost,
        metadata=metadata,
        consult_cache=consult_cache,
        cost_basis=basis,
    )


# ---------------------------------------------------------------------------
# text_to_speech (TTS: text → audio Artifact)
# ---------------------------------------------------------------------------


def plan_text_to_speech(
    text: str,
    *,
    quality: str = "balanced",
    voice: Optional[str] = None,
    model_id: Optional[str] = None,
    duration_s: Optional[float] = None,
    tokens: Optional[int] = None,
    extra: Optional[dict] = None,
    metadata: Optional[dict] = None,
    consult_cache: bool = True,
) -> CallPlan:
    """Plan a :func:`falaw.text_to_speech` call (text → audio Artifact).

    Mirrors the eager :func:`falaw.text_to_speech` signature so a planned
    call and an eager call with identical inputs collapse to the same
    cache entry. ``voice`` semantics are model-specific.

    ``duration_s`` and ``tokens`` are *optional* hints used only by the
    cost estimator — they never enter ``arguments``, so they cannot move
    the cache identity. ``duration_s`` prices ``per_second`` records (the
    produced audio's actual duration comes back on the materialized
    Artifact); ``tokens`` prices ``per_token`` records. For
    character-billed TTS (ElevenLabs — its registry record says so
    explicitly) pass ``tokens=len(text)``. Without the matching hint a
    quantity-priced record stays ``estimated_cost_usd=None`` — unknown,
    never free, which forces approval downstream.
    """
    application, record = _resolve_model_id_and_record(
        model_id=model_id, category="tts", quality_tier=quality
    )
    arguments: dict = {"text": text}
    if voice:
        arguments["voice"] = voice
    if extra:
        arguments.update(extra)
    cost, basis = _catalogue_price(record, seconds=duration_s, tokens=tokens)
    return make_call_plan(
        tool="text_to_speech",
        application=application,
        arguments=arguments,
        output_kind="audio",
        estimated_cost_usd=cost,
        metadata=metadata,
        consult_cache=consult_cache,
        cost_basis=basis,
    )


#: The prompt-driven generative-audio defaults per kind. Deliberately EXPLICIT
#: model ids rather than ``pick_model(category=...)``: the ``music`` category's
#: first balanced entry is DiffRhythm, which generates songs from LYRICS — a
#: bare prompt would make a structurally valid call that runs, bills, and
#: produces nothing the caller asked for (the exact failure class working
#: rule 10 names). Overridable per call via ``model_id``.
#:
#: SFX and ambient default to Stable Audio 3 small-SFX, not MMAudio: MMAudio's
#: weights are CC BY-NC 4.0 whatever fal's ``license_type`` says, so sound it
#: made may not be used commercially (falaw#88). MMAudio stays reachable via
#: ``model_id=``.
GENERATE_AUDIO_DEFAULTS = {
    "ambient": "fal-ai/stable-audio-3/small/sfx/text-to-audio",
    "sfx": "fal-ai/stable-audio-3/small/sfx/text-to-audio",
    "music": "fal-ai/lyria2",
}


@dataclass(frozen=True)
class _AudioArgs:
    """How one audio endpoint spells its inputs (they differ per vendor)."""

    prompt: str = "prompt"
    duration: Optional[str] = None  # None: the endpoint takes no duration
    cast: Callable[[float], Any] = float
    default_duration_s: Optional[float] = None
    """Used when the caller gives none. fal's own default (often 30 s) is long
    for an effect and makes a per-second quote unknowable."""
    defaults: Mapping[str, Any] = field(default_factory=dict)
    """Arguments pinned so the output matches the recorded prompt and quote."""
    samples: Optional[str] = None
    """Argument counting the samples billed per call, when the endpoint bills
    per sample (Mirelo returns two unless told otherwise)."""


def _whole_seconds(seconds: float) -> int:
    return max(1, int(round(float(seconds))))


#: Stable Audio 3 expands prompts by default, so the audio would no longer
#: match the prompt falaw caches and journals.
_SA3 = dict(
    duration="duration",
    default_duration_s=10,
    defaults={"enable_prompt_expansion": False},
)

#: Endpoints whose input names or duration type differ from the default
#: (``prompt``, no duration). An id absent here takes ``prompt`` only.
#: The eventual home of this is an argument-spelling field on ``ModelRecord``
#: (falaw#16).
_AUDIO_ARGS = {
    "fal-ai/mmaudio-v2/text-to-audio": _AudioArgs(
        duration="duration", cast=_whole_seconds, default_duration_s=8
    ),
    "fal-ai/stable-audio-3/small/sfx/text-to-audio": _AudioArgs(**_SA3),
    "fal-ai/stable-audio-3/medium/text-to-audio": _AudioArgs(**_SA3),
    "mirelo-ai/sfx2.0/text-to-audio": _AudioArgs(
        duration="duration",
        default_duration_s=10,
        defaults={"num_samples": 1},
        samples="num_samples",
    ),
    "sonilo/v1.1/text-to-sound-effects": _AudioArgs(
        duration="duration", default_duration_s=8
    ),
    "fal-ai/elevenlabs/sound-effects/v2": _AudioArgs(
        prompt="text", duration="duration_seconds", default_duration_s=8
    ),
}


def resolve_generate_audio(
    prompt: str,
    *,
    kind: str = "ambient",
    duration_s: Optional[float] = None,
    model_id: Optional[str] = None,
    extra: Optional[dict] = None,
) -> tuple[str, dict, Optional[float]]:
    """``(application, arguments, billed_seconds)`` for a generate_audio call.

    The one place planned and eager :func:`falaw.generate_audio` agree on the
    model and the argument shape (so identical inputs share a cache entry).
    ``duration_s`` is forwarded only to endpoints that take one; ``billed_seconds``
    is what the quote is computed on (seconds x samples for per-sample endpoints).
    """
    if kind not in GENERATE_AUDIO_DEFAULTS:
        raise ValueError(
            f"unknown kind {kind!r}; expected one of {sorted(GENERATE_AUDIO_DEFAULTS)}"
        )
    application = model_id or GENERATE_AUDIO_DEFAULTS[kind]
    spec = _AUDIO_ARGS.get(application, _AudioArgs())
    if duration_s is None:
        duration_s = spec.default_duration_s
    arguments: dict = {spec.prompt: prompt, **spec.defaults}
    if duration_s is not None and spec.duration:
        arguments[spec.duration] = spec.cast(duration_s)
    arguments.update(extra or {})
    billed = duration_s
    if billed is not None and spec.samples:
        billed = billed * arguments.get(spec.samples, 1)
    return application, arguments, billed


def plan_generate_audio(
    prompt: str,
    *,
    kind: str = "ambient",
    duration_s: Optional[float] = None,
    model_id: Optional[str] = None,
    extra: Optional[dict] = None,
    metadata: Optional[dict] = None,
    consult_cache: bool = True,
) -> CallPlan:
    """Plan a :func:`falaw.generate_audio` call (prompt → ambient/SFX/music).

    The planning primitive behind an ambient bed or music cue (falaw#10):
    the user who leaves their editor to hunt a city-night ambience is the
    user this generates one for — costed, cached and planned like every
    other call. Mirrors the eager :func:`falaw.generate_audio` signature so
    a planned call and an eager call with identical inputs collapse to the
    same cache entry. Pure data; no network at plan time.

    ``kind`` selects the default model (see :data:`GENERATE_AUDIO_DEFAULTS`
    for why these are explicit ids). ``duration_s`` reaches the model as its
    duration argument where the model takes one (see
    :func:`resolve_generate_audio`) AND feeds the cost estimate; for models
    with no duration argument it is estimator-only.
    """
    application, arguments, duration_s = resolve_generate_audio(
        prompt, kind=kind, duration_s=duration_s, model_id=model_id, extra=extra
    )
    record = get_model(application)
    cost, basis = _catalogue_price(record, seconds=duration_s)
    return make_call_plan(
        tool="generate_audio",
        application=application,
        arguments=arguments,
        output_kind="audio",
        estimated_cost_usd=cost,
        metadata=metadata,
        consult_cache=consult_cache,
        cost_basis=basis,
    )


# ---------------------------------------------------------------------------
# llm_complete  (the planning sibling of falaw.llm_complete)
# ---------------------------------------------------------------------------


MAX_OUTPUT_TOKENS_ARGUMENT = "max_tokens"
"""any-llm's response-cap argument, and hence the default output-token hint.

The cap the caller already put in ``extra`` is a *fact of the call*, not a
guess, so a plan that carries one quotes against it without being told twice.
"""


def plan_llm_complete(
    prompt: str,
    *,
    system: str = "",
    model: Optional[str] = None,
    temperature: float = 0.7,
    output_kind: str = "text",
    input_tokens: Optional[int] = None,
    max_output_tokens: Optional[int] = None,
    llm_rates: Optional[LlmRateTable] = None,
    extra: Optional[dict] = None,
    metadata: Optional[dict] = None,
    consult_cache: bool = True,
) -> CallPlan:
    """Plan a :func:`falaw.llm_complete` call without executing it.

    Routes through ``fal-ai/any-llm`` with the *exact same* application id and
    argument shape as the eager :func:`falaw.llm_complete`, so a planned call
    and an eager call with identical inputs collapse to the same cache entry.

    ``output_kind`` is ``"text"`` for a free-form completion or ``"json"`` when
    the prompt asks for a strict-JSON response — it tells :func:`falaw.execute`
    what kind of :class:`lacing.Artifact` to materialize. Either way the LLM
    response is materialized to a content-addressed cache *file*
    (``Artifact.path``), because LLM output is text, not a URL.

    **Cost is a ceiling for the routed model**, not the router's flat price
    (falaw#50, option A). ``fal-ai/any-llm`` is one registry record routing
    thirty models at two published request tiers, so the record's single
    ``per_call`` figure under-quotes every premium model tenfold — including
    this function's own default. :func:`falaw.llm_ceiling_usd` prices the
    ``model`` argument instead:

    - no token hints → fal's published per-request price for that model;
    - ``input_tokens`` **and** ``max_output_tokens`` → the greater of that
      price and the upstream per-token cost of a prompt that long capped at
      that many output tokens. Monotone in both hints;
    - a model the rate table does not price, or a token quote that cannot be
      bounded → ``estimated_cost_usd`` is ``None``, which lights up
      :attr:`falaw.plan.Plan.has_unknown_costs` and forces approval. It is
      never quietly the router's flat price.

    ``input_tokens`` is what opts a call into a token quote. Given one,
    ``max_output_tokens`` defaults to whatever the caller already put under
    :data:`MAX_OUTPUT_TOKENS_ARGUMENT` in ``extra`` — the cap is a fact of the
    call, not a second thing to remember. Without one, ``extra`` is left alone:
    capping your response is not asking to be quoted by tokens, and reading the
    cap as half a token quote would drop a call that has a perfectly good
    request price down to forced approval.

    Both hints are **estimator-only**: they never enter ``arguments``, so adding
    one to an existing call site changes the quote without moving the cache key
    or the plan hash.

    ``llm_rates`` swaps in a caller's own rate table — the seam for someone who
    has reconciled real numbers against their fal invoice.
    """
    from .llm import _DEFAULT_LLM, _DEFAULT_MODEL

    application = _DEFAULT_LLM
    routed_model = model or _DEFAULT_MODEL
    arguments: dict = {
        "model": routed_model,
        "prompt": prompt,
        "temperature": temperature,
    }
    if system:
        arguments["system_prompt"] = system
    arguments.update(extra or {})
    if input_tokens is not None and max_output_tokens is None:
        max_output_tokens = _int_or_none(arguments.get(MAX_OUTPUT_TOKENS_ARGUMENT))
    return make_call_plan(
        tool="llm_complete",
        application=application,
        arguments=arguments,
        output_kind=output_kind,  # type: ignore[arg-type]  # "text" | "json"
        estimated_cost_usd=llm_ceiling_usd(
            routed_model,
            input_tokens=input_tokens,
            max_output_tokens=max_output_tokens,
            rates=llm_rates,
        ),
        metadata=metadata,
        consult_cache=consult_cache,
        # The basis records the *routed* model, not ``application``: the router
        # is one record, the price belongs to the model it routes to — and the
        # hints below never enter ``arguments``, so nothing else on a persisted
        # call could reconstruct this quote (falaw#60).
        cost_basis=llm_cost_basis(
            routed_model,
            input_tokens=input_tokens,
            max_output_tokens=max_output_tokens,
            custom_rates=llm_rates is not None,
        ),
    )


def _int_or_none(value) -> Optional[int]:
    """``value`` as an int when it genuinely is one, else ``None``.

    ``extra`` is a free-form pass-through, so ``max_tokens`` may hold anything
    a model accepts. Only a real non-negative int is a usable output bound;
    anything else leaves the hint unset rather than coercing a guess.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value
