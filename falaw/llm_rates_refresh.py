"""Refresh proposals for the LLM rate table, never a silent overwrite (falaw#56).

``falaw/data/llm_rates.json`` was assembled by hand from two live sources and
has no refresh job, so it ages without saying so (falaw#50 option A found
this). Both sources move on their own schedule:

1. fal's own any-llm endpoint doc (``ANY_LLM_DOC_URL``) — the ``model`` enum,
   the flat per-request price, and the verbatim premium list.
2. OpenRouter's public catalogue (``OPENROUTER_MODELS_URL``) — the upstream
   ``pricing.prompt`` / ``pricing.completion`` any-llm resells.

:func:`refresh_llm_rates` fetches both through an injectable seam, parses them
with pure functions (:func:`parse_any_llm_doc`, :func:`parse_openrouter_models`),
and diffs the result against the committed table. A price change is a
decision, not something this module gets to make on your behalf — the
committed ``llm_rates.json`` a test pins the premium set against is **never**
written here. ``write=True`` persists a *proposed* table plus a
human-readable diff alongside it; promoting the proposal over the committed
file is a separate, human step.

>>> from falaw.llm_rates_refresh import parse_any_llm_doc
>>> doc = parse_any_llm_doc(
...     '- **Price**: $0.001 per requests\\n'
...     '- **`model`** (`ModelEnum`, _optional_):\\n'
...     '  Name of the model to use. Premium models are charged at 10x the '
...     'rate of standard models, they include: a/b, c/d. Default value: `"a/b"`\\n'
...     '  - Options: `"a/b"`, `"c/d"`, `"e/f"`\\n'
... )
>>> doc.base_per_call_usd
0.001
>>> doc.premium_multiple
10
>>> sorted(doc.premium_models)
['a/b', 'c/d']
>>> doc.model_enum
('a/b', 'c/d', 'e/f')
"""

from __future__ import annotations

import datetime
import json
import os
import re
from dataclasses import dataclass
from typing import Callable, Mapping, Optional

from .llm_rates import _rates_path
from .registry import register_tool

ANY_LLM_DOC_URL = "https://fal.ai/models/fal-ai/any-llm/llms.txt"
"""fal's any-llm endpoint doc: model enum, flat price, premium list."""

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
"""OpenRouter's public model catalogue: upstream per-token list prices."""

PROPOSED_RATES_FILENAME = "llm_rates.proposed.json"
"""Basename of the proposed table a refresh writes under ``falaw/data``."""

RATES_DIFF_FILENAME = "llm_rates.diff.txt"
"""Basename of the human-readable diff a refresh writes under ``falaw/data``."""

TOKEN_RATE_PRECISION = 6
"""Decimal places kept for a converted ``*_usd_per_mtok`` rate."""

_PRICE_RE = re.compile(r"\*\*Price\*\*:\s*\$(?P<amount>[0-9.]+)\s*per\s*requests?")
_MODEL_FIELD_RE = re.compile(r"\*\*`model`\*\*.*?(?=\n- \*\*`|\Z)", re.DOTALL)
_PREMIUM_RE = re.compile(
    r"Premium models are charged at (?P<mult>\d+)x the rate of standard "
    r"models, they include:\s*(?P<list>.+?)\.\s*Default value:",
    re.DOTALL,
)
"""Stops at the literal ``. Default value:`` that follows the list, not the
first ``.`` — several model ids (``gpt-4.1``, ``claude-3.5-sonnet``, ...)
contain a period of their own."""
_OPTIONS_RE = re.compile(r"Options:\s*(?P<opts>(?:`\"[^\"]+\"`,?\s*)+)")
_QUOTED_RE = re.compile(r'`"([^"]+)"`')
_INPUTS_RE = re.compile(r"input parameters:(?P<inputs>.*?)### Output Schema", re.DOTALL)
_PARAM_RE = re.compile(r"^- \*\*`(\w+)`\*\*", re.MULTILINE)

