"""``plan_generate_audio`` / ``generate_audio`` — the ambient/SFX/music primitive (falaw#10).

The user this exists for leaves his editor to hunt city-night ambient beds;
the models that generate them were already in the registry with nothing able
to plan, cost, or cache a call. The load-bearing choices under test: kinds
route to PROMPT-driven models (the music category's first balanced entry is
lyrics-driven DiffRhythm — a bare prompt would make a structurally valid
call that runs, bills, and produces nothing asked for), plans are pure data
with a non-None cost, and planned/eager calls share one argument shape so
they collapse to the same cache entry.
"""

from __future__ import annotations

import pytest

from falaw import plan_generate_audio
from falaw.operations._plan import GENERATE_AUDIO_DEFAULTS


def test_the_issue_acceptance_case_plans_costed_with_no_network():
    p = plan_generate_audio("rain on a tin roof", kind="ambient", duration_s=12)
    assert p.tool == "generate_audio"
    assert p.output_kind == "audio"
    assert p.application == "fal-ai/stable-audio-3/small/sfx/text-to-audio"
    assert p.arguments == {"prompt": "rain on a tin roof", "duration": 12.0}
    assert p.estimated_cost_usd is not None and p.estimated_cost_usd > 0


def test_kinds_route_to_prompt_driven_models_only():
    """DiffRhythm generates songs from LYRICS; it must never be a default a
    bare prompt reaches — model_id= is the door for callers who bring the
    right arguments."""
    assert plan_generate_audio("x", kind="sfx").application == (
        "fal-ai/stable-audio-3/small/sfx/text-to-audio"
    )
    music = plan_generate_audio("gentle acoustic guitar", kind="music")
    assert music.application == "fal-ai/lyria2"
    assert "diffrhythm" not in {m for m in GENERATE_AUDIO_DEFAULTS.values()}
    with pytest.raises(ValueError, match="unknown kind"):
        plan_generate_audio("x", kind="dialogue")


def test_duration_reaches_only_models_that_take_one():
    ambient = plan_generate_audio("wind", kind="ambient", duration_s=7.4)
    assert ambient.arguments["duration"] == 7.4
    mm = plan_generate_audio(
        "wind", kind="sfx", duration_s=7.4, model_id="fal-ai/mmaudio-v2/text-to-audio"
    )
    assert mm.arguments["duration"] == 7  # mmaudio takes integer seconds
    music = plan_generate_audio("waltz", kind="music", duration_s=30)
    assert "duration" not in music.arguments  # estimator-only for lyria2
    assert music.estimated_cost_usd == pytest.approx(30 * 0.0033333, rel=0.01)


def test_explicit_model_id_pins_and_extra_threads():
    p = plan_generate_audio(
        "storm",
        kind="ambient",
        model_id="fal-ai/lyria2",
        extra={"negative_prompt": "voices"},
        metadata={"panel_id": "p01"},
    )
    assert p.application == "fal-ai/lyria2"
    assert p.arguments["negative_prompt"] == "voices"
    assert p.metadata == {"panel_id": "p01"}


def test_planned_and_eager_calls_share_one_argument_shape(monkeypatch):
    """Identical inputs must collapse to the same cache entry, which starts
    with byte-identical (application, arguments)."""
    captured = {}

    def fake_call_fal(application, arguments):
        captured.update({"application": application, "arguments": dict(arguments)})
        return {"audio": {"url": "https://fal.example/x.wav"}}

    import falaw.operations.audio as audio_ops

    monkeypatch.setattr(audio_ops, "call_fal", fake_call_fal)
    from falaw import generate_audio

    generate_audio("rain on a tin roof", kind="ambient", duration_s=12)
    plan = plan_generate_audio("rain on a tin roof", kind="ambient", duration_s=12)
    assert captured["application"] == plan.application
    assert captured["arguments"] == plan.arguments


def test_the_tool_is_registered_for_the_mcp_bridge():
    from falaw.registry import get_tool

    spec = get_tool("generate_audio")
    assert spec.input_schema["properties"]["kind"]["enum"] == [
        "ambient",
        "sfx",
        "music",
    ]


def test_the_generative_audio_models_are_all_priced():
    """The issue's last acceptance criterion — no None cost_estimate among
    the generative audio/music models (an unpriced model reads as free and
    clears any budget, the muvid#47 family)."""
    from falaw.registry import get_model

    for mid in (
        "fal-ai/mmaudio-v2/text-to-audio",
        "fal-ai/lyria2",
        "fal-ai/diffrhythm",
    ):
        assert get_model(mid).cost_estimate is not None, mid


def test_default_sfx_is_not_non_commercial():
    """falaw#88: MMAudio's weights are CC BY-NC; it must stay opt-in."""
    assert "mmaudio" not in GENERATE_AUDIO_DEFAULTS["sfx"]
    assert "mmaudio" not in GENERATE_AUDIO_DEFAULTS["ambient"]


@pytest.mark.parametrize(
    "model_id, prompt_key, duration_key, price",
    [
        ("fal-ai/stable-audio-3/medium/text-to-audio", "prompt", "duration", 0.0376),
        ("mirelo-ai/sfx2.0/text-to-audio", "prompt", "duration", 0.010 * 4),
        ("fal-ai/elevenlabs/sound-effects/v2", "text", "duration_seconds", 0.002 * 4),
        ("sonilo/v1.1/text-to-sound-effects", "prompt", "duration", 0.0018 * 4),
    ],
)
def test_sfx_endpoints_are_priced_and_spelled_per_vendor(
    model_id, prompt_key, duration_key, price
):
    p = plan_generate_audio("door slam", kind="sfx", duration_s=4, model_id=model_id)
    assert p.arguments[prompt_key] == "door slam"
    assert p.arguments[duration_key] == 4
    assert p.estimated_cost_usd == pytest.approx(price)


def test_mirelo_quote_matches_the_bill_by_pinning_one_sample():
    p = plan_generate_audio(
        "x", kind="sfx", duration_s=2, model_id="mirelo-ai/sfx2.0/text-to-audio"
    )
    assert p.arguments["num_samples"] == 1


def test_extract_first_url_reads_list_shaped_audio():
    from falaw.plan import extract_first_url

    raw = {"audio": [{"url": "https://x/a.wav"}, {"url": "https://x/b.wav"}]}
    assert extract_first_url(raw) == "https://x/a.wav"
    assert extract_first_url({"audio": [], "audios": []}) is None
