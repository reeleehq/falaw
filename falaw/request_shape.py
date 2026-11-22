"""What a model's request accepts, read from fal's published OpenAPI schema (falaw#159).

A :class:`~falaw.base.ModelRecord` carries request-shape facts a planner acts
on: ``accepts_negative_prompt`` (send a negative prompt, or drop it),
``max_prompt_chars`` (refuse a prompt fal would 422 after queueing) and
``size_param`` (``image_size`` presets, or ``aspect_ratio``). Set by hand they
rot, and a ``False`` read both "checked: no such input" and "never checked".
Here they are derived from one fetched fact, the model's input property names
(``accepted_inputs``; ``None`` on a record means never fetched):

- :func:`input_properties`: the ``POST`` request body's properties, from the
  OpenAPI document fal serves per endpoint (the one :mod:`falaw.liveness`
  probes: free, no key);
- :func:`request_shape`: those properties as the record's fields;
- :func:`refresh_request_shapes`: fetch every catalogued model (or ``ids``),
  and with ``write=True`` put the fields into ``falaw/data/models.json``. Then
  run ``python -m falaw export-schema`` and the TS codegen, as for any
  catalogue change.

>>> doc = {"paths": {"/fal-ai/x": {"post": {"requestBody": {"content": {"application/json":
...     {"schema": {"$ref": "#/components/schemas/XInput"}}}}}}},
...     "components": {"schemas": {"XInput": {"properties": {
...         "prompt": {"type": "string", "maxLength": 1000}, "negative_prompt": {"type": "string"},
...         "image_size": {"$ref": "#/components/schemas/ImageSize"}}}}}}
>>> shape = request_shape(input_properties(doc))
>>> shape["accepted_inputs"], shape["accepts_negative_prompt"], shape["max_prompt_chars"]
(['image_size', 'negative_prompt', 'prompt'], True, 1000)
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Iterable, Mapping, Optional

from .liveness import OPENAPI_URL

#: ``url -> parsed JSON``; injectable so tests never touch the network.
JsonGetter = Callable[[str], Any]

#: The input that sizes an image by fal's named presets; the alternative is
#: ``aspect_ratio`` (with ``resolution``).
IMAGE_SIZE_PARAM: str = "image_size"
ASPECT_RATIO_PARAM: str = "aspect_ratio"
NEGATIVE_PROMPT_PARAM: str = "negative_prompt"
PROMPT_PARAM: str = "prompt"

#: The record fields a refresh writes.
SHAPE_FIELDS: tuple[str, ...] = (
    "accepted_inputs",
    "accepts_negative_prompt",
    "max_prompt_chars",
    "size_param",
)


def _get_json(url: str) -> Any:
    from .errors import import_httpx

    httpx = import_httpx("reading fal.ai model input schemas")
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        response = client.get(url)
        if response.status_code == 404:
            return None  # a retired endpoint: falaw.liveness's to report
        response.raise_for_status()
        return response.json()


def _resolve(doc: Mapping, node: Any) -> Any:
    """``node`` with a local ``$ref`` (``#/components/...``) followed."""
    seen = 0
    while isinstance(node, Mapping) and "$ref" in node and seen < 32:
        ref = node["$ref"]
        if not ref.startswith("#/"):
            return node
        target: Any = doc
        for part in ref[2:].split("/"):
            if not isinstance(target, Mapping) or part not in target:
                return node  # a dangling reference: its name is still an input
            target = target[part]
        node, seen = target, seen + 1
    return node


def _object_properties(doc: Mapping, schema: Any) -> dict[str, Any]:
    """The properties of an object schema, ``allOf`` parts merged."""
    schema = _resolve(doc, schema) or {}
    props = dict(schema.get("properties") or {})
    for part in schema.get("allOf") or ():
        props.update(_object_properties(doc, part))
    return props


def _max_length(doc: Mapping, spec: Any) -> Optional[int]:
    """A string property's ``maxLength``, also inside ``anyOf``/``oneOf`` branches
    (``[string with maxLength, null]``); the largest when several state one."""
    spec = _resolve(doc, spec) or {}
    found = [spec["maxLength"]] if "maxLength" in spec else []
    for key in ("anyOf", "oneOf"):
        found += [m for b in spec.get(key) or () if (m := _max_length(doc, b)) is not None]
    return max(found) if found else None


def input_properties(doc: Mapping) -> dict[str, dict]:
    """The input properties (``{name: schema}``) of the ``POST`` request body in
    an endpoint's OpenAPI document, ``$ref``s resolved and ``allOf`` merged, each
    with its ``maxLength`` lifted out of an ``anyOf``. ``ValueError`` when the
    document has no such body or it has no properties: an empty answer would
    read as "accepts nothing"."""
    for ops in (doc.get("paths") or {}).values():
        body = (ops.get("post") or {}).get("requestBody")
        if not body:
            continue
        props = _object_properties(doc, body["content"]["application/json"]["schema"])
        if not props:
            raise ValueError("the POST request body declares no properties")
        out = {}
        for name, spec in props.items():
            resolved = dict(_resolve(doc, spec) or {})
            length = _max_length(doc, spec)
            if length is not None:
                resolved["maxLength"] = length
            out[name] = resolved
        return out
    raise ValueError("no POST request body in this OpenAPI document")


def request_shape(properties: Mapping[str, Mapping]) -> dict[str, Any]:
    """The record fields (:data:`SHAPE_FIELDS`) an endpoint's input properties
    imply: their names (sorted), whether ``negative_prompt`` is one, the
    ``prompt``'s ``maxLength`` (``None`` when it states none), and the size
    input (``aspect_ratio`` only when the model takes it and no ``image_size``).

    >>> request_shape({"prompt": {}, "aspect_ratio": {}})["size_param"]
    'aspect_ratio'
    """
    names = sorted(properties)
    max_chars = (properties.get(PROMPT_PARAM) or {}).get("maxLength")
    size = (
        ASPECT_RATIO_PARAM
        if ASPECT_RATIO_PARAM in properties and IMAGE_SIZE_PARAM not in properties
        else IMAGE_SIZE_PARAM
    )
    return {
        "accepted_inputs": names,
        "accepts_negative_prompt": NEGATIVE_PROMPT_PARAM in properties,
        "max_prompt_chars": int(max_chars) if max_chars is not None else None,
        "size_param": size,
    }


def fetch_request_shape(
    endpoint_id: str, *, get_json: Optional[JsonGetter] = None
) -> Optional[dict]:
    """:func:`request_shape` of one endpoint, from fal's OpenAPI document;
    ``None`` for an endpoint fal no longer serves (a 404, :mod:`falaw.liveness`)."""
    doc = (get_json or _get_json)(f"{OPENAPI_URL}?endpoint_id={endpoint_id}")
    return None if doc is None else request_shape(input_properties(doc))


def _catalogue_path() -> str:
    return os.path.join(os.path.dirname(__file__), "data", "models.json")


def refresh_request_shapes(
    ids: Optional[Iterable[str]] = None,
    *,
    get_json: Optional[JsonGetter] = None,
    write: bool = False,
    path: Optional[str] = None,
) -> dict[str, Optional[dict]]:
    """``{endpoint_id: shape}`` for ``ids`` (default: every catalogued model),
    each fetched from fal. With ``write``, each record of the catalogue
    (``path``, default ``falaw/data/models.json``) gets those fields; a field
    left at its default (``None``, ``False``, ``image_size``) is dropped from
    the record rather than written, as the catalogue writes defaults. A
    retired endpoint (``None``) is left as it is. A schema that cannot be read
    (a 429, a 5xx, a shape this module does not know) is never guessed: the
    others are fetched (and written), then ``RuntimeError`` names each failure."""
    path = path or _catalogue_path()
    with open(path, encoding="utf-8") as f:
        records = json.load(f)
    wanted = list(ids) if ids is not None else [r["id"] for r in records]
    shapes: dict[str, Optional[dict]] = {}
    failures: dict[str, str] = {}
    for endpoint_id in wanted:
        try:
            shapes[endpoint_id] = fetch_request_shape(endpoint_id, get_json=get_json)
        except Exception as e:  # noqa: BLE001 - one bad answer must not lose the rest
            failures[endpoint_id] = f"{type(e).__name__}: {e}"
    if write:
        defaults = {"accepts_negative_prompt": False, "max_prompt_chars": None,
                    "size_param": IMAGE_SIZE_PARAM}  # fmt: skip
        for record in records:
            shape = shapes.get(record["id"])
            if shape is None:
                continue
            for name in SHAPE_FIELDS:
                if name in defaults and shape[name] == defaults[name]:
                    record.pop(name, None)
                else:
                    record[name] = shape[name]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
            f.write("\n")
        from .registry import _load_models

        _load_models.cache_clear()  # this process reads the new records too
    if failures:
        raise RuntimeError(
            f"{len(failures)} of {len(wanted)} schemas could not be read"
            + (" (the others were written)" if write else "")
            + ": "
            + "; ".join(f"{i}: {why}" for i, why in failures.items())
        )
    return shapes
