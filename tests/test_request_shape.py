"""Request-shape facts derived from fal's OpenAPI input schema (falaw#159)."""

from __future__ import annotations

import json
import os
import shutil

import pytest

import falaw
from falaw.request_shape import (
    fetch_request_shape,
    input_properties,
    refresh_request_shapes,
    request_shape,
)

ROOT = os.path.dirname(os.path.dirname(__file__))
CATALOGUE = os.path.join(ROOT, "falaw", "data", "models.json")


def _doc(properties: dict) -> dict:
    """An endpoint's OpenAPI document, as fal serves it, with these input properties."""
    return {
        "paths": {"/fal-ai/x": {"post": {"requestBody": {"content": {"application/json": {
            "schema": {"$ref": "#/components/schemas/XInput"}}}}}}},
        "components": {"schemas": {"XInput": {"properties": properties}}},
    }  # fmt: skip


def test_the_shape_is_read_from_the_request_body():
    shape = request_shape(input_properties(_doc({
        "prompt": {"type": "string", "maxLength": 2500},
        "negative_prompt": {"type": "string"},
        "aspect_ratio": {"enum": ["16:9", "1:1"]},
    })))  # fmt: skip
    assert shape == {
        "accepted_inputs": ["aspect_ratio", "negative_prompt", "prompt"],
        "accepts_negative_prompt": True,
        "max_prompt_chars": 2500,
        "size_param": "aspect_ratio",
    }
    with pytest.raises(ValueError, match="no POST request body"):
        input_properties({"paths": {}})


def test_a_retired_endpoint_is_none_not_accepts_nothing():
    assert fetch_request_shape("fal-ai/gone", get_json=lambda url: None) is None


def test_a_refresh_writes_the_derived_fields_and_leaves_retired_and_default_ones(tmp_path):
    path = tmp_path / "models.json"
    shutil.copy(CATALOGUE, path)
    first, second = (r["id"] for r in json.loads(path.read_text())[:2])
    docs = {first: _doc({"prompt": {"maxLength": 300}, "negative_prompt": {}}), second: None}
    shapes = refresh_request_shapes(
        [first, second],
        get_json=lambda url: docs[url.split("endpoint_id=")[1]],
        write=True,
        path=str(path),
    )
    assert shapes[second] is None
    by_id = {r["id"]: r for r in json.loads(path.read_text())}
    assert by_id[first]["accepted_inputs"] == ["negative_prompt", "prompt"]
    assert by_id[first]["accepts_negative_prompt"] is True
    assert by_id[first]["max_prompt_chars"] == 300
    assert "size_param" not in by_id[first]  # the default is not written
    assert "accepted_inputs" not in by_id[second]


def test_the_catalogue_flags_agree_with_the_inputs_they_come_from():
    """The committed snapshot, read RAW (the TS mirror reads the rows, not the
    records): every row whose inputs were fetched carries the flags those
    inputs imply, and ``accepts_input`` tells unknown from no."""
    with open(CATALOGUE, encoding="utf-8") as f:
        rows = json.load(f)
    fetched = [r for r in rows if r.get("accepted_inputs") is not None]
    assert fetched, "the catalogue has been refreshed from fal"
    for row in fetched:
        inputs = set(row["accepted_inputs"])
        assert row.get("accepts_negative_prompt", False) == ("negative_prompt" in inputs), row["id"]
        if row.get("size_param") == "aspect_ratio":
            assert "aspect_ratio" in inputs and "image_size" not in inputs, row["id"]
    never = [m for m in falaw.list_models() if m.accepted_inputs is None]
    assert all(m.accepts_input("negative_prompt") is None for m in never)


def test_a_record_refuses_what_contradicts_its_inputs():
    from dataclasses import replace

    from falaw.base import ModelRecord

    with pytest.raises(ValueError, match="no negative_prompt"):
        ModelRecord(id="m", category="image", accepted_inputs=["prompt"], accepts_negative_prompt=True)
    rec = ModelRecord(id="m", category="image", accepted_inputs=["prompt"])
    with pytest.raises(ValueError, match="no negative_prompt"):
        replace(rec, accepts_negative_prompt=True)
    with pytest.raises(TypeError, match="collection of input names"):
        ModelRecord(id="m", category="image", accepted_inputs="prompt")


def test_all_of_bodies_and_any_of_caps_are_read_and_an_empty_body_refused():
    doc = _doc({})
    doc["components"]["schemas"]["XInput"] = {"allOf": [
        {"properties": {"prompt": {"anyOf": [{"type": "string", "maxLength": 900}, {"type": "null"}]}}},
        {"properties": {"negative_prompt": {"type": "string"}}},
    ]}  # fmt: skip
    shape = request_shape(input_properties(doc))
    assert shape["accepted_inputs"] == ["negative_prompt", "prompt"]
    assert shape["max_prompt_chars"] == 900
    with pytest.raises(ValueError, match="declares no properties"):
        input_properties(_doc({}))


def test_a_refresh_reads_the_rest_and_then_names_what_failed(tmp_path):
    path = tmp_path / "models.json"
    shutil.copy(CATALOGUE, path)
    first, second = (r["id"] for r in json.loads(path.read_text())[:2])

    def get(url):
        if url.endswith(second):
            raise RuntimeError("HTTP 429")
        return _doc({"prompt": {}})

    with pytest.raises(RuntimeError, match=f"1 of 2 .*{second}: RuntimeError: HTTP 429"):
        refresh_request_shapes([first, second], get_json=get, write=True, path=str(path))
    assert {r["id"]: r for r in json.loads(path.read_text())}[first]["accepted_inputs"] == ["prompt"]


def test_an_aspect_ratio_model_refuses_an_image_size_in_extra():
    from falaw.operations._image_args import image_arguments

    ultra = falaw.get_model("fal-ai/flux-pro/v1.1-ultra")
    with pytest.raises(ValueError, match="not image_size"):
        image_arguments(ultra, "x", "landscape_4_3", {"image_size": "square_hd"})
    assert image_arguments(ultra, "x", "landscape_16_9", None)["aspect_ratio"] == "16:9"


@pytest.mark.live_api
def test_the_catalogue_still_matches_fals_live_schemas():
    """What fal serves now against the committed snapshot; a failure means:
    run the refresh. It reads fal's OpenAPI endpoint, which needs no key and
    bills nothing, but it is network, so it runs behind the suite's one live
    gate (``FALAW_LIVE_API=1``)."""
    fetched = [m for m in falaw.list_models() if m.accepted_inputs is not None]
    for m in fetched:
        live = fetch_request_shape(m.id)
        assert live is not None, f"{m.id} is retired"
        assert frozenset(live["accepted_inputs"]) == m.accepted_inputs, m.id
        for field in ("accepts_negative_prompt", "max_prompt_chars", "size_param"):
            assert live[field] == getattr(m, field), (m.id, field)
