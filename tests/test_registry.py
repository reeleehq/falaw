from falaw.registry import get_model, list_models, list_tools, pick_model


def test_list_models_seeded_categories():
    cats = {m.category for m in list_models()}
    for expected in (
        "image",
        "image_edit",
        "image_to_video",
        "text_to_video",
        "lipsync",
        "tts",
        "voice_clone",
        "upscale",
        "background_removal",
        "music",
        "llm",
        "avatar",
    ):
        assert expected in cats, f"missing category: {expected}"


def test_pick_model_picks_image_fast():
    m = pick_model(category="image", quality_tier="fast")
    assert m.category == "image"
    assert m.quality_tier == "fast"


def test_pick_model_falls_back_when_tier_absent():
    # 'avatar' category only has 'balanced' in the seed; asking for 'ultra'
    # should still return something rather than KeyError.
    m = pick_model(category="avatar", quality_tier="ultra")
    assert m.category == "avatar"


def test_get_model_alias():
    m = get_model("flux-schnell")
    assert m.id == "fal-ai/flux/schnell"


def test_image_tools_registered():
    names = {t.name for t in list_tools(tag="image")}
    for expected in (
        "generate_image",
        "edit_image",
        "upscale_image",
        "remove_background",
    ):
        assert expected in names, f"missing tool: {expected}"


def test_video_tools_registered():
    names = {t.name for t in list_tools(tag="video")}
    for expected in (
        "text_to_video",
        "image_to_video",
        "lipsync",
        "talking_avatar_from_text",
    ):
        assert expected in names, f"missing tool: {expected}"


def test_audio_tools_registered():
    names = {t.name for t in list_tools(tag="audio")}
    assert "text_to_speech" in names
    assert "voice_clone" in names
