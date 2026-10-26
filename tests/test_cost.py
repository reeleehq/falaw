"""CostEstimate + estimate_scene_cost rollup."""

from __future__ import annotations

import pytest

from falaw import (
    Beat,
    Character,
    CostEstimate,
    CostRollup,
    Environment,
    ModelRecord,
    Scene,
    Voice,
    estimate_call_cost,
    estimate_scene_cost,
    make_beat,
    make_shot,
)
from falaw import registry


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FALAW_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FALAW_CACHE_DIR", str(tmp_path / "cache"))


def test_cost_estimate_per_call():
    record = ModelRecord(
        id="x",
        category="image",
        cost_estimate=CostEstimate(kind="per_call", amount=0.05),
    )
    assert estimate_call_cost(record) == pytest.approx(0.05)
    assert estimate_call_cost(record, count=3) == pytest.approx(0.15)


def test_cost_estimate_per_second():
    record = ModelRecord(
        id="x",
        category="text_to_video",
        cost_estimate=CostEstimate(kind="per_second", amount=0.10),
    )
    assert estimate_call_cost(record, seconds=12.0) == pytest.approx(1.20)


def test_cost_estimate_per_second_is_unknown_without_a_duration():
    """An unpriceable per-second call is ``None`` (unknown), never 0.0 (free).

    Reporting 0.0 here would tell a cost gate that the single most
    expensive thing fal bills for is free, and it would spend without
    prompting. See :func:`estimate_call_cost`.
    """
    record = ModelRecord(
        id="x",
        category="text_to_video",
        cost_estimate=CostEstimate(kind="per_second", amount=0.10),
    )
    assert estimate_call_cost(record, seconds=None) is None
    # An *explicit* zero is a real quantity, and still prices at zero.
    assert estimate_call_cost(record, seconds=0.0) == pytest.approx(0.0)


def test_cost_estimate_per_token_is_unknown_without_a_token_count():
    record = ModelRecord(
        id="x",
        category="llm",
        cost_estimate=CostEstimate(kind="per_token", amount=0.002),
    )
    assert estimate_call_cost(record, tokens=None) is None
    assert estimate_call_cost(record, tokens=1000) == pytest.approx(2.0)


def test_unknown_per_second_cost_lights_up_plan_has_unknown_costs():
    """The end of the wire: an unknown duration must reach the gate.

    ``total_cost_usd`` alone reads $0.00 either way (``billable_cost_usd``
    coerces ``None``→0.0 so sums stay well-defined), so ``has_unknown_costs``
    is the *only* signal separating "free" from "unpriceable". This asserts
    it actually fires through a real planner call.
    """
    from falaw import Plan
    from falaw.operations._plan import plan_image_to_video

    # Seedance 2.0 declares duration "auto": nothing to price at when unsent.
    seedance = "bytedance/seedance-2.0/image-to-video"

    unpriced = Plan(calls=(plan_image_to_video("https://e/a.png", model_id=seedance),))
    assert unpriced.has_unknown_costs is True
    assert unpriced.total_cost_usd == pytest.approx(0.0)  # NOT evidence of "free"

    priced = Plan(
        calls=(
            plan_image_to_video("https://e/a.png", model_id=seedance, duration_s=5.0),
        )
    )
    assert priced.has_unknown_costs is False
    assert priced.total_cost_usd > 0


def test_cost_estimate_per_megapixel_uses_default_when_missing():
    record = ModelRecord(
        id="x",
        category="image",
        cost_estimate=CostEstimate(kind="per_megapixel", amount=0.10),
    )
    # Default 0.6 MP if megapixels not supplied.
    assert estimate_call_cost(record) == pytest.approx(0.06)
    assert estimate_call_cost(record, megapixels=2.0) == pytest.approx(0.20)


def test_estimate_call_cost_returns_none_when_no_estimate():
    """Distinguish 'no estimate' from 'free'."""
    record = ModelRecord(id="x", category="image")
    assert estimate_call_cost(record) is None


