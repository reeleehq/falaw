"""max_prompt_chars is enforced for every operation, not only text-to-image (falaw#170)."""

import pytest

from falaw import FalPromptTooLong
from falaw.operations._plan import (
    plan_generate_audio,
    plan_image_to_video,
    plan_text_to_video,
)
from falaw.registry import get_model


def _over(model_id: str) -> str:
    limit = get_model(model_id).max_prompt_chars
    assert limit, f"{model_id} should record max_prompt_chars"
    return "x" * (limit + 1)


def test_text_to_video_prompt_over_the_cap_is_refused():
    model = "fal-ai/kling-video/v1.5/pro/text-to-video"
    with pytest.raises(FalPromptTooLong):
        plan_text_to_video(_over(model), model_id=model, consult_cache=False)


def test_image_to_video_prompt_over_the_cap_is_refused():
    model = "fal-ai/kling-video/v2.1/master/image-to-video"
    with pytest.raises(FalPromptTooLong):
        plan_image_to_video(
            "https://example.com/a.png", _over(model), model_id=model, consult_cache=False
        )


def test_audio_prompt_over_the_cap_is_refused():
    model = "fal-ai/lyria2"
    with pytest.raises(FalPromptTooLong):
        plan_generate_audio(_over(model), model_id=model, consult_cache=False)