#: any-llm's input parameters as of the last human review. The rate table's ceiling
#: assumes none of them lets a call write a prompt cache (falaw#129, see the
#: :mod:`falaw.llm_rates` docstring), so the refresh reports any parameter fal adds.
REVIEWED_ANY_LLM_INPUTS = frozenset(
    {
        "prompt",
        "system_prompt",
        "reasoning",
        "priority",
        "temperature",
        "max_tokens",
        "model",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class AnyLlmDoc:
    """The pricing-relevant facts parsed out of fal's any-llm doc.

    Attributes:
        base_per_call_usd: The flat per-request price fal publishes for the
            standard tier.
        premium_multiple: How many times the base price a premium-tier
            request costs.
        premium_models: The routed-model ids fal's doc lists as premium,
            verbatim (a model here that is not in ``model_enum`` belongs to a
            different endpoint, e.g. a vision-only variant, and is not a rate
            table row).
        model_enum: Every routed-model id the ``model`` argument accepts, in
            the doc's own order.
        input_params: The input parameter names the doc lists (empty when the
            doc has no input section).
    """

    base_per_call_usd: float
    premium_multiple: int
    premium_models: frozenset[str]
    model_enum: tuple[str, ...]
    input_params: frozenset[str] = frozenset()


def parse_any_llm_doc(text: str) -> AnyLlmDoc:
    """Pure parse of fal's any-llm ``llms.txt`` into :class:`AnyLlmDoc`.

    Raises:
        ValueError: the doc is missing the price line, the ``model`` field,
            its premium sentence, or its options list — any of which means
            fal changed the doc's shape and a human should look, not that the
            refresh should guess.
    """
    price_match = _PRICE_RE.search(text)
    if price_match is None:
        raise ValueError("any-llm doc: no '$X per requests' price line found")
    base_per_call_usd = float(price_match.group("amount"))

    model_field_match = _MODEL_FIELD_RE.search(text)
    if model_field_match is None:
        raise ValueError("any-llm doc: no `model` field block found")
    model_field = model_field_match.group(0)

    premium_match = _PREMIUM_RE.search(model_field)
    if premium_match is None:
        raise ValueError("any-llm doc: no premium-tier sentence found")
    premium_multiple = int(premium_match.group("mult"))
    premium_models = frozenset(
        m.strip() for m in premium_match.group("list").split(",") if m.strip()
    )

    options_match = _OPTIONS_RE.search(model_field)
    if options_match is None:
        raise ValueError("any-llm doc: no `model` Options list found")
    model_enum = tuple(_QUOTED_RE.findall(options_match.group("opts")))
    if not model_enum:
        raise ValueError("any-llm doc: `model` Options list parsed empty")

    inputs_match = _INPUTS_RE.search(text)
    input_params = frozenset(
        _PARAM_RE.findall(inputs_match.group("inputs")) if inputs_match else ()
    )

    return AnyLlmDoc(
        base_per_call_usd=base_per_call_usd,
        premium_multiple=premium_multiple,
        premium_models=premium_models,
        model_enum=model_enum,
        input_params=input_params,
    )


def parse_openrouter_models(payload: dict) -> dict[str, tuple[float, float]]:
    """``{model_id: (input_usd_per_mtok, output_usd_per_mtok)}`` from OpenRouter.

    Pure parse of the ``GET /api/v1/models`` body. OpenRouter quotes
    ``pricing.prompt``/``pricing.completion`` as USD-per-token strings; this
    scales them to the table's per-million-token unit. A model with a
    missing, non-numeric, or non-positive prompt/completion price is left out
    — unknown, never a guessed zero.
    """
    rates: dict[str, tuple[float, float]] = {}
    for row in payload.get("data", ()):
        model_id = row.get("id")
        pricing = row.get("pricing") or {}
        if not model_id:
            continue
        prompt = _positive_float(pricing.get("prompt"))
        completion = _positive_float(pricing.get("completion"))
        if prompt is None or completion is None:
            continue
        rates[model_id] = (_per_mtok(prompt), _per_mtok(completion))
    return rates


def parse_openrouter_long_prompts(payload: dict) -> dict[str, Optional[dict]]:
    """``{model_id: long_prompt block or None}`` for every OpenRouter model with overrides.

    Pure parse of ``pricing.overrides`` in the ``GET /api/v1/models`` body
    (falaw#124): an override bills its ``prompt``/``completion`` rates once a
    prompt reaches ``min_prompt_tokens``. The block has the shape the rate
    tables share (:func:`falaw.llm_prices.parse_long_prompt`), so
    ``over_input_tokens`` is ``min_prompt_tokens - 1``: the tier starts *at* the
    threshold, and a ceiling must not quote the boundary at the cheaper rate.

    ``None`` marks a model whose overrides this parse cannot price: more than
    one, or one without an integer threshold and two positive rates.
    :func:`build_proposed_rows` then drops that model's token rates, because
    quoting its base rates alone is the under-quote this tier exists to prevent.
    """
    blocks: dict[str, Optional[dict]] = {}
    for row in payload.get("data", ()):
        model_id = row.get("id")
        overrides = (row.get("pricing") or {}).get("overrides")
        if model_id and overrides:
            blocks[model_id] = (
                _long_prompt_block(overrides[0]) if len(overrides) == 1 else None
            )
    return blocks


def _long_prompt_block(override: dict) -> Optional[dict]:
    threshold = override.get("min_prompt_tokens")
    prompt = _positive_float(override.get("prompt"))
    completion = _positive_float(override.get("completion"))
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, int)
        or threshold < 1
        or None in (prompt, completion)
    ):
        return None
    return {
        "over_input_tokens": threshold - 1,
        "input_usd_per_mtok": _per_mtok(prompt),
        "output_usd_per_mtok": _per_mtok(completion),
    }


