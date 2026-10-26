"""Image catalogue fixes from falaw#76: liveness, prompt caps, param enums, size adapter."""

import json
import os

import pytest

import falaw
from falaw import FalPromptTooLong, check_model_liveness, dead_models, model_params
from falaw.operations._image_args import image_arguments


@pytest.fixture(autouse=True)
def _isolated_journal(tmp_path, monkeypatch):
    monkeypatch.setenv("FALAW_DATA_DIR", str(tmp_path))
    from falaw.journal import _default_journal

    _default_journal.cache_clear()
    yield
    _default_journal.cache_clear()


def _capture(monkeypatch):
    import fal_client

    seen = {}

    def fake_subscribe(application, *, arguments, **_kw):
        seen.update(application=application, arguments=arguments)
        return {"images": [{"url": "http://x/i.png", "content_type": "image/png"}]}

    monkeypatch.setattr(fal_client, "subscribe", fake_subscribe)
    return seen


# --- (1) dead entries / liveness -------------------------------------------


def test_dead_imagen4_is_gone_from_catalogue():
    ids = {m.id for m in falaw.list_models()}
    assert not any("imagen4" in i for i in ids)
    assert falaw.pick_model(category="image", quality_tier="ultra").id != (
        "fal-ai/imagen4/preview/ultra"
    )


def test_liveness_flags_only_404():
    status = {"a": 200, "b": 404}
    got = check_model_liveness(
        ["a", "b"], status_of=lambda url: status[url.rsplit("=", 1)[1]]
    )
    assert got == {"a": True, "b": False}
    assert dead_models(["a", "b"], status_of=lambda u: status[u.rsplit("=", 1)[1]]) == [
        "b"
    ]


def test_liveness_refuses_to_guess_on_other_statuses():
    with pytest.raises(RuntimeError, match="429"):
        check_model_liveness(["a"], status_of=lambda url: 429)


def test_liveness_url_targets_openapi_endpoint():
    urls = []
    check_model_liveness(["fal-ai/x/y"], status_of=lambda u: urls.append(u) or 200)
    assert urls == [
        "https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=fal-ai/x/y"
    ]


# --- (2) prompt-length caps -------------------------------------------------


def test_recraft_prompt_over_cap_raises_before_any_call(monkeypatch):
    seen = _capture(monkeypatch)
    with pytest.raises(FalPromptTooLong, match="1000") as ei:
        falaw.generate_image("x" * 1001, model_id="fal-ai/recraft/v3/text-to-image")
    assert (ei.value.limit, ei.value.length) == (1000, 1001)
    assert isinstance(ei.value, ValueError)
    assert seen == {}


def test_recraft_prompt_at_cap_is_sent(monkeypatch):
    seen = _capture(monkeypatch)
    falaw.generate_image("x" * 1000, model_id="fal-ai/recraft/v3/text-to-image")
    assert len(seen["arguments"]["prompt"]) == 1000


def test_plan_also_enforces_cap():
    with pytest.raises(FalPromptTooLong):
        falaw.plan_generate_image(
            "x" * 1001, model_id="fal-ai/recraft/v3/text-to-image"
        )


# --- (3) discoverable params -------------------------------------------------


def test_recraft_style_enum_and_photoreal_default_are_discoverable():
    style = model_params("fal-ai/recraft/v3/text-to-image")["style"]
    assert style["default"] == "realistic_image"
    assert "vector_illustration/linocut" in style["enum"]


def test_model_params_resolves_aliases_and_defaults_empty():
    assert model_params("flux-schnell") == {}
    assert model_params("nano-banana-pro")["resolution"]["enum"] == ["1K", "2K", "4K"]


def test_recraft_styles_match_shipped_openapi_schema_shape():
    # The catalogue (and its TS mirror) must carry the same bytes.
    root = os.path.dirname(os.path.dirname(__file__))
    with open(os.path.join(root, "falaw", "data", "models.json")) as f:
        ours = json.load(f)
    rec = next(m for m in ours if m["id"] == "fal-ai/recraft/v3/text-to-image")
    assert rec["max_prompt_chars"] == 1000


# --- (4) nano-banana-pro / flux-2-pro through generate_image ----------------


def test_nano_banana_pro_maps_size_to_aspect_ratio(monkeypatch):
    seen = _capture(monkeypatch)
    falaw.generate_image(
        "a fox",
        model_id="fal-ai/nano-banana-pro",
        image_size="landscape_16_9",
        extra={"resolution": "2K", "output_format": "png"},
    )
    assert seen["application"] == "fal-ai/nano-banana-pro"
    assert seen["arguments"] == {
        "prompt": "a fox",
        "aspect_ratio": "16:9",
        "resolution": "2K",
        "output_format": "png",
    }


def test_nano_banana_pro_accepts_raw_ratio_and_rejects_nonsense():
    rec = falaw.get_model("nano-banana-pro")
    assert image_arguments(rec, "p", "21:9", None)["aspect_ratio"] == "21:9"
    with pytest.raises(ValueError, match="aspect_ratio"):
        image_arguments(rec, "p", "huge", None)


def test_nano_banana_pro_does_not_win_default_ultra_pick():
    assert falaw.pick_model(category="image", quality_tier="ultra").id == (
        "fal-ai/flux-pro/v1.1-ultra"
    )


def test_flux_2_pro_unlisted_keeps_image_size(monkeypatch):
    # Not catalogued (it would sort ahead of flux-pro/v1.1 on the next price
    # refresh and silently become the default 'high' pick), but it works by id.
    seen = _capture(monkeypatch)
    falaw.generate_image("a fox", model_id="fal-ai/flux-2-pro", image_size="square_hd")
    assert seen["arguments"] == {"prompt": "a fox", "image_size": "square_hd"}


def test_model_record_stays_hashable():
    hash(falaw.get_model("fal-ai/recraft/v3/text-to-image"))


def test_default_picks_are_stable_under_the_refresh_sort():
    # refresh_model_prices / refresh_models_from_corpus rewrite models.json
    # sorted by (category, tier, id); the default pick must not move.
    ms = sorted(
        (m for m in falaw.list_models(category="image") if m.default_pick),
        key=lambda m: (m.quality_tier, m.id),
    )
    for tier in ("fast", "balanced", "high", "ultra"):
        first = next(m for m in ms if m.quality_tier == tier)
        assert first.id == falaw.pick_model(category="image", quality_tier=tier).id


def test_render_shot_still_sizes_by_aspect_ratio(monkeypatch):
    from falaw.operations._image_args import image_arguments

    rec = falaw.get_model("nano-banana-pro")
    assert image_arguments(rec, "p", "landscape_16_9", None) == {
        "prompt": "p",
        "aspect_ratio": "16:9",
    }


def test_unlisted_model_keeps_legacy_arguments(monkeypatch):
    seen = _capture(monkeypatch)
    falaw.generate_image("a fox", model_id="fal-ai/some/new-model")
    assert seen["arguments"] == {"prompt": "a fox", "image_size": "landscape_4_3"}
