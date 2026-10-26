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
    assert full.cost_basis.quantities == {"tokens": 86400}  # 1280*720*4*24/1024
    p480 = falaw.plan_image_to_video(
        "u",
        model_id="bytedance/seedance-2.0/image-to-video",
        extra={"resolution": "480p"},
        **kw,
    )
    assert p480.cost_basis.quantities == {"tokens": round(854 * 480 * 4 * 24 / 1024)}


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
    with pytest.raises(ValueError, match="does not offer resolution"):
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


@pytest.mark.parametrize("seconds", [2, 30, float("nan")])
def test_a_duration_the_model_would_reject_is_refused_not_quoted(seconds):
    with pytest.raises(ValueError):
        falaw.plan_image_to_video(
            "u",
            model_id="bytedance/seedance-2.0/image-to-video",
            duration_s=seconds,
            consult_cache=False,
        )


def test_a_resolution_the_model_does_not_offer_is_refused():
    with pytest.raises(ValueError, match="does not offer resolution"):
        falaw.plan_image_to_video(
            "u",
            model_id="bytedance/seedance-2.0/fast/image-to-video",
            duration_s=5,
            extra={"resolution": "1080p"},
            consult_cache=False,
        )


def test_empty_or_auto_duration_is_unknown_not_free():
    for bad in ("", "auto", True):
        p = falaw.plan_text_to_video(
            "x",
            model_id="seedance2-t2v",
            extra={"duration": bad},
            consult_cache=False,
        )
        assert p.estimated_cost_usd is None


def test_half_seconds_round_to_even_like_the_ts_twin():
    kw = dict(model_id="seedance2-t2v", consult_cache=False)
    assert (
        falaw.plan_text_to_video("x", duration_s=4.5, **kw).arguments["duration"] == "4"
    )
    assert (
        falaw.plan_text_to_video("x", duration_s=5.5, **kw).arguments["duration"] == "6"
    )


def test_duration_rule_rejects_what_the_default_model_would():
    from falaw.cost import video_duration_arg

    with pytest.raises(ValueError):
        video_duration_arg(
            falaw.get_model("fal-ai/bytedance/seedance/v1/pro/image-to-video"), 30
        )


def test_reference_limits_surface_through_model_constraints():
    c = falaw.model_constraints("seedance2-ref")
    assert c["max_references"] == {"image_urls": 9, "video_urls": 3, "audio_urls": 3}
    assert falaw.model_constraints("seedance2-i2v")["max_references"] == {}
