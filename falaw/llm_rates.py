"""Per-routed-model LLM rates: the data behind a *ceiling* quote (falaw#50, option A).

``fal-ai/any-llm`` is one registry record that routes thirty different models,
so a single record-level ``cost_estimate`` cannot express what a call actually
costs. Until now every planned LLM call quoted that one record's flat
$0.001 — which under-quotes in the one direction a cost gate must never err.
Two facts, both read off the vendor's own documentation, say by how much:

1. **fal bills the router per request, at two tiers.** Its endpoint doc says
   "$0.001 per requests" and "Premium models are charged at 10x the rate of
   standard models", followed by the verbatim premium list. falaw's default
   model — ``anthropic/claude-sonnet-4.5`` — is on that list, so *every*
   planned LLM call has been quoting a tenth of the published price.
2. **The routed model has an upstream per-token rate.** any-llm is "powered by
   OpenRouter" and shares its model-id namespace, so OpenRouter's published
   prompt/completion rates are what fal resells. A reseller cannot durably
   charge less than its own cost, which makes those rates a floor on the true
   price of a long prompt on a big model.

Neither basis dominates the other: the flat request price wins on a short
prompt, the token rates win on a long one. So the ceiling is the **maximum
over every basis known for that model** (:func:`llm_ceiling_usd`) — the only
composition that cannot under-quote either way, and monotone non-decreasing in
both token hints.

The table itself is data, not code: :data:`RATES_FILENAME` under ``falaw/data``,
versioned, one row per routed model, each row carrying its own ``source`` and
``date``. Nothing here touches the network — planning stays free.

>>> rate = get_llm_rate('anthropic/claude-sonnet-4.5')
>>> rate.tier
'premium'
>>> rate.per_call_usd
0.01

A model the table does not know is **unknown, not free** — the estimator
returns ``None`` so the plan lights up ``has_unknown_costs`` and forces
approval, rather than falling back to the router's flat price:

>>> get_llm_rate('some/model-fal-never-heard-of') is None
True
>>> llm_ceiling_usd('some/model-fal-never-heard-of') is None
True
"""

from __future__ import annotations

import datetime
import json
import os
import warnings
from dataclasses import dataclass
from functools import lru_cache
from typing import Mapping, Optional

from .base import data_table_version

RATES_FILENAME = "llm_rates.json"
"""Basename of the rate table under ``falaw/data``."""

TOKENS_PER_RATE_UNIT = 1_000_000
"""Token count the table's ``*_per_mtok`` columns are quoted per."""

DEFAULT_STALENESS_THRESHOLD_DAYS = 90
"""Warn once a priced row's ``date`` is this many days old.

``llm_rates.json`` has no refresh job that runs itself (falaw#56): a
repriced or retiered model does not fail any test, so a quote can go stale
silently. This is the default threshold :func:`llm_ceiling_usd` checks a
row's ``date`` against before returning a quote."""


class LlmRatesStaleWarning(UserWarning):
    """A quote was served from a rate row older than the staleness threshold."""


def _is_stale(date: str, *, threshold_days: int, today: datetime.date) -> bool:
    """True when ``date`` (ISO, possibly blank/malformed) is too old to trust."""
    if not date:
        return True
    try:
        parsed = datetime.date.fromisoformat(date)
    except ValueError:
        return True
    return (today - parsed).days > threshold_days


def warn_if_stale(
    rate: "LlmRate",
    *,
    threshold_days: int = DEFAULT_STALENESS_THRESHOLD_DAYS,
    today: Optional[datetime.date] = None,
) -> Optional[str]:
    """Warn (never raise) when ``rate`` is older than ``threshold_days``.

    Safe to call at import time or on every quote: it only ever calls
    :func:`warnings.warn`, so a stale table degrades a quote's trustworthiness
    without ever breaking a caller. Returns the warning message when one was
    issued, else ``None`` (handy for tests, which can assert on it without
    a ``pytest.warns`` context).

    ``stacklevel=2`` attributes the warning to :func:`llm_ceiling_usd`'s call
    site here rather than to every external caller of *that* — a fixed
    location, not one that moves with the caller. That matters because
    Python's default warning filter only dedups a repeated warning by its
    exact ``(message, category, module, lineno)``: a fixed location plus a
    message keyed on ``(model, date)`` means a caller quoting the same stale
    row in a loop (including a blank/unknown ``date``, which always reads as
    stale) sees the warning once per process, not once per call.
    """
    today = today or datetime.date.today()
    if not _is_stale(rate.date, threshold_days=threshold_days, today=today):
        return None
    message = (
        f"llm_rates: {rate.model!r} is priced as of "
        f"{rate.date or 'an unknown date'}, more than {threshold_days} days "
        f"before {today.isoformat()} -- run `falaw refresh-llm-rates` "
        "(or `python -m falaw refresh-llm-rates`) to check for a repricing."
    )
    warnings.warn(message, LlmRatesStaleWarning, stacklevel=2)
    return message


