"""Concurrency knob + iter_render_scene yield-as-done."""

from __future__ import annotations

import threading
import time

import pytest

from falaw.scene import (
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
    from falaw.events import clear_subscribers
    from falaw.journal import _default_journal

    _default_journal.cache_clear()
    clear_subscribers()
    yield
    _default_journal.cache_clear()
    clear_subscribers()


def _patch_fal_with_delay(monkeypatch, *, delay_s: float = 0.05):
    """Stub fal_client.subscribe so each call sleeps then returns."""
    import fal_client

    in_flight = []
    max_in_flight = [0]
    lock = threading.Lock()

    def fake(application, *, arguments, **_kw):
        with lock:
            in_flight.append(1)
            max_in_flight[0] = max(max_in_flight[0], len(in_flight))
        try:
            time.sleep(delay_s)
            if (
                "tts" in application
                or "speech" in application
                or "playai" in application
            ):
                return {
                    "audio": {
                        "url": "http://x/spoken.mp3",
                        "content_type": "audio/mpeg",
                    }
                }
            if "ai-avatar" in application or "omnihuman" in application:
                return {"video": {"url": "http://x/talking.mp4"}}
            if "image-to-video" in application:
                return {"video": {"url": "http://x/i2v.mp4"}}
            if "voice-clone" in application:
                return {"audio_url": "http://x/cloned.mp3"}
            return {
                "images": [{"url": "http://x/img.png", "content_type": "image/png"}]
            }
        finally:
            with lock:
                in_flight.pop()

    monkeypatch.setattr(fal_client, "subscribe", fake)
    return max_in_flight


def _make_scene(n_shots=4, n_beats=4):
    sarah = Character(
        name="Sarah",
        reference_image_url="http://x/sarah.png",
        voice=Voice(name="Sarah", voice_id="v1"),
    )
    diner = Environment(name="diner", description="1950s diner")
    shots = tuple(
        make_shot(
            f"shot {i}",
            framing="medium",
            environment="diner",
            characters=("Sarah",),
            index=i,
        )
        for i in range(n_shots)
    )
    beats = tuple(
        make_beat("Sarah", f"line {i}", shot_id=shots[0].id, index=i)
        for i in range(n_beats)
    )
    return Scene(
        title="t",
        characters=(sarah,),
        environments=(diner,),
        shots=shots,
        beats=beats,
    )


def test_render_scene_concurrency_runs_in_parallel(monkeypatch):
    max_in_flight = _patch_fal_with_delay(monkeypatch, delay_s=0.05)
    from falaw import render_scene

    scene = _make_scene(n_shots=4, n_beats=4)
    t0 = time.time()
    manifest = render_scene(scene, concurrency=4)
    elapsed = time.time() - t0
    assert manifest["shot_count"] == 4
    assert manifest["beat_count"] == 4
    # With concurrency=4 we should observe at least 2 concurrent calls.
    assert max_in_flight[0] >= 2
    # Loose upper bound on wall time: serial would be ~16 * 0.05 = 0.8s.
    # With c=4 we expect under 0.4s; we use a generous 1.0 to avoid CI flake.
    assert elapsed < 1.0


def test_render_scene_serial_default(monkeypatch):
    max_in_flight = _patch_fal_with_delay(monkeypatch, delay_s=0.01)
    from falaw import render_scene

    scene = _make_scene(n_shots=2, n_beats=2)
    render_scene(scene)
    assert max_in_flight[0] == 1, "default concurrency should be serial"


def test_iter_render_scene_yields_kind_pairs(monkeypatch):
    _patch_fal_with_delay(monkeypatch, delay_s=0.0)
    from falaw import iter_render_scene

    scene = _make_scene(n_shots=2, n_beats=2)
    pairs = list(iter_render_scene(scene))
    kinds = [k for k, _ in pairs]
    assert kinds.count("shot") == 2
    assert kinds.count("beat") == 2


def test_iter_render_scene_serial_preserves_order(monkeypatch):
    _patch_fal_with_delay(monkeypatch, delay_s=0.0)
    from falaw import iter_render_scene

    scene = _make_scene(n_shots=3, n_beats=2)
    pairs = list(iter_render_scene(scene, concurrency=1))
    kinds = [k for k, _ in pairs]
    # Serial: all shots first, then all beats.
    assert kinds == ["shot", "shot", "shot", "beat", "beat"]


def test_iter_render_scene_yields_results_as_completed_under_concurrency(
    monkeypatch,
):
    """With concurrency > 1, results should be yielded incrementally."""
    _patch_fal_with_delay(monkeypatch, delay_s=0.02)
    from falaw import iter_render_scene

    scene = _make_scene(n_shots=4, n_beats=0)

    delivered = []
    for kind, result in iter_render_scene(scene, concurrency=4):
        delivered.append((kind, time.time()))

    # Expect at least 4 deliveries.
    assert len(delivered) == 4
    # Span between first and last should be small — they ran in parallel.
    span = delivered[-1][1] - delivered[0][1]
    assert span < 0.5


def test_render_scene_workers_see_the_bound_byo_key(monkeypatch):
    """A pool worker must authenticate with the caller's bound key.

    Without ``copy_context().run`` per task the worker sees no bound key, falls
    back to the module-level ``subscribe`` (the operator's env key) and bills the
    wrong account. Fake transport only; the key is a made-up marker.
    """
    import sys
    import types

    from falaw import iter_render_scene, using_fal_credentials

    paths: list = []
    image = {"images": [{"url": "http://x/img.png", "content_type": "image/png"}]}

    def module_subscribe(application, *, arguments, **_kw):
        paths.append(("module", None))
        return image

    class SyncClient:
        def __init__(self, key=None, default_timeout=120.0):
            self.key = key

        def subscribe(self, application, *, arguments, **_kw):
            paths.append(("client", self.key))
            return image

    fake = types.SimpleNamespace(
        InProgress=type("InProgress", (), {}),
        subscribe=module_subscribe,
        SyncClient=SyncClient,
    )
    monkeypatch.setitem(sys.modules, "fal_client", fake)
    scene = _make_scene(n_shots=3, n_beats=0)
    with using_fal_credentials("byo-test-marker"):
        list(iter_render_scene(scene, concurrency=3))
    assert paths == [("client", "byo-test-marker")] * 3