def test_estimate_scene_cost_aggregates_per_line(monkeypatch):
    """Estimate a scene with one shot + two beats and assert the rollup math."""

    # Override pick_model so test is deterministic and doesn't depend on
    # whatever costs are wired into the live catalog.
    fake_records = {
        "image": ModelRecord(
            id="img-fast",
            category="image",
            quality_tier="balanced",
            cost_estimate=CostEstimate(kind="per_image", amount=0.04),
        ),
        "tts": ModelRecord(
            id="tts-balanced",
            category="tts",
            quality_tier="balanced",
            cost_estimate=CostEstimate(kind="per_second", amount=0.02),
        ),
        "avatar": ModelRecord(
            id="ai-avatar",
            category="avatar",
            quality_tier="high",
            cost_estimate=CostEstimate(kind="per_second", amount=0.10),
        ),
    }

    import falaw.cost as cost_mod

    def fake_pick_model(*, category, quality_tier="balanced"):
        return fake_records[category]

    monkeypatch.setattr(cost_mod, "pick_model", fake_pick_model)

    sarah = Character(
        name="Sarah",
        reference_image_url="http://x/sarah.png",
        voice=Voice(name="Sarah", voice_id="v1"),
    )
    diner = Environment(name="diner", description="1950s diner")
    shot = make_shot(
        "two-shot at the booth",
        framing="medium",
        environment="diner",
        characters=("Sarah",),
        index=0,
    )
    scene = Scene(
        title="t",
        characters=(sarah,),
        environments=(diner,),
        shots=(shot,),
        beats=(
            make_beat("Sarah", "Why are you here?", shot_id=shot.id, index=0),
            make_beat("Sarah", "I came to see you.", shot_id=shot.id, index=1),
        ),
    )

    rollup = estimate_scene_cost(scene)
    assert isinstance(rollup, CostRollup)

    # Expected: 1 image ($0.04) + per-beat (tts + avatar) at 0.4s/word.
    # Beat 1 "Why are you here?" — 4 words → 1.6s.
    # Beat 2 "I came to see you." — 5 words → 2.0s.
    # Beat cost: secs × ($0.02 tts + $0.10 avatar) = secs × 0.12
    expected = 0.04 + 1.6 * 0.12 + 2.0 * 0.12
    assert rollup.total_amount == pytest.approx(expected, abs=0.01)
    by_kind = rollup.by_kind()
    assert "shot.image" in by_kind
    assert "beat.tts" in by_kind
    assert "beat.avatar" in by_kind


def test_estimate_scene_cost_skipped_lists_unpriced_models(monkeypatch):
    """When no cost_estimate is set, the model is reported in 'skipped'."""
    import falaw.cost as cost_mod

    fake_records = {
        "image": ModelRecord(id="img-no-cost", category="image"),  # no estimate
        "tts": ModelRecord(
            id="tts",
            category="tts",
            cost_estimate=CostEstimate(kind="per_second", amount=0.01),
        ),
        "avatar": ModelRecord(
            id="avatar",
            category="avatar",
            cost_estimate=CostEstimate(kind="per_second", amount=0.05),
        ),
    }
    monkeypatch.setattr(
        cost_mod,
        "pick_model",
        lambda *, category, quality_tier="balanced": fake_records[category],
    )

    sarah = Character(
        name="Sarah",
        reference_image_url="http://x/s.png",
        voice=Voice(name="Sarah", voice_id="v"),
    )
    shot = make_shot("a", index=0)
    scene = Scene(title="t", characters=(sarah,), shots=(shot,), beats=())

    rollup = estimate_scene_cost(scene)
    assert any("img-no-cost" in s for s in rollup.skipped)
    # Total should not include the unpriced shot.
    assert rollup.total_amount == 0.0


def test_estimate_scene_cost_includes_video_when_shots_as_video(monkeypatch):
    import falaw.cost as cost_mod

    fake_records = {
        "image": ModelRecord(
            id="i",
            category="image",
            cost_estimate=CostEstimate(kind="per_image", amount=0.04),
        ),
        "image_to_video": ModelRecord(
            id="i2v",
            category="image_to_video",
            cost_estimate=CostEstimate(kind="per_second", amount=0.50),
        ),
    }
    monkeypatch.setattr(
        cost_mod,
        "pick_model",
        lambda *, category, quality_tier="balanced": fake_records[category],
    )

    shot = make_shot("a", index=0)

    # A Shot carries no duration (screen time comes from the renderer's
    # per-shot run, not the IR), and the i2v model here is priced
    # per_second — so the video line is genuinely UNPRICEABLE and is
    # reported in ``skipped`` rather than as a line.
    #
    # This previously emitted a $0.00 ``shot.video`` line: "unknown"
    # laundered into "free" via a `or 0.0` before estimate_call_cost
    # could object. That is strictly worse than omitting it, because a
    # CostRollup carrying a $0.00 line and an empty ``skipped`` looks
    # COMPLETE — a caller gating a budget sees a free clip, not a
    # missing one. ``skipped`` exists for exactly this.
    scene = Scene(title="t", shots=(shot,))
    rollup = estimate_scene_cost(scene, shots_as_video=True)
    kinds = {ln.kind for ln in rollup.lines}
    assert "shot.image" in kinds
    assert "shot.video" not in kinds, "an unpriceable clip must not appear as $0.00"
    assert any("i2v" in s and "duration" in s for s in rollup.skipped), (
        f"the rollup must say WHY the clip is unpriced; got {rollup.skipped}"
    )


