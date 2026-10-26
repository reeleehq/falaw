"""Export the Python SSOT as committed JSON for the TypeScript twin (``ts/``).

falaw ships twice: as this Python package and as the npm package ``falaw-client``
(``ts/``), which *plans* in the browser and *executes* through a server relay.
The two must agree on the plan and result shapes, the model catalogue and its
prices, the cost rules, the model-picking rules, the response parser, and the
canonical byte-form every hash is taken over. None of that is re-authored on
the TypeScript side: this module writes it out as JSON, the TS build generates
its types from the schemas and reads the catalogue as data, and its parity tests
replay the fixtures below and assert the same output, hash for hash.

What lands in ``<out_dir>``:

- ``call-plan.schema.json``, ``result.schema.json``, ``model-record.schema.json``
  — the dataclasses as JSON Schema (via ``pydantic.TypeAdapter``), the codegen
  inputs for the Zod types.
- ``models.json`` — the catalogue, **byte for byte**, so the TS side can compute
  the same ``models_table_version`` digest a :class:`falaw.CostBasis` records.
- ``constants.json`` — the default backend, the plan dict schema tag, the
  catalogue pricer identity, the tier order, the response-kind keys, and the
  literal vocabularies (``OutputKind``, ``CacheStatus``).
- ``fixtures/plans.json`` — planner inputs → the ``CallPlan`` dict this package
  builds (cost, basis and all) and its ``plan_hash``; plus multi-call plans.
- ``fixtures/responses.json`` — raw fal responses → the ``Result`` this package
  parses them into.
- ``fixtures/pick_model.json``, ``fixtures/cost.json``, ``fixtures/canonical.json``
  — model selection, cost estimation, and the canonical blob + SHA-256 for a set
  of payloads (the byte-form parity that makes ``plan_hash`` agree).

``tests/test_schema_export.py`` pins the committed directory to a fresh export,
so a change here that forgets ``python -m falaw export-schema`` fails CI on this
side, before the TS side can drift.

>>> from falaw.schema_export import PLAN_CASES
>>> PLAN_CASES[0]["tool"]
'generate_image'
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Mapping, get_args

from .base import CostEstimate, ModelRecord
from .canonical import (
    DFLT_BACKEND,
    cache_key_payload,
    canonical_blob,
    plan_identity_payload,
)
from .cost import (
    DFLT_MEGAPIXELS,
    DFLT_VIDEO_RESOLUTION,
    DFLT_VIDEO_ASPECT,
    RESOLUTION_SHORT_SIDE,
    estimate_call_cost,
)
from .upload import FILE_PREFIX
from .operations._plan import (
    plan_generate_image,
    plan_image_to_video,
    plan_reference_to_video,
    plan_text_to_video,
)
from .plan import (
    CONTENT_REF_PREFIX,
    PLAN_DICT_SCHEMA,
    CacheStatus,
    OutputKind,
    Plan,
    _PLACEHOLDER_PREFIX,
    call_plan_to_dict,
    plan_hash,
    plan_to_dict,
)
from .registry import (
    MODEL_CATALOGUE_TABLE,
    _models_path,
    _TIER_ORDER,
    models_table_version,
    pick_model,
)
from .reprice import CATALOGUE_PRICER
from .results import _KIND_KEYS, parse_response

__all__ = ["export_schema", "PLAN_CASES", "RESPONSE_CASES", "CANONICAL_CASES"]

_PLANNERS = {
    "generate_image": plan_generate_image,
    "image_to_video": plan_image_to_video,
    "text_to_video": plan_text_to_video,
    "reference_to_video": plan_reference_to_video,
}

#: Planner inputs the TS ``planGenerateImage`` / ``planImageToVideo`` must turn
#: into the same ``CallPlan``. ``consult_cache=False`` throughout: a browser has
#: no cache to peek, so ``cache_status`` is ``"unknown"`` on both sides.
PLAN_CASES: tuple[dict, ...] = (
    {"tool": "generate_image", "input": {"prompt": "a tiger eye, macro, 35mm"}},
    {"tool": "generate_image", "input": {"prompt": "a tiger eye", "quality": "fast"}},
    {
        "tool": "generate_image",
        "input": {
            "prompt": "a tiger eye",
            "quality": "ultra",
            "image_size": "square_hd",
        },
    },
    {
        "tool": "generate_image",
        "input": {
            "prompt": "café at dusk ☕",
            "model_id": "flux-dev",  # an alias, resolved to the record's id
            "extra": {
                "seed": 7,
                "guidance_scale": 3.5,
                "tags": ["b", "a"],
                "nested": {"z": 1, "a": "é", "ok": True, "none": None},
            },
        },
    },
    {
        "tool": "generate_image",
        "input": {"prompt": "a tiger eye", "metadata": {"panel": "p3", "n": 2}},
    },
    {"tool": "image_to_video", "input": {"image_url": "https://x.example/tiger.png"}},
    {
        "tool": "image_to_video",
        "input": {
            "image_url": "https://x.example/tiger.png",
            "prompt": "slow push in",
            "duration_s": 6,
        },
    },
    {
        "tool": "image_to_video",
        "input": {
            "image_url": "https://x.example/tiger.png",
            "quality": "ultra",
            "duration_s": 5.5,
        },
    },
    {
        "tool": "image_to_video",
        "input": {"image_url": "<from 0>", "model_id": "hailuo-pro", "duration_s": 6},
    },
    # Token-billed video (falaw#86): the duration is sent as fal's string enum
    # and the quote is tokens, from the default / the requested resolution.
    {
        "tool": "image_to_video",
        "input": {
            "image_url": "https://x.example/tiger.png",
            "model_id": "seedance2-i2v",
            "duration_s": 5,
        },
    },
    {
        "tool": "text_to_video",
        "input": {
            "prompt": "a tiger walks",
            "model_id": "seedance2-fast-t2v",
            "duration_s": 4.5,
            "extra": {"resolution": "480p"},
        },
    },
    {"tool": "text_to_video", "input": {"prompt": "a tiger walks", "duration_s": 5}},
    {
        "tool": "text_to_video",
        "input": {"prompt": "a tiger walks", "model_id": "seedance2-t2v"},
    },
    {  # the frame follows the aspect ratio: 21:9 bills more pixels than 16:9
        "tool": "text_to_video",
        "input": {
            "prompt": "a tiger walks",
            "model_id": "seedance2-t2v",
            "duration_s": 6,
            "extra": {"aspect_ratio": "21:9", "resolution": "1080p"},
        },
    },
    {  # an empty duration is unknown, not zero seconds (free)
        "tool": "text_to_video",
        "input": {
            "prompt": "a tiger walks",
            "model_id": "seedance2-t2v",
            "extra": {"duration": ""},
        },
    },
    # Reference-to-video (falaw#99): a quote ignores reference counts, only limits are checked.
    {
        "tool": "reference_to_video",
        "input": {
            "prompt": "a tiger walks",
            "model_id": "seedance2-ref",
            "duration_s": 5,
            "image_urls": ["https://x.example/a.png"],
        },
    },
    {
        "tool": "reference_to_video",
        "input": {
            "prompt": "a tiger walks",
            "model_id": "seedance2-ref",
            "duration_s": 5,
            "video_urls": ["https://x.example/a.mp4"],
        },
    },
    {  # 4K bills a lower per-token rate
        "tool": "text_to_video",
        "input": {
            "prompt": "a tiger walks",
            "model_id": "seedance2-t2v",
            "duration_s": 5,
            "extra": {"resolution": "4k"},
        },
    },
)

#: Planner inputs that must raise (the fixtures cannot express a raise in
#: ``PLAN_CASES``): the TS twin must throw with ``message`` in its text.
PLAN_ERROR_CASES: tuple[dict, ...] = (
    {
        "tool": "reference_to_video",
        "input": {
            "prompt": "x",
            "model_id": "seedance2-ref",
            "duration_s": 5,
            "image_urls": [f"https://x.example/{i}.png" for i in range(10)],
        },
        "message": "takes at most 9 image_urls, got 10",
    },
    {
        "tool": "generate_image",
        "input": {
            "prompt": "x",
            "model_id": "seedream45",
            "extra": {"image_size": {"width": 64, "height": 64}},
        },
        "message": "total pixels",
    },
)

#: Multi-call plans (by ``PLAN_CASES`` index) whose ``plan_hash`` and totals the
#: TS side must reproduce — the second one chains a video onto an image.
MULTI_PLAN_CASES: tuple[tuple[int, ...], ...] = ((0, 5), (3, 8), (1, 1))

#: Raw fal responses → what ``parse_response`` makes of them.
RESPONSE_CASES: tuple[dict, ...] = (
    {
        "application": "fal-ai/flux/dev",
        "arguments": {"prompt": "a tiger eye"},
        "raw": {
            "images": [
                {
                    "url": "https://v3.fal.media/a.png",
                    "width": 1024,
                    "height": 768,
                    "content_type": "image/png",
                },
                {
                    "url": "https://v3.fal.media/b.png",
                    "width": 1024,
                    "height": 768,
                    "content_type": "image/png",
                    "nsfw": False,
                },
            ],
            "seed": 42,
            "timings": {"inference": 1.2},
            "has_nsfw_concepts": [False, False],
            "prompt": "a tiger eye",
        },
    },
    {
        "application": "fal-ai/some/model",
        "arguments": {},
        "raw": {
            "image": {
                "url": "https://v3.fal.media/one.jpg",
                "width": 512,
                "height": 512,
            }
        },
    },
    {
        "application": "fal-ai/minimax/hailuo-02/pro/image-to-video",
        "arguments": {"image_url": "https://x.example/tiger.png"},
        "raw": {
            "video": {
                "url": "https://v3.fal.media/clip.mp4",
                "content_type": "video/mp4",
                "duration": 6.0,
                "fps": 25,
            }
        },
    },
    {
        "application": "fal-ai/tts",
        "arguments": {"text": "hi"},
        "raw": {"audio_url": "https://v3.fal.media/say.mp3"},
    },
    {
        "application": "fal-ai/mixed",
        "arguments": {},
        "raw": {
            "images": ["https://v3.fal.media/bare.png"],
            "videos": [{"url": "https://v3.fal.media/v.mp4"}],
            "extra": 1,
        },
    },
    {
        "application": "fal-ai/odd",
        "arguments": {},
        "raw": {"output": {"url": "https://v3.fal.media/unknown.bin"}},
    },
    {"application": "fal-ai/odd", "arguments": {}, "raw": {"images": [{"width": 10}]}},
)

#: Model-selection requests the TS ``pickModel`` must answer identically
#: (including the neighbouring-tier fallback and an unknown tier).
PICK_MODEL_CASES: tuple[tuple[str, str], ...] = tuple(
    (category, tier)
    for category in (
        "image",
        "image_edit",
        "image_to_video",
        "text_to_video",
        "reference_to_video",
        "tts",
    )
    for tier in (*_TIER_ORDER, "weird")
)

#: Cost-rule cases over synthetic records (every ``CostKind``, with and without
#: the quantity hint) plus the catalogue's own image and video defaults.
COST_CASES: tuple[dict, ...] = (
    {"cost_estimate": None, "count": 1},
    {"cost_estimate": {"kind": "per_call", "amount": 0.05}, "count": 1},
    {"cost_estimate": {"kind": "per_call", "amount": 0.05}, "count": 3},
    {"cost_estimate": {"kind": "per_image", "amount": 0.04}, "count": 2},
    {"cost_estimate": {"kind": "per_second", "amount": 0.08}, "count": 1},
    {"cost_estimate": {"kind": "per_second", "amount": 0.08}, "count": 1, "seconds": 6},
    {
        "cost_estimate": {"kind": "per_second", "amount": 0.08},
        "count": 2,
        "seconds": 5.5,
    },
    {"cost_estimate": {"kind": "per_megapixel", "amount": 0.025}, "count": 1},
    {
        "cost_estimate": {"kind": "per_megapixel", "amount": 0.025},
        "count": 1,
        "megapixels": 1.5,
    },
    {"cost_estimate": {"kind": "per_token", "amount": 0.000002}, "count": 1},
    {
        "cost_estimate": {"kind": "per_token", "amount": 0.000002},
        "count": 1,
        "tokens": 1500,
    },
)

#: Payloads whose canonical blob and SHA-256 the TS ``canonicalBlob`` must
#: reproduce byte for byte: key sorting at every depth, unicode escaping,
#: booleans, null, non-integral floats, nested lists.
CANONICAL_CASES: tuple[Any, ...] = (
    {},
    [],
    {"b": 1, "a": [1, 2.5, "é", True, None, {"y": "x", "x": "y"}]},
    {"app": "fal-ai/flux/dev", "args": {"prompt": "café at dusk ☕ — 35mm", "seed": 7}},
    {"nested": {"deep": {"deeper": [{"z": 0.1, "a": "  line sep"}]}}, "tab": "a\tb\n"},
    ["<from 0>", {"image_url": "<from 0>"}],
)

#: ``(application, arguments, tool, backend, key_extra)`` whose two identity
#: projections the TS side must build identically (omit-if-default rules).
IDENTITY_CASES: tuple[dict, ...] = (
    {
        "application": "fal-ai/flux/dev",
        "arguments": {"prompt": "x"},
        "tool": "generate_image",
    },
    {
        "application": "fal-ai/flux/dev",
        "arguments": {"prompt": "x"},
        "tool": "generate_image",
        "backend": "comfyui",
    },
    {
        "application": "fal-ai/flux/dev",
        "arguments": {"prompt": "x"},
        "tool": "generate_image",
        "key_extra": {"impl_version": "3"},
    },
    {
        "application": "fal-ai/flux/dev",
        "arguments": {"prompt": "x"},
        "tool": None,
        "key_extra": {},
    },
)


def export_schema(out_dir: "str | Path | None" = None) -> list[Path]:
    """Write the JSON contract under ``out_dir``; return the paths written.

    ``out_dir`` defaults to the ``schema/`` directory of *this checkout*. This is
    repository tooling: from an installed wheel (no ``pyproject.toml`` beside the
    package) it refuses rather than writing a stray ``schema/`` wherever the shell
    happens to be.
    """
    out = _resolve_out_dir(out_dir)
    fixtures = out / "fixtures"
    fixtures.mkdir(parents=True, exist_ok=True)
    return [
        _write(out / "call-plan.schema.json", _schema_of(_call_plan_type())),
        _write(out / "result.schema.json", _schema_of(_result_type())),
        _write(out / "model-record.schema.json", _schema_of(ModelRecord)),
        _copy(Path(_models_path()), out / "models.json"),
        _write(out / "constants.json", _constants()),
        _write(fixtures / "plans.json", _plan_fixtures()),
        _write(fixtures / "responses.json", _response_fixtures()),
        _write(fixtures / "pick_model.json", _pick_model_fixtures()),
        _write(fixtures / "cost.json", _cost_fixtures()),
        _write(fixtures / "canonical.json", _canonical_fixtures()),
    ]


def _resolve_out_dir(out_dir: "str | Path | None") -> Path:
    if out_dir is not None:
        return Path(out_dir)
    root = Path(__file__).resolve().parent.parent
    if not (root / "pyproject.toml").exists():
        raise FileNotFoundError(
            "export-schema is repository tooling: no checkout found next to this "
            f"package ({root}). Run it from a clone of thorwhalen/falaw, or pass "
            "out_dir explicitly."
        )
    return root / "schema"


# --- schemas --------------------------------------------------------------------


def _call_plan_type():
    from .plan import CallPlan

    return CallPlan


def _result_type():
    from .results import Result

    return Result


def _schema_of(tp) -> dict:
    """``tp`` as JSON Schema, with ``default_factory`` defaults made explicit.

    Pydantic emits no ``default`` for a ``field(default_factory=dict)``, so the
    generated Zod would leave ``arguments`` / ``metadata`` optional where this
    side always materialises ``{}``. A factory default is still a default: it
    is written into the schema (top level and ``$defs``) so a parsed value on
    the TS side carries the same shape a constructed one does here.
    """
    from pydantic import TypeAdapter

    schema = TypeAdapter(tp).json_schema()
    _add_factory_defaults(schema, tp)
    # A dataclass docstring is documentation, not contract, and whether it is
    # emitted as ``description`` depends on the pydantic version (2.13 started
    # to). Drop it at the object level so the committed export is identical
    # across versions; field-level descriptions, when declared, stay.
    schema.pop("description", None)
    _items_from_prefix_items(schema)
    for name, sub in schema.get("$defs", {}).items():
        sub.pop("description", None)
        if name in _NESTED_DATACLASSES:
            _add_factory_defaults(sub, _NESTED_DATACLASSES[name])
    return schema


def _items_from_prefix_items(schema: dict) -> None:
    """Express a uniform ``prefixItems`` (a ``tuple[float, float]``) as ``items``.

    json-schema-to-zod cannot render ``prefixItems`` and types the tuple as
    ``z.array(z.any())``; as ``items`` with the min/max bounds it emits
    ``z.array(z.number()).min(2).max(2)``, as close to the tuple as Zod v4 codegen gets.
    """
    for prop in schema.get("properties", {}).values():
        for branch in [prop, *prop.get("anyOf", [])]:
            prefix = branch.get("prefixItems")
            if prefix and "items" not in branch and all(p == prefix[0] for p in prefix):
                # `items` REPLACES `prefixItems`: json-schema-to-zod prefers the
                # latter and, unable to render it, falls back to z.any().
                branch["items"] = dict(prefix[0])
                del branch["prefixItems"]


def _add_factory_defaults(schema: dict, tp) -> None:
    props = schema.get("properties", {})
    for f in dataclasses.fields(tp):
        if f.default_factory is not dataclasses.MISSING and f.name in props:
            props[f.name].setdefault("default", _jsonable(f.default_factory()))


def _jsonable(value: Any) -> Any:
    return list(value) if isinstance(value, tuple) else value


def _nested_dataclasses() -> dict:
    from .plan import CostBasis
    from .results import Asset

    return {"CostBasis": CostBasis, "Asset": Asset, "CostEstimate": CostEstimate}


_NESTED_DATACLASSES = _nested_dataclasses()


# --- constants ------------------------------------------------------------------


def _constants() -> dict:
    return {
        "dflt_backend": DFLT_BACKEND,
        "plan_dict_schema": PLAN_DICT_SCHEMA,
        "catalogue_pricer": CATALOGUE_PRICER,
        "model_catalogue_table": MODEL_CATALOGUE_TABLE,
        "models_table_version": models_table_version(),
        "tier_order": list(_TIER_ORDER),
        "kind_keys": [list(pair) for pair in _KIND_KEYS],
        "placeholder_prefix": _PLACEHOLDER_PREFIX,
        "file_prefix": FILE_PREFIX,
        "content_ref_prefix": CONTENT_REF_PREFIX,
        "default_megapixels": DFLT_MEGAPIXELS,
        "default_video_resolution": DFLT_VIDEO_RESOLUTION,
        "video_resolution_short_side": dict(RESOLUTION_SHORT_SIDE),
        "default_video_aspect": DFLT_VIDEO_ASPECT,
        "output_kinds": list(get_args(OutputKind)),
        "cache_statuses": list(get_args(CacheStatus)),
    }


# --- fixtures -------------------------------------------------------------------


def _plan_fixtures() -> dict:
    calls = []
    for case in PLAN_CASES:
        plan = _PLANNERS[case["tool"]](**case["input"], consult_cache=False)
        calls.append(
            {
                "tool": case["tool"],
                "input": case["input"],
                "expected": call_plan_to_dict(plan),
                "plan_hash": plan_hash(Plan(calls=(plan,))),
            }
        )
    plans = []
    for indices in MULTI_PLAN_CASES:
        members = tuple(
            _PLANNERS[PLAN_CASES[i]["tool"]](
                **PLAN_CASES[i]["input"], consult_cache=False
            )
            for i in indices
        )
        plan = Plan(calls=members)
        plans.append(
            {
                "calls": list(indices),
                "expected": plan_to_dict(plan),
                "plan_hash": plan_hash(plan),
                "total_cost_usd": plan.total_cost_usd,
                "has_unknown_costs": plan.has_unknown_costs,
            }
        )
    errors = []
    for case in PLAN_ERROR_CASES:
        try:
            _PLANNERS[case["tool"]](**case["input"], consult_cache=False)
        except ValueError as e:
            if case["message"] not in str(e):
                raise RuntimeError(
                    f"{case['tool']} raised {e!s}, not {case['message']!r}"
                )
        else:
            raise RuntimeError(f"{case['tool']} did not raise: {case['input']}")
        errors.append({k: case[k] for k in ("tool", "input", "message")})
    return {"calls": calls, "plans": plans, "errors": errors}


def _response_fixtures() -> list[dict]:
    return [
        {
            **case,
            "expected": dataclasses.asdict(
                parse_response(
                    case["raw"],
                    application=case["application"],
                    arguments=case["arguments"],
                )
            ),
        }
        for case in RESPONSE_CASES
    ]


def _pick_model_fixtures() -> list[dict]:
    out = []
    for category, tier in PICK_MODEL_CASES:
        try:
            expected: "str | None" = pick_model(category=category, quality_tier=tier).id
            error = None
        except KeyError as e:
            expected, error = None, str(e)
        out.append(
            {
                "category": category,
                "quality_tier": tier,
                "expected": expected,
                "error": error,
            }
        )
    return out


def _cost_fixtures() -> list[dict]:
    out = []
    for case in COST_CASES:
        ce = case["cost_estimate"]
        record = ModelRecord(
            id="synthetic",
            category="image",
            cost_estimate=CostEstimate(**ce) if ce else None,
        )
        hints = {k: case[k] for k in ("seconds", "megapixels", "tokens") if k in case}
        out.append(
            {
                **case,
                "expected": estimate_call_cost(record, count=case["count"], **hints),
            }
        )
    return out


def _canonical_fixtures() -> dict:
    blobs = []
    for payload in CANONICAL_CASES:
        blob = canonical_blob(payload)
        blobs.append(
            {
                "payload": payload,
                "blob": blob.decode("utf-8"),
                "sha256": hashlib.sha256(blob).hexdigest(),
            }
        )
    identities = []
    for case in IDENTITY_CASES:
        kw: dict[str, Any] = {}
        if "backend" in case:
            kw["backend"] = case["backend"]
        if "key_extra" in case:
            kw["key_extra"] = case["key_extra"]
        identities.append(
            {
                **case,
                "cache_key_payload": cache_key_payload(
                    case["application"], case["arguments"], **kw
                ),
                "plan_identity_payload": plan_identity_payload(
                    case["application"], case["arguments"], tool=case["tool"], **kw
                ),
            }
        )
    return {"blobs": blobs, "identities": identities}


# --- io -------------------------------------------------------------------------


def _write(path: Path, obj: Any) -> Path:
    """Deterministic JSON: sorted keys, stable formatting, unicode kept readable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def _copy(src: Path, dst: Path) -> Path:
    """The catalogue byte for byte — its digest is what ``CostBasis`` records."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return dst


def _mapping(obj: Mapping[str, Any]) -> dict:
    return dict(obj)
