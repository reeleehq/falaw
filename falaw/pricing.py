"""Read fal's pricing API into ``models.json`` cost estimates (falaw#18).

19 of the catalogue's 40 models carry no structured ``cost_estimate``, so
``Plan.has_unknown_costs`` — correctly — forces approval on nearly every
plan. fal publishes the real numbers (``GET /v1/models/pricing``), and this
module turns them into catalogue entries with ``source="api"``:

>>> from falaw import refresh_model_prices
>>> summary = refresh_model_prices()          # dry-run: reports, writes nothing
>>> summary = refresh_model_prices(write=True)   # persists to models.json  # doctest: +SKIP

Design rules, in order of importance:

- **This is a refresh job, not a runtime lookup.** ``plan_*`` never touches
  the network; plans price themselves from the committed catalogue.
- **An unmapped billing unit is recorded, never guessed.** fal's ``unit`` is
  a free string ("image", "megapixel", GPU/compute units, …); only units with
  an unambiguous :data:`~falaw.base.CostKind` mapping become estimates. A
  GPU-second is machine time, not output time — mapping it to ``per_second``
  would misprice by the model's realtime factor, so it stays unpriced and
  visible in the summary instead.
- **The API wins, loudly.** A hand-written price the API disagrees with is
  overwritten, and the delta is reported — stale pricing data is the normal
  case, not the exception.
"""

from __future__ import annotations

import datetime
import json
import re
from typing import Callable, Optional

from .base import CostEstimate
from .registry import _load_models, _models_path, register_tool


PRICING_URL = "https://api.fal.ai/v1/models/pricing"
"""fal's unit-pricing endpoint. Accepts 1-50 ``endpoint_id`` values per call."""

MAX_IDS_PER_REQUEST = 50
"""The endpoint's documented per-request cap on ``endpoint_id`` values."""

_UNIT_TO_COST_KIND: dict[str, str] = {
    "image": "per_image",
    "megapixel": "per_megapixel",
    "second": "per_second",
    "video_second": "per_second",
    "audio_second": "per_second",
    "token": "per_token",
    "call": "per_call",
    "request": "per_call",
}
"""fal billing units with an unambiguous :data:`~falaw.base.CostKind`.

Keyed in the singular; :func:`_cost_rule_for_unit` also accepts the plural
forms the live API actually returns ("megapixels", "seconds") and a few
unambiguous *scaled* units ("minutes", "10 seconds", "1m tokens"). Anything
else — "compute seconds" (GPU time, not output time), "units",
"generations", "video segments", "steps", "1000 characters" — is
deliberately unmapped — see the module docstring for why guessing would be
worse than staying unpriced.
"""

_SCALED_UNITS: dict[str, tuple[str, float]] = {
    # unit -> (CostKind, multiplier turning price-per-unit into price-per-kind)
    "minute": ("per_second", 1 / 60),
    # NOT "1m tokens": video models bill by *video tokens* (a function of
    # resolution x duration falaw cannot compute), so a per_token estimate
    # would make exactly those calls unpriceable at plan time — worse than
    # keeping a hand-written per_second approximation. Recorded instead.
}


def _cost_rule_for_unit(unit: str) -> "Optional[tuple[str, float]]":
    """``(CostKind, price multiplier)`` for a fal billing unit, or ``None``.

    The multiplier converts the API's price-per-``unit`` into the kind's
    price-per-unit: $6/minute is $0.10/second, "$0.32 per 10 seconds" is
    $0.032/second, "$2 per 1m tokens" is $0.000002/token.
    """
    singular = unit[:-1] if unit.endswith("s") else unit
    kind = _UNIT_TO_COST_KIND.get(unit) or _UNIT_TO_COST_KIND.get(singular)
    if kind is not None:
        return kind, 1.0
    scaled = _SCALED_UNITS.get(unit) or _SCALED_UNITS.get(singular)
    if scaled is not None:
        return scaled
    n_seconds = re.fullmatch(r"(\d+) seconds?", unit)
    if n_seconds is not None:
        return "per_second", 1 / int(n_seconds.group(1))
    return None