def test_estimate_scene_cost_prices_video_when_told_the_clip_length(monkeypatch):
    """Tell it the length and the video line is priced normally.

    The other half of the contract: the "unpriceable" guard is *narrow*.
    A caller who knows the clip length still gets a real number — the
    rollup didn't become useless, it became honest about what it needs.
    """
    from falaw import cost as cost_mod

    fake_records = {
        "image": ModelRecord(
            id="img",
            category="image",
            cost_estimate=CostEstimate(kind="per_image", amount=0.01),
        ),
        "image_to_video": ModelRecord(
            id="i2v",
            category="image_to_video",
            cost_estimate=CostEstimate(kind="per_second", amount=0.50),
        ),
    }
    monkeypatch.setattr(
        cost_mod,
        "pick_model",
        lambda *, category, quality_tier="balanced": fake_records[category],
    )

    rollup = estimate_scene_cost(
        Scene(title="t", shots=(make_shot("a", index=0),)),
        shots_as_video=True,
        shot_seconds=4.0,
    )

    video = [ln for ln in rollup.lines if ln.kind == "shot.video"]
    assert len(video) == 1
    assert video[0].amount == pytest.approx(2.0)  # $0.50/s × 4s
    assert not rollup.skipped


def test_cost_rollup_by_kind_sums_correctly():
    rollup = CostRollup(
        total_amount=0.30,
        lines=(
            cost_line("shot.image", "s1", 0.04),
            cost_line("shot.image", "s2", 0.04),
            cost_line("beat.tts", "b1", 0.10),
            cost_line("beat.avatar", "b1", 0.12),
        ),
    )
    by_kind = rollup.by_kind()
    assert by_kind["shot.image"] == pytest.approx(0.08)
    assert by_kind["beat.tts"] == pytest.approx(0.10)
    assert by_kind["beat.avatar"] == pytest.approx(0.12)


def cost_line(kind, item_id, amount):
    from falaw import CostLine

    return CostLine(
        kind=kind,
        item_id=item_id,
        model_id="m",
        amount=amount,
        currency="USD",
    )


# --- Regression: actively-used models have populated cost_estimate ----------


def test_priced_models_loaded_from_data_json():
    """Selected models in data/models.json must have a populated cost_estimate."""
    from falaw.registry import _load_models

    _load_models.cache_clear()
    models = _load_models()
    must_be_priced = {
        "fal-ai/flux/dev",
        "fal-ai/flux-pro/v1.1",
        "fal-ai/bytedance/omnihuman/v1.5",
        "fal-ai/minimax/hailuo-02/pro/image-to-video",
    }
    for mid in must_be_priced:
        assert mid in models, f"{mid} missing from models.json"
        assert models[mid].cost_estimate is not None, (
            f"{mid} has no cost_estimate populated — agents can't budget without it"
        )


def test_hailuo_uses_per_second_pricing_from_the_vendor_rate_card():
    """Hailuo Pro is billed per video second per fal's pricing API ($0.08/s —
    consistent with the old hand-written '$0.50/clip at the ~6s default').
    The docs-era per_call record was the approximation (falaw#18)."""
    from falaw.registry import _load_models

    _load_models.cache_clear()
    hailuo = _load_models()["fal-ai/minimax/hailuo-02/pro/image-to-video"]
    assert hailuo.cost_estimate is not None
    assert hailuo.cost_estimate.kind == "per_second"
    assert hailuo.cost_estimate.source == "api"
    assert estimate_call_cost(hailuo) is None  # no duration -> unpriceable
    cost = estimate_call_cost(hailuo, seconds=6.0)
    assert cost is not None and cost == pytest.approx(0.48)


def test_omnihuman_per_second_pricing_matches_empirical():
    """OmniHuman cost matches the empirical observation: 8s ≈ $0.80."""
    from falaw.registry import _load_models

    _load_models.cache_clear()
    omni = _load_models()["fal-ai/bytedance/omnihuman/v1.5"]
    assert omni.cost_estimate is not None
    assert omni.cost_estimate.kind == "per_second"
    cost = estimate_call_cost(omni, seconds=8.0)
    assert cost is not None
    # Allow ±25% wiggle: this is ground for fluctuation in fal pricing.
    assert 0.6 < cost < 1.0
