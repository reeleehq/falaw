"""Token-priced video models: Seedance 2.0 / 1.5 / 1.0 pro and Seedream 4.5 (falaw#86)."""

from __future__ import annotations

import pytest

import falaw
from falaw.cost import video_price_quantities


def test_seedance_2_quote_matches_the_issue_observation():
    p = falaw.plan_image_to_video(
        "https://x/a.png",
        model_id="bytedance/seedance-2.0/image-to-video",
        duration_s=5,
        consult_cache=False,
    )
    # 1280*720*24*5/1024 tokens at $0.014 per 1k; the issue measured ~$0.3034/s.
    assert p.estimated_cost_usd == pytest.approx(5 * 0.3024, rel=1e-3)
    assert p.arguments["duration"] == "5"  # what is quoted is what is sent
    assert p.cost_basis.quantities == {"tokens": 108000}


def test_fast_is_eighty_percent_and_resolution_follows_extra():
    kw = dict(duration_s=4, consult_cache=False)
    full = falaw.plan_image_to_video(
        "u", model_id="bytedance/seedance-2.0/image-to-video", **kw
    )
    fast = falaw.plan_image_to_video(
        "u", model_id="bytedance/seedance-2.0/fast/image-to-video", **kw
    )
    assert fast.estimated_cost_usd == pytest.approx(0.8 * full.estimated_cost_usd)
    p480 = falaw.plan_image_to_video(
        "u",
        model_id="bytedance/seedance-2.0/image-to-video",
        extra={"resolution": "480p"},
        **kw,
    )
    assert p480.estimated_cost_usd < full.estimated_cost_usd


def test_auto_duration_is_unknown_not_free():
    p = falaw.plan_text_to_video(
        "a fox", model_id="bytedance/seedance-2.0/text-to-video", consult_cache=False
    )
    assert p.estimated_cost_usd is None
    assert p.tool == "text_to_video" and p.output_kind == "video"


def test_extra_duration_wins_and_drives_the_quote():
    p = falaw.plan_text_to_video(
        "a fox",
        model_id="fal-ai/bytedance/seedance/v1.5/pro/text-to-video",
        duration_s=5,
        extra={"duration": "8"},
        consult_cache=False,
    )
    assert p.arguments["duration"] == "8"
    assert p.cost_basis.quantities == {"tokens": round(1280 * 720 * 8 * 24 / 1024)}


def test_default_text_to_video_pick_is_stable_and_priced():
    p = falaw.plan_text_to_video("a fox", duration_s=5, consult_cache=False)
    assert p.application == "fal-ai/bytedance/seedance/v1/pro/text-to-video"
    assert p.estimated_cost_usd == pytest.approx(1920 * 1080 * 24 * 5 / 1024 * 2.5e-6)


def test_unknown_resolution_is_refused():
    rec = falaw.get_model("seedance2-i2v")
    with pytest.raises(ValueError, match="unknown resolution"):
        video_price_quantities(rec, seconds=5, resolution="9000p")


def test_per_second_models_are_unchanged():
    rec = falaw.get_model("fal-ai/veo3")
    assert video_price_quantities(rec, seconds=5) == {"seconds": 5}
    assert video_price_quantities(rec) == {}


def test_reference_limits_are_discoverable():
    params = falaw.model_params("seedance2-ref")
    assert params["image_urls"]["max_items"] == 9
    assert params["video_urls"]["max_items"] == 3
    assert falaw.pick_model(category="reference_to_video", quality_tier="high").id == (
        "bytedance/seedance-2.0/reference-to-video"
    )


def test_seedream_45_priced_per_image_and_minimum_size_documented():
    rec = falaw.get_model("seedream45")
    assert rec.cost_estimate.kind == "per_image" and rec.cost_estimate.amount == 0.04
    assert "2560x1440" in rec.description
    assert falaw.get_model("seedream45-edit").category == "image_edit"
    p = falaw.plan_generate_image("a fox", model_id="seedream45", consult_cache=False)
    assert p.estimated_cost_usd == pytest.approx(0.04)