def _row_problem(row: dict) -> Optional[str]:
    """Why an API price row cannot be stamped, or ``None`` when it can.

    The catalogue is what every plan prices itself from, so a bad row is
    refused here — loudly, in the summary — rather than discovered later as
    a plan-time refusal (negative/NaN), an unmetered known-free call (zero),
    or a mis-summed currency.
    """
    raw = row.get("unit_price")
    if raw is None:
        return "row has no unit_price"
    try:
        amount = float(raw)
    except (TypeError, ValueError):
        return f"unit_price {raw!r} is not a number"
    if not (amount > 0):  # also catches NaN
        return f"unit_price {raw!r} is not a positive number"
    currency = str(row.get("currency", "USD"))
    if currency != "USD":
        return f"currency {currency!r} is not USD (estimator sums USD only)"
    return None


def _stamp_notes(stamp: str, *, converted: str, old: Optional[dict]) -> str:
    """The refreshed estimate's ``notes``, preserving a human's prior note.

    Hand-written notes can carry operational warnings; replacing them with a
    fetch stamp would erase them invisibly. A previous *API* stamp is just
    an older version of this line and is not chained.
    """
    base = f"fal pricing API, fetched {stamp}{converted}"
    old_notes = (old or {}).get("notes", "")
    if old_notes and (old or {}).get("source") != "api":
        return f"{base}; was: {old_notes}"
    return base


# Injectable HTTP seam: callable(url, params: list[tuple[str, str]],
# headers: dict) -> parsed JSON body, or None for HTTP 404. Params are
# (key, value) pairs because the live endpoint accepts the repeated-key
# array syntax (?endpoint_id=a&endpoint_id=b) but 404s on the comma-joined
# form its docs also advertise. 404 is load-bearing: ONE unknown id fails
# the WHOLE batch with {"error": {"type": "not_found"}}, so the fetcher
# needs to see it (and bisect) rather than crash. Tests stub this;
# production uses httpx.
HttpGetJson = Callable[[str, "list[tuple[str, str]]", dict], Optional[dict]]


MAX_429_RETRIES = 5
"""Attempts per request before giving up on a rate-limited endpoint.

The bisection around unknown ids multiplies request count, and the live
endpoint rate-limits aggressively — a refresh job should wait its turn,
not die halfway with a partial price table."""


def _default_http_get(
    url: str, params: "list[tuple[str, str]]", headers: dict
) -> Optional[dict]:
    import time

    from .errors import import_httpx

    httpx = import_httpx("refreshing fal.ai prices")

    with httpx.Client(timeout=15.0) as client:
        for attempt in range(MAX_429_RETRIES):
            response = client.get(url, params=params, headers=headers)
            if response.status_code == 404:
                return None
            if response.status_code == 429 and attempt < MAX_429_RETRIES - 1:
                retry_after = response.headers.get("Retry-After")
                delay = (
                    float(retry_after)
                    if retry_after and retry_after.replace(".", "", 1).isdigit()
                    else 2.0 * (attempt + 1)
                )
                time.sleep(delay)
                continue
            response.raise_for_status()
            return response.json()
    raise AssertionError("unreachable")  # pragma: no cover


def _resolve_api_key(api_key: Optional[str]) -> str:
    from ocracy.kit import resolve_credential

    from .core import FAL_KEY_ENVVARS, FAL_PROVIDER

    return resolve_credential(
        FAL_PROVIDER,
        api_key=api_key,
        env_var=FAL_KEY_ENVVARS,
        error=RuntimeError,
        hint="Pass api_key=, or set FAL_KEY. The pricing endpoint is free but "
        "authenticated.",
    )


