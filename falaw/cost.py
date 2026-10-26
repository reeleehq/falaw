"""Cost estimation: ModelRecord.cost_estimate + Scene rollups.

Two surfaces here:

- :func:`estimate_call_cost(record, *, count=1, seconds=None, megapixels=None,
  tokens=None)` — turn one model's :class:`CostEstimate` into a USD figure.
- :func:`estimate_scene_cost(scene, *, ...)` — walk every Shot + Beat in a
  :class:`falaw.Scene` and sum the per-call costs that
  :func:`falaw.render_scene` would incur. Returns a structured rollup
  (per-line + totals) so UIs can show "this render would cost ~$0.42".

A scene-level estimate is *advisory*. It's based on the same
``pick_model(category, quality_tier=...)`` lookup that the renderer
uses, multiplied by per-line duration / pixel budgets. Real costs vary
with model fluctuations and provider billing rules, but this is good
enough to gate on (e.g. ``--budget=1.00``) and to surface in
``muvid status``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Optional

from .base import CostEstimate, ModelRecord
from .registry import pick_model
from .scene import Beat, Scene, Shot


@dataclass(frozen=True, slots=True, kw_only=True)
class CostLine:
    """One line item in a scene rollup."""

    kind: str  # "shot.image" | "shot.video" | "beat.tts" | "beat.avatar" | ...
    item_id: str  # shot.id or beat.id
    model_id: str
    amount: float
    currency: str
    note: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class CostRollup:
    """Result of :func:`estimate_scene_cost`."""

    total_amount: float
    currency: str = "USD"
    lines: tuple[CostLine, ...] = ()
    skipped: tuple[str, ...] = ()  # human-readable notes for entries we couldn't price

    def by_kind(self) -> dict[str, float]:
        """Sum per ``kind`` for quick inspection."""
        out: dict[str, float] = {}
        for ln in self.lines:
            out[ln.kind] = out.get(ln.kind, 0.0) + ln.amount
        return out


DFLT_MEGAPIXELS = 0.6
"""Pixel budget assumed for a ``per_megapixel`` call when the caller gives none:
a 16:9 canvas 1024 wide (≈0.59 MP), enough for a useful upper-bound estimate.
Exported to the TypeScript twin, which must assume the same."""


RESOLUTION_SHORT_SIDE = {"480p": 480, "720p": 720, "1080p": 1080, "4k": 2160}
"""The short side, in pixels, of fal's named video resolutions. The frame is
that squared times the aspect ratio's long/short ratio (:func:`frame_pixels`)."""

DFLT_VIDEO_ASPECT = "16:9"
"""Aspect ratio assumed when none is given or fal derives it (``"auto"``, from
the input image): the common case, and 1:1 or 4:3 then over-quote."""

DFLT_VIDEO_RESOLUTION = "720p"
"""Resolution assumed for a token-billed video model that records no default."""


_ASPECT = re.compile(r"\s*(\d+)\s*:\s*(\d+)\s*")


def quote_aspect(record: ModelRecord, aspect_ratio: str | None = None) -> str:
    """The aspect ratio a quote assumes, so that it stays a ceiling.

    An explicit ratio is used as given. When it is absent or ``"auto"`` (fal
    derives it from the input image) and the record lists a ``"W:H"`` enum, the
    widest ratio listed, which has the most pixels; without an enum,
    :data:`DFLT_VIDEO_ASPECT`.
    """
    spec = record.param_specs.get("aspect_ratio", {})
    aspect_ratio = aspect_ratio or spec.get("default")
    if aspect_ratio not in (None, "", "auto"):
        return aspect_ratio
    ratios = [r for r in spec.get("enum", ()) if _ASPECT.fullmatch(str(r))]
    return max(ratios, key=lambda r: frame_pixels("480p", r), default=DFLT_VIDEO_ASPECT)


def frame_pixels(resolution: str, aspect_ratio: str | None = None) -> float:
    """Pixels per frame of a ``resolution`` at ``aspect_ratio`` (``"W:H"``).

    An estimate within about a percent of what fal bills (it rounds frame
    sides to codec-friendly multiples): ``short_side ** 2 * long / short``.
    """
    short = RESOLUTION_SHORT_SIDE[resolution]
    ratio = DFLT_VIDEO_ASPECT if aspect_ratio in (None, "", "auto") else aspect_ratio
    match = _ASPECT.fullmatch(str(ratio))
    w, h = (int(g) for g in match.groups()) if match else (0, 0)
    if w <= 0 or h <= 0:
        raise ValueError(f"aspect_ratio must look like '16:9' or 'auto', got {ratio!r}")
    return short * short * max(w, h) / min(w, h)


