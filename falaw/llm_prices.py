"""One first-party LLM price table: what a direct Anthropic / OpenAI call costs (falaw#81).

:mod:`falaw.llm_rates` prices LLMs *routed through fal* (``fal-ai/any-llm``).
This module prices calls made straight to the model vendor, the way reelee's
agent loop and chat relay and foley's rungs make them. Those three used to keep
a private copy of the same numbers and drifted; this is the one home.

>>> llm_call_cost_usd("anthropic", "claude-opus-4-7",
...                   {"input_tokens": 1_000_000, "output_tokens": 0})
(5.0, True)

The answer is ``(usd, known)``. A model the table does not list is **unknown,
not free**: it is priced at the dearest rates listed for that provider and
``known`` is ``False``. The cost is then a *floor on a guess*, not a ceiling: an
unlisted model can cost more than the dearest listed one (an older, pricier
model). A spend cap can count it; a caller that must never under-count should
refuse an unpriced model by testing ``known``:

>>> usd, known = llm_call_cost_usd("anthropic", "claude-from-the-future",
...                                {"input_tokens": 1_000_000})
>>> known, usd > 0
(False, True)

``usage`` is the vendor's own reported usage, a mapping or an object with
attributes, in either of OpenAI's two shapes (Responses or Chat Completions):

>>> llm_call_cost_usd("openai", "gpt-5", {"prompt_tokens": 1000,
...     "completion_tokens": 100, "prompt_tokens_details": {"cached_tokens": 1000}})
(0.001125, True)

The table is data, not code: :data:`PRICES_FILENAME` under ``falaw/data``, one
row per model, each row carrying its own ``source`` and ``date``. Nothing here
touches the network. Model ids are matched **exactly**: a dated snapshot is not
priced as its family, because older snapshots can cost more.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType
from typing import Any, Mapping, Optional

from .base import data_table_version

PRICES_FILENAME = "first_party_llm_prices.json"
"""Basename of the price table under ``falaw/data``."""

TOKENS_PER_PRICE_UNIT = 1_000_000
"""Token count the table's ``*_usd_per_mtok`` columns are quoted per."""

COST_DECIMALS = 9
"""Digits the returned USD is rounded to, which only removes float noise."""

PROVIDERS = ("anthropic", "openai")
"""First-party providers the table prices."""


@dataclass(frozen=True, slots=True, kw_only=True)
class LlmPriceRates:
    """USD per million tokens for one prompt-length regime of one model."""

    input_usd_per_mtok: float
    output_usd_per_mtok: float
    cache_read_usd_per_mtok: Optional[float] = None
    cache_write_usd_per_mtok: Optional[float] = None
    cache_write_1h_usd_per_mtok: Optional[float] = None


@dataclass(frozen=True, slots=True, kw_only=True)
class LlmPrice:
    """One row of the first-party table: a model's rates and where they came from."""

    provider: str
    model: str
    rates: LlmPriceRates
    long_prompt_over_tokens: Optional[int] = None
    long_prompt_rates: Optional[LlmPriceRates] = None
    source: str = ""
    date: str = ""
    notes: str = ""


LlmPriceTable = Mapping[tuple[str, str], LlmPrice]


def _prices_path() -> str:
    return os.path.join(os.path.dirname(__file__), "data", PRICES_FILENAME)


def _rates(row: Mapping[str, Any]) -> LlmPriceRates:
    def opt(key: str) -> Optional[float]:
        return None if row.get(key) is None else float(row[key])

    return LlmPriceRates(
        input_usd_per_mtok=float(row["input_usd_per_mtok"]),
        output_usd_per_mtok=float(row["output_usd_per_mtok"]),
        cache_read_usd_per_mtok=opt("cache_read_usd_per_mtok"),
        cache_write_usd_per_mtok=opt("cache_write_usd_per_mtok"),
        cache_write_1h_usd_per_mtok=opt("cache_write_1h_usd_per_mtok"),
    )


def parse_long_prompt(
    row: Mapping[str, Any],
) -> tuple[Optional[int], Optional[LlmPriceRates]]:
    """``(over_input_tokens, rates)`` from a row's ``long_prompt`` block, or ``(None, None)``.

    The one reading of the block both falaw rate tables share: the rates replace the
    row's own once a prompt exceeds ``over_input_tokens``.
    """
    long_prompt = row.get("long_prompt")
    if not long_prompt:
        return None, None
    return int(long_prompt["over_input_tokens"]), _rates(long_prompt)


