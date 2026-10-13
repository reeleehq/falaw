"""Tests for falaw.composite_character_in_environment + plan_*."""

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
            "images": [{"url": "http://x/composite.png", "content_type": "image/png"}]
        }

    fake = types.SimpleNamespace(InProgress=type("IP", (), {}), subscribe=subscribe)
    monkeypatch.setitem(sys.modules, "fal_client", fake)
    return captured


def test_composite_passes_both_image_urls(monkeypatch):
    captured = _patch_fal(monkeypatch)
    from falaw import composite_character_in_environment

    composite_character_in_environment(
        character_image_url="http://x/thor.png",
        environment_image_url="http://x/bell_tower.png",
        prompt="Thor in the tower",
    )
    assert len(captured) == 1
    args = captured[0]["arguments"]
    assert args["image_url"] == "http://x/thor.png"
    assert args["image_urls"] == ["http://x/thor.png", "http://x/bell_tower.png"]
    assert "Thor in the tower" in args["prompt"]


def test_composite_uses_default_prompt_when_none_given(monkeypatch):
    captured = _patch_fal(monkeypatch)
    from falaw import composite_character_in_environment

    composite_character_in_environment(
        character_image_url="http://x/thor.png",
        environment_image_url="http://x/bell_tower.png",
    )
    args = captured[0]["arguments"]
    assert "Preserve the person's identity" in args["prompt"]


def test_composite_picks_image_edit_model_by_default(monkeypatch):
    captured = _patch_fal(monkeypatch)
    from falaw import composite_character_in_environment

    composite_character_in_environment(
        character_image_url="http://x/c.png",
        environment_image_url="http://x/e.png",
    )
    assert "flux-kontext" in captured[0]["application"]


def test_composite_model_id_override(monkeypatch):
    captured = _patch_fal(monkeypatch)
    from falaw import composite_character_in_environment

    composite_character_in_environment(
        character_image_url="http://x/c.png",
        environment_image_url="http://x/e.png",
        model_id="fal-ai/bytedance/seededit/v3/edit-image",
    )
    assert captured[0]["application"] == "fal-ai/bytedance/seededit/v3/edit-image"


# --- plan_composite_character_in_environment --------------------------------


def test_plan_composite_call_shape():
    from falaw import plan_composite_character_in_environment

    p = plan_composite_character_in_environment(
        character_image_url="http://x/c.png",
        environment_image_url="http://x/e.png",
        prompt="Thor playing piano in the tower",
        metadata={"shot_id": "s01"},
    )
    assert p.tool == "composite_character_in_environment"
    assert "flux-kontext" in p.application
    assert p.output_kind == "image"
    assert p.arguments["image_urls"] == ["http://x/c.png", "http://x/e.png"]
    assert p.metadata["shot_id"] == "s01"


def test_plan_composite_has_cost_estimate():
    """Phase 0.4 priced flux-kontext/dev — composite plans must report cost."""
    from falaw import plan_composite_character_in_environment

    p = plan_composite_character_in_environment(
        character_image_url="http://x/c.png",
        environment_image_url="http://x/e.png",
    )
    assert p.estimated_cost_usd is not None
    assert p.estimated_cost_usd > 0


def test_plan_composite_round_trip(monkeypatch):
    """plan_composite → execute_plan → Artifact with the composite URL."""
    _patch_fal(monkeypatch)
    from falaw import (
        Plan,
        execute_plan,
        plan_composite_character_in_environment,
    )

    plan = Plan(
        calls=(
            plan_composite_character_in_environment(
                character_image_url="http://x/c.png",
                environment_image_url="http://x/e.png",
            ),
        )
    )
    artifacts = execute_plan(plan, use_cache=False)
    assert len(artifacts) == 1
    assert artifacts[0].kind == "image"
    assert artifacts[0].url == "http://x/composite.png"