def _per_mtok(per_token: float) -> float:
    # Rounded to TOKEN_RATE_PRECISION: scaling a per-token float (e.g.
    # 0.0000004) by 1e6 reintroduces binary-float noise (0.39999999999999997)
    # that would diff as "changed" against a hand-typed 0.4 forever.
    return round(per_token * 1_000_000, TOKEN_RATE_PRECISION)


def _positive_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def build_proposed_rows(
    any_llm: AnyLlmDoc,
    openrouter_rates: "dict[str, tuple[float, float]]",
    *,
    date: str,
    long_prompts: "Mapping[str, Optional[dict]]",
) -> "list[dict]":
    """One rate-table row per id in ``any_llm.model_enum``, freshly derived.

    ``long_prompts`` (:func:`parse_openrouter_long_prompts`) adds a
    ``long_prompt`` block to a priced row whose model has one; a model whose
    tier could not be parsed (``None``) gets no token rates at all.

    The whole table is regenerated from the two sources every run — there is
    no merge with the committed file here. The committed file only changes
    when a human promotes a proposal, so there is nothing stale to carry
    forward into it.
    """
    any_llm_source = f"fal any-llm endpoint doc ({ANY_LLM_DOC_URL})"
    both_source = f"{any_llm_source}; upstream per-token rates from OpenRouter ({OPENROUTER_MODELS_URL})"
    rows: list[dict] = []
    for model in any_llm.model_enum:
        premium = model in any_llm.premium_models
        per_call_usd = any_llm.base_per_call_usd * (
            any_llm.premium_multiple if premium else 1
        )
        token_rates = openrouter_rates.get(model)
        long_prompt = long_prompts.get(model)
        unpriced_tier = model in long_prompts and long_prompt is None
        if token_rates is None or unpriced_tier:
            rows.append(
                {
                    "model": model,
                    "tier": "premium" if premium else "standard",
                    "per_call_usd": per_call_usd,
                    "input_usd_per_mtok": None,
                    "output_usd_per_mtok": None,
                    "source": any_llm_source,
                    "date": date,
                    "notes": (
                        "upstream publishes a long-prompt tier this refresh cannot "
                        "parse, so its token rates are unknown"
                        if unpriced_tier
                        else "no per-token rate published upstream for this id on "
                        "the fetch date; the per-request tier is the only "
                        "known basis"
                    ),
                }
            )
        else:
            input_rate, output_rate = token_rates
            row = {
                "model": model,
                "tier": "premium" if premium else "standard",
                "per_call_usd": per_call_usd,
                "input_usd_per_mtok": input_rate,
                "output_usd_per_mtok": output_rate,
            }
            if long_prompt is not None:
                row["long_prompt"] = dict(long_prompt)
            rows.append({**row, "source": both_source, "date": date, "notes": ""})
    return rows


_DIFFED_FIELDS = (
    "tier",
    "per_call_usd",
    "input_usd_per_mtok",
    "output_usd_per_mtok",
    "long_prompt",
)


