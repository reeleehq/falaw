"""Check a call's arguments against the limits its catalogue record states.

The data-driven seam for request-shape limits that fal would otherwise reject
with an HTTP 422 after queueing: ``param_specs[name]`` may carry ``max_items``
(a list argument such as reference images) and ``min_pixels`` / ``max_pixels``
(an explicit ``{"width", "height"}`` size). One function, called from the two
places every call passes through — :func:`falaw.make_call_plan` and
:func:`falaw.call_fal` — so no planner or eager verb can forget it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .base import ModelRecord
from .errors import FalPromptTooLong


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def check_prompt_length(prompt: str, record: "ModelRecord | None") -> None:
    """Raise :class:`FalPromptTooLong` when ``prompt`` exceeds the model's cap."""
    limit = record.max_prompt_chars if record else None
    if limit is not None and len(prompt) > limit:
        raise FalPromptTooLong(
            f"{record.id} accepts prompts of at most {limit} characters; this one "
            f"is {len(prompt)} ({len(prompt) - limit} over). Shorten it (a long "
            "reusable style suffix is the usual culprit) or pick a model with a "
            "larger limit.",
            model=record.id,
            limit=limit,
            length=len(prompt),
        )


def check_call_arguments(record: ModelRecord, arguments: Mapping[str, Any]) -> None:
    """Raise ``ValueError`` if ``arguments`` break a limit ``record`` states: list
    sizes, pixel counts, and the prompt's ``max_prompt_chars`` for every operation
    (not only text-to-image, falaw#170)."""
    prompt = arguments.get("prompt")
    if isinstance(prompt, str):
        check_prompt_length(prompt, record)
    for name, spec in record.param_specs.items():
        if name not in arguments:
            continue
        value = arguments[name]
        limit = spec.get("max_items")
        if limit is not None:
            if not isinstance(value, (list, tuple)):
                raise ValueError(f"{record.id}: {name} must be a list, got {value!r}")
            if len(value) > limit:
                raise ValueError(
                    f"{record.id} takes at most {limit} {name}, got {len(value)}"
                )
        low, high = spec.get("min_pixels"), spec.get("max_pixels")
        if (low or high) and isinstance(value, Mapping):
            width, height = value.get("width"), value.get("height")
            if not (_is_int(width) and _is_int(height)):
                raise ValueError(
                    f"{record.id}: {name} needs integer width and height, got {value!r}"
                )
            pixels = width * height
            if (low and pixels < low) or (high and pixels > high):
                raise ValueError(
                    f"{record.id} needs an explicit {name} of {low or 0:,} to "
                    f"{high or float('inf'):,} total pixels; {width}x{height} is "
                    f"{pixels:,}. Use a larger size or a named preset."
                )
