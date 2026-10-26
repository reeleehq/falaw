"""The terms ledger: may this ``(model, backend)`` be used for *this* job? (falaw#16)

falaw is the only layer that knows which vendor model a job will actually
call, so it is the layer that can know whether that call is permitted.
Copyleft is the famous perimeter; vendor terms of service are the one that
binds a commercial product. This module owns a per-``(model, backend)`` ledger
(``falaw/data/model_terms.json``) and the plan-time check over it.

The key is ``(model, backend)``, not ``model``: the backend decides whether an
upstream weights licence flows through to us. Through a hosted API the host
holds the weights licence (``license_binds_us="no"``); the same weights
self-hosted bind us directly (``"yes"``). Same model id, different position.

**Fail closed.** ``unknown`` is a refusal, not a warning — the discipline
:attr:`falaw.Plan.has_unknown_costs` applies to money, applied to licences. A
``(model, backend)`` with no row at all is ``unknown`` too, so a model nobody
has reviewed is refused rather than waved through. The check is opt-in per
call: ``plan_*(..., terms_context=TermsContext(...))``. With no context
(the default, for local/internal use) nothing is checked.

This is an implementation of what the terms *say*, not legal advice; it
refuses when unsure and does not adjudicate. The *context* (is this job
serving a third party? will its output be C2PA-stamped?) is the caller's, never
read from a global; the ledger is data, the check is falaw's.

>>> ctx = TermsContext(third_party=True)
>>> check_terms("fal-ai/flux/schnell", "comfyui", ctx)   # Apache-2.0, ours to serve
>>> check_terms("fal-ai/flux/dev", "comfyui", ctx)
Traceback (most recent call last):
    ...
falaw.errors.FalTermsViolation: ...
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, fields
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .errors import FalTermsViolation

TERMS_PATH = Path(__file__).parent / "data" / "model_terms.json"
"""The ledger — separate from ``models.json`` so it refreshes on its own
cadence and is reviewed as a legal artifact."""

TRI_STATE = frozenset({"yes", "no", "unknown"})
PERMISSION = frozenset({"allowed", "forbidden", "unknown"})


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelTerms:
    """One ledger row. A field left ``unknown`` is a refusal when it matters."""

    model_id: str
    backend: str
    license: str = "unknown"  # SPDX id where one exists, else the bespoke name
    license_binds_us: str = "unknown"  # "yes" | "no" (the host holds it) | "unknown"
    commercial_use: str = "unknown"  # "allowed" | "forbidden" | "unknown"
    third_party_tenancy: str = "unknown"  # may we run this for someone who is not us
    c2pa_compatible: str = "unknown"  # may output carry a C2PA AI-generated claim
    provenance_constraint: str = ""  # free text, e.g. a "human generated" clause
    notes: str = ""
    source_url: str = ""
    observed_on: str = ""  # ISO date: makes a stale row visible as stale

    def __post_init__(self):
        for name, allowed in (
            ("license_binds_us", TRI_STATE),
            ("c2pa_compatible", TRI_STATE),
            ("commercial_use", PERMISSION),
            ("third_party_tenancy", PERMISSION),
        ):
            if getattr(self, name) not in allowed:
                raise ValueError(
                    f"{self.model_id}@{self.backend}: {name}="
                    f"{getattr(self, name)!r}; expected one of {sorted(allowed)}"
                )


@dataclass(frozen=True, slots=True, kw_only=True)
class TermsContext:
    """What the job needs from the terms — supplied by the caller, never global.

    The defaults describe the strictest ordinary use (commercial) without
    claiming anything extra; ``third_party`` and ``c2pa`` are opt-in because
    they are the facts only the deployment knows.
    """

    commercial: bool = True
    third_party: bool = False  # the job serves someone who is not us
    c2pa: bool = False  # output will be stamped trainedAlgorithmicMedia


@lru_cache(maxsize=4)
def _load(path: str) -> Mapping[tuple[str, str], ModelTerms]:
    known = {f.name for f in fields(ModelTerms)}
    rows = {}
    for raw in json.loads(Path(path).read_text(encoding="utf-8")):
        extra = set(raw) - known
        if extra:
            raise ValueError(f"model_terms row has unknown keys {sorted(extra)}: {raw}")
        row = ModelTerms(**raw)
        key = (row.model_id, row.backend)
        if key in rows:
            raise ValueError(f"model_terms has a duplicate row for {key}")
        rows[key] = row
    return rows


def load_terms(
    path: Optional[str | Path] = None,
) -> Mapping[tuple[str, str], ModelTerms]:
    """The ledger as ``{(model_id, backend): ModelTerms}`` (cached per path)."""
    return _load(str(path or TERMS_PATH))


def get_terms(
    model_id: str, backend: str, *, ledger: Optional[Mapping] = None
) -> Optional[ModelTerms]:
    """The row for ``(model_id, backend)``, or ``None`` when nobody reviewed it."""
    return (load_terms() if ledger is None else ledger).get((model_id, backend))


def _refusal(row: Optional[ModelTerms], context: TermsContext) -> Optional[str]:
    """The first clause that makes this row unusable for *context*, else None."""
    if row is None:
        return "no terms row: nobody has reviewed this model on this backend"
    if row.license_binds_us == "unknown":
        return "license_binds_us is unknown (hosted vs. self-hosted position)"
    if context.commercial:
        if row.commercial_use == "forbidden":
            return f"commercial use is forbidden ({row.license})"
        if row.commercial_use == "unknown":
            return "commercial_use is unknown"
    if context.third_party:
        if row.third_party_tenancy == "forbidden":
            return f"third-party tenancy is forbidden ({row.license})"
        if row.third_party_tenancy == "unknown":
            return "third_party_tenancy is unknown"
    if context.c2pa:
        if row.c2pa_compatible == "no":
            return f"incompatible with C2PA provenance: {row.provenance_constraint}"
        if row.c2pa_compatible == "unknown":
            return "c2pa_compatible is unknown"
    return None


def check_terms(
    model_id: str,
    backend: str,
    context: Optional[TermsContext],
    *,
    ledger: Optional[Mapping] = None,
) -> None:
    """Raise :class:`FalTermsViolation` unless ``(model_id, backend)`` is
    usable for *context*. ``context=None`` (the default everywhere) checks
    nothing: the strict path is opt-in per deployment.
    """
    if context is None:
        return
    row = get_terms(model_id, backend, ledger=ledger)
    clause = _refusal(row, context)
    if clause is None:
        return
    source = f" (see {row.source_url})" if row and row.source_url else ""
    raise FalTermsViolation(
        f"{model_id!r} on backend {backend!r} refused: {clause}{source}",
        model_id=model_id,
        backend=backend,
        clause=clause,
        source_url=row.source_url if row else "",
    )


def third_party_tenancy_ok(
    model_id: str, backend: str, *, ledger: Optional[Mapping] = None
) -> bool:
    """The routing-visible projection: may a router send third-party work to
    ``(model_id, backend)`` without consulting the full ledger? ``False`` when
    unsure — the cheap 80%, so a router can drop an incompatible backend."""
    row = get_terms(model_id, backend, ledger=ledger)
    return _refusal(row, TermsContext(commercial=False, third_party=True)) is None


def unreviewed_models(
    *, ledger: Optional[Mapping] = None, backend: str = "fal"
) -> list[str]:
    """Catalogue models with no ledger row on *backend* — what still needs a
    human read of the terms (each is refused under a strict context)."""
    from .registry import list_models

    ledger = load_terms() if ledger is None else ledger
    return sorted(m.id for m in list_models() if (m.id, backend) not in ledger)


__all__ = [
    "ModelTerms",
    "TermsContext",
    "TERMS_PATH",
    "check_terms",
    "get_terms",
    "load_terms",
    "third_party_tenancy_ok",
    "unreviewed_models",
]
