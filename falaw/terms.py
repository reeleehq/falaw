"""The terms ledger: may this ``(model, backend)`` be used for *this* job? (falaw#16)

falaw is the only layer that knows which vendor model a job will actually
call, so it is the layer that can know whether that call is permitted.
Copyleft is the famous perimeter; vendor terms of service are the one that
binds a commercial product. This module owns a per-``(model, backend)`` ledger
(``falaw/data/model_terms.json``) and the plan-time check over it.

Rows are keyed on ``CallPlan.application`` — the *resolved* model id, never an
alias — and ``CallPlan.backend``. A self-hosted backend must therefore plan
its calls under the catalogue model id the ledger row names.

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
serving a third party? will its output be C2PA-stamped?) is the caller's (an argument, or
scoped to a block by :func:`using_terms_context`), never process-global; the ledger is data, the check is falaw's.

>>> ctx = TermsContext(third_party=True)
>>> check_terms("fal-ai/flux/schnell", "comfyui", ctx)   # Apache-2.0, ours to serve
>>> check_terms("fal-ai/flux/dev", "comfyui", ctx)
Traceback (most recent call last):
    ...
falaw.errors.FalTermsViolation: ...
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, fields
from functools import lru_cache
from hashlib import sha256
from types import MappingProxyType
from pathlib import Path
from typing import Optional

from .errors import FalTermsViolation
from .licences import validate_licence
from .routing import ROUTERS, routed_model  # noqa: F401  (ROUTERS re-exported)

TERMS_PATH = Path(__file__).parent / "data" / "model_terms.json"
"""The ledger — separate from ``models.json`` so it refreshes on its own
cadence and is reviewed as a legal artifact."""

TRI_STATE = frozenset({"yes", "no", "unknown"})
PERMISSION = frozenset({"allowed", "forbidden", "unknown"})

DECISIVE_FIELDS = (
    "license",
    "license_binds_us",
    "commercial_use",
    "third_party_tenancy",
    "c2pa_compatible",
    "provenance_constraint",
)
"""The ledger fields :func:`_refusal` reads: a change to one can change a verdict."""

ROW_DIGEST_CHARS = 16
"""Hex characters of a row's digest kept in a clearance stamp."""

CLEARANCE_KEY = "terms_cleared"
"""``CallPlan.metadata`` key under which a cleared plan records its clearance."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelTerms:
    """One ledger row. A field left ``unknown`` is a refusal when it matters."""

    model_id: str
    backend: str
    license: str = "unknown"  # SPDX id, else LicenseRef-*, see falaw.licences
    license_binds_us: str = "unknown"  # "yes" | "no" (the host holds it) | "unknown"
    commercial_use: str = "unknown"  # "allowed" | "forbidden" | "unknown"
    third_party_tenancy: str = "unknown"  # may we run this for someone who is not us
    c2pa_compatible: str = "unknown"  # may output carry a C2PA AI-generated claim
    provenance_constraint: str = ""  # free text, e.g. a "human generated" clause
    notes: str = ""
    source_url: str = ""
    observed_on: str = ""  # ISO date: makes a stale row visible as stale

    def __post_init__(self):
        validate_licence(self.license)
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
    """What the job needs from the terms — supplied by the caller, never process-global
    (an explicit argument, or scoped to a block by :func:`using_terms_context`).

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
    return MappingProxyType(rows)


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


_AMBIENT: ContextVar[Optional[TermsContext]] = ContextVar(
    "falaw_terms_context", default=None
)


@contextmanager
def using_terms_context(context: Optional[TermsContext]) -> Iterator[None]:
    """Scope *context* over every call made inside the block, eager or planned.

    The eager verbs (``generate_image``, ``render_scene``, ...) take no
    ``terms_context``; this is the one seam that covers all of them, enforced
    where every call passes (:func:`falaw.cache.cached_call_fal`,
    :func:`falaw.core.call_fal`). Scoped to the block (and its threads/tasks),
    never process-global: the deployment decides, per job.
    """
    token = _AMBIENT.set(context)
    try:
        yield
    finally:
        _AMBIENT.reset(token)


def current_terms_context() -> Optional[TermsContext]:
    """The context bound by :func:`using_terms_context`, else ``None``."""
    return _AMBIENT.get()


def effective_terms_context(explicit: Optional[TermsContext]) -> Optional[TermsContext]:
    """The context a check runs under: an explicit ``terms_context=`` argument
    wins; otherwise the one scoped by :func:`using_terms_context`. (Entry
    points that take no argument still enforce the scoped one at the call
    chokepoints, so the strictest applicable check always runs.)"""
    return explicit if explicit is not None else _AMBIENT.get()


def terms_subject(application: str, arguments: Optional[Mapping] = None) -> str:
    """The model id the ledger judges for this call: the routed model for a
    router such as ``fal-ai/any-llm`` (:func:`falaw.routing.routed_model`), else
    *application* itself."""
    return routed_model(application, arguments)