@dataclass(frozen=True, slots=True, kw_only=True)
class LlmRate:
    """What one routed model costs, on every basis the table knows.

    Attributes:
        model: The ``model`` argument value this row prices, e.g.
            ``"anthropic/claude-sonnet-4.5"``.
        tier: fal's billing tier for the router — ``"standard"`` or
            ``"premium"``. Informational; ``per_call_usd`` is already
            materialized, so no multiplier arithmetic happens in code.
        per_call_usd: What fal bills per request when this model is routed.
        input_usd_per_mtok: Upstream list price per
            :data:`TOKENS_PER_RATE_UNIT` prompt tokens, or ``None`` when no
            upstream rate is published for this id — unknown, never zero.
        output_usd_per_mtok: The same for completion tokens.
        source: Where these numbers came from.
        date: ISO date they were read on. Rates move; a quote is only as
            fresh as its row.
        notes: Free-form caveats.
    """

    model: str
    tier: str
    per_call_usd: float
    input_usd_per_mtok: Optional[float] = None
    output_usd_per_mtok: Optional[float] = None
    source: str = ""
    date: str = ""
    notes: str = ""

    @property
    def has_token_rates(self) -> bool:
        """True when both token columns are populated, so a token quote is possible."""
        return (
            self.input_usd_per_mtok is not None and self.output_usd_per_mtok is not None
        )


LlmRateTable = Mapping[str, LlmRate]


def _rates_path() -> str:
    return os.path.join(os.path.dirname(__file__), "data", RATES_FILENAME)


@lru_cache(maxsize=1)
def load_llm_rates() -> LlmRateTable:
    """The committed rate table, keyed by routed-model id.

    Cached: the file is read once per process. Tests and callers with their
    own reconciled numbers pass a mapping to ``rates=`` instead of mutating
    this one.
    """
    with open(_rates_path(), encoding="utf-8") as f:
        table = json.load(f)
    return {
        row["model"]: LlmRate(
            model=row["model"],
            tier=row["tier"],
            per_call_usd=float(row["per_call_usd"]),
            input_usd_per_mtok=_optional_float(row.get("input_usd_per_mtok")),
            output_usd_per_mtok=_optional_float(row.get("output_usd_per_mtok")),
            source=row.get("source", ""),
            date=row.get("date", ""),
            notes=row.get("notes", ""),
        )
        for row in table["rows"]
    }


def _optional_float(value) -> Optional[float]:
    return None if value is None else float(value)


LLM_RATES_TABLE = f"falaw/data/{RATES_FILENAME}"
"""Identity a :class:`falaw.CostBasis` records for an LLM-priced call."""

CUSTOM_LLM_RATES_TABLE = "caller-supplied"
"""What a basis records when the caller quoted against their own ``rates=`` table.

It has no file to digest, so its ``table_version`` stays empty — and, more
importantly, **the committed table must never re-price it**. Two tables are two
sets of books: re-quoting a $0.50 row from a caller's reconciled invoice against
falaw's $0.01 published rate is a 50x *under-quote* wearing the clothes of a
price drop. :func:`falaw.reprice_plan` therefore refuses a basis whose ``table``
does not match the pricer's, reporting it as unknown; a caller who wants their
own numbers re-quoted passes a :class:`falaw.Pricer` that names this table."""


@lru_cache(maxsize=1)
def llm_rates_table_version() -> str:
    """The rate table's version — see :func:`falaw.base.data_table_version`.

    Cached per process, like the table itself.
    """
    return data_table_version(_rates_path())


def list_llm_rates(*, rates: Optional[LlmRateTable] = None) -> list[LlmRate]:
    """Every row in the table, in file order — the catalogue view."""
    return list((rates if rates is not None else load_llm_rates()).values())


def get_llm_rate(
    model: str, *, rates: Optional[LlmRateTable] = None
) -> Optional[LlmRate]:
    """The row for ``model``, or ``None`` when the table does not price it.

    ``None`` is the load-bearing answer: it means *unknown*, and every caller
    must propagate it as unknown rather than substituting the router's flat
    price for a model nobody has priced.
    """
    return (rates if rates is not None else load_llm_rates()).get(model)