def video_price_quantities(
    record: ModelRecord,
    *,
    seconds: float | None = None,
    resolution: str | None = None,
    aspect_ratio: str | None = None,
) -> dict:
    """The quantity hints that price one video call against ``record``.

    ``{"tokens": n}`` for a model billed per video token (its
    ``tokens_per_pixel_second`` is set), else ``{"seconds": s}``; ``{}`` when
    ``seconds`` is unknown, so the call stays unpriceable rather than free.
    ``resolution`` defaults to the model's recorded default; ``aspect_ratio``
    to :func:`quote_aspect`'s ceiling. The record's
    ``resolution_rate_factors`` entry for ``resolution`` scales the tokens, so
    they are rate-equivalent tokens at the recorded rate: the quote stays
    ``rate x tokens``.
    """
    if seconds is None:
        return {}
    factor = record.tokens_per_pixel_second
    if factor is None:
        return {"seconds": seconds}
    spec = record.param_specs.get("resolution", {})
    resolution = resolution or spec.get("default") or DFLT_VIDEO_RESOLUTION
    allowed = spec.get("enum") or sorted(RESOLUTION_SHORT_SIDE)
    if resolution not in allowed or resolution not in RESOLUTION_SHORT_SIDE:
        raise ValueError(
            f"{record.id} does not offer resolution {resolution!r}; "
            f"expected one of {list(allowed)}"
        )
    pixels = frame_pixels(resolution, quote_aspect(record, aspect_ratio))
    return {
        "tokens": round(
            pixels
            * seconds
            * factor
            * record.resolution_rate_factors.get(resolution, 1.0)
        )
    }


def video_duration_arg(record: ModelRecord, duration_s: float) -> str:
    """``duration_s`` as the string fal's duration enum wants, or ``ValueError``.

    The one rule the planner (what is sent and quoted) and the scene rollup
    share, so neither prices a call fal would reject: whole seconds (halves to
    even), and within the record's ``duration`` enum when it lists numbers
    (``"auto"`` aside).
    """
    if not math.isfinite(duration_s):
        raise ValueError(f"{record.id}: duration must be finite, got {duration_s!r}")
    seconds = round(duration_s)
    enum = record.param_specs.get("duration", {}).get("enum") or ()
    allowed = sorted(int(v) for v in enum if str(v).isdigit())
    if allowed and seconds not in allowed:
        raise ValueError(
            f"{record.id} accepts durations of {allowed[0]} to {allowed[-1]} s; "
            f"got {duration_s}"
        )
    return str(seconds)