@lru_cache(maxsize=1)
def load_llm_prices() -> LlmPriceTable:
    """The committed table, keyed by ``(provider, model)``. Read once per process."""
    with open(_prices_path(), encoding="utf-8") as f:
        table = json.load(f)
    out: dict[tuple[str, str], LlmPrice] = {}
    for row in table["rows"]:
        over_tokens, long_rates = parse_long_prompt(row)
        out[(row["provider"], row["model"])] = LlmPrice(
            provider=row["provider"],
            model=row["model"],
            rates=_rates(row),
            long_prompt_over_tokens=over_tokens,
            long_prompt_rates=long_rates,
            source=row.get("source", ""),
            date=row.get("date", ""),
            notes=row.get("notes", ""),
        )
    return MappingProxyType(out)


@lru_cache(maxsize=1)
def llm_prices_table_version() -> str:
    """The table's version, a digest of its bytes (see :func:`falaw.base.data_table_version`)."""
    return data_table_version(_prices_path())


def list_llm_prices(
    provider: Optional[str] = None, *, prices: Optional[LlmPriceTable] = None
) -> list[LlmPrice]:
    """Every row, or the rows of one ``provider``."""
    table = load_llm_prices() if prices is None else prices
    return [p for p in table.values() if provider is None or p.provider == provider]


def get_llm_price(
    provider: str, model: str, *, prices: Optional[LlmPriceTable] = None
) -> Optional[LlmPrice]:
    """The row for ``model`` (exact id), or ``None`` when the table does not list it."""
    table = load_llm_prices() if prices is None else prices
    return table.get((provider, str(model or "").strip()))


def llm_call_cost_usd(
    provider: str,
    model: str,
    usage: Any,
    *,
    prices: Optional[LlmPriceTable] = None,
) -> tuple[float, bool]:
    """``(USD, known)`` for one first-party call from the vendor's reported ``usage``.

    - ``provider="anthropic"``: ``input_tokens`` (uncached), ``output_tokens``,
      ``cache_read_input_tokens``, ``cache_creation_input_tokens``.
    - ``provider="openai"``: Responses (``input_tokens`` / ``output_tokens`` /
      ``input_tokens_details.cached_tokens``) or Chat Completions
      (``prompt_tokens`` / ``completion_tokens`` /
      ``prompt_tokens_details.cached_tokens``). Input includes the cached part,
      which is billed at the cached rate; reasoning tokens are already in output.

    ``known`` is ``False`` when the model is not in the table; the cost is then
    priced at the provider's dearest listed rates, which is not a ceiling for a
    model pricier than any listed (see the module docstring). ``prices=`` swaps in the caller's
    own table, e.g. one reconciled against an invoice.

    Raises:
        ValueError: ``provider`` is not one of :data:`PROVIDERS`.
    """
    _check_provider(provider)
    table = load_llm_prices() if prices is None else prices
    price = table.get((provider, str(model or "").strip()))
    known = price is not None
    rates = price.rates if price else _dearest_rates(provider, table)
    counts = llm_token_counts(provider, usage)
    if (
        price
        and price.long_prompt_rates
        and counts.input > price.long_prompt_over_tokens
    ):
        rates = price.long_prompt_rates
    usd = _usd(rates, counts)
    return round(usd, COST_DECIMALS), known


@dataclass(frozen=True, slots=True, kw_only=True)
class LlmTokenCounts:
    """The token counts a first-party call's ``usage`` reports, normalized across
    providers: the very counts :func:`llm_call_cost_usd` prices, so a caller that
    records them next to the cost cannot disagree with it (falaw#89).

    ``fresh_input`` is billed at the input rate, ``cache_read`` and
    ``cache_write`` at their own; ``cache_write_1h`` is the part of
    ``cache_write`` on the 1-hour tier (already included in it: do not add the two). ``reasoning`` is informational: it is
    already inside ``output``.
    """

    fresh_input: int = 0
    cache_read: int = 0
    cache_write: int = 0
    cache_write_1h: int = 0
    output: int = 0
    reasoning: int = 0

    @property
    def input(self) -> int:
        """Every prompt token, cached or not."""
        return self.fresh_input + self.cache_read + self.cache_write


