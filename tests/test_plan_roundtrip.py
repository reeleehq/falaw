"""End-to-end Plan/Execute round-trip test.

Exercises the full Phase-1a contract:

1. Build a multi-step Plan (generate_image → image_to_video) without any
   API access.
2. Inspect the Plan: total_cost_usd, cache_hit_savings_usd, has_unknown_costs.
3. Execute via a stubbed fal_client.
4. Verify the resulting Artifacts are well-formed (URLs extracted,
   provenance set, costs propagated).
5. Re-execute and verify the cache short-circuits the second pass — and
   that re-planning shows cache_status='hit'.

This is the keystone test for Phase 1a: it's the first end-to-end proof
that an agent can build a multi-step render plan and drive it without
writing bash glue.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FALAW_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FALAW_CACHE_DIR", str(tmp_path / "cache"))
    from falaw.events import clear_subscribers
    from falaw.journal import _default_journal

    _default_journal.cache_clear()
    clear_subscribers()
    yield
    clear_subscribers()
    _default_journal.cache_clear()


def _patch_fal(monkeypatch):
    """Install a fal_client stub. Returns a list that grows with each call."""
    captured: list[dict] = []

    def subscribe(application, *, arguments, with_logs, on_queue_update):
        captured.append({"application": application, "arguments": dict(arguments)})
        if "image-to-video" in application or "hailuo" in application:
            return {
                "video": {
                    "url": "http://x/animated.mp4",
                    "duration": 8.0,
                    "content_type": "video/mp4",
                }
            }
        if "omnihuman" in application or "ai-avatar" in application:
            return {
                "video": {
                    "url": "http://x/talk.mp4",
                    "duration": 5.0,
                    "content_type": "video/mp4",
                }
            }
        if "flux-kontext" in application or "image_edit" in application:
            return {
                "images": [{"url": "http://x/edited.png", "content_type": "image/png"}]
            }
        # Default: image generation.
        return {"images": [{"url": "http://x/img.png", "content_type": "image/png"}]}

    fake = types.SimpleNamespace(
        InProgress=type("IP", (), {"__init__": lambda s, logs: None}),
        subscribe=subscribe,
    )
    monkeypatch.setitem(sys.modules, "fal_client", fake)
    return captured


def test_two_step_render_plan_roundtrip(monkeypatch, fake_assets):
    """The keystone test: plan → inspect → execute → verify Artifacts."""
    captured = _patch_fal(monkeypatch)
    from falaw import (
        Plan,
        execute_plan,
        plan_generate_image,
        plan_image_to_video,
    )

    # 1. Build a plan WITHOUT any fal contact.
    p1 = plan_generate_image(
        prompt="bell tower in moonlight",
        quality="balanced",
        metadata={"shot_id": "s01", "step": "still"},
    )
    p2 = plan_image_to_video(
        # In real use, p2's image_url would be filled in after p1 executes,
        # or via a placeholder the orchestrator resolves. For this test we
        # use a literal URL to keep the planning step self-contained.
        # Reference the upstream plan_generate_image artifact via the
        # canonical placeholder syntax. The executor rewrites this to
        # artifacts[0].url just before the i2v call fires.
        image_url="<from 0>",
        duration_s=3.0,
        metadata={"shot_id": "s01", "step": "motion"},
    )
    plan = Plan(calls=(p1, p2))
    assert captured == [], "planning should not have made any API calls"

    # 2. Inspect — should report a positive cost from the populated estimates.
    assert plan.total_cost_usd > 0
    assert plan.cache_hit_savings_usd == 0  # nothing cached yet
    assert plan.has_unknown_costs is False, (
        f"both ops should have populated cost_estimate; plan: "
        f"{[(c.tool, c.application, c.estimated_cost_usd) for c in plan.calls]}"
    )

    # p1 has no placeholder, so its peek is trustworthy: 'miss' (nothing
    # cached yet). p2 is the chained call — its arguments still hold
    # "<from 0>", so the peek is not (falaw#15 D2): 'unknown', never a
    # fabricated 'miss'.
    assert p1.cache_status == "miss"
    assert p2.cache_status == "unknown"

    # 3. Execute — should produce two Artifacts.
    artifacts = execute_plan(plan)
    assert len(artifacts) == 2

    img_artifact, video_artifact = artifacts
    assert img_artifact.kind == "image"
    assert img_artifact.url == "http://x/img.png"
    assert img_artifact.mime == "image/png"
    assert img_artifact.cost_usd is not None and img_artifact.cost_usd > 0

    assert video_artifact.kind == "video"
    assert video_artifact.url == "http://x/animated.mp4"
    assert video_artifact.duration_s == 8.0
    assert video_artifact.cost_usd is not None and video_artifact.cost_usd > 0

    # Provenance is set.
    assert img_artifact.provenance.was_generated_by.startswith("agent:fal@")
    assert img_artifact.provenance.activity == "create"

    # Captured exactly two fal calls.
    assert len(captured) == 2

    # Artifacts are content-addressed: asset_id is the SHA-256 of the bytes,
    # not of the URL they happened to be served from (falaw#14).
    from lacing import hash_bytes

    img_bytes = fake_assets.synthetic("http://x/img.png")
    assert img_artifact.asset_id == hash_bytes(img_bytes)
    assert img_artifact.bytes_size == len(img_bytes)
    assert video_artifact.asset_id == hash_bytes(
        fake_assets.synthetic("http://x/animated.mp4")
    )

    # 4. Re-execute — cache should short-circuit, no new fal calls.
    captured.clear()
    artifacts_again = execute_plan(plan)
    assert len(captured) == 0, "second execute should hit the cache"
    # Same bytes → same Artifact asset_ids.
    assert artifacts_again[0].asset_id == img_artifact.asset_id
    assert artifacts_again[1].asset_id == video_artifact.asset_id

    # 5. Re-plan — now cache_status should report 'hit'.
    p1_after = plan_generate_image(
        prompt="bell tower in moonlight",
        quality="balanced",
        metadata={"shot_id": "s01", "step": "still"},
    )
    assert p1_after.cache_status == "hit", (
        "after a successful execute, re-planning the same call should report a cache hit"
    )

    # And the post-cache plan reports the savings:
    plan_after = Plan(calls=(p1_after,))
    assert plan_after.total_cost_usd == 0.0  # cache hit means no billable cost
    assert plan_after.cache_hit_savings_usd > 0

    # 6. Re-plan the CHAINED call — this is where D2 lived (falaw#15). Its
    # arguments still hold the unresolved "<from 0>" placeholder; execute
    # keys on the upstream's *resolved* content ref, which the peek cannot
    # reproduce. Before the fix this silently reported "miss" (the unresolved
    # key is never written by anything, so it can only ever fabricate one).
    # It must report "unknown" — a guess is not an observation.
    p2_after = plan_image_to_video(
        image_url="<from 0>",
        duration_s=3.0,
        metadata={"shot_id": "s01", "step": "motion"},
    )
    assert p2_after.cache_status == "unknown", (
        "a chained call's key can't be peeked with an unresolved placeholder "
        "— report 'unknown', never a fabricated 'miss' or 'hit' (falaw#15 D2)"
    )


def test_dry_run_plan_does_not_call_fal(monkeypatch):
    """dry_run=True must not call fal under any circumstance."""
    captured = _patch_fal(monkeypatch)
    from falaw import Plan, execute_plan, plan_generate_image

    plan = Plan(calls=(plan_generate_image(prompt="x"),))
    artifacts = execute_plan(plan, dry_run=True)
    assert captured == []  # no API calls
    assert len(artifacts) == 1
    assert artifacts[0].url is None  # synthetic
    assert artifacts[0].kind == "image"


def test_plan_with_explicit_model_id_pins_application(monkeypatch):
    """plan_*(model_id=…) bypasses pick_model and pins the application field."""
    from falaw import plan_animate_face

    p = plan_animate_face(
        image_url="http://x/face.png",
        audio_url="http://x/voice.mp3",
        model_id="fal-ai/bytedance/omnihuman/v1.5",
        duration_s=8.0,
    )
    assert p.application == "fal-ai/bytedance/omnihuman/v1.5"
    # Cost estimate from the empirical $0.10/s * 8s = $0.80
    assert p.estimated_cost_usd == pytest.approx(0.80)


def test_plan_image_to_video_prices_hailuo_by_the_second(monkeypatch):
    """Hailuo Pro is per_second per fal's rate card ($0.08/s) — duration
    multiplies cost now; the docs-era $0.50/clip was the ~6s default
    approximated as per_call (falaw#18)."""
    from falaw import plan_image_to_video

    p = plan_image_to_video(
        image_url="http://x/img.png",
        model_id="fal-ai/minimax/hailuo-02/pro/image-to-video",
        duration_s=8.0,
    )
    assert p.estimated_cost_usd == pytest.approx(0.64)


def test_plan_text_to_speech_builds_tts_call():
    """plan_text_to_speech mirrors plan_lipsync's shape — tool, application,
    arguments, output_kind. Picks a TTS model by quality tier."""
    from falaw import plan_text_to_speech

    p = plan_text_to_speech(text="Hello world", quality="balanced")
    assert p.tool == "text_to_speech"
    assert p.output_kind == "audio"
    assert p.arguments["text"] == "Hello world"
    assert "voice" not in p.arguments  # omitted when not passed
    assert p.application  # some TTS model resolved


def test_plan_text_to_speech_threads_voice_and_extra():
    from falaw import plan_text_to_speech

    p = plan_text_to_speech(
        text="Salut",
        voice="fr-FR-female-1",
        extra={"stability": 0.5},
        metadata={"panel_id": "p01"},
    )
    assert p.arguments["text"] == "Salut"
    assert p.arguments["voice"] == "fr-FR-female-1"
    assert p.arguments["stability"] == 0.5
    assert p.metadata == {"panel_id": "p01"}


def test_plan_text_to_speech_pins_explicit_model_id():
    from falaw import plan_text_to_speech

    p = plan_text_to_speech(
        text="x",
        model_id="fal-ai/elevenlabs/tts/multilingual-v2",
    )
    assert p.application == "fal-ai/elevenlabs/tts/multilingual-v2"


def test_plan_text_to_speech_prices_per_token_records_via_tokens():
    """ElevenLabs is per_token (char-billed, per its own registry note):
    tokens=len(text) yields a real number; without it the plan stays
    honestly unknown — None, never $0.00."""
    import pytest

    from falaw import plan_text_to_speech

    text = "Hello narration line"
    priced = plan_text_to_speech(
        text=text,
        model_id="fal-ai/elevenlabs/tts/multilingual-v2",
        tokens=len(text),
    )
    assert priced.estimated_cost_usd == pytest.approx(0.00018 * len(text))

    unpriced = plan_text_to_speech(
        text=text, model_id="fal-ai/elevenlabs/tts/multilingual-v2"
    )
    assert unpriced.estimated_cost_usd is None


def test_plan_text_to_speech_tokens_is_an_estimator_hint_not_an_argument():
    """`tokens` (like `duration_s`) must never move the cache identity: a
    priced plan and an unpriced plan of the same call are the same call."""
    from falaw import plan_text_to_speech

    a = plan_text_to_speech(
        text="x", model_id="fal-ai/elevenlabs/tts/multilingual-v2", tokens=1
    )
    b = plan_text_to_speech(text="x", model_id="fal-ai/elevenlabs/tts/multilingual-v2")
    assert "tokens" not in a.arguments
    assert a.arguments == b.arguments
    assert (a.tool, a.application, a.output_kind) == (
        b.tool,
        b.application,
        b.output_kind,
    )


def test_plan_text_to_speech_minimax_stays_unknown():
    """minimax's record carries no cost_estimate: unpriceable regardless of
    hints — None documents the registry gap instead of inventing a price."""
    from falaw import plan_text_to_speech

    p = plan_text_to_speech(
        text="x", model_id="fal-ai/minimax/speech-02-hd", tokens=1, duration_s=1.0
    )
    assert p.estimated_cost_usd is None


def test_full_plan_with_metadata_threading(monkeypatch):
    """Metadata propagates from CallPlan to executed Artifact's
    producer_call_id-adjacent fields. (Today we attach it via the converter
    only when the orchestrator chooses; the plan carries the raw metadata.)"""
    _patch_fal(monkeypatch)
    from falaw import Plan, execute_plan, plan_generate_image

    p = plan_generate_image(
        prompt="x",
        metadata={"shot_id": "s01", "attributed_to": "user:thor"},
    )
    plan = Plan(calls=(p,))
    artifacts = execute_plan(plan)
    # Default converter reads attributed_to from metadata for provenance.
    assert artifacts[0].provenance.was_attributed_to == "user:thor"
