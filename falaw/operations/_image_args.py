"""Argument building for text-to-image calls, shared by the eager and plan ops.

One place that knows how a model wants its size spelled and what its prompt may
hold, so ``generate_image`` and ``plan_generate_image`` cannot drift apart
(an eager call and a planned call with identical inputs must hash alike).
"""

from __future__ import annotations

import math
import os
from typing import Any, Optional, Sequence

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


def negative_prompt_arguments(
    record: Optional[ModelRecord], negative_prompt: Optional[str]
) -> dict:
    """``{"negative_prompt": text}`` for a model that declares one
    (:attr:`ModelRecord.accepts_negative_prompt`), else ``{}``: the text is dropped,
    never joined into the positive prompt, where it would ask for what it names.
    Model-generic (a video planner can use it too, falaw#155)."""
    text = (negative_prompt or "").strip()
    if text and record is not None and record.accepts_negative_prompt:
        return {"negative_prompt": text}
    return {}


def dropped_inputs(given: dict, arguments: dict) -> list:
    """The inputs a caller ``given`` (``{name: value}``) that did not reach the built
    ``arguments`` (the model has no slot for them), so a plan can say so
    (``CallPlan.metadata["dropped_inputs"]``, outside the plan hash): a constraint
    that never reached the picture is something to tell the person."""
    return [k for k, v in given.items() if (v or "").strip() and k not in arguments]


def image_arguments(
    record: Optional[ModelRecord],
    prompt: str,
    image_size: str,
    extra: Optional[dict],
    *,
    negative_prompt: Optional[str] = None,
) -> dict:
    """The wire arguments for one text-to-image call.

    ``image_size`` is always one of fal's named presets (or ``"W:H"`` for a
    model that takes ``aspect_ratio``); models whose ``size_param`` is
    ``aspect_ratio`` get the equivalent ratio instead. ``extra`` wins over
    everything, so ``extra={"resolution": "2K"}`` and the like pass through.
    ``negative_prompt`` goes in only for a model that accepts one
    (:func:`negative_prompt_arguments`).
    """
    check_prompt_length(prompt, record)
    extra = {**negative_prompt_arguments(record, negative_prompt), **(extra or {})}
    if record is None or record.size_param == "image_size":
        return {"prompt": prompt, "image_size": image_size, **extra}
    ratio = IMAGE_SIZE_ASPECT_RATIOS.get(image_size)
    if ratio is None and ":" in image_size:
        ratio = image_size
    if ratio is None:
        raise ValueError(
            f"{record.id} sizes images by {record.size_param}, and {image_size!r} "
            f"is neither a named preset ({sorted(IMAGE_SIZE_ASPECT_RATIOS)}) nor "
            "a 'W:H' ratio."
        )
    return {"prompt": prompt, record.size_param: ratio, **extra}


CONTROL_CATEGORY = "image_control"
"""Catalogue category of the models that take structural conditioning."""

EASYCONTROL_SPATIAL_MODES = ("canny", "depth", "hedsketch", "pose", "seg")
"""fal's EasyControl methods that condition on a guide image's *structure*.

Each ``mode`` is sent as ``control_method_url`` with ``image_control_type``
``"spatial"`` (fal-ai/flux-general's ``easycontrols``). Subject-style methods
(``subject``, ``ghibli``), custom weights and ``controlnet_unions`` stay
reachable through ``extra``."""

DFLT_CONTROL_SCALE = 1.0
"""fal's own default strength for an EasyControl entry."""


def easycontrols(control: Sequence[dict]) -> list[dict]:
    """fal's ``easycontrols`` list for ``control``: ``[{"mode", "image", "scale"?}]``.

    ``image`` is a URL fal can fetch, or a local :class:`os.PathLike`: a plan
    turns it into an upload marker (:func:`falaw.make_call_plan`), the eager op
    uploads it (:func:`falaw.upload`).

    >>> easycontrols([{"mode": "canny", "image": "https://x/edges.png", "scale": 0.6}])
    [{'control_method_url': 'canny', 'image_url': 'https://x/edges.png', 'image_control_type': 'spatial', 'scale': 0.6}]

    Raises:
        ValueError: no entry, an unknown mode, a missing image, or a scale that
            is not a finite number.
    """
    if not control:
        raise ValueError(
            "control needs at least one {'mode', 'image'} entry; use "
            "generate_image for an unconditioned image."
        )
    return [_easycontrol(entry) for entry in control]


def _easycontrol(entry: Any) -> dict:
    if not isinstance(entry, dict):
        raise ValueError(
            f"a control entry is a dict with 'mode' and 'image'; got {entry!r}"
        )
    unknown = set(entry) - {"mode", "image", "scale"}
    if unknown:
        raise ValueError(
            f"unknown control key(s) {sorted(unknown)}: an entry takes 'mode', "
            "'image' and 'scale'; pass anything else through extra."
        )
    mode = entry.get("mode")
    if mode not in EASYCONTROL_SPATIAL_MODES:
        raise ValueError(
            f"control mode {mode!r} is not one of {list(EASYCONTROL_SPATIAL_MODES)}."
        )
    image = entry.get("image")
    if not (isinstance(image, os.PathLike) or (isinstance(image, str) and image)):
        raise ValueError(
            f"control entry {mode!r} needs an 'image': a URL, or a path in a plan."
        )
    scale = entry.get("scale", DFLT_CONTROL_SCALE)
    if (
        isinstance(scale, bool)
        or not isinstance(scale, (int, float))
        or not math.isfinite(scale)
    ):
        raise ValueError(f"control scale must be a finite number; got {scale!r}")
    return {
        "control_method_url": mode,
        "image_url": image,
        "image_control_type": "spatial",
        "scale": float(scale),
    }


def controlled_image_arguments(
    record: Optional[ModelRecord],
    prompt: str,
    image_size: str,
    control: Sequence[dict],
    extra: Optional[dict],
    *,
    negative_prompt: Optional[str] = None,
) -> dict:
    """The wire arguments for a structurally conditioned image call.

    :func:`image_arguments` plus ``easycontrols``; ``extra`` still wins over
    everything. Shared by the eager op and its ``plan_*`` sibling so the two
    hash alike.

    Raises:
        ValueError: ``record`` is a catalogued model of another category, which
            would silently ignore the control (an unlisted model, ``None``,
            passes through).
    """
    if record is not None and record.category != CONTROL_CATEGORY:
        raise ValueError(
            f"{record.id} is a {record.category!r} model and ignores structural "
            f"control; pick an {CONTROL_CATEGORY!r} model (or none, for the default)."
        )
    return {
        **image_arguments(record, prompt, image_size, None, negative_prompt=negative_prompt),
        "easycontrols": easycontrols(control),
        **(extra or {}),
    }


def refs_arguments(
    prompt: str,
    refs: list,
    extra: Optional[dict],
    *,
    record: Optional[ModelRecord] = None,
    negative_prompt: Optional[str] = None,
) -> dict:
    """The argument dict for a reference-conditioned image call.

    Image-edit models disagree on the parameter name — some read ``image_url``
    (singular), others ``image_urls`` (plural). Passing both lets the receiving
    model use whichever it understands; ``image_url`` carries the primary
    (first) reference. ``negative_prompt`` as in :func:`image_arguments`;
    ``extra`` wins. Shared by the eager op and its ``plan_*`` sibling so an
    eager call and a planned call with identical inputs collapse to one cache
    entry.
    """
    return {
        "image_url": refs[0],
        "image_urls": list(refs),
        "prompt": prompt,
        **negative_prompt_arguments(record, negative_prompt),
        **(extra or {}),
    }
