"""Tests for the model capability/limit metadata (the 'static reminder of
limitations' a shot-list builder surfaces)."""

import falaw
from falaw import get_model, model_constraints, video_model_constraints
from falaw.base import ModelRecord

_SEEDANCE = "fal-ai/bytedance/seedance/v1/pro/image-to-video"


def test_modelrecord_capability_defaults():
    m = ModelRecord(id="x", category="video")
    assert m.max_clip_seconds is None
    assert m.single_character_recommended is False
    assert m.supported_resolutions == ()
    assert m.default_negative_prompt == ""


def test_seedance_constraints_populated():
    c = model_constraints(_SEEDANCE)
    assert c["max_clip_seconds"] == 12.0
    assert c["single_character_recommended"] is True
    assert "720p" in c["supported_resolutions"]
    assert "plastic skin" in c["default_negative_prompt"]


def test_supported_resolutions_is_tuple_on_record():
    m = get_model(_SEEDANCE)
    assert isinstance(m.supported_resolutions, tuple)
    assert m.max_clip_seconds == 12.0


def test_video_model_constraints_lists_only_video_models():
    vc = video_model_constraints()
    assert len(vc) >= 6
    assert all("video" in c["category"] for c in vc)
    assert "fal-ai/veo3" in {c["id"] for c in vc}


def test_model_constraints_resolves_alias():
    # 'hailuo-pro' is an alias for the hailuo-02 pro model.
    c = model_constraints("hailuo-pro")
    assert c["id"] == "fal-ai/minimax/hailuo-02/pro/image-to-video"
    assert c["max_clip_seconds"] == 6.0
