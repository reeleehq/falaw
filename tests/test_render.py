"""End-to-end smoke tests for the directorial workflow.

We monkeypatch fal_client.subscribe to avoid network calls, but the
test exercises the real Scene IR + cache + render pipeline.
"""

from __future__ import annotations

import pytest

from falaw.scene import (
    Beat,
    Character,
    Environment,
    Scene,
    Voice,
    make_beat,
    make_shot,
)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FALAW_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FALAW_CACHE_DIR", str(tmp_path / "cache"))
    from falaw.journal import _default_journal

    _default_journal.cache_clear()
    yield
    _default_journal.cache_clear()


def _patch_fal(monkeypatch):
    """Return a list that grows with each (application, arguments) call."""
    import fal_client

    captured: list[dict] = []

    def fake(application, *, arguments, **_kw):
        captured.append({"application": application, "arguments": dict(arguments)})
        if "tts" in application or "speech" in application or "playai" in application:
            return {
                "audio": {"url": "http://x/spoken.mp3", "content_type": "audio/mpeg"}
            }
        if "ai-avatar" in application or "omnihuman" in application:
            return {"video": {"url": "http://x/talking.mp4"}}
        if "lipsync" in application:
            return {"video": {"url": "http://x/lipsynced.mp4"}}
        if "image-to-video" in application:
            return {"video": {"url": "http://x/i2v.mp4"}}
        if "voice-clone" in application:
            return {"audio_url": "http://x/cloned.mp3"}
        # default: image
        return {"images": [{"url": "http://x/img.png", "content_type": "image/png"}]}

    monkeypatch.setattr(fal_client, "subscribe", fake)
    return captured


def test_render_beat_caches_subsequent_calls(monkeypatch):
    captured = _patch_fal(monkeypatch)
    from falaw import render_beat

    voice = Voice(name="Sarah", reference_audio_url="http://x/sarah.wav")
    sarah = Character(
        name="Sarah",
        description="mid-30s",
        reference_image_url="http://x/sarah-face.png",
        voice=voice,
    )
    beat = make_beat("Sarah", "Why are you here?", emotion="wary", index=0)

    first = render_beat(beat, sarah)
    assert first["cache_hit"] is False
    assert first["video_url"] == "http://x/talking.mp4"
    assert first["audio_url"]  # cloned audio URL set

    calls_after_first = len(captured)
    second = render_beat(beat, sarah)
    assert second["cache_hit"] is True
    # No additional fal calls on the second render.
    assert len(captured) == calls_after_first


def test_edited_beat_invalidates_outer_cache(monkeypatch):
    """A beat-level edit must invalidate the render_beat cache.

    Whether the *underlying* fal calls re-fire depends on whether the
    edit propagates to model arguments (e.g. emotion is not currently
    passed to TTS, so the inner cache may still hit). The contract this
    test enforces is: when we hand `render_beat` content it has not
    seen before, it does NOT return a cached manifest.
    """
    _patch_fal(monkeypatch)
    from falaw import render_beat
    from falaw.scene import Beat

    sarah = Character(
        name="Sarah",
        reference_image_url="http://x/face.png",
        voice=Voice(name="Sarah", voice_id="v1"),
    )
    b1 = make_beat("Sarah", "Hello.", emotion="calm", index=0)
    first = render_beat(b1, sarah)
    assert first["cache_hit"] is False

    b2 = Beat(
        id=b1.id,
        speaker=b1.speaker,
        line="Hello.",
        emotion="frantic",
        action=b1.action,
        shot_id=b1.shot_id,
        notes=b1.notes,
    )
    second = render_beat(b2, sarah)
    assert second["cache_hit"] is False
    # And re-rendering the same edit *is* a hit.
    third = render_beat(b2, sarah)
    assert third["cache_hit"] is True


def test_render_scene_orchestrates(monkeypatch):
    captured = _patch_fal(monkeypatch)
    from falaw import render_scene

    sarah = Character(
        name="Sarah",
        reference_image_url="http://x/sarah.png",
        voice=Voice(name="Sarah", voice_id="v1"),
    )
    tom = Character(
        name="Tom",
        reference_image_url="http://x/tom.png",
        voice=Voice(name="Tom", voice_id="v2"),
    )
    diner = Environment(name="diner", description="1950s diner")
    shot = make_shot(
        "two-shot at the booth",
        framing="medium",
        environment="diner",
        characters=("Sarah", "Tom"),
        index=0,
    )
    scene = Scene(
        title="t",
        characters=(sarah, tom),
        environments=(diner,),
        shots=(shot,),
        beats=(
            make_beat("Sarah", "Why are you here?", shot_id=shot.id, index=0),
            make_beat("Tom", "I came to apologize.", shot_id=shot.id, index=1),
        ),
    )
    manifest = render_scene(scene)
    assert manifest["shot_count"] == 1
    assert manifest["beat_count"] == 2
    assert all(b.get("video_url") for b in manifest["beats"])

    # Re-render the same scene; everything should be a cache hit.
    calls_before = len(captured)
    again = render_scene(scene)
    assert again["cache_hits"] >= 3  # 1 shot + 2 beats
    assert len(captured) == calls_before


def test_render_scene_skips_empty_beats(monkeypatch):
    _patch_fal(monkeypatch)
    from falaw import render_scene

    a = Character(
        name="A",
        reference_image_url="http://x/a.png",
        voice=Voice(name="A", voice_id="v"),
    )
    scene = Scene(
        title="t",
        characters=(a,),
        beats=(
            make_beat("A", "", action="", index=0),  # empty
            make_beat("A", "Hello.", index=1),
        ),
    )
    m = render_scene(scene)
    assert m["beat_count"] == 2
    assert any("skipped" in b for b in m["beats"])


def test_render_beat_avatar_model_id_override(monkeypatch):
    """avatar_model_id forces a specific avatar model regardless of quality tier."""
    captured = _patch_fal(monkeypatch)
    from falaw import render_beat

    sarah = Character(
        name="Sarah",
        description="mid-30s",
        reference_image_url="http://x/face.png",
        voice=Voice(name="Sarah", voice_id="v1"),
    )
    beat = make_beat("Sarah", "Hello.", emotion="calm", index=0)

    render_beat(beat, sarah, avatar_model_id="fal-ai/bytedance/omnihuman/v1.5")

    avatar_calls = [c for c in captured if "omnihuman" in c["application"]]
    assert len(avatar_calls) == 1, (
        f"expected exactly one omnihuman call when avatar_model_id is set, "
        f"got {[c['application'] for c in captured]}"
    )


def test_render_shot_image_model_id_override(monkeypatch):
    """image_model_id forces a specific image model regardless of quality tier."""
    captured = _patch_fal(monkeypatch)
    from falaw import render_shot
    from falaw.scene import Shot

    shot = make_shot(description="bell tower at night", framing="wide", index=0)
    render_shot(shot, image_model_id="fal-ai/flux-pro/v1.1")

    img_calls = [c for c in captured if "flux-pro" in c["application"]]
    assert len(img_calls) == 1


def test_render_shot_image_to_video_model_id_override(monkeypatch):
    """image_to_video_model_id forces a specific i2v model when as_video=True."""
    captured = _patch_fal(monkeypatch)
    from falaw import render_shot

    shot = make_shot(description="frosty bells", framing="medium", index=0)
    render_shot(
        shot,
        as_video=True,
        image_to_video_model_id="fal-ai/minimax/hailuo-02/pro/image-to-video",
    )

    i2v_calls = [c for c in captured if "hailuo" in c["application"]]
    assert len(i2v_calls) == 1
