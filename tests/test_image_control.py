"""Structural conditioning: fal-ai/flux-general's EasyControl (falaw#140).

A guide image (a rig's edges, depth or pose) decides where the subject lands.
Offline: ``call_fal`` and the uploader are fakes, and the autouse fixtures in
``conftest.py`` serve the asset transport and isolate the cache.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import falaw
from falaw import (
    FalTermsViolation,
    TermsContext,
    generate_image_with_control,
    pick_model,
    plan_generate_image_with_control,
    using_uploader,
)
from falaw.cost import DFLT_MEGAPIXELS
from falaw.operations._image_args import CONTROL_CATEGORY
from falaw.terms import get_terms, is_cleared

GUIDE = "https://example.com/rig-pose.png"
MODEL = "fal-ai/flux-general"
OUT = {"images": [{"url": "https://v3.fal.media/out.png"}]}


@pytest.fixture
def guide(tmp_path):
    path = tmp_path / "rig.png"
    path.write_bytes(b"\x89PNG fake")
    return path


@pytest.fixture
def uploads():
    """The uploader, a counting fake: no network, one URL per transfer."""
    seen = []

    def fake_upload(path):
        seen.append(path)
        return f"https://v3b.fal.media/up/{len(seen)}.png"

    with using_uploader(fake_upload):
        yield seen


@pytest.fixture
def sent(monkeypatch):
    """What reaches fal, ``(application, arguments)`` per call, eager or planned."""
    calls = []

    def fake_call_fal(application, arguments, **kw):
        calls.append((application, dict(arguments)))
        return OUT

    monkeypatch.setattr("falaw.core.call_fal", fake_call_fal)
    monkeypatch.setattr("falaw.operations.images.call_fal", fake_call_fal)
    return calls


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


def test_a_local_guide_plans_as_a_marker_and_executes_uploaded_once(
    guide, uploads, sent
):
    def plan():
        call = plan_generate_image_with_control(
            "p", [{"mode": "canny", "image": guide}]
        )
        return call, falaw.Plan(calls=(call,))

    call, first = plan()
    marker = call.arguments["easycontrols"][0]["image_url"]
    assert isinstance(marker, str) and str(guide) in marker
    assert call.local_files == (("easycontrols", 0, "image_url"),)
    assert call.cache_status == "miss"
    falaw.execute_plan(first)
    assert uploads == [str(guide)]
    wire = sent[0][1]["easycontrols"][0]["image_url"]
    assert wire == "https://v3b.fal.media/up/1.png"

    call, again = plan()
    assert call.cache_status == "hit"  # keyed on the bytes, not the path or URL
    falaw.execute_plan(again)
    assert len(sent) == 1 and len(uploads) == 1

    guide.write_bytes(b"\x89PNG edited")
    call, edited = plan()
    assert call.cache_status == "miss"
    falaw.execute_plan(edited)
    assert len(sent) == 2 and len(uploads) == 2


def test_the_eager_op_uploads_a_local_guide_before_sending(guide, uploads, sent):
    generate_image_with_control("p", [{"mode": "depth", "image": guide}])
    assert uploads == [str(guide)]
    ((application, arguments),) = sent
    assert application == MODEL
    assert arguments["easycontrols"][0]["image_url"] == "https://v3b.fal.media/up/1.png"


def test_a_malformed_call_is_refused_before_any_upload(guide, uploads, sent):
    with pytest.raises(ValueError, match="not one of"):
        generate_image_with_control("p", [{"mode": "subject", "image": guide}])
    assert uploads == [] and sent == []


def test_the_eager_op_sends_what_the_plan_would(sent):
    control = [{"mode": "pose", "image": GUIDE, "scale": 0.5}]
    result = generate_image_with_control("p", control)
    planned = plan_generate_image_with_control("p", control, consult_cache=False)
    assert sent == [(planned.application, planned.arguments)]
    assert result.assets[0].url == "https://v3.fal.media/out.png"


def test_a_catalogued_model_that_ignores_control_is_refused(sent):
    control = [{"mode": "canny", "image": GUIDE}]
    with pytest.raises(ValueError, match="ignores structural control"):
        plan_generate_image_with_control(
            "p", control, model_id="fal-ai/flux/dev", consult_cache=False
        )
    with pytest.raises(ValueError, match="ignores structural control"):
        generate_image_with_control("p", control, model_id="fal-ai/flux/dev")
    assert sent == []


def test_an_unlisted_model_passes_through(sent):
    control = [{"mode": "canny", "image": GUIDE}]
    generate_image_with_control("p", control, model_id="someone/flux-control-fork")
    ((application, arguments),) = sent
    assert application == "someone/flux-control-fork"
    assert arguments["easycontrols"][0]["control_method_url"] == "canny"


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


def test_flux_general_is_refused_for_commercial_use_and_cleared_otherwise():
    row = get_terms(MODEL, "fal")
    assert row is not None
    assert row.license == "LicenseRef-flux-1-dev-non-commercial"
    control = [{"mode": "pose", "image": GUIDE}]
    with pytest.raises(FalTermsViolation, match="commercial_use"):
        plan_generate_image_with_control(
            "p", control, consult_cache=False, terms_context=TermsContext()
        )
    personal = TermsContext(commercial=False)
    call = plan_generate_image_with_control(
        "p", control, consult_cache=False, terms_context=personal
    )
    assert is_cleared(call, personal)
