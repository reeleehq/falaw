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
    """The committed snapshot: every record whose inputs were fetched carries
    flags those inputs imply, and ``accepts_input`` tells unknown from no."""
    fetched = [m for m in falaw.list_models() if m.accepted_inputs is not None]
    assert fetched, "the catalogue has been refreshed from fal"
    for m in fetched:
        assert m.accepts_negative_prompt == ("negative_prompt" in m.accepted_inputs), m.id
        if m.size_param == "aspect_ratio":
            assert "aspect_ratio" in m.accepted_inputs and "image_size" not in m.accepted_inputs, m.id
        assert m.accepts_input("prompt") in (True, False)
    never = [m for m in falaw.list_models() if m.accepted_inputs is None]
    assert all(m.accepts_input("negative_prompt") is None for m in never)


@pytest.mark.skipif(
    not os.environ.get("FALAW_LIVE_SCHEMA"),
    reason="set FALAW_LIVE_SCHEMA=1 to re-check the catalogue against fal's live schemas",
)
def test_the_catalogue_still_matches_fals_live_schemas():
    """Opt-in, free (fal's OpenAPI endpoint needs no key): what fal serves now
    against the committed snapshot. A failure means: run the refresh."""
    fetched = [m for m in falaw.list_models() if m.accepted_inputs is not None]
    for m in fetched:
        live = fetch_request_shape(m.id)
        assert live is not None, f"{m.id} is retired"
        assert frozenset(live["accepted_inputs"]) == m.accepted_inputs, m.id
