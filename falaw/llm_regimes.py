"""Token-rate regimes: the one vocabulary both falaw LLM rate tables price in (falaw#128).

:mod:`falaw.llm_prices` (first-party calls) and :mod:`falaw.llm_rates` (calls routed
through fal's any-llm) both bill a model's tokens at a set of per-million rates, and
some models switch to a dearer set once a prompt passes a length threshold. This module
owns that shape (:class:`LlmPriceRates`), how a table row spells it (:func:`rates_from_row`,
:func:`parse_long_prompt`) and which set a prompt is billed at (:func:`rates_for_prompt`),
so neither table keeps its own copy.

>>> base = LlmPriceRates(input_usd_per_mtok=1.0, output_usd_per_mtok=2.0)
>>> long = LlmPriceRates(input_usd_per_mtok=3.0, output_usd_per_mtok=4.0)
>>> rates_for_prompt(base, 100, long_prompt_over_tokens=100, long_prompt_rates=long) is base
True
>>> rates_for_prompt(base, 101, long_prompt_over_tokens=100, long_prompt_rates=long) is long
True
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional


@dataclass(frozen=True, slots=True, kw_only=True)
class LlmPriceRates:
    """USD per million tokens for one prompt-length regime of one model."""

    input_usd_per_mtok: float
    output_usd_per_mtok: float
    cache_read_usd_per_mtok: Optional[float] = None
    cache_write_usd_per_mtok: Optional[float] = None
    cache_write_1h_usd_per_mtok: Optional[float] = None


def rates_from_row(row: Mapping[str, Any]) -> LlmPriceRates:
    """The ``*_usd_per_mtok`` columns of a table row (or a ``long_prompt`` block)."""

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

    The rates replace the row's own once a prompt exceeds ``over_input_tokens``.
    """
    long_prompt = row.get("long_prompt")
    if not long_prompt:
        return None, None
    return int(long_prompt["over_input_tokens"]), rates_from_row(long_prompt)


def rates_for_prompt(
    rates: LlmPriceRates,
    input_tokens: int,
    *,
    long_prompt_over_tokens: Optional[int],
    long_prompt_rates: Optional[LlmPriceRates],
) -> LlmPriceRates:
    """The rates a prompt of ``input_tokens`` is billed at: the long-prompt tier
    past its threshold, else ``rates``."""
    if long_prompt_rates is not None and input_tokens > long_prompt_over_tokens:
        return long_prompt_rates
    return rates