def fetch_model_prices(
    endpoint_ids: "list[str]",
    *,
    api_key: Optional[str] = None,
    http_get: Optional[HttpGetJson] = None,
    batch_size: int = MAX_IDS_PER_REQUEST,
) -> dict[str, dict]:
    """``{endpoint_id: {"unit_price", "unit", "currency"}}`` from fal's API.

    Batches requests at ``batch_size`` ids (the endpoint caps at
    :data:`MAX_IDS_PER_REQUEST`). Ids the API does not know are simply
    absent from the result — the caller decides what absence means. That
    takes work: the live endpoint answers a batch containing even one
    unknown id with a blanket 404, so a failed batch is bisected down to
    the ids that actually price (O(unknown x log batch) extra requests).
    """
    get = http_get or _default_http_get
    headers = {"Authorization": f"Key {_resolve_api_key(api_key)}"}
    prices: dict[str, dict] = {}
    for start in range(0, len(endpoint_ids), batch_size):
        _fetch_batch(endpoint_ids[start : start + batch_size], get, headers, prices)
    return prices


def _fetch_batch(
    batch: "list[str]", get: HttpGetJson, headers: dict, prices: dict
) -> None:
    """Collect one batch's prices into ``prices``, bisecting around 404s."""
    if not batch:
        return
    params = [("endpoint_id", endpoint) for endpoint in batch]
    while True:
        body = get(PRICING_URL, params, headers)
        if body is None:  # some id in the batch is unknown to the API
            if len(batch) == 1:
                return  # this one: absent from the result, caller reports it
            middle = len(batch) // 2
            _fetch_batch(batch[:middle], get, headers, prices)
            _fetch_batch(batch[middle:], get, headers, prices)
            return
        for row in body.get("prices", ()):
            endpoint = row.get("endpoint_id")
            if endpoint:
                prices[endpoint] = row
        cursor = body.get("next_cursor")
        if not body.get("has_more") or cursor is None:
            return
        previous = [value for key, value in params if key == "cursor"]
        if previous and previous[0] == str(cursor):
            # A server repeating the same cursor with has_more=True would
            # spin this loop forever; trust the data, not the vendor.
            return
        params = [("endpoint_id", endpoint) for endpoint in batch] + [
            ("cursor", str(cursor))
        ]