def diff_llm_rate_tables(
    committed_rows: "list[dict]", proposed_rows: "list[dict]"
) -> dict:
    """Compare two ``rows`` lists (as loaded from the table JSON) by model id.

    Returns ``{"added", "removed", "changed", "unchanged"}``: ``added``/
    ``removed`` are sorted model-id lists; ``changed`` is a list of
    ``{"model", "field", "old", "new", "source", "date"}`` for every
    :data:`_DIFFED_FIELDS` value that moved (``source``/``date`` themselves
    are provenance, not a price fact, so they never appear as a *diffed
    field* even though every row gets a fresh stamp — but the *proposed*
    row's own ``source``/``date`` ride along on every change entry, so the
    human-readable diff carries where the new number came from, not just
    what it is); ``unchanged`` is a count.
    """
    committed = {r["model"]: r for r in committed_rows}
    proposed = {r["model"]: r for r in proposed_rows}

    added = sorted(set(proposed) - set(committed))
    removed = sorted(set(committed) - set(proposed))
    changed: list[dict] = []
    unchanged = 0
    for model in sorted(set(committed) & set(proposed)):
        old, new = committed[model], proposed[model]
        row_changed = False
        for field in _DIFFED_FIELDS:
            if old.get(field) != new.get(field):
                changed.append(
                    {
                        "model": model,
                        "field": field,
                        "old": old.get(field),
                        "new": new.get(field),
                        "source": new.get("source", ""),
                        "date": new.get("date", ""),
                    }
                )
                row_changed = True
        if not row_changed:
            unchanged += 1

    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged": unchanged,
    }


def format_llm_rates_diff(diff: dict) -> str:
    """Render :func:`diff_llm_rate_tables`'s result as a human-readable report."""
    lines: list[str] = []
    if not diff["added"] and not diff["removed"] and not diff["changed"]:
        lines.append(f"No changes ({diff['unchanged']} rows unchanged).")
        return "\n".join(lines)

    if diff["added"]:
        lines.append(f"Added ({len(diff['added'])}):")
        lines.extend(f"  + {model}" for model in diff["added"])
    if diff["removed"]:
        lines.append(f"Removed ({len(diff['removed'])}):")
        lines.extend(f"  - {model}" for model in diff["removed"])
    if diff["changed"]:
        lines.append(f"Changed ({len(diff['changed'])} fields):")
        for entry in diff["changed"]:
            lines.append(
                f"  ~ {entry['model']}: {entry['field']} "
                f"{entry['old']!r} -> {entry['new']!r}  "
                f"[{entry.get('date') or 'no date'} "
                f"{entry.get('source') or 'no source'}]"
            )
    lines.append(f"Unchanged: {diff['unchanged']} rows.")
    return "\n".join(lines)


# Injectable HTTP seams. Production uses httpx; tests pass a fixture-backed
# stub so no test ever reaches the network. Two seams, not one, because the
# two sources have different response shapes (plain text vs. JSON). httpx is
# not a declared falaw dependency -- it rides in transitively via fal-client
# (same precedent as `pricing.py`'s `_default_http_get`); either default only
# imports it lazily, inside the function, so a `write=False` refresh with an
# injected `http_get_*` (as every test uses) never needs it installed.
HttpGetText = Callable[[str], str]
HttpGetJson = Callable[[str], dict]


def _default_http_get_text(url: str) -> str:
    from .errors import import_httpx

    httpx = import_httpx("refreshing LLM rates")

    with httpx.Client(timeout=15.0) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def _default_http_get_json(url: str) -> dict:
    from .errors import import_httpx

    httpx = import_httpx("refreshing LLM rates")

    with httpx.Client(timeout=15.0) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


def _data_dir() -> str:
    return os.path.dirname(_rates_path())


def _proposed_path(data_dir: Optional[str] = None) -> str:
    return os.path.join(data_dir or _data_dir(), PROPOSED_RATES_FILENAME)


def _diff_path(data_dir: Optional[str] = None) -> str:
    return os.path.join(data_dir or _data_dir(), RATES_DIFF_FILENAME)


