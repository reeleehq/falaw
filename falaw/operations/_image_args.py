"""Argument building for text-to-image calls, shared by the eager and plan ops.

One place that knows how a model wants its size spelled and what its prompt may
hold, so ``generate_image`` and ``plan_generate_image`` cannot drift apart
(an eager call and a planned call with identical inputs must hash alike).
"""

from __future__ import annotations

from typing import Optional

from ..base import ModelRecord
from ..errors import FalPromptTooLong
from ..registry import get_model

IMAGE_SIZE_ASPECT_RATIOS = {
    "square_hd": "1:1",
    "square": "1:1",
    "portrait_4_3": "3:4",
    "portrait_16_9": "9:16",
    "landscape_4_3": "4:3",
    "landscape_16_9": "16:9",
}
"""fal's named ``image_size`` presets, as the aspect ratio they denote."""


def known_record(model: str) -> Optional[ModelRecord]:
    """The catalogue record for ``model``, or ``None`` for an unlisted id."""
    try:
        return get_model(model)
    except KeyError:
        return None


def check_prompt_length(prompt: str, record: Optional[ModelRecord]) -> None:
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


def image_arguments(
    record: Optional[ModelRecord],
    prompt: str,
    image_size: str,
    extra: Optional[dict],
) -> dict:
    """The wire arguments for one text-to-image call.

    ``image_size`` is always one of fal's named presets (or ``"W:H"`` for a
    model that takes ``aspect_ratio``); models whose ``size_param`` is
    ``aspect_ratio`` get the equivalent ratio instead. ``extra`` wins over
    everything, so ``extra={"resolution": "2K"}`` and the like pass through.
    """
    check_prompt_length(prompt, record)
    if record is None or record.size_param == "image_size":
        return {"prompt": prompt, "image_size": image_size, **(extra or {})}
    ratio = IMAGE_SIZE_ASPECT_RATIOS.get(image_size)
    if ratio is None and ":" in image_size:
        ratio = image_size
    if ratio is None:
        raise ValueError(
            f"{record.id} sizes images by {record.size_param}, and {image_size!r} "
            f"is neither a named preset ({sorted(IMAGE_SIZE_ASPECT_RATIOS)}) nor "
            "a 'W:H' ratio."
        )
    return {"prompt": prompt, record.size_param: ratio, **(extra or {})}