def _refusal(row: Optional[ModelTerms], context: TermsContext) -> Optional[str]:
    """The clause that makes this row unusable for *context*, else None.

    A definite prohibition outranks an unknown: "commercial use is forbidden"
    tells the caller more than "binds_us is unknown" about the same row.
    """
    if row is None:
        return "no terms row: nobody has reviewed this model on this backend"
    needed = [("license_binds_us", row.license_binds_us, None)]
    if context.commercial:
        needed.append(("commercial_use", row.commercial_use, "forbidden"))
    if context.third_party:
        needed.append(("third_party_tenancy", row.third_party_tenancy, "forbidden"))
    if context.c2pa:
        needed.append(("c2pa_compatible", row.c2pa_compatible, "no"))
    for name, value, prohibited in needed:
        if value == prohibited:
            detail = (
                row.provenance_constraint if name == "c2pa_compatible" else row.license
            )
            return f"{name} is {prohibited}" + (f" ({detail})" if detail else "")
    for name, value, _ in needed:
        if value == "unknown":
            return f"{name} is unknown"
    return None


def check_terms(
    model_id: str,
    backend: str,
    context: Optional[TermsContext],
    *,
    ledger: Optional[Mapping] = None,
    arguments: Optional[Mapping] = None,
) -> None:
    """Raise :class:`FalTermsViolation` unless ``(model_id, backend)`` is
    usable for *context*. ``context=None`` (the default everywhere) checks
    nothing: the strict path is opt-in per deployment. Pass the call's
    ``arguments`` so a router is judged by the model it routes to
    (:func:`terms_subject`).
    """
    if context is None:
        return
    model_id = terms_subject(model_id, arguments)
    row = get_terms(model_id, backend, ledger=ledger)
    clause = _refusal(row, context)
    if clause is None:
        return
    if row is None and backend != "fal":
        clause += f" (a {backend!r} backend must plan under the catalogue model id)"
    source = f" (see {row.source_url})" if row and row.source_url else ""
    raise FalTermsViolation(
        f"{model_id!r} on backend {backend!r} refused: {clause}{source}",
        model_id=model_id,
        backend=backend,
        clause=clause,
        source_url=row.source_url if row else "",
    )


def row_digest(row: Optional[ModelTerms]) -> str:
    """A short digest of the fields of a ledger row that decide a clearance
    (``""`` for no row): the version of the terms a clearance was granted
    under, so an edit to a verdict shows up even when nobody bumped
    ``observed_on``. Prose fields (notes, source) and new fields do not move it."""
    if row is None:
        return ""
    blob = json.dumps(
        {name: getattr(row, name) for name in DECISIVE_FIELDS}, sort_keys=True
    ).encode("utf-8")
    return sha256(blob).hexdigest()[:ROW_DIGEST_CHARS]


def clearance(
    application: str,
    backend: str,
    context: TermsContext,
    arguments: Optional[Mapping] = None,
    *,
    ledger: Optional[Mapping] = None,
) -> dict:
    """The descriptive record a plan carries once :func:`check_terms` passed:
    what was cleared, where, for which job, under which version of the row.
    Lives in ``CallPlan.metadata`` (never hashed), so a persisted plan can show
    it was cleared."""
    model = terms_subject(application, arguments)
    return {
        "model": model,
        "backend": backend,
        "context": asdict(context),
        "row": row_digest(get_terms(model, backend, ledger=ledger)),
    }


def is_cleared(
    call, context: TermsContext, *, ledger: Optional[Mapping] = None
) -> bool:
    """Whether *call* (a ``CallPlan``) carries a clearance that still describes
    it: same model and backend as now, for exactly *context*, under the ledger
    row as it reads now. A call re-targeted after planning
    (``dataclasses.replace(call, backend=...)``, a replayed or repriced plan) or
    whose row was edited since fails this, so it must be re-checked, never
    trusted. Stamps are issued against the default ledger; pass ``ledger=`` to
    verify against another. A stamp from before the row digest existed has no
    ``row`` and reads as not cleared."""
    stamp = call.metadata.get(CLEARANCE_KEY)
    return stamp == clearance(
        call.application, call.backend, context, call.arguments, ledger=ledger
    )


def third_party_tenancy_ok(
    model_id: str, backend: str, *, ledger: Optional[Mapping] = None
) -> bool:
    """The routing-visible projection: may a router send third-party work to
    ``(model_id, backend)`` without consulting the full ledger? ``False`` when
    unsure — the cheap 80%, so a router can drop an incompatible backend."""
    row = get_terms(model_id, backend, ledger=ledger)
    return _refusal(row, TermsContext(third_party=True)) is None


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
    "clearance",
    "current_terms_context",
    "effective_terms_context",
    "get_terms",
    "row_digest",
    "is_cleared",
    "load_terms",
    "terms_subject",
    "third_party_tenancy_ok",
    "unreviewed_models",
    "using_terms_context",
]