def llm_token_counts(provider: str, usage: Any) -> LlmTokenCounts:
    """The :class:`LlmTokenCounts` of a vendor ``usage``, in the shapes
    :func:`llm_call_cost_usd` accepts (a mapping or an SDK object).

    >>> llm_token_counts("openai", {"prompt_tokens": 1000, "completion_tokens": 100,
    ...     "prompt_tokens_details": {"cached_tokens": 400}})
    LlmTokenCounts(fresh_input=600, cache_read=400, cache_write=0, cache_write_1h=0, output=100, reasoning=0)

    A key that is present but ``None`` falls through to the next shape's key
    (``{"input_tokens": None, "prompt_tokens": 7}`` counts 7).

    Raises:
        ValueError: ``provider`` is not one of :data:`PROVIDERS`.
    """
    _check_provider(provider)
    if provider == "anthropic":
        cache_write = _count(_get(usage, "cache_creation_input_tokens"))
        return LlmTokenCounts(
            fresh_input=_count(_get(usage, "input_tokens")),
            cache_read=_count(_get(usage, "cache_read_input_tokens")),
            cache_write=cache_write,
            cache_write_1h=min(
                cache_write,
                _count(
                    _get(_get(usage, "cache_creation"), "ephemeral_1h_input_tokens")
                ),
            ),
            output=_count(_get(usage, "output_tokens")),
        )
    total_in = _count(_first(usage, "input_tokens", "prompt_tokens"))
    cached = _count(
        _get(
            _first(usage, "input_tokens_details", "prompt_tokens_details"),
            "cached_tokens",
        )
    )
    details_out = _first(usage, "output_tokens_details", "completion_tokens_details")
    return LlmTokenCounts(
        fresh_input=max(0, total_in - cached),
        cache_read=cached,
        output=_count(_first(usage, "output_tokens", "completion_tokens")),
        reasoning=_count(_get(details_out, "reasoning_tokens")),
    )


def _usd(rates: LlmPriceRates, counts: LlmTokenCounts) -> float:
    cache_read_rate = _or(rates.cache_read_usd_per_mtok, rates.input_usd_per_mtok)
    cache_write_rate = _or(rates.cache_write_usd_per_mtok, rates.input_usd_per_mtok)
    cache_write_1h_rate = _or(rates.cache_write_1h_usd_per_mtok, cache_write_rate)
    return (
        rates.input_usd_per_mtok * counts.fresh_input
        + cache_read_rate * counts.cache_read
        + cache_write_rate * (counts.cache_write - counts.cache_write_1h)
        + cache_write_1h_rate * counts.cache_write_1h
        + rates.output_usd_per_mtok * counts.output
    ) / TOKENS_PER_PRICE_UNIT


def _check_provider(provider: str) -> None:
    if provider not in PROVIDERS:
        raise ValueError(
            f"No first-party price table for provider {provider!r}; "
            f"known providers: {', '.join(PROVIDERS)}."
        )


def _dearest_rates(provider: str, table: LlmPriceTable) -> LlmPriceRates:
    """Per-column maximum over a provider's rows: the upper bound for an unlisted model."""
    rows = [
        r
        for p in table.values()
        if p.provider == provider
        for r in (p.rates, p.long_prompt_rates)
        if r is not None
    ]
    if not rows:
        raise ValueError(f"The price table lists no {provider!r} models to bound with.")

    def top(attr: str) -> Optional[float]:
        values = [getattr(r, attr) for r in rows if getattr(r, attr) is not None]
        return max(values) if values else None

    return LlmPriceRates(
        input_usd_per_mtok=top("input_usd_per_mtok"),
        output_usd_per_mtok=top("output_usd_per_mtok"),
        cache_read_usd_per_mtok=top("cache_read_usd_per_mtok"),
        cache_write_usd_per_mtok=top("cache_write_usd_per_mtok"),
        cache_write_1h_usd_per_mtok=top("cache_write_1h_usd_per_mtok"),
    )


def _get(obj: Any, key: str) -> Any:
    """``obj[key]`` for a mapping, ``obj.key`` for an SDK object, else ``None``."""
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        return obj.get(key)
    return getattr(obj, key, None)


def _first(obj: Any, *keys: str) -> Any:
    for key in keys:
        value = _get(obj, key)
        if value is not None:
            return value
    return None


def _count(value: Any) -> int:
    """A token count: a positive whole number as an int, else 0.

    Accepts ints, numpy integers, floats and numeric strings (a proxy that
    round-trips usage through JSON or a DataFrame hands back all of these);
    bools, negatives and anything unparseable count as none.
    """
    if value is None or isinstance(value, bool):
        return 0
    try:
        count = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(count, 0)


def _or(value: Optional[float], fallback: float) -> float:
    return fallback if value is None else value
