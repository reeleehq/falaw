"""Structural conditioning: fal-ai/flux-general's EasyControl (falaw#140).

A guide image (a rig's edges, depth or pose) decides where the subject lands.
Offline: the eager op's ``call_fal`` is replaced, and plans never execute.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from falaw import (
    generate_image_with_control,
    pick_model,
    plan_generate_image_with_control,
)
from falaw.cost import DFLT_MEGAPIXELS
from falaw.operations._image_args import CONTROL_CATEGORY
from falaw.terms import get_terms

GUIDE = "https://example.com/rig-pose.png"
MODEL = "fal-ai/flux-general"


def test_the_control_category_picks_flux_general_and_plain_images_never_do():
    assert pick_model(category=CONTROL_CATEGORY).id == MODEL
    for tier in ("fast", "balanced", "high", "ultra"):
        assert pick_model(category="image", quality_tier=tier).id != MODEL


def test_a_plan_sends_easycontrols_and_prices_per_megapixel():
    call = plan_generate_image_with_control(
        "hands on a steering wheel",
        [
            {"mode": "pose", "image": GUIDE, "scale": 0.7},
            {"mode": "canny", "image": GUIDE},
        ],
        consult_cache=False,
    )
    assert call.application == MODEL
    assert call.tool == "generate_image_with_control"
    assert call.arguments["easycontrols"] == [
        {
            "control_method_url": "pose",
            "image_url": GUIDE,
            "image_control_type": "spatial",
            "scale": 0.7,
        },
        {
            "control_method_url": "canny",
            "image_url": GUIDE,
            "image_control_type": "spatial",
            "scale": 1.0,  # fal's default
        },
    ]
    assert call.arguments["prompt"] == "hands on a steering wheel"
    assert call.arguments["image_size"] == "landscape_4_3"
    assert call.estimated_cost_usd == pytest.approx(0.075 * DFLT_MEGAPIXELS)


def test_extra_wins_over_everything():
    call = plan_generate_image_with_control(
        "p",
        [{"mode": "depth", "image": GUIDE}],
        extra={"easycontrols": [], "num_inference_steps": 12},
        consult_cache=False,
    )
    assert call.arguments["easycontrols"] == []
    assert call.arguments["num_inference_steps"] == 12


def test_a_local_guide_image_becomes_an_upload_marker_in_the_plan(tmp_path):
    guide = tmp_path / "rig.png"
    guide.write_bytes(b"\x89PNG fake")
    call = plan_generate_image_with_control(
        "p", [{"mode": "canny", "image": guide}], consult_cache=False
    )
    marker = call.arguments["easycontrols"][0]["image_url"]
    assert isinstance(marker, str) and str(guide) in marker
    assert call.local_files == (("easycontrols", 0, "image_url"),)


def test_the_eager_op_sends_what_the_plan_would(monkeypatch):
    sent = []

    def fake_call_fal(application, arguments, **kw):
        sent.append((application, arguments))
        return {"images": [{"url": "https://v3.fal.media/out.png"}]}

    monkeypatch.setattr("falaw.operations.images.call_fal", fake_call_fal)
    control = [{"mode": "pose", "image": GUIDE, "scale": 0.5}]
    result = generate_image_with_control("p", control)
    planned = plan_generate_image_with_control("p", control, consult_cache=False)
    assert sent == [(planned.application, planned.arguments)]
    assert result.assets[0].url == "https://v3.fal.media/out.png"


@pytest.mark.parametrize(
    "control, match",
    [
        ([], "at least one"),
        (["canny"], "is a dict"),
        ([{"mode": "subject", "image": GUIDE}], "not one of"),
        ([{"mode": "canny"}], "needs an 'image'"),
        ([{"mode": "canny", "image": ""}], "needs an 'image'"),
        ([{"mode": "canny", "image": GUIDE, "scale": "high"}], "finite number"),
        ([{"mode": "canny", "image": GUIDE, "scale": float("nan")}], "finite number"),
        ([{"mode": "canny", "image": GUIDE, "scale": True}], "finite number"),
        ([{"mode": "canny", "image": GUIDE, "strength": 1}], "unknown control key"),
    ],
)
def test_a_malformed_control_is_refused_before_any_call(control, match):
    with pytest.raises(ValueError, match=match):
        plan_generate_image_with_control("p", control, consult_cache=False)


def test_flux_general_has_a_terms_row_on_fal():
    row = get_terms(MODEL, "fal")
    assert row is not None
    assert row.license == "LicenseRef-flux-1-dev-non-commercial"
