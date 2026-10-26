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
        extra={"aspect_ratio": "16:9"},
        consult_cache=False,
    )
    # 1280*720*24*5/1024 tokens at $0.014 per 1k; the issue measured ~$0.3034/s.
    assert p.estimated_cost_usd == pytest.approx(5 * 0.3024, rel=1e-3)
    assert p.arguments["duration"] == "5"  # what is quoted is what is sent
    assert p.cost_basis.quantities == {"tokens": 108000}


def test_fast_is_eighty_percent_and_resolution_follows_extra():
    kw = dict(duration_s=4, consult_cache=False)
    wide = {"aspect_ratio": "16:9"}
    full = falaw.plan_image_to_video(
        "u", model_id="bytedance/seedance-2.0/image-to-video", extra=wide, **kw
    )
    fast = falaw.plan_image_to_video(
        "u", model_id="bytedance/seedance-2.0/fast/image-to-video", extra=wide, **kw
    )
    assert fast.estimated_cost_usd == pytest.approx(0.8 * full.estimated_cost_usd)
    assert full.cost_basis.quantities == {"tokens": 86400}  # 1280*720*4*24/1024
    p480 = falaw.plan_image_to_video(
        "u",
        model_id="bytedance/seedance-2.0/image-to-video",
        extra={**wide, "resolution": "480p"},
        **kw,
    )
    assert p480.cost_basis.quantities == {
        "tokens": round(480 * 480 * 16 / 9 * 4 * 24 / 1024)
    }


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
    p = falaw.plan_text_to_video(
        "a fox", duration_s=5, extra={"aspect_ratio": "16:9"}, consult_cache=False
    )
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


# --- falaw#95 ---------------------------------------------------------------------


def test_the_aspect_ratio_changes_the_frame_not_just_the_label():
    from falaw.cost import frame_pixels

    assert frame_pixels("720p") == 1280 * 720  # 16:9 by default / when auto
    assert frame_pixels("720p", "auto") == frame_pixels("720p", "16:9")
    assert frame_pixels("720p", "9:16") == frame_pixels(
        "720p", "16:9"
    )  # portrait, same area
    assert frame_pixels("720p", "21:9") == pytest.approx(720 * 720 * 21 / 9)
    assert frame_pixels("720p", "1:1") == 720 * 720
    with pytest.raises(ValueError, match="aspect_ratio"):
        frame_pixels("720p", "wide")
    kw = dict(model_id="seedance2-t2v", duration_s=5, consult_cache=False)
    wide = falaw.plan_text_to_video("x", extra={"aspect_ratio": "21:9"}, **kw)
    square = falaw.plan_text_to_video("x", extra={"aspect_ratio": "1:1"}, **kw)
    assert wide.estimated_cost_usd > square.estimated_cost_usd * 1.5


def test_seedance_15_is_quoted_at_the_audio_on_default_rate():
    p = falaw.plan_text_to_video(
        "x",
        model_id="seedance15-t2v",
        duration_s=5,
        consult_cache=False,
    )
    tokens = round(1280 * 720 * 5 * 24 / 1024)
    assert p.estimated_cost_usd == pytest.approx(
        tokens * 2.4e-6
    )  # fal page: $2.40/M with audio
    assert falaw.model_params("seedance15-t2v")["generate_audio"]["default"] is True


def test_new_models_state_their_real_tier_but_are_never_default_picks():
    rec = falaw.get_model("seedance2-t2v")
    assert rec.quality_tier == "high" and rec.default_pick is False
    assert falaw.pick_model(category="text_to_video", quality_tier="high").id == (
        "fal-ai/bytedance/seedance/v1/pro/text-to-video"
    )
    assert (
        falaw.pick_model(category="image", quality_tier="high").id
        == "fal-ai/flux-pro/v1.1"
    )
    # a category made only of opted-out records still answers
    assert falaw.pick_model(category="reference_to_video").default_pick