def refresh_model_prices(
    *,
    write: bool = False,
    api_key: Optional[str] = None,
    http_get: Optional[HttpGetJson] = None,
    models_path: Optional[str] = None,
    today: Optional[str] = None,
) -> dict:
    """Refresh ``models.json`` cost estimates from fal's pricing API.

    Returns a summary dict; ``write=False`` (default) reports what would
    change without touching the file. ``models_path`` and ``today`` exist
    for tests (the fetch date lands in each estimate's ``notes``).
    """
    path = models_path or _models_path()
    with open(path, encoding="utf-8") as f:
        records = json.load(f)

    prices = fetch_model_prices(
        [r["id"] for r in records], api_key=api_key, http_get=http_get
    )
    stamp = today or datetime.date.today().isoformat()

    newly_priced: list[str] = []
    overwritten: list[dict] = []
    restamped: list[str] = []
    rejected_rows: dict[str, str] = {}
    unmapped: dict[str, str] = {}
    missing_from_api: list[str] = []
    stamped_ids: set = set()

    for record in records:
        row = prices.get(record["id"])
        if row is None:
            missing_from_api.append(record["id"])
            continue
        unit = str(row.get("unit", ""))
        rule = _cost_rule_for_unit(unit)
        if rule is None:
            # Recorded, never guessed; any existing estimate is kept.
            unmapped[record["id"]] = unit
            continue
        problem = _row_problem(row)
        if problem is not None:
            # A bogus row must not poison the catalogue: a negative or NaN
            # price makes every later CallPlan for the model refuse at plan
            # time, a zero plans as known-free and sails through spend
            # gates, and a non-USD amount would be summed as USD downstream.
            rejected_rows[record["id"]] = problem
            continue
        kind, multiplier = rule
        converted = "" if multiplier == 1.0 else f", converted from unit {unit!r}"
        old = record.get("cost_estimate")
        new_estimate = {
            "kind": kind,
            "amount": float(row["unit_price"]) * multiplier,
            "currency": str(row.get("currency", "USD")),
            "notes": _stamp_notes(stamp, converted=converted, old=old),
            "source": "api",
        }
        if old is not None and old.get("source") == "empirical":
            # A measured real bill outranks the rate card (which may cover
            # a different resolution/config tier). The issue's rule: API
            # outranks *approximate*, not empirical. A disagreement is
            # still a signal worth surfacing; agreement changes nothing.
            if (old.get("kind"), old.get("amount")) != (kind, new_estimate["amount"]):
                overwritten.append(
                    {
                        "id": record["id"],
                        "old": {k: old.get(k) for k in ("kind", "amount", "source")},
                        "new": {"kind": kind, "amount": new_estimate["amount"]},
                        "kept": "empirical",
                    }
                )
            continue
        if old is None:
            newly_priced.append(record["id"])
        elif (old.get("kind"), old.get("amount")) != (kind, new_estimate["amount"]):
            overwritten.append(
                {
                    "id": record["id"],
                    "old": {k: old.get(k) for k in ("kind", "amount", "source")},
                    "new": {"kind": kind, "amount": new_estimate["amount"]},
                }
            )
        else:
            # Same numbers, but source/notes/date still change on disk — a
            # real write that must show in the dry-run, not slip through
            # invisibly.
            restamped.append(record["id"])
        record["cost_estimate"] = new_estimate
        stamped_ids.add(record["id"])

    # Every estimate this refresh stamped must load as a CostEstimate
    # before anything is written.
    for record in records:
        if record["id"] in stamped_ids:
            CostEstimate(**record["cost_estimate"])

    summary = {
        "total": len(records),
        "priced_by_api": len(prices),
        "newly_priced": sorted(newly_priced),
        "price_deltas": overwritten,
        "restamped": sorted(restamped),
        "rejected_rows": rejected_rows,
        "unmapped_units": unmapped,
        "missing_from_api": sorted(missing_from_api),
        "write": write,
    }

    if write:
        merged = sorted(
            records,
            key=lambda r: (r.get("category", ""), r.get("quality_tier", ""), r["id"]),
        )
        with open(path, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
            f.write("\n")
        _load_models.cache_clear()
        from .journal import _default_journal

        _default_journal().append(
            kind="note",
            text=(
                f"refresh_model_prices: {len(newly_priced)} newly priced, "
                f"{len(overwritten)} overwritten, {len(restamped)} restamped, "
                f"{len(rejected_rows)} rejected rows, "
                f"{len(unmapped)} unmapped units"
            ),
            tags=("refresh", "cost"),
            context={
                "newly_priced": sorted(newly_priced)[:10],
                "price_deltas": overwritten[:10],
                "unmapped_units": unmapped,
            },
        )

    return summary


@register_tool(
    name="refresh_model_prices",
    description=(
        "Fetch fal's unit pricing for every model in `falaw/data/models.json` "
        "and write structured cost_estimates with source='api'. Hand-written "
        "prices the API disagrees with are overwritten and the delta reported. "
        "Units with no CostKind mapping (GPU/compute units) are recorded, not "
        "guessed. Reads the vendor's free pricing endpoint; makes no billed "
        "call. Pass `write=True` to persist; default is a dry-run summary."
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
def _refresh_model_prices_tool(*, write: bool = False) -> dict:
    """Bridge-facing wrapper for :func:`refresh_model_prices`.

    Separate because bridges derive a JSON schema from the function
    signature, and the real function's dependency-injection seams
    (``http_get``, ``models_path``, ``today``) are not JSON-schema
    representable — nor anything a tool caller should reach.
    """
    return refresh_model_prices(write=write)
