"""LLM-driven tools: text completion, screenplay → Scene IR, IR editing.

These wrap fal-ai/any-llm so the agent (or the user) can invoke an LLM
inline as part of a falaw workflow --- e.g. parsing a treatment into a
structured Scene, or rewriting a Beat from a directorial note.

We intentionally keep these thin. The contract is: any-llm is the
universal LLM endpoint, you pick the model via `model`, and we return
plain Python (str or parsed dict).
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, NamedTuple, Optional

from ..cache import cached_call_fal
from ..cost import estimate_call_cost
from ..llm_prices import llm_token_counts
from ..llm_rates import llm_cost_bases
from ..routing import ANY_LLM, routed_model
from ..registry import get_model, register_tool
from ..scene import Beat, Scene, beat_id, make_beat, make_shot, shot_id

_DEFAULT_LLM = ANY_LLM
# Valid any-llm OpenRouter ids (as of mid-2026); see fal-ai/any-llm schema.
# Sonnet 4.5 is the strongest balanced default for structured-output tasks.
_DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"


@register_tool(
    name="llm_complete",
    description=(
        "Run a single LLM completion via fal-ai/any-llm. Returns the raw "
        "text output. Use `system` for instruction prompts, `prompt` for "
        "the user message. Cached by content."
    ),
    tags=("llm", "completion"),
    input_schema={
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "system": {"type": "string"},
            "model": {
                "type": "string",
                "default": _DEFAULT_MODEL,
                "description": "OpenRouter model id, e.g. 'anthropic/claude-3-5-sonnet'.",
            },
            "temperature": {"type": "number", "default": 0.7},
            "extra": {"type": "object"},
        },
    },
    output_schema={"type": "string"},
    examples=(
        {
            "prompt": "summarize this scene in one line",
            "system": "you are a script consultant",
        },
    ),
)
def llm_complete(
    prompt: str,
    *,
    system: str = "",
    model: str = _DEFAULT_MODEL,
    temperature: float = 0.7,
    extra: Optional[dict] = None,
) -> str:
    """Single-shot LLM completion. Returns the assistant text.

    Delegates to :func:`llm_complete_with_receipt` (one argument-construction
    site, so the two spellings share one cache identity) and discards the
    receipt. A caller that accounts for spend wants the receipt variant.
    """
    text, _ = llm_complete_with_receipt(
        prompt, system=system, model=model, temperature=temperature, extra=extra
    )
    return text


@dataclass(frozen=True, slots=True)
class LlmReceipt:
    """What one eager LLM call cost — the record the eager path never kept.

    The falaw half of falaw#50's option B: the eager :func:`llm_complete`
    returned a bare string, so LLM spend was invisible to every accounting
    surface — not because estimates were ``None``, but because *nothing was
    recorded at all* (the field signature: real dollars spent beside
    ``plans: 0``). A caller that books receipts uses
    :func:`llm_complete_with_receipt` and gets this alongside the text.

    Field semantics, honest by construction:

    - ``chars_in`` / ``chars_out`` are **measured facts** (prompt+system in,
      response text out).
    - ``tokens_in`` / ``tokens_out`` are **best-effort** from the raw
      response's usage block (OpenAI ``prompt_tokens``/``completion_tokens``
      and Anthropic ``input_tokens``/``output_tokens`` shapes, normalized by
      :func:`falaw.llm_token_counts`, so an Anthropic ``tokens_in`` counts
      its cache reads and writes too). ``None`` means *unrecorded by the
      provider response* (absent or nonsense, e.g. negative), never zero.
    - ``estimated_cost_usd`` is ``0.0`` on a cache hit (nothing was billed),
      else fal's published per-request price **for the routed model**, read
      off the rate table (:func:`falaw.llm_ceiling_usd`) — an estimate, not
      an observed bill. When the response reports both token counts and the
      routed model has upstream token rates, it is the greater of that price
      and those tokens at the upstream rates (long-prompt tier included,
      falaw#130), the same max-over-bases a plan-time quote takes, so a long
      prompt is not recorded at the flat request price. fal publishes no
      per-token price for any-llm, so that figure is an upstream-rate
      estimate. fal's documented any-llm output schema (``output``,
      ``reasoning``, ``partial``, ``error``) carries no ``usage`` block, so
      an any-llm receipt stays at the request price unless a response
      reports usage, which is priced the moment one does. The rate rows carry
      no cache rates, so cache-read tokens are priced at the full input rate:
      for a cached prompt the figure is an upper estimate. It is the routed
      model and not the ``fal-ai/any-llm`` record because the record carries fal's *standard* tier, and a premium
      routed model bills ten times that: pricing every turn from the record
      under-reported premium spend tenfold in the ledger a consumer sums
      (falaw#55). A cost the response itself reports (``usage.cost``) is one
      more basis in that max, never an override (falaw#135): fal bills
      any-llm a flat per-request price, and a ``usage.cost`` passed through
      from OpenRouter is the *upstream* cost, which can be far below fal's
      bill, so a receipt never records less than its estimate. ``None`` only
      when nothing can price it at all.
    - ``cost_source`` says which of those cases produced the number, so a
      receipt consumer never has to guess: ``"cache_hit"``,
      ``"rate_table:per_call"``, ``"rate_table:upstream_tokens"`` (the
      reported tokens at upstream rates exceeded the request price: an
      upstream-rate estimate, not a fal-published price),
      ``"observed:usage_cost"`` (the response reported a ``usage.cost``
      strictly above the estimate, or nothing else could price the call),
      ``"registry:<kind>"`` (the fallback for a model the table does not
      price), or ``"unknown"``.
    - ``rates_table_version`` / ``rate_date`` say which rate table, and which
      day's row of it, a ``"rate_table:*"`` cost was read from
      (:attr:`falaw.llm_rates.LlmCostBases.table_version` and
      :attr:`~falaw.llm_rates.LlmCostBases.rate_date`), so a receipt can be
      audited or re-quoted later the way a plan's :class:`falaw.CostBasis`
      is. Both are set exactly when ``cost_source`` starts with
      ``"rate_table:"``, and ``""`` otherwise.
    """

    application: str
    model: str
    cache_hit: bool
    chars_in: int
    chars_out: int
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    estimated_cost_usd: Optional[float] = None
    cost_source: str = "unknown"
    rates_table_version: str = ""
    rate_date: str = ""


_USAGE_SHAPES = (
    ("openai", "prompt_tokens", "completion_tokens"),
    ("anthropic", "input_tokens", "output_tokens"),
)
"""``(provider, input key, output key)`` per usage shape, in the order tried."""

_USAGE_COST_KEY = "cost"
"""Key of the USD a call cost in a usage block (OpenRouter's ``usage.cost``)."""

_OBSERVED_COST_SOURCE = "observed:usage_cost"
"""``cost_source`` of a receipt whose reported ``usage.cost`` bound its cost."""


def _usage_block(raw: Any) -> Optional[dict]:
    """The response's top-level ``usage`` dict, or ``None`` when it has none."""
    usage = raw.get("usage") if isinstance(raw, dict) else None
    return usage if isinstance(usage, dict) else None


def _extract_llm_usage(raw: Any) -> tuple[Optional[int], Optional[int]]:
    """Best-effort ``(tokens_in, tokens_out)`` from an LLM response's usage block.

    Recognises the two shapes that exist in the wild — OpenAI
    (``usage.prompt_tokens`` / ``usage.completion_tokens``) and Anthropic
    (``usage.input_tokens`` / ``usage.output_tokens``) — wherever the
    ``usage`` dict sits at the top level, and counts them with
    :func:`falaw.llm_token_counts`: Anthropic's ``input_tokens`` excludes
    cache reads and writes, which are prompt tokens all the same. Each side is
    read from the first shape that reports it, so a block mixing the two still
    yields both. A side whose key is absent or not a non-negative ``int`` is
    ``None``: unrecorded, never invented, and never above what OpenAI's
    ``prompt_tokens`` itself says (its cached part is a subset of it).
    """
    usage = _usage_block(raw)
    if usage is None:
        return None, None

    def _is_count(value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0

    def _side(side: str) -> Optional[int]:
        for provider, in_key, out_key in _USAGE_SHAPES:
            reported = usage.get(in_key if side == "input" else out_key)
            if reported is None:
                continue
            if not _is_count(reported):
                return None
            counted = getattr(llm_token_counts(provider, usage), side)
            return min(counted, reported) if provider == "openai" else counted
        return None

    return _side("input"), _side("output")


def llm_complete_with_receipt(
    prompt: str,
    *,
    system: str = "",
    model: str = _DEFAULT_MODEL,
    temperature: float = 0.7,
    extra: Optional[dict] = None,
) -> tuple[str, LlmReceipt]:
    """Single-shot LLM completion that also reports what it cost.

    Same arguments, same wire call, same cache identity as
    :func:`llm_complete` — the receipt is a side channel, observed from the
    call this function was making anyway (the cache layer's ``cache_hit``
    event, the response's usage block, the registry's estimate). Library
    surface only — deliberately NOT a registered tool: the tool surface
    keeps the one string-returning ``llm_complete``.
    """
    arguments: dict = {
        "model": model,
        "prompt": prompt,
        "temperature": temperature,
    }
    if system:
        arguments["system_prompt"] = system
    arguments.update(extra or {})

    hit_seen: list[bool] = []

    def _watch(event) -> None:
        if getattr(event, "kind", "") == "cache_hit":
            hit_seen.append(True)

    raw = cached_call_fal(_DEFAULT_LLM, arguments, on_event=_watch)
    text = _extract_llm_text(raw)
    tokens_in, tokens_out = _extract_llm_usage(raw)

    cache_hit = bool(hit_seen)
    served_by = routed_model(_DEFAULT_LLM, arguments)  # arguments always name a model
    cost = _receipt_cost(
        _extract_usage_cost(raw),
        served_by=served_by,
        cache_hit=cache_hit,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )

    return text, LlmReceipt(
        application=_DEFAULT_LLM,
        model=served_by,
        cache_hit=cache_hit,
        chars_in=len(prompt) + len(system),
        chars_out=len(text),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        **cost._asdict(),
    )


def _extract_usage_cost(raw: Any) -> Optional[float]:
    """The cost the response itself reports (``usage.cost``), or ``None``.

    OpenRouter puts the USD a call cost in ``usage.cost``; fal's documented
    any-llm output carries no ``usage`` block today, so this is ``None`` until
    a response reports one (falaw#135). A value that is not a finite,
    non-negative number (an int too large for a float included) is not a cost
    and reads as ``None``; ``-0.0`` reads as ``0.0``.
    """
    usage = _usage_block(raw)
    reported = usage.get(_USAGE_COST_KEY) if usage is not None else None
    if isinstance(reported, bool) or not isinstance(reported, (int, float)):
        return None
    try:
        usd = float(reported)
    except OverflowError:
        return None
    if not (math.isfinite(usd) and usd >= 0):
        return None
    return abs(usd)  # -0.0 passes ``>= 0``; record it as 0.0


class _ReceiptCost(NamedTuple):
    """The :class:`LlmReceipt` cost fields, in one value (field names match)."""

    estimated_cost_usd: Optional[float]
    cost_source: str
    rates_table_version: str = ""
    rate_date: str = ""


def _receipt_cost(
    observed_usd: Optional[float],
    *,
    served_by: str,
    cache_hit: bool,
    tokens_in: Optional[int],
    tokens_out: Optional[int],
) -> _ReceiptCost:
    """What a call cost, and on what basis: the whole precedence in one place.

    1. A cache hit billed nothing: ``0.0``, ``"cache_hit"``.
    2. Otherwise the estimate: the rate table's bound for the routed model
       (falling back to the registry for a model the table does not price).
    3. A reported ``observed_usd`` is one more basis in the max (falaw#135):
       it binds only when strictly above the estimate, or when there is no
       estimate. It never lowers one: fal bills any-llm a flat per-request
       price, and an OpenRouter ``usage.cost`` passed through is the
       *upstream* cost, which fal's own docs show far below that bill.

    Prices the **routed model** against the rate table (falaw#50, option A),
    not the ``fal-ai/any-llm`` record. The router's single ``per_call`` figure
    is fal's *standard* tier; a premium routed model — falaw's own default
    among them — bills ten times that, so the record under-reported every
    premium turn tenfold in the very ledger a consumer sums to answer "what
    have I spent?" (falaw#55).

    The registry stays as a named fallback for a model the table does not
    price. Unlike a plan-time quote, a receipt is a record of money already
    spent: dropping to ``None`` there deletes a known-approximate number rather
    than gating anything, and ``cost_source`` says which case produced it, so
    a consumer can tell a table-priced row from a router-priced one.

    With both token counts reported and token rates on the row, the table
    bound is the greater of the request price and those tokens at the
    upstream rates (falaw#130), computed once by
    :func:`falaw.llm_rates.llm_cost_bases`; ``"rate_table:upstream_tokens"``
    names the case where the tokens bind, an upstream-rate estimate since fal
    publishes no per-token price.
    """
    if cache_hit:
        return _ReceiptCost(0.0, "cache_hit")
    bases = llm_cost_bases(served_by, input_tokens=tokens_in, output_tokens=tokens_out)
    if bases is not None:
        usd, basis = bases.bound()
        estimate = _ReceiptCost(
            usd,
            f"rate_table:{basis}",
            rates_table_version=bases.table_version,
            rate_date=bases.rate_date,
        )
    else:
        record = get_model(_DEFAULT_LLM)
        ce = record.cost_estimate
        estimate = _ReceiptCost(
            estimate_call_cost(record, count=1),
            f"registry:{ce.kind}" if ce is not None else "unknown",
        )
    if observed_usd is not None and (
        estimate.estimated_cost_usd is None
        or observed_usd > estimate.estimated_cost_usd
    ):
        return _ReceiptCost(observed_usd, _OBSERVED_COST_SOURCE)
    return estimate


def _extract_llm_text(raw: Any) -> str:
    """Best-effort: pull a plain text response out of any-llm's reply shape."""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        for key in ("output", "text", "response", "completion", "content"):
            v = raw.get(key)
            if isinstance(v, str) and v.strip():
                return v
        # OpenAI-shaped: {"choices": [{"message": {"content": "..."}}]}
        choices = raw.get("choices")
        if isinstance(choices, list) and choices:
            msg = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str):
                    return content
    return str(raw)


# --- screenplay → Scene IR -------------------------------------------------


_SCREENPLAY_SYSTEM_PROMPT = """\
You convert prose screenplays or treatments into structured Scene JSON.

Output schema (strict JSON, no commentary):
{
  "title": str,
  "style": str,                 # overall visual style; "" if unstated
  "characters": [{"name": str, "description": str}],
  "environments": [{"name": str, "description": str, "time_of_day": str}],
  "shots": [{"id": str, "description": str, "framing": str,
             "environment": str, "characters": [str], "camera": str}],
  "beats": [{"id": str, "speaker": str, "line": str, "action": str,
             "emotion": str, "shot_id": str}]
}

Rules:
- Every beat's `speaker` MUST match a character's `name` exactly (or be "" for narration/action).
- Every beat's `shot_id` MUST match a shot's `id`.
- Every shot's `environment` MUST match an environment's `name`.
- Use kebab-case-with-hash-style stable ids: e.g. "001-wide-diner-establishing".
- Prefer 3-8 shots and 8-30 beats per scene unless the input is much longer.
- `description` fields should be one to two sentences, concrete enough for an image model.
- Output ONLY the JSON object. No preamble. No code fences.
"""


@register_tool(
    name="parse_screenplay",
    description=(
        "Parse prose screenplay/treatment text into a structured Scene "
        "(via any-llm). Returns a falaw.Scene you can render directly. "
        "Use `model_hint` to pick a stronger LLM for nuanced material."
    ),
    tags=("llm", "scene", "preproduction"),
    input_schema={
        "type": "object",
        "required": ["text"],
        "properties": {
            "text": {"type": "string"},
            "title": {"type": "string"},
            "style": {"type": "string"},
            "model": {"type": "string", "default": _DEFAULT_MODEL},
        },
    },
    output_schema={"type": "object", "description": "falaw.Scene"},
    examples=(),
)
def parse_screenplay(
    text: str,
    *,
    title: str = "",
    style: str = "",
    model: str = _DEFAULT_MODEL,
) -> Scene:
    """Convert prose screenplay text into a Scene IR via an LLM call."""
    user_prompt_lines = []
    if title:
        user_prompt_lines.append(f"Working title: {title}")
    if style:
        user_prompt_lines.append(f"Visual style: {style}")
    user_prompt_lines.append("---")
    user_prompt_lines.append(text)
    user_prompt = "\n".join(user_prompt_lines)

    response = llm_complete(
        user_prompt,
        system=_SCREENPLAY_SYSTEM_PROMPT,
        model=model,
        temperature=0.2,
    )
    parsed = _parse_json_loose(response)
    return _scene_from_llm_dict(
        parsed,
        default_title=title or parsed.get("title", "Untitled"),
        default_style=style or parsed.get("style", ""),
    )


def _parse_json_loose(s: str) -> dict:
    """Pull a JSON object out of a possibly-noisy LLM response."""
    # Strip code fences if present.
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s.strip(), flags=re.MULTILINE)
    # Extract the largest balanced {...} substring.
    match = re.search(r"\{.*\}", s, flags=re.DOTALL)
    if not match:
        raise ValueError(
            f"parse_screenplay: no JSON object in LLM response: {s[:200]!r}"
        )
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"parse_screenplay: JSON decode failed at {exc.pos}: {exc.msg}\n"
            f"---response head---\n{s[:400]}"
        ) from exc


def _scene_from_llm_dict(d: dict, *, default_title: str, default_style: str) -> Scene:
    from ..scene import Character, Environment

    chars = tuple(
        Character(name=c["name"], description=c.get("description", ""))
        for c in (d.get("characters") or [])
    )
    envs = tuple(
        Environment(
            name=e["name"],
            description=e.get("description", ""),
            time_of_day=e.get("time_of_day", ""),
        )
        for e in (d.get("environments") or [])
    )
    shots = tuple(
        make_shot(
            description=s.get("description", ""),
            framing=s.get("framing", "medium"),
            environment=s.get("environment", ""),
            characters=tuple(s.get("characters", [])),
            camera=s.get("camera", ""),
            index=i,
        )._replace_id_with(s.get("id"))
        if False  # placeholder; we set ids manually below
        else _shot_with_explicit_id(s, i)
        for i, s in enumerate(d.get("shots") or [])
    )
    beats = tuple(
        _beat_with_explicit_id(b, i) for i, b in enumerate(d.get("beats") or [])
    )
    return Scene(
        title=d.get("title", default_title),
        style=d.get("style", default_style),
        characters=chars,
        environments=envs,
        shots=shots,
        beats=beats,
        notes=d.get("notes", ""),
    )


def _shot_with_explicit_id(s: dict, idx: int):
    from ..scene import Shot

    sid = s.get("id") or shot_id(
        description=s.get("description", ""),
        framing=s.get("framing", ""),
        index=idx,
    )
    return Shot(
        id=sid,
        description=s.get("description", ""),
        framing=s.get("framing", "medium"),
        environment=s.get("environment", ""),
        characters=tuple(s.get("characters", [])),
        camera=s.get("camera", ""),
        notes=s.get("notes", ""),
    )


def _beat_with_explicit_id(b: dict, idx: int) -> Beat:
    bid = b.get("id") or beat_id(
        speaker=b.get("speaker", ""),
        line=b.get("line", ""),
        action=b.get("action", ""),
        index=idx,
    )
    return Beat(
        id=bid,
        speaker=b.get("speaker", ""),
        line=b.get("line", ""),
        action=b.get("action", ""),
        emotion=b.get("emotion", ""),
        shot_id=b.get("shot_id", ""),
        notes=b.get("notes", ""),
    )


# --- IR editing via natural-language note ---------------------------------


_DIRECT_BEAT_SYSTEM = """\
You are a script editor. The user gives you one Beat (JSON) and a directorial note.
Return the EDITED Beat as strict JSON --- same id, same shape, modified fields.
Adjust `line`, `action`, `emotion`, `notes` as needed.
Output ONLY the JSON object.
"""


@register_tool(
    name="apply_note_to_beat",
    description=(
        "Apply a directorial note to a single Beat using an LLM. Returns "
        "an updated Beat (same id; modified content fields). Use this to "
        "implement 'he cracks on this line; she softens but hides it' "
        "without manually rewriting the structure."
    ),
    tags=("direction", "scene", "llm"),
    input_schema={
        "type": "object",
        "required": ["beat", "note"],
        "properties": {
            "beat": {"type": "object", "description": "falaw.Beat"},
            "note": {
                "type": "string",
                "description": "Plain-English directorial instruction.",
            },
            "model": {"type": "string", "default": _DEFAULT_MODEL},
        },
    },
    output_schema={"type": "object", "description": "falaw.Beat"},
    examples=(
        {
            "beat": {
                "id": "001-john-abcd",
                "speaker": "John",
                "line": "It's fine.",
                "emotion": "",
            },
            "note": "He cracks on this line --- voice goes up.",
        },
    ),
)
def apply_note_to_beat(
    beat: Beat,
    note: str,
    *,
    model: str = _DEFAULT_MODEL,
) -> Beat:
    """Use the LLM to apply a directorial note to a Beat."""
    payload = {
        "id": beat.id,
        "speaker": beat.speaker,
        "line": beat.line,
        "action": beat.action,
        "emotion": beat.emotion,
        "notes": beat.notes,
        "shot_id": beat.shot_id,
    }
    user_prompt = (
        f"BEAT (JSON):\n{json.dumps(payload, indent=2)}\n\n"
        f"NOTE: {note}\n\n"
        f"Return the edited beat as strict JSON."
    )
    response = llm_complete(
        user_prompt,
        system=_DIRECT_BEAT_SYSTEM,
        model=model,
        temperature=0.2,
    )
    parsed = _parse_json_loose(response)
    return Beat(
        id=parsed.get("id", beat.id),
        speaker=parsed.get("speaker", beat.speaker),
        line=parsed.get("line", beat.line),
        action=parsed.get("action", beat.action),
        emotion=parsed.get("emotion", beat.emotion),
        shot_id=parsed.get("shot_id", beat.shot_id),
        notes=parsed.get("notes", beat.notes),
        duration_s=beat.duration_s,
    )


@register_tool(
    name="apply_note_to_scene",
    description=(
        "Apply a directorial note to the whole Scene by asking the LLM "
        "for a JSON patch (which beats/shots to edit, with new content). "
        "Returns a new Scene. Use for cross-cutting notes like 'tighten "
        "the pacing in the middle' or 'add a reaction shot after beat 5'."
    ),
    tags=("direction", "scene", "llm"),
    input_schema={
        "type": "object",
        "required": ["scene", "note"],
        "properties": {
            "scene": {"type": "object", "description": "falaw.Scene"},
            "note": {"type": "string"},
            "model": {"type": "string", "default": _DEFAULT_MODEL},
        },
    },
    output_schema={"type": "object", "description": "falaw.Scene"},
    examples=(),
)
def apply_note_to_scene(
    scene: Scene,
    note: str,
    *,
    model: str = _DEFAULT_MODEL,
) -> Scene:
    """Apply a cross-cutting note: LLM proposes per-beat edits, we apply them."""
    from ..scene import scene_to_dict

    user_prompt = (
        f"SCENE (JSON):\n{json.dumps(scene_to_dict(scene), indent=2, default=str)}\n\n"
        f"NOTE: {note}\n\n"
        "Return the edited Scene as strict JSON. Preserve ids where the "
        "content is unchanged so the renderer can cache. Output ONLY the JSON object."
    )
    response = llm_complete(
        user_prompt,
        system="You are a script editor. Edit the Scene IR per the note.",
        model=model,
        temperature=0.2,
    )
    parsed = _parse_json_loose(response)
    return _scene_from_llm_dict(
        parsed, default_title=scene.title, default_style=scene.style
    )