def refresh_llm_rates(
    *,
    write: bool = False,
    http_get_any_llm_doc: Optional[HttpGetText] = None,
    http_get_openrouter_models: Optional[HttpGetJson] = None,
    rates_path: Optional[str] = None,
    proposed_path: Optional[str] = None,
    diff_path: Optional[str] = None,
    today: Optional[str] = None,
) -> dict:
    """Fetch both sources, propose a fresh table, diff it — never overwrite.

    ``rates_path`` (default: the committed ``llm_rates.json``) is read only,
    never written: this function has no code path that touches the committed
    table, by design — a repriced or retiered model is a decision for a human
    to promote, not something a refresh job gets to make silently. With
    ``write=True``, the freshly-derived table is written to ``proposed_path``
    (default: ``llm_rates.proposed.json`` next to the committed file) and the
    diff report to ``diff_path`` (default: ``llm_rates.diff.txt``).

    Returns a summary dict: ``{"fetched_at", "committed_models",
    "proposed_models", "diff", "write", "proposed_path", "diff_path"}``. The
    two path keys are ``None`` when ``write=False``.
    """
    get_text = http_get_any_llm_doc or _default_http_get_text
    get_json = http_get_openrouter_models or _default_http_get_json

    any_llm_text = get_text(ANY_LLM_DOC_URL)
    openrouter_body = get_json(OPENROUTER_MODELS_URL)

    any_llm = parse_any_llm_doc(any_llm_text)
    openrouter_rates = parse_openrouter_models(openrouter_body)

    stamp = today or datetime.date.today().isoformat()
    proposed_rows = build_proposed_rows(
        any_llm,
        openrouter_rates,
        date=stamp,
        long_prompts=parse_openrouter_long_prompts(openrouter_body),
    )

    path = rates_path or _rates_path()
    with open(path, encoding="utf-8") as f:
        committed_table = json.load(f)
    committed_rows = committed_table["rows"]

    diff = diff_llm_rate_tables(committed_rows, proposed_rows)
    diff_text = format_llm_rates_diff(diff)
    unreviewed_inputs = sorted(any_llm.input_params - REVIEWED_ANY_LLM_INPUTS)
    if unreviewed_inputs:
        diff_text = (
            f"any-llm has new input parameters {unreviewed_inputs}: check that none "
            "lets a call write a prompt cache before promoting (falaw#129).\n\n"
            + diff_text
        )

    summary = {
        "fetched_at": stamp,
        "committed_models": len(committed_rows),
        "proposed_models": len(proposed_rows),
        "diff": diff,
        "unreviewed_any_llm_inputs": unreviewed_inputs,
        "write": write,
        "proposed_path": None,
        "diff_path": None,
    }

    if write:
        out_proposed = proposed_path or _proposed_path()
        out_diff = diff_path or _diff_path()
        proposed_table = dict(committed_table)
        proposed_table["rows"] = sorted(proposed_rows, key=lambda r: r["model"])
        with open(out_proposed, "w", encoding="utf-8") as f:
            json.dump(proposed_table, f, indent=2, ensure_ascii=False)
            f.write("\n")
        with open(out_diff, "w", encoding="utf-8") as f:
            f.write(diff_text)
            f.write("\n")
        summary["proposed_path"] = out_proposed
        summary["diff_path"] = out_diff

        from .journal import _default_journal

        _default_journal().append(
            kind="note",
            text=(
                f"refresh_llm_rates: {len(diff['added'])} added, "
                f"{len(diff['removed'])} removed, "
                f"{len(diff['changed'])} fields changed across "
                f"{len({c['model'] for c in diff['changed']})} models -- "
                f"proposal written to {os.path.basename(out_proposed)}, "
                "committed table untouched"
            ),
            tags=("refresh", "cost", "llm_rates"),
            context={"diff": diff},
        )

    return summary


@register_tool(
    name="refresh_llm_rates",
    description=(
        "Fetch fal's any-llm doc and OpenRouter's model catalogue and diff "
        "them against `falaw/data/llm_rates.json`. Never overwrites the "
        "committed table -- a repriced or retiered model is a decision, not "
        "an auto-apply. Pass `write=True` to persist a proposed table "
        "(`llm_rates.proposed.json`) plus a human-readable diff "
        "(`llm_rates.diff.txt`) for a human to review and promote; default "
        "is a dry-run summary. Reads two free, unauthenticated endpoints; "
        "makes no billed call."
    ),
    tags=("refresh", "maintenance", "cost", "free"),
    input_schema={
        "type": "object",
        "properties": {
            "write": {"type": "boolean", "default": False},
        },
    },
    output_schema={"type": "object"},
)
def _refresh_llm_rates_tool(*, write: bool = False) -> dict:
    """Bridge-facing wrapper for :func:`refresh_llm_rates`.

    Separate because bridges derive a JSON schema from the function
    signature, and the real function's dependency-injection seams are not
    JSON-schema representable -- nor anything a tool caller should reach.
    """
    return refresh_llm_rates(write=write)
