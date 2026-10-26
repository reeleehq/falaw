"""Tool and model registries.

Two registries, both queryable by tags/categories:

* `ToolRegistry` --- decorator-populated, holds the agent-facing surface.
* `ModelRegistry` --- JSON-backed, catalog of fal models with quality tiers.

Bridges (skill / MCP / HTTP) read the tool registry. Operations call
`pick_model` to map a (category, quality) pair to a concrete fal model id.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Callable, Optional

from .base import CostEstimate, ModelRecord, ToolSpec, data_table_version

_TOOLS: dict[str, ToolSpec] = {}


def register_tool(**spec_kwargs) -> Callable:
    """Decorator: register the wrapped function as a falaw tool.

    >>> @register_tool(name='echo', description='echo back', tags=('demo',))
    ... def _echo(x): return x
    >>> get_tool('echo').name
    'echo'
    """

    def decorate(func: Callable) -> Callable:
        spec = ToolSpec(func=func, **spec_kwargs)
        _TOOLS[spec.name] = spec
        return func

    return decorate


def get_tool(name: str) -> ToolSpec:
    if name not in _TOOLS:
        raise KeyError(f"No falaw tool registered as {name!r}; known: {sorted(_TOOLS)}")
    return _TOOLS[name]


def list_tools(*, tag: Optional[str] = None) -> list[ToolSpec]:
    return [t for t in _TOOLS.values() if tag is None or tag in t.tags]


# --- model registry --------------------------------------------------------


def _models_path() -> str:
    return os.path.join(os.path.dirname(__file__), "data", "models.json")


@lru_cache(maxsize=1)
def _load_models() -> dict[str, ModelRecord]:
    with open(_models_path()) as f:
        records = json.load(f)
    out: dict[str, ModelRecord] = {}
    for r in records:
        r = dict(r)
        r["aliases"] = tuple(r.get("aliases") or ())
        if "supported_resolutions" in r:
            r["supported_resolutions"] = tuple(r.get("supported_resolutions") or ())
        if r.get("typical_wall_time_s") is not None:
            r["typical_wall_time_s"] = tuple(r["typical_wall_time_s"])
        ce = r.get("cost_estimate")
        if isinstance(ce, dict):
            r["cost_estimate"] = CostEstimate(**ce)
        # else: None or already a CostEstimate — pass through unchanged.
        out[r["id"]] = ModelRecord(**r)
    return out


MODEL_CATALOGUE_TABLE = "falaw/data/models.json"
"""Identity a :class:`falaw.CostBasis` records for a catalogue-priced call."""


@lru_cache(maxsize=1)
def models_table_version() -> str:
    """The catalogue's version — see :func:`falaw.base.data_table_version`.

    Cached per process, like the catalogue itself.
    """
    return data_table_version(_models_path())


def model_constraints(id: str) -> dict:
    """The capability/limit fields for a model — the "static reminder of
    limitations" a shot-list builder surfaces. Resolves aliases.

    Returns a JSON-able dict; ``max_clip_seconds`` etc. are ``None`` / empty
    when unknown for that model.
    """
    m = get_model(id)
    return {
        "id": m.id,
        "category": m.category,
        "quality_tier": m.quality_tier,
        "max_clip_seconds": m.max_clip_seconds,
        "single_character_recommended": m.single_character_recommended,
        "supported_resolutions": list(m.supported_resolutions),
        "default_negative_prompt": m.default_negative_prompt,
        "max_references": {
            name: spec["max_items"]
            for name, spec in m.param_specs.items()
            if "max_items" in spec
        },
        "docs_url": m.docs_url,
    }


def model_params(id: str) -> dict:
    """Per-model parameters worth knowing before a call, ``{name: spec}``.

    Each spec is ``{"enum": [...], "default": ...}`` (or ``{"max_items": n}`` for
    a list argument such as reference images); resolves aliases. For
    ``fal-ai/recraft/v3/text-to-image`` this shows ``style`` defaults to
    ``realistic_image`` — a photograph, whatever the prompt describes — and
    lists the styles that actually give a woodcut or a linocut. Empty when the
    catalogue records none (fal's OpenAPI schema is the full source).
    """
    return {k: dict(v) for k, v in get_model(id).param_specs.items()}


def video_model_constraints() -> list[dict]:
    """``model_constraints`` for every video model in the catalog — the data a
    shot-list builder shows as its model-limits reference."""
    return [
        model_constraints(m.id)
        for m in _load_models().values()
        if "video" in m.category.lower()
    ]


def list_models(
    *,
    category: Optional[str] = None,
    quality_tier: Optional[str] = None,
) -> list[ModelRecord]:
    return [
        m
        for m in _load_models().values()
        if (category is None or m.category == category)
        and (quality_tier is None or m.quality_tier == quality_tier)
    ]


def get_model(id: str) -> ModelRecord:
    models = _load_models()
    if id in models:
        return models[id]
    for m in models.values():
        if id in m.aliases:
            return m
    raise KeyError(f"No model {id!r} known to falaw. Try list_models() to browse.")


# Tier ordering used to fall back to nearby tiers when an exact match is missing.
_TIER_ORDER = ("fast", "balanced", "high", "ultra")


def pick_model(
    *,
    category: str,
    quality_tier: str = "balanced",
) -> ModelRecord:
    """Pick a sensible fal model for a (category, quality) request.

    First-match semantics: when several models share a tier, the earlier
    entry wins. Curated entries are written first in `data/models.json`,
    so they take precedence over corpus-merged additions. If no model
    has the exact tier, neighboring tiers are tried. KeyError only when
    the category is empty.
    """
    everything = list_models(category=category)
    # A record opted out of default picks never wins; a category made only of
    # such records (nothing else to offer) still answers.
    candidates = [m for m in everything if m.default_pick] or everything

    def _first_with_tier(tier: str) -> Optional[ModelRecord]:
        return next((m for m in candidates if m.quality_tier == tier), None)

    exact = _first_with_tier(quality_tier)
    if exact is not None:
        return exact
    if quality_tier in _TIER_ORDER:
        i = _TIER_ORDER.index(quality_tier)
        for offset in range(1, len(_TIER_ORDER)):
            for j in (i - offset, i + offset):
                if 0 <= j < len(_TIER_ORDER):
                    near = _first_with_tier(_TIER_ORDER[j])
                    if near is not None:
                        return near
    if not candidates:
        raise KeyError(f"No models known for category={category!r}. Try list_models().")
    return candidates[0]
