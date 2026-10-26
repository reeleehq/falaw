"""Core types: ToolSpec and ModelRecord.

These dataclasses are the single source of truth from which every external
surface (Claude skill, MCP server, HTTP service, UI) is derived.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping, Optional

JSONSchema = Mapping[str, Any]

TABLE_VERSION_CHARS = 12
"""Hex characters of the digest :func:`data_table_version` returns."""


def data_table_version(path: str) -> str:
    """Short content digest naming the version of a committed data table.

    The one definition for every table falaw ships (``models.json``,
    ``llm_rates.json``), so a :class:`falaw.CostBasis` stamped by one is
    comparable with a basis stamped by another.

    Deliberately the *bytes*, not a declared ``version`` field: 0.0.46 moved
    every premium LLM row's price tenfold without touching one, and that drift
    is exactly what a persisted quote must be able to detect. A digest cannot
    forget to be bumped.
    """
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:TABLE_VERSION_CHARS]


CostKind = Literal["per_call", "per_image", "per_second", "per_token", "per_megapixel"]


@dataclass(frozen=True, slots=True, kw_only=True)
class CostEstimate:
    """Quantitative cost of one fal call against this model.

    Attributes:
        kind: How the price scales. ``per_call`` is the simplest:
            constant per invocation regardless of size. ``per_second``
            applies to video / TTS where output length matters.
            ``per_image`` covers batch image gen. ``per_megapixel``
            covers high-res image generation. ``per_token`` covers
            LLM-style endpoints.
        amount: USD (or ``currency``) per unit defined by ``kind``.
        currency: ISO 4217 code. ``"USD"`` is the only supported value
            today; the field exists so we can extend without a schema
            migration.
        notes: Free-form caveats — "rounded up to next second", etc.
        source: How the estimate was obtained — ``"docs"``,
            ``"empirical"``, ``"approximate"``. Lets us flag stale or
            unverified entries in audits.
    """

    kind: CostKind
    amount: float
    currency: str = "USD"
    notes: str = ""
    source: str = "approximate"


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolSpec:
    """Single source of truth for a tool exposed by falaw.

    A ToolSpec is what the registry stores. Bridges read it to produce
    Claude-skill instructions, MCP tool descriptors, HTTP endpoints, etc.
    """

    name: str
    description: str
    func: Callable[..., Any]
    input_schema: JSONSchema = field(default_factory=dict)
    output_schema: JSONSchema = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    examples: tuple[Mapping[str, Any], ...] = ()
    version: str = "0.0.1"


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelRecord:
    """One entry in the fal model catalog."""

    id: str
    category: str
    description: str = ""
    aliases: tuple[str, ...] = ()
    quality_tier: str = ""  # "fast" | "balanced" | "high" | "ultra" | "unranked"
    cost_hint: str = ""  # legacy free-form text; kept for back-compat
    cost_estimate: Optional[CostEstimate] = None  # quantitative; preferred
    docs_url: str = ""

    # --- capability / limit metadata (the "static reminder of limitations"
    #     a shot-list builder surfaces; mostly meaningful for video models) ---
    max_clip_seconds: Optional[float] = None
    """Practical max length of a single generated clip, in seconds (e.g. ~10
    for Seedance). Drives the "this shot is too long, split it" warning."""
    single_character_recommended: bool = False
    """True when the model handles a single character per shot far better than
    multiple interacting ones — drives the "two characters, consider
    shot/reverse-shot" warning."""
    supported_resolutions: tuple[str, ...] = ()
    """Resolutions the model offers, cheap→expensive (e.g. ("720p", "1080p"))."""
    default_negative_prompt: str = ""
    """Quality/realism negatives worth appending by default (e.g. to avoid the
    plastic-skin look). Empty when none."""
    default_pick: bool = True
    """Whether :func:`falaw.pick_model` may choose this record when a caller names
    only a category and tier. ``False`` for a record that is catalogued, priced
    and usable by id or alias but must never become the default — so its
    ``quality_tier`` can state its real quality, and a price refresh's re-sort
    cannot promote it (falaw#95)."""
    tokens_per_pixel_second: Optional[float] = None
    """For a model billed per *video token*: tokens = width x height x seconds
    x this (Seedance: 24/1024). With a ``per_token`` ``cost_estimate`` it lets
    plan time quote an honest cost from a resolution and a duration
    (:func:`falaw.cost.video_price_quantities`). ``None`` for every other
    model."""
    resolution_rate_factors: Mapping[str, float] = field(
        default_factory=dict, hash=False
    )
    """Per-resolution discounts off the recorded per-token rate, for a model
    whose higher resolutions bill less per token (Seedance 2.0 at ``"4k"``).
    Each value is in (0, 1]: the fraction of the recorded rate fal bills, rounded
    up so a quote stays a ceiling. The recorded rate is relative, so a price
    refresh that moves it moves these quotes with it. A quote's
    ``cost_basis.quantities["tokens"]`` is then rate-equivalent tokens, not the
    tokens fal counts. See :func:`falaw.cost.video_price_quantities`."""

    # --- request-shape metadata (image models; falaw#76) ---
    max_prompt_chars: Optional[int] = None
    """Hard cap on ``prompt`` length, from the model's OpenAPI schema. Calls
    over it fail at fal with an HTTP 422 after queueing; falaw raises first."""
    size_param: str = "image_size"
    """Which argument carries the output size: ``"image_size"`` (fal's named
    presets, the default) or ``"aspect_ratio"`` (+ ``resolution``)."""
    param_specs: Mapping[str, Mapping[str, Any]] = field(
        default_factory=dict, hash=False
    )
    """Discoverable per-model parameters that matter for choosing well, as
    ``{name: {"enum": [...], "default": ...}}`` — e.g. Recraft's ``style``,
    whose photoreal default silently overrides a woodcut prompt. See
    :func:`falaw.model_params`."""
