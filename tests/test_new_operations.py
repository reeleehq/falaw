"""Smoke tests for new operations: monkeypatch fal_client.subscribe so no API key is needed."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_journal(tmp_path, monkeypatch):
    monkeypatch.setenv("FALAW_DATA_DIR", str(tmp_path))
    from falaw.journal import _default_journal

    _default_journal.cache_clear()
    yield
    _default_journal.cache_clear()


def _patch_subscribe(monkeypatch, response_for):
    """Patch fal_client.subscribe to return whatever response_for(application) yields.

    response_for: callable taking application_id -> response dict.
    Records calls in the returned `captured` list.
    """
    import fal_client

    captured: list[dict] = []

    def fake(application, *, arguments, **_kw):
        captured.append({"application": application, "arguments": arguments})
        return response_for(application)

    monkeypatch.setattr(fal_client, "subscribe", fake)
    return captured


def test_edit_image(monkeypatch):
    captured = _patch_subscribe(
        monkeypatch,
        lambda app: {
            "images": [{"url": "http://x/edited.png", "content_type": "image/png"}]
        },
    )
    from falaw import edit_image

    r = edit_image("http://x/in.png", "make it blue", quality="balanced")
    assert captured[0]["application"] == "fal-ai/flux-kontext/dev"
    assert captured[0]["arguments"]["image_url"] == "http://x/in.png"
    assert captured[0]["arguments"]["prompt"] == "make it blue"
    assert r.first.url == "http://x/edited.png"


def test_upscale_image(monkeypatch):
    captured = _patch_subscribe(
        monkeypatch,
        lambda app: {"images": [{"url": "http://x/big.png"}]},
    )
    from falaw import upscale_image

    r = upscale_image("http://x/in.png", scale=4.0)
    assert captured[0]["application"] == "fal-ai/clarity-upscaler"
    assert captured[0]["arguments"]["scale"] == 4.0
    assert r.first.url == "http://x/big.png"


def test_remove_background(monkeypatch):
    captured = _patch_subscribe(
        monkeypatch,
        lambda app: {
            "image": {"url": "http://x/cutout.png", "content_type": "image/png"}
        },
    )
    from falaw import remove_background

    r = remove_background("http://x/in.png")
    assert "birefnet" in captured[0]["application"]
    assert r.first.url == "http://x/cutout.png"


def test_text_to_video(monkeypatch):
    captured = _patch_subscribe(
        monkeypatch,
        lambda app: {"video": {"url": "http://x/clip.mp4", "duration": 5.0}},
    )
    from falaw import text_to_video

    r = text_to_video("a sunset over Lisbon", quality="high")
    assert (
        captured[0]["application"] == "fal-ai/bytedance/seedance/v1/pro/text-to-video"
    )
    assert r.first.kind == "video"
    assert r.first.duration_s == 5.0


def test_image_to_video(monkeypatch):
    captured = _patch_subscribe(
        monkeypatch,
        lambda app: {"video": {"url": "http://x/animated.mp4"}},
    )
    from falaw import image_to_video

    r = image_to_video("http://x/in.jpg", "the camera pans left", quality="balanced")
    assert "image-to-video" in captured[0]["application"]
    assert captured[0]["arguments"]["prompt"] == "the camera pans left"
    assert r.first.url == "http://x/animated.mp4"


def test_voice_clone(monkeypatch):
    captured = _patch_subscribe(
        monkeypatch,
        lambda app: {"audio_url": "http://x/cloned.mp3"},
    )
    from falaw import voice_clone

    r = voice_clone("http://x/ref.wav", "hello in my voice")
    assert captured[0]["application"] == "fal-ai/minimax/voice-clone"
    assert captured[0]["arguments"]["reference_audio_url"] == "http://x/ref.wav"
    assert r.first.kind == "audio"


def test_lipsync_takes_video_url(monkeypatch):
    """lipsync re-syncs an existing VIDEO clip; image+audio is animate_face's job."""
    captured = _patch_subscribe(
        monkeypatch,
        lambda app: {"video": {"url": "http://x/synced.mp4"}},
    )
    from falaw import lipsync

    r = lipsync("http://x/clip.mp4", "http://x/audio.mp3")
    assert captured[0]["application"] == "fal-ai/sync-lipsync/v2"
    assert captured[0]["arguments"]["video_url"] == "http://x/clip.mp4"
    assert r.first.kind == "video"


def test_animate_face_image_plus_audio(monkeypatch):
    """animate_face is the still-image+audio → talking video primitive."""
    captured = _patch_subscribe(
        monkeypatch,
        lambda app: {"video": {"url": "http://x/talking.mp4"}},
    )
    from falaw import animate_face

    r = animate_face("http://x/face.jpg", "http://x/audio.mp3", prompt="warm")
    assert (
        "avatar" in captured[0]["application"]
        or "omnihuman" in captured[0]["application"]
    )
    assert captured[0]["arguments"]["image_url"] == "http://x/face.jpg"
    # ai-avatar requires `prompt`; omnihuman accepts it. We always pass it.
    assert "prompt" in captured[0]["arguments"]
    assert r.first.kind == "video"


def test_talking_avatar_from_text_chains_via_animate_face(monkeypatch):
    """Composer should TTS first, then pass the audio URL into animate_face."""

    def response_for(app):
        if "tts" in app or "speech" in app:
            return {
                "audio": {"url": "http://x/spoken.mp3", "content_type": "audio/mpeg"}
            }
        return {"video": {"url": "http://x/talking.mp4"}}

    captured = _patch_subscribe(monkeypatch, response_for)
    from falaw import talking_avatar_from_text

    r = talking_avatar_from_text("Hello world.", "http://x/face.jpg")
    assert len(captured) == 2, f"expected 2 fal calls, got {len(captured)}"
    assert "tts" in captured[0]["application"] or "speech" in captured[0]["application"]
    # Second call should hit the avatar (image+audio) family, NOT lipsync.
    assert (
        "avatar" in captured[1]["application"]
        or "omnihuman" in captured[1]["application"]
    )
    assert captured[1]["arguments"]["audio_url"] == "http://x/spoken.mp3"
    assert captured[1]["arguments"]["image_url"] == "http://x/face.jpg"
    assert r.first.kind == "video"