def test_an_opted_out_only_category_still_answers_and_others_skip_opted_out(
    monkeypatch,
):
    import falaw.registry as registry
    from falaw.base import ModelRecord

    only_hidden = [
        ModelRecord(id="h", category="c", quality_tier="high", default_pick=False)
    ]
    mixed = [
        ModelRecord(id="hidden", category="c", quality_tier="high", default_pick=False),
        ModelRecord(id="shown", category="c", quality_tier="high"),
    ]
    monkeypatch.setattr(
        registry, "list_models", lambda category=None, **kw: only_hidden
    )
    assert registry.pick_model(category="c", quality_tier="high").id == "h"
    monkeypatch.setattr(registry, "list_models", lambda category=None, **kw: mixed)
    assert registry.pick_model(category="c", quality_tier="high").id == "shown"


def test_default_picks_are_stable_under_the_refresh_sort_in_every_category():
    for category in {m.category for m in falaw.list_models()}:
        ms = sorted(
            (m for m in falaw.list_models(category=category) if m.default_pick),
            key=lambda m: (m.quality_tier, m.id),
        )
        for tier in ("fast", "balanced", "high", "ultra"):
            first = next((m for m in ms if m.quality_tier == tier), None)
            if first is not None:
                assert (
                    first.id
                    == falaw.pick_model(category=category, quality_tier=tier).id
                )


def test_seedream_explicit_sizes_are_checked_while_planning_is_free():
    ok = falaw.plan_generate_image(
        "x",
        model_id="seedream45",
        extra={"image_size": {"width": 2560, "height": 1440}},
        consult_cache=False,
    )
    assert ok.arguments["image_size"] == {"width": 2560, "height": 1440}
    for size in (
        {"width": 1024, "height": 1024},
        {"width": 4097, "height": 4097},
        {"width": "2560", "height": 1440},
        {"width": 2560.0, "height": 1440},
    ):
        with pytest.raises(ValueError, match="total pixels|integer width"):
            falaw.plan_generate_image(
                "x",
                model_id="seedream45",
                extra={"image_size": size},
                consult_cache=False,
            )
    # presets and models without bounds are untouched
    falaw.plan_generate_image("x", model_id="seedream45", consult_cache=False)
    falaw.plan_generate_image(
        "x",
        model_id="fal-ai/flux/dev",
        extra={"image_size": {"width": 64, "height": 64}},
        consult_cache=False,
    )


def test_plan_reference_to_video_checks_counts_and_prices():
    p = falaw.plan_reference_to_video(
        "x",
        image_urls=["a", "b"],
        audio_urls=["c"],
        duration_s=5,
        consult_cache=False,
    )
    assert p.tool == "reference_to_video" and p.application.endswith(
        "reference-to-video"
    )
    assert p.arguments["image_urls"] == ["a", "b"] and "video_urls" not in p.arguments
    assert p.arguments["duration"] == "5" and p.estimated_cost_usd > 0
    with pytest.raises(ValueError, match="at most 3 video_urls"):
        falaw.plan_reference_to_video("x", video_urls=["v"] * 4, consult_cache=False)


def test_eager_video_duration_matches_the_planners(monkeypatch):
    sent = []
    monkeypatch.setattr(
        "falaw.operations.video.call_fal",
        lambda model, arguments, **kw: sent.append((model, arguments)) or {},
    )
    falaw.text_to_video("x", model_id="seedance2-t2v", duration_s=5)
    planned = falaw.plan_text_to_video(
        "x", model_id="seedance2-t2v", duration_s=5, consult_cache=False
    )
    assert sent[0] == (planned.application, planned.arguments)
    with pytest.raises(ValueError, match="duration_s is only sent"):
        falaw.text_to_video("x", model_id="fal-ai/veo3", duration_s=5)
    falaw.image_to_video("u", model_id="seedance2-i2v")  # no duration: untouched


def test_the_size_limit_holds_for_the_edit_verbs_and_the_eager_call(monkeypatch):
    bad = {"image_size": {"width": 100, "height": 100}}
    with pytest.raises(ValueError):
        falaw.plan_edit_image("u", "x", model_id="seedream45-edit", extra=bad)
    monkeypatch.setattr(
        "falaw.core._import_fal_client", lambda: pytest.fail("reached the network")
    )
    with pytest.raises(ValueError, match="total pixels"):
        falaw.generate_image("x", model_id="seedream45", extra=bad)


