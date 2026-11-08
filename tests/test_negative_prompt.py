"""A negative prompt reaches a model that accepts one, and nothing else (reeleehq/reelee#859).

FLUX takes no ``negative_prompt``; joining the text into ``prompt`` would ASK for what
it names. So the planners and eager ops send it only to a model whose record declares
``accepts_negative_prompt`` (set from fal's published input schema), and an eager and
a planned call build the same arguments.
"""

from __future__ import annotations

import sys
import types

import pytest

from falaw import get_model, plan_generate_image, plan_generate_image_with_refs

ACCEPTS, REFUSES = "fal-ai/sana/sprint", "fal-ai/flux/dev"
EDIT_ACCEPTS, EDIT_REFUSES = "fal-ai/omnigen-v2", "fal-ai/flux-kontext/dev"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FALAW_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FALAW_CACHE_DIR", str(tmp_path / "cache"))


def test_the_catalogue_declares_which_image_models_accept_one():
    assert get_model(ACCEPTS).accepts_negative_prompt
    assert get_model(EDIT_ACCEPTS).accepts_negative_prompt
    assert not get_model(REFUSES).accepts_negative_prompt
    assert not get_model("fal-ai/flux-pro/v1.1").accepts_negative_prompt


@pytest.mark.parametrize("model, sent", [(ACCEPTS, True), (REFUSES, False)])
def test_the_text_to_image_plan_sends_it_only_where_accepted(model, sent):
    args = plan_generate_image("a lighthouse", model_id=model, negative_prompt=" glasses ").arguments
    assert args.get("negative_prompt") == ("glasses" if sent else None)
    assert "glasses" not in args["prompt"], "never folded into the positive prompt"


@pytest.mark.parametrize("model, sent", [(EDIT_ACCEPTS, True), (EDIT_REFUSES, False)])
def test_the_reference_plan_sends_it_only_where_accepted(model, sent):
    args = plan_generate_image_with_refs(
        "Alex at the bell", ["http://x/alex.png"], model_id=model, negative_prompt="beard"
    ).arguments
    assert ("negative_prompt" in args) is sent


def test_no_negative_prompt_adds_nothing_and_extra_still_wins():
    assert "negative_prompt" not in plan_generate_image("x", model_id=ACCEPTS).arguments
    args = plan_generate_image(
        "x", model_id=ACCEPTS, negative_prompt="a", extra={"negative_prompt": "b"}
    ).arguments
    assert args["negative_prompt"] == "b"


@pytest.fixture
def fal_calls(monkeypatch):
    captured = []

    def subscribe(application, *, arguments, with_logs, on_queue_update):
        captured.append(dict(arguments))
        return {"images": [{"url": "http://x/out.png", "content_type": "image/png"}]}

    monkeypatch.setitem(
        sys.modules, "fal_client", types.SimpleNamespace(InProgress=type("IP", (), {}), subscribe=subscribe)
    )
    return captured


def test_each_eager_call_sends_what_its_plan_would(fal_calls):
    import falaw

    control = [{"mode": "canny", "image": "http://x/guide.png"}]
    pairs = [
        (falaw.generate_image, falaw.plan_generate_image, ("a lighthouse",), ACCEPTS),
        (falaw.generate_image_with_refs, falaw.plan_generate_image_with_refs,
         ("Alex", ["http://x/alex.png"]), EDIT_ACCEPTS),
        (falaw.generate_image_with_control, falaw.plan_generate_image_with_control,
         ("a lighthouse", control), "fal-ai/flux-general"),
    ]
    for eager, plan, args, model in pairs:
        eager(*args, model_id=model, negative_prompt="glasses")
        planned = plan(*args, model_id=model, negative_prompt="glasses")
        assert fal_calls[-1] == dict(planned.arguments), eager.__name__
        assert fal_calls[-1]["negative_prompt"] == "glasses"


def test_the_control_plan_sends_it_to_flux_general():
    from falaw import plan_generate_image_with_control

    control = [{"mode": "canny", "image": "http://x/guide.png"}]
    args = plan_generate_image_with_control(
        "a lighthouse", control, model_id="fal-ai/flux-general", negative_prompt="glasses"
    ).arguments
    assert args["negative_prompt"] == "glasses"


def test_a_dropped_negative_is_named_in_the_plan_metadata_not_its_hash():
    dropped = plan_generate_image("a lighthouse", model_id=REFUSES, negative_prompt="glasses")
    plain = plan_generate_image("a lighthouse", model_id=REFUSES)
    assert dropped.metadata.get("dropped_inputs") == ["negative_prompt"]
    assert "dropped_inputs" not in (plain.metadata or {})
    assert dropped.arguments == plain.arguments
    sent = plan_generate_image("a lighthouse", model_id=ACCEPTS, negative_prompt="glasses")
    assert "dropped_inputs" not in (sent.metadata or {})


def test_a_negative_sent_through_extra_is_not_reported_dropped():
    plan = plan_generate_image(
        "x", model_id=REFUSES, negative_prompt="glasses", extra={"negative_prompt": "glasses"}
    )
    assert plan.arguments["negative_prompt"] == "glasses"
    assert "dropped_inputs" not in (plan.metadata or {})
