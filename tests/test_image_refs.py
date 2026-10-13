"""Tests for falaw.generate_image_with_refs + plan_generate_image_with_refs.

The reference-conditioned image primitive: unlike ``generate_image`` (pure
text-to-image, where reference images are silently ignored by the model),
this routes to a reference-capable image-edit model (Flux Kontext et al.)
and threads the references as ``image_url`` (first) + ``image_urls`` (all).

This is the missing fal capability behind reelee #173 (character face
consistency across storyboard panels): a recurring subject's reference image
must reach a model that actually ingests it.
"""

from __future__ import annotations

import sys
import types

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


def _patch_fal(monkeypatch, *, response=None):
    captured: list[dict] = []

    def subscribe(application, *, arguments, with_logs, on_queue_update):
        captured.append({"application": application, "arguments": dict(arguments)})
        return response or {
            "images": [{"url": "http://x/out.png", "content_type": "image/png"}]
        }

    fake = types.SimpleNamespace(InProgress=type("IP", (), {}), subscribe=subscribe)
    monkeypatch.setitem(sys.modules, "fal_client", fake)
    return captured


# --- eager op ----------------------------------------------------------------


def test_generate_image_with_refs_threads_single_ref(monkeypatch):
    captured = _patch_fal(monkeypatch)
    from falaw import generate_image_with_refs

    generate_image_with_refs(
        "Alex looks up at the bell",
        ["http://x/alex.png"],
    )
    assert len(captured) == 1
    args = captured[0]["arguments"]
    # First ref anchors the primary subject (singular key) AND appears in the
    # plural key — image-edit models disagree on the param name.
    assert args["image_url"] == "http://x/alex.png"
    assert args["image_urls"] == ["http://x/alex.png"]
    assert args["prompt"] == "Alex looks up at the bell"


def test_generate_image_with_refs_threads_multiple_refs(monkeypatch):
    captured = _patch_fal(monkeypatch)
    from falaw import generate_image_with_refs

    generate_image_with_refs(
        "Alex in the bell tower",
        ["http://x/alex.png", "http://x/tower.png"],
    )
    args = captured[0]["arguments"]
    assert args["image_url"] == "http://x/alex.png"  # first = primary
    assert args["image_urls"] == ["http://x/alex.png", "http://x/tower.png"]


def test_generate_image_with_refs_picks_image_edit_model(monkeypatch):
    """The whole point: route to a model that actually ingests references,
    NOT a text-to-image model that drops them."""
    captured = _patch_fal(monkeypatch)
    from falaw import generate_image_with_refs

    generate_image_with_refs("x", ["http://x/ref.png"])
    app = captured[0]["application"]
    # Default (balanced) image-edit model is Flux Kontext dev.
    assert "kontext" in app or "omnigen" in app or "seededit" in app
    # It is NOT a plain text-to-image flux.
    assert app != "fal-ai/flux/dev"


def test_generate_image_with_refs_model_id_override(monkeypatch):
    captured = _patch_fal(monkeypatch)
    from falaw import generate_image_with_refs

    generate_image_with_refs(
        "x", ["http://x/ref.png"], model_id="fal-ai/flux-pro/kontext/max"
    )
    assert captured[0]["application"] == "fal-ai/flux-pro/kontext/max"


def test_generate_image_with_refs_drops_empty_urls(monkeypatch):
    captured = _patch_fal(monkeypatch)
    from falaw import generate_image_with_refs

    generate_image_with_refs("x", ["", "http://x/ref.png", ""])
    args = captured[0]["arguments"]
    assert args["image_url"] == "http://x/ref.png"
    assert args["image_urls"] == ["http://x/ref.png"]


def test_generate_image_with_refs_merges_extra(monkeypatch):
    captured = _patch_fal(monkeypatch)
    from falaw import generate_image_with_refs

    generate_image_with_refs("x", ["http://x/ref.png"], extra={"guidance_scale": 3.5})
    assert captured[0]["arguments"]["guidance_scale"] == 3.5


def test_generate_image_with_refs_requires_a_ref(monkeypatch):
    _patch_fal(monkeypatch)
    from falaw import generate_image_with_refs

    with pytest.raises(ValueError, match="at least one reference"):
        generate_image_with_refs("x", [])
    with pytest.raises(ValueError, match="at least one reference"):
        generate_image_with_refs("x", ["", ""])


# --- plan_* sibling ----------------------------------------------------------


def test_plan_generate_image_with_refs_shape():
    from falaw import plan_generate_image_with_refs

    cp = plan_generate_image_with_refs(
        "Alex in the tower",
        ["http://x/alex.png", "http://x/tower.png"],
        consult_cache=False,
    )
    assert cp.tool == "generate_image_with_refs"
    assert cp.output_kind == "image"
    assert cp.arguments["image_url"] == "http://x/alex.png"
    assert cp.arguments["image_urls"] == ["http://x/alex.png", "http://x/tower.png"]
    assert cp.arguments["prompt"] == "Alex in the tower"
    # Routes to a reference-capable model, not a plain text-to-image flux.
    assert cp.application != "fal-ai/flux/dev"


def test_plan_and_eager_share_cache_key(monkeypatch):
    """A planned call and an eager call with identical inputs must produce the
    same fal arguments so they collapse to one content-addressed cache entry."""
    captured = _patch_fal(monkeypatch)
    from falaw import generate_image_with_refs, plan_generate_image_with_refs

    generate_image_with_refs("Alex", ["http://x/alex.png"])
    cp = plan_generate_image_with_refs(
        "Alex", ["http://x/alex.png"], consult_cache=False
    )
    assert captured[0]["arguments"] == cp.arguments
    assert captured[0]["application"] == cp.application


def test_plan_generate_image_with_refs_requires_a_ref():
    from falaw import plan_generate_image_with_refs

    with pytest.raises(ValueError, match="at least one reference"):
        plan_generate_image_with_refs("x", [], consult_cache=False)