def test_reference_limits_hold_however_the_urls_arrive():
    with pytest.raises(ValueError, match="at most 3 video_urls"):
        falaw.plan_reference_to_video(
            "x", extra={"video_urls": ["v"] * 9}, consult_cache=False
        )
    with pytest.raises(TypeError, match="not one string"):
        falaw.plan_reference_to_video("x", image_urls="ab", consult_cache=False)
    with pytest.raises(ValueError, match="must be a list"):
        falaw.plan_reference_to_video(
            "x", extra={"image_urls": "ab"}, consult_cache=False
        )


def test_eager_resolves_aliases_like_the_planner_with_or_without_a_duration(
    monkeypatch,
):
    sent = []
    monkeypatch.setattr(
        "falaw.operations.video.call_fal",
        lambda model, arguments, **kw: sent.append((model, arguments)) or {},
    )
    falaw.text_to_video("x", model_id="seedance2-t2v")
    planned = falaw.plan_text_to_video(
        "x", model_id="seedance2-t2v", consult_cache=False
    )
    assert sent[0] == (planned.application, planned.arguments)


@pytest.mark.parametrize("ratio", ["+16:9", "1_6:9", "0:0", "1.5:1", "16:9:1"])
def test_aspect_ratios_parse_strictly(ratio):
    from falaw.cost import frame_pixels

    with pytest.raises(ValueError, match="aspect_ratio"):
        frame_pixels("720p", ratio)


# ---------------------------------------------------------------------------
# Ceilings: auto aspect, 4K and reference-video rates (falaw#99)
# ---------------------------------------------------------------------------


def test_auto_aspect_is_quoted_at_the_widest_listed_ratio():
    from falaw.cost import quote_aspect

    rec = falaw.get_model("seedance2-i2v")
    assert quote_aspect(rec, "auto") == quote_aspect(rec) == "21:9"
    assert quote_aspect(rec, "9:16") == "9:16"  # explicit wins
    assert (
        quote_aspect(falaw.get_model("flux-dev")) == "16:9"
    )  # no enum: the house default


def test_a_21_9_result_is_never_under_quoted():
    kw = dict(model_id="seedance2-i2v", duration_s=5, consult_cache=False)
    auto = falaw.plan_image_to_video("u", **kw)
    wide = falaw.plan_image_to_video("u", extra={"aspect_ratio": "21:9"}, **kw)
    assert auto.cost_basis.quantities == wide.cost_basis.quantities


def test_4k_bills_the_lower_per_token_rate():
    kw = dict(model_id="seedance2-t2v", duration_s=5, consult_cache=False)
    full = falaw.plan_text_to_video(
        "x", extra={"aspect_ratio": "16:9", "resolution": "4k"}, **kw
    )
    pixels = 3840 * 2160
    # fal: $0.008/1k at 4K; the factor rounds up, so the quote is a ceiling just above it.
    exact = pixels * 5 * 24 / 1024 * 0.008e-3
    assert exact <= full.estimated_cost_usd <= exact * 1.01


def test_resolution_rate_factors_are_well_formed():
    for rec in falaw.list_models():
        for res, factor in rec.resolution_rate_factors.items():
            assert res in rec.supported_resolutions, (rec.id, res)
            assert 0 < factor <= 1, (rec.id, res, factor)


def test_4k_quote_is_the_1080p_style_math_times_the_factor():
    rec = falaw.get_model("seedance2-t2v")
    at_4k = video_price_quantities(rec, seconds=5, resolution="4k", aspect_ratio="16:9")
    expected = 3840 * 2160 * 5 * rec.tokens_per_pixel_second * 0.572
    assert at_4k["tokens"] == round(expected)
    # No factor for a resolution that bills the recorded rate.
    at_1080 = video_price_quantities(rec, seconds=5, resolution="1080p", aspect_ratio="16:9")
    assert at_1080["tokens"] == round(1920 * 1080 * 5 * rec.tokens_per_pixel_second)


def test_reference_videos_are_not_discounted_until_fal_billing_is_verified():
    kw = dict(model_id="seedance2-ref", duration_s=5, consult_cache=False)
    images = falaw.plan_reference_to_video("x", image_urls=["https://x/a.png"], **kw)
    videos = falaw.plan_reference_to_video("x", video_urls=["https://x/a.mp4"], **kw)
    assert videos.estimated_cost_usd == images.estimated_cost_usd
