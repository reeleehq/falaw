"""Every fal model reelee-web sends through reelee's proxy is catalogued and priced (falaw#82).

reelee prices each proxied submission with ``get_model`` + ``estimate_call_cost``;
a model missing here is recorded as an unknown $0.00 and never moves a spend cap.
No network: this reads the committed catalogue only.
"""

import pytest

from falaw import estimate_call_cost, get_model

# The ids in reelee-web's ``FAL_PRICE_TABLE_USD`` (src/ai/image-providers/fal-pricing.ts).
REELEE_WEB_IDS = (
    "fal-ai/flux/schnell",
    "fal-ai/flux/dev",
    "fal-ai/flux-pro/v1.1",
    "fal-ai/flux-pro",
    "fal-ai/flux-pro/v1.1-ultra",
    "fal-ai/ltx-video",
    "fal-ai/ltx-video/image-to-video",
    "fal-ai/mochi-v1",
    "fal-ai/kling-video/v1.5/pro",
    "fal-ai/kling-video/v1.5/standard",
)
VIDEO_IDS = REELEE_WEB_IDS[5:]
CLIP_SECONDS = 5.0


@pytest.mark.parametrize("model_id", REELEE_WEB_IDS)
def test_every_reelee_web_model_is_priced(model_id):
    record = get_model(model_id)
    assert record.cost_estimate is not None
    assert estimate_call_cost(record, seconds=CLIP_SECONDS) > 0


@pytest.mark.parametrize("model_id", VIDEO_IDS)
def test_video_models_declare_a_clip_limit(model_id):
    record = get_model(model_id)
    assert record.max_clip_seconds is not None
    assert record.max_clip_seconds >= CLIP_SECONDS


@pytest.mark.parametrize(
    "model_id, expected_usd",
    [
        ("fal-ai/ltx-video", 0.02),
        ("fal-ai/ltx-video/image-to-video", 0.02),
        ("fal-ai/mochi-v1", 0.4),
        ("fal-ai/kling-video/v1.5/pro", 0.5),  # $0.1/s
    ],
)
def test_five_second_clip_prices_from_fal_pages(model_id, expected_usd):
    cost = estimate_call_cost(get_model(model_id), seconds=CLIP_SECONDS)
    assert cost == pytest.approx(expected_usd)


def test_bare_kling_pro_id_resolves_to_a_real_endpoint():
    assert get_model("fal-ai/kling-video/v1.5/pro").id.endswith("/pro/image-to-video")


def test_unpublished_price_is_flagged_approximate():
    ce = get_model("fal-ai/kling-video/v1.5/standard").cost_estimate
    assert ce.source == "approximate"


def test_catalogued_only_models_never_become_a_default_pick():
    """Deprecated / research-licence entries are priced, not recommended (``unranked``)."""
    import falaw

    unranked = {m.id for m in falaw.list_models(quality_tier="unranked")}
    assert unranked, "the reelee-web-only models should carry the 'unranked' tier"
    for category in {m.category for m in falaw.list_models()}:
        for tier in ("fast", "balanced", "high", "ultra"):
            assert falaw.pick_model(category=category, quality_tier=tier).id not in unranked