def _numeric_seconds(value) -> float | None:
    """A duration argument as seconds; ``None`` for absent, ``"auto"`` or junk
    (unknown, so the call stays unpriced rather than free)."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if math.isfinite(seconds) else None


def video_call_arguments(
    record: ModelRecord,
    arguments: dict,
    *,
    duration_s: float | None,
    extra: dict | None,
) -> tuple[dict, float | None]:
    """``(wire arguments, seconds the call bills)`` for a video call.

    The one place planned and eager video calls agree. ``duration_s`` is *sent*
    only for a model whose record lists a ``duration`` parameter (Seedance spells
    it as a string enum), validated by :func:`video_duration_arg`; elsewhere it
    is estimator-only when planning, since models name that argument
    differently. ``extra`` wins over everything and the billed seconds follow
    what it says. With no duration anywhere, nothing is sent and the call is
    priced at the record's declared default (fal bills that default; ``"auto"``
    stays unknown), so the cache key stays the real run's.
    """
    arguments = {**arguments, **(extra or {})}
    seconds = duration_s
    if "duration" in record.param_specs:
        if duration_s is not None and "duration" not in arguments:
            arguments["duration"] = video_duration_arg(record, duration_s)
        spec = record.param_specs["duration"]
        dflt = spec.get("default") if isinstance(spec, dict) else None
        seconds = _numeric_seconds(arguments.get("duration", dflt))
    return arguments, seconds


def estimate_call_cost(
    record: ModelRecord,
    *,
    count: int = 1,
    seconds: float | None = None,
    megapixels: float | None = None,
    tokens: int | None = None,
) -> Optional[float]:
    """Cost of one fal call against ``record``.

    Returns ``None`` when the cost is **unknown**, so callers can
    distinguish "free" from "we can't say". That happens when the record
    carries no ``cost_estimate`` at all, or when its pricing is
    quantity-based (``per_second`` / ``per_token``) and the caller did
    not supply the quantity — an unpriceable call, not a free one.

    Returning ``0.0`` for a missing quantity would be actively dangerous:
    a ``per_second`` clip is the single most expensive thing fal bills
    for, and a caller gating a budget on the answer would read
    "$0.00" and spend real money without a prompt. ``None`` instead
    propagates to ``CallPlan.estimated_cost_usd`` and lights up
    ``Plan.has_unknown_costs``, which exists for exactly this case.
    Callers that know the quantity should pass it; ``per_second`` callers
    can fall back to ``record.max_clip_seconds`` for an upper bound.

    ``per_megapixel`` is deliberately different: an image's pixel budget
    has a sane house default (below), so it stays priceable.
    """
    ce: CostEstimate | None = record.cost_estimate
    if ce is None:
        return None
    if ce.kind == "per_call":
        return ce.amount * count
    if ce.kind == "per_image":
        return ce.amount * count
    if ce.kind == "per_second":
        if seconds is None:
            return None  # unknown duration → unpriceable, NOT free
        return ce.amount * seconds * count
    if ce.kind == "per_megapixel":
        # Default to a 16:9 1024-wide canvas if the caller didn't say
        # (≈0.59 MP); enough to give a useful upper-bound estimate.
        mp = megapixels if megapixels is not None else DFLT_MEGAPIXELS
        return ce.amount * mp * count
    if ce.kind == "per_token":
        if tokens is None:
            return None  # unknown token count → unpriceable, NOT free
        return ce.amount * tokens * count
    return None


def _shot_pricing_lines(
    shot: Shot,
    *,
    style: str,
    shots_as_video: bool,
    quality: str,
    skipped: list[str],
    seconds: float | None = None,
) -> list[CostLine]:
    out: list[CostLine] = []
    # A Shot carries no duration (screen time comes from the renderer's
    # per-shot run, not the IR), so this falls back to the caller's
    # ``seconds`` and is otherwise None → the i2v line is unpriceable and
    # lands in ``skipped``. Coercing it to 0.0 here instead would launder
    # "unknown" into "free" *before* ``estimate_call_cost`` ever sees it,
    # defeating that function's guard and putting a $0.00 line —
    # indistinguishable from a real price, and absent from ``skipped`` —
    # on a clip that bills ~$1-2.
    duration = getattr(shot, "duration_s", None)
    if duration is None:
        duration = seconds
    duration = float(duration) if duration is not None else None

    img_record = pick_model(category="image", quality_tier=quality)
    img_cost = estimate_call_cost(img_record)
    if img_cost is None:
        skipped.append(
            f"shot {shot.id} image gen: no cost_estimate on {img_record.id!r}"
        )
    else:
        out.append(
            CostLine(
                kind="shot.image",
                item_id=shot.id,
                model_id=img_record.id,
                amount=img_cost,
                currency=(
                    img_record.cost_estimate.currency
                    if img_record.cost_estimate
                    else "USD"
                ),
                note="storyboard still",
            )
        )

    if shots_as_video:
        v_record = pick_model(category="image_to_video", quality_tier=quality)
        v_cost, problem, billed = None, "", None
        try:
            # the planner's own rule: as sent, else the model's declared default
            _, billed = video_call_arguments(
                v_record, {}, duration_s=duration, extra=None
            )
            v_cost = estimate_call_cost(
                v_record, **video_price_quantities(v_record, seconds=billed)
            )
        except ValueError as e:  # a duration the model would reject
            problem = str(e)
        if v_cost is None:
            why = problem or (
                "no duration on the Shot, and the model is priced per second or per token"
                if billed is None
                else f"no cost_estimate on {v_record.id!r}"
            )
            skipped.append(f"shot {shot.id} i2v: {why}")
        else:
            out.append(
                CostLine(
                    kind="shot.video",
                    item_id=shot.id,
                    model_id=v_record.id,
                    amount=v_cost,
                    currency=(
                        v_record.cost_estimate.currency
                        if v_record.cost_estimate
                        else "USD"
                    ),
                    note=f"image_to_video × {billed:.1f}s",
                )
            )
    return out


def _beat_pricing_lines(
    beat: Beat,
    *,
    speaker_has_voice_clone: bool,
    tts_quality: str,
    lipsync_quality: str,
    estimated_seconds: float | None,
    skipped: list[str],
) -> list[CostLine]:
    if not beat.line:
        return []

    out: list[CostLine] = []
    secs = (
        estimated_seconds
        if estimated_seconds is not None
        else _word_count(beat.line) * 0.4
    )

    tts_category = "voice_clone" if speaker_has_voice_clone else "tts"
    try:
        tts_record = pick_model(category=tts_category, quality_tier=tts_quality)
    except KeyError:
        skipped.append(f"beat {beat.id} tts: no model in category {tts_category!r}")
        return out

    tts_cost = estimate_call_cost(tts_record, seconds=secs)
    if tts_cost is None:
        skipped.append(f"beat {beat.id} tts: no cost_estimate on {tts_record.id!r}")
    else:
        out.append(
            CostLine(
                kind="beat.tts",
                item_id=beat.id,
                model_id=tts_record.id,
                amount=tts_cost,
                currency=(
                    tts_record.cost_estimate.currency
                    if tts_record.cost_estimate
                    else "USD"
                ),
                note=f"~{secs:.1f}s of speech",
            )
        )

    av_record = pick_model(category="avatar", quality_tier=lipsync_quality)
    av_cost = estimate_call_cost(av_record, seconds=secs)
    if av_cost is None:
        skipped.append(f"beat {beat.id} avatar: no cost_estimate on {av_record.id!r}")
    else:
        out.append(
            CostLine(
                kind="beat.avatar",
                item_id=beat.id,
                model_id=av_record.id,
                amount=av_cost,
                currency=(
                    av_record.cost_estimate.currency
                    if av_record.cost_estimate
                    else "USD"
                ),
                note=f"face animation × {secs:.1f}s",
            )
        )

    return out


def estimate_scene_cost(
    scene: Scene,
    *,
    tts_quality: str = "balanced",
    lipsync_quality: str = "high",
    shot_quality: str = "balanced",
    shots_as_video: bool = False,
    shot_seconds: float | None = None,
) -> CostRollup:
    """Estimate the USD cost of a full :func:`render_scene` invocation.

    Walks every shot + beat with the same ``pick_model`` semantics
    the renderer uses, then sums per-call costs. Returns a structured
    :class:`CostRollup` with per-line breakdowns, plus a list of
    "skipped" entries the caller should surface (typically: a model
    with no ``cost_estimate`` populated).

    ``shot_seconds`` is the assumed clip length used to price
    ``shots_as_video``. A :class:`Shot` carries no duration of its own —
    screen time comes from the renderer's per-shot run — and
    image-to-video models bill **per second**, so without this the video
    lines are genuinely unpriceable and are reported in
    :attr:`CostRollup.skipped` rather than silently priced at $0.00.
    Pass the length you expect (the beat path has the same knob as
    ``estimated_seconds``).
    """
    chars_by_name = {c.name: c for c in scene.characters}
    lines: list[CostLine] = []
    skipped: list[str] = []

    for shot in scene.shots:
        lines.extend(
            _shot_pricing_lines(
                shot,
                style=scene.style,
                shots_as_video=shots_as_video,
                quality=shot_quality,
                seconds=shot_seconds,
                skipped=skipped,
            )
        )

    for beat in scene.beats:
        speaker = chars_by_name.get(beat.speaker)
        if speaker is None:
            continue
        cloning = bool(speaker.voice and speaker.voice.reference_audio_url)
        lines.extend(
            _beat_pricing_lines(
                beat,
                speaker_has_voice_clone=cloning,
                tts_quality=tts_quality,
                lipsync_quality=lipsync_quality,
                estimated_seconds=getattr(beat, "duration_s", None),
                skipped=skipped,
            )
        )

    total = sum(ln.amount for ln in lines)
    currency = lines[0].currency if lines else "USD"
    return CostRollup(
        total_amount=total,
        currency=currency,
        lines=tuple(lines),
        skipped=tuple(skipped),
    )


def _word_count(text: str) -> int:
    return len([w for w in text.split() if w])