def llm_ceiling_usd(
    model: str,
    *,
    input_tokens: Optional[int] = None,
    max_output_tokens: Optional[int] = None,
    count: int = 1,
    rates: Optional[LlmRateTable] = None,
) -> Optional[float]:
    """Ceiling cost in USD of ``count`` calls routing ``model``, or ``None``.

    Two modes, decided by whether the caller passes a token hint at all.

    **No hints** — quote fal's published per-request price for the routed
    model. That is a known vendor fact, and for the premium tier it is ten
    times what the router's flat record said:

    >>> flat = llm_ceiling_usd('anthropic/claude-sonnet-4.5')
    >>> flat
    0.01

    **Both hints** — quote the **maximum** of that request price and
    ``input_tokens`` in plus ``max_output_tokens`` out at the routed model's
    upstream rates. Taking the max is what makes it a ceiling: the flat price
    binds a short prompt, the token sum binds a long one, and quoting either
    alone under-quotes the other case.

    >>> long_prompt = llm_ceiling_usd(
    ...     'anthropic/claude-sonnet-4.5', input_tokens=20_000, max_output_tokens=4_000
    ... )
    >>> round(long_prompt, 4)
    0.12
    >>> long_prompt > flat        # length raises the quote; the flat rate is a floor
    True

    Monotone in both hints, so a bigger hint never quotes less:

    >>> a = llm_ceiling_usd('openai/gpt-4o', input_tokens=1_000, max_output_tokens=100)
    >>> b = llm_ceiling_usd('openai/gpt-4o', input_tokens=9_000, max_output_tokens=100)
    >>> b >= a
    True

    Both hints are upper bounds the *caller* holds at plan time: the prompt is
    already written, and ``max_tokens`` caps the response. Real output length
    is unknowable before the call, which is exactly why this quotes the cap and
    never a midpoint guess.

    A token quote is therefore **all or nothing**. Asking for one that cannot
    be bounded yields ``None`` — unknown, which forces approval — rather than a
    number that looks like a ceiling and is not. That covers one hint without
    the other (an uncapped response has no bound to quote):

    >>> llm_ceiling_usd('anthropic/claude-sonnet-4.5', input_tokens=50_000) is None
    True

    and a row with no published upstream token rates (the request price alone
    is not a ceiling on a token bill nobody has priced):

    >>> llm_ceiling_usd(
    ...     'google/gemini-flash-1.5', input_tokens=50_000, max_output_tokens=1_000
    ... ) is None
    True

    Args:
        model: The ``model`` argument the call will send to the router.
        input_tokens: Upper bound on prompt tokens. ``None`` together with
            ``max_output_tokens`` selects the per-request basis alone.
        max_output_tokens: The response cap (any-llm's ``max_tokens``).
        count: Number of identical calls.
        rates: Override table, for a caller who has reconciled real rates
            against their own billing.

    Raises:
        TypeError: a token hint or ``count`` that is not a plain ``int``.
            A ``bool`` and a ``float`` both do the arithmetic silently —
            ``True`` prices one token, ``1.5e4`` prices a fractional one —
            so a caller who passed the wrong thing would get a number rather
            than a complaint.
        ValueError: a negative token hint or ``count``, which would make the
            token basis *lower* the ceiling — silently, and in the one
            direction a spend gate must never err.
    """
    _require_count(
        input_tokens=input_tokens, max_output_tokens=max_output_tokens, count=count
    )

    rate = get_llm_rate(model, rates=rates)
    if rate is None:
        return None  # unpriceable model → unknown, NOT the router's flat price
    warn_if_stale(rate)

    if input_tokens is None and max_output_tokens is None:
        return rate.per_call_usd * count
    if input_tokens is None or max_output_tokens is None or not rate.has_token_rates:
        return None  # a token quote was asked for and cannot be bounded

    token_cost = (
        input_tokens * rate.input_usd_per_mtok
        + max_output_tokens * rate.output_usd_per_mtok
    ) / TOKENS_PER_RATE_UNIT
    return max(rate.per_call_usd, token_cost) * count


def _require_count(**quantities: Optional[int]) -> None:
    """Refuse anything but a non-negative ``int`` (or ``None``) for each quantity."""
    for name, value in quantities.items():
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an int; got {value!r}")
        if value < 0:
            raise ValueError(f"{name} must be non-negative; got {value!r}")
