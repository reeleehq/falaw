"""Plan / Execute primitives — separate planning (data) from execution (effects).

Today every falaw operation is eager: ``generate_image(prompt)`` makes the
API call immediately. That means:

- A budget gate has to predict cost from outside the call and *hope* the
  prediction matches what the operation will actually do.
- Tests need a fake fal_client to exercise any code that touches an
  operation, even when the test is about composition or cost.
- A UI can't show "you're about to spend $4.12, click confirm" without
  a separate, parallel cost-prediction code path.

The fix is to give every operation two surfaces:

1. ``plan_X(...) -> CallPlan``: pure data describing the call that *would*
   happen — model_id, arguments, predicted cost, cache status. No API contact.
2. ``execute(plan, ...) -> list[Artifact]``: turns a Plan (one or more
   CallPlans) into materialized Artifacts. The eager wrappers
   (``generate_image``, etc.) are now thin: ``execute(plan_X(...))[0]``.

A higher-level orchestrator (a music-video render, a storyboard generation)
builds a Plan by composing CallPlans across multiple operations. The Plan
gets a typed ``total_cost_usd``, can be inspected, edited, dry-run, or
serialized — all without the network.

Examples
--------

>>> from falaw.plan import CallPlan, Plan
>>> p1 = CallPlan(
...     tool="generate_image",
...     application="fal-ai/flux/dev",
...     arguments={"prompt": "a tiger", "image_size": "landscape_4_3"},
...     output_kind="image",
...     estimated_cost_usd=0.025,
...     cache_status="miss",
... )
>>> p2 = CallPlan(
...     tool="image_to_video",
...     application="fal-ai/minimax/hailuo-02/pro/image-to-video",
...     arguments={"image_url": "<from p1>"},
...     output_kind="video",
...     estimated_cost_usd=0.50,
...     cache_status="miss",
... )
>>> plan = Plan(calls=(p1, p2))
>>> plan.total_cost_usd
0.525
>>> plan.cache_hit_savings_usd
0.0
>>> [c.tool for c in plan.calls]
['generate_image', 'image_to_video']

Plans concatenate, so an orchestrator can build one shot's Plan and then
append it to a scene-level Plan:

>>> shot_plan = Plan(calls=(p1,))
>>> scene_plan = Plan(calls=()) + shot_plan + Plan(calls=(p2,))
>>> len(scene_plan.calls)
2
"""

from __future__ import annotations

import warnings
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterator, Literal, Optional

from .canonical import DFLT_BACKEND
from .degrade import (
    DEGRADE_WARNING_SINK,
    deferred_degrade_warnings,
    emit_degradation,
)
from .outcomes import CallOutcome, ExecutionReport


CacheStatus = Literal["hit", "miss", "stale", "unknown"]
"""Whether the cache will short-circuit this call.

- ``hit``: A cached response exists and will be returned without an API call.
- ``miss``: No cache entry; the call will hit fal.
- ``stale``: An entry exists but is expected to be invalidated (e.g. a
  ``force=True`` re-render asked for it). Today we don't distinguish stale
  from miss for cost — both are billed.
- ``unknown``: Plan was built without consulting the cache.
"""


OutputKind = Literal["image", "video", "audio", "json", "text", "binary"]
"""Coarse class of what this call produces. Mirrors :class:`lacing.Artifact.kind`
so the producer knows what shape of Artifact to materialize."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CostBasis:
    """How a :attr:`CallPlan.estimated_cost_usd` was arrived at (falaw#60).

    A frozen quote goes stale the moment the rate table moves — 0.0.46 moved
    falaw's LLM prices tenfold — and a persisted plan cannot be re-quoted from
    ``application`` and ``arguments`` alone: the quantity hints that priced it
    (the clip's duration, the prompt's token bound) are estimator-only and
    never enter the wire arguments. This records them, plus *which* table
    priced them, so a saved plan can be re-quoted faithfully
    (:func:`falaw.reprice_plan`) and audited after the fact.

    Pure data. Nothing here reaches the network, and nothing here enters
    :func:`plan_hash` or the per-call cache key: a basis says what a call
    *cost*, never what it *produces*, so stamping one leaves every existing
    digest byte-identical.
    """

    pricer: str
    """Which pricing rule produced the figure — a key into
    :data:`falaw.reprice.DFLT_PRICERS`. ``"model_catalogue"`` for a record
    priced out of ``models.json``, ``"llm_rates"`` for a routed LLM priced out
    of ``llm_rates.json``. An unrecognized name re-prices as *unknown*, never
    as the old number."""

    priced: str
    """The entity that was priced: a :attr:`falaw.ModelRecord.id` for the
    catalogue pricer, the routed ``model`` argument for the LLM pricer.
    Distinct from :attr:`CallPlan.application`, which for ``fal-ai/any-llm``
    names the router rather than the model that sets the price."""

    quantities: dict = field(default_factory=dict)
    """The estimator-only shape hints fed to the pricer, by keyword —
    ``{"seconds": 6.0}``, ``{"input_tokens": 20000, "max_output_tokens": 4000}``.
    Absent keys mean the hint was not supplied, which is what made a
    quantity-priced call unpriceable in the first place. Omit-when-unset: a
    hint that was ``None`` at plan time is left out rather than written as
    ``null``."""

    table: str = ""
    """Identity of the rate table consulted, e.g.
    ``"falaw/data/llm_rates.json"``. Free-form so a caller's own reconciled
    table can name itself."""

    table_version: str = ""
    """The version of that table at plan time — falaw stamps a short content
    digest, so a table whose numbers moved gets a different value even when
    its declared version did not. Empty means unversioned/unknown."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CallPlan:
    """A single planned fal call. Pure data — no API contact yet.

    ``application`` and ``arguments`` are the *exact* tuple
    ``cached_call_fal(application, arguments)`` would take, so a Plan can be
    cache-checked, executed, or replayed without ambiguity.
    """

    tool: str
    """High-level tool name — ``"generate_image"``, ``"image_to_video"``, etc.
    Distinct from ``application`` because one tool may dispatch to several
    fal models depending on quality tier."""

    application: str
    """The fal model id that will be invoked (e.g. ``"fal-ai/flux/dev"``).
    Backend-scoped: what it names depends on :attr:`backend`."""

    backend: str = DFLT_BACKEND
    """Which execution backend :func:`execute_plan` dispatches this call to
    (falaw#15) — see :mod:`falaw.backends`. Defaults to
    :data:`falaw.canonical.DFLT_BACKEND` (``"fal"``), the only backend until a
    second one lands. Enters the per-call cache key and ``plan_hash`` only
    when it is **not** the default, so every call falaw has ever planned or
    cached keeps its exact pre-#15 digest — see :mod:`falaw.canonical`."""

    arguments: dict
    """Keyword arguments to pass to fal. Will be JSON-canonicalized for
    cache key computation; should be JSON-serializable."""

    output_kind: OutputKind
    """What kind of Artifact this call will produce."""

    estimated_cost_usd: Optional[float] = None
    """Predicted cost in USD. ``None`` when the model has no ``cost_estimate``
    populated (callers can distinguish "free" from "unknown")."""

    cache_status: CacheStatus = "unknown"
    """Whether the cache will short-circuit this call. ``"hit"`` means
    ``execute`` won't bill, so :attr:`Plan.total_cost_usd` and
    :attr:`Plan.cache_hit_savings_usd` reflect that."""

    expected_duration_s: Optional[tuple[float, float]] = None
    """``(min, max)`` duration the model can produce, or ``None`` if no
    duration contract is known. Plan-level validators can check that the
    requested duration fits this range and raise :class:`FalDurationOutOfRange`
    *before* the call instead of letting it silently truncate."""

    metadata: dict = field(default_factory=dict)
    """Free-form labels for downstream consumers. Conventional keys:
    ``shot_id``, ``beat_id``, ``character_name``, ``strategy``."""

    key_extra: dict = field(default_factory=dict)
    """Identity beyond the wire arguments — entries that change what the call
    *produces* without appearing in ``arguments``. Participates in the
    per-call cache key AND ``plan_hash``, under omit-if-empty (an empty dict
    leaves every existing key byte-identical). Unlike ``metadata``, which is
    deliberately identity-free labelling, putting something here says "a
    cached result minted without this value must not be reused". First
    customer: nw's Transform ``impl_version`` (nw#27) — "same interface,
    changed behaviour" must miss the cache without renaming anything."""

    cost_basis: Optional[CostBasis] = None
    """How :attr:`estimated_cost_usd` was computed, or ``None`` when nothing
    recorded it (falaw#60). Present, the quote can be re-run against today's
    rate table by :func:`falaw.reprice_plan`; absent, that function reports the
    call as ``"no_basis"`` and clears its cost to unknown rather than passing a
    stale figure off as current. Purely descriptive — it stays out of
    :func:`plan_hash` and the per-call cache key, and out of the serialized
    dict entirely when unset, so every plan falaw has ever hashed or persisted
    is unmoved."""

    def __post_init__(self) -> None:
        # Every cost sum and the executor's per-artifact stamp read this
        # field unvalidated (Artifact enforces ge=0, but model_copy skips
        # validation), so the refusal lives at the SSOT. `not (x >= 0)`
        # also catches NaN.
        cost = self.estimated_cost_usd
        if cost is not None and not (cost >= 0):
            raise ValueError(
                f"estimated_cost_usd must be a non-negative number or None, "
                f"got {cost!r} for {self.application!r}."
            )

    # -- predicted-billable cost --------------------------------------------

    @property
    def billable_cost_usd(self) -> float:
        """Cost that will actually be billed (0 on cache hit, estimate otherwise).

        Returns ``0.0`` (not ``None``) on cache hit or unknown estimate so
        sums are well-defined; use :attr:`estimated_cost_usd` ``is None`` to
        check unknown status explicitly.
        """
        if self.cache_status == "hit":
            return 0.0
        return self.estimated_cost_usd or 0.0


@dataclass(frozen=True, slots=True)
class Plan:
    """An ordered sequence of :class:`CallPlan` — a render plan, in essence.

    Plans compose: ``a + b`` returns a new Plan with ``a.calls`` followed by
    ``b.calls``. ``Plan(calls=())`` is the identity. Plans are frozen, so
    edits return new Plans (use :meth:`with_call_replaced` for in-place-feel).
    """

    calls: tuple[CallPlan, ...] = ()

    def __add__(self, other: "Plan") -> "Plan":
        if not isinstance(other, Plan):
            return NotImplemented
        return Plan(calls=self.calls + other.calls)

    def __len__(self) -> int:
        return len(self.calls)

    def __iter__(self):
        return iter(self.calls)

    def __getitem__(self, idx):
        return self.calls[idx]

    @property
    def total_cost_usd(self) -> float:
        """Sum of :attr:`CallPlan.billable_cost_usd` across all calls."""
        return sum((c.billable_cost_usd for c in self.calls), 0.0)

    @property
    def cache_hit_savings_usd(self) -> float:
        """USD that would have been spent without the cache.

        Equal to ``sum(c.estimated_cost_usd for c in calls if c.cache_status == "hit"
        and c.estimated_cost_usd is not None)``.
        """
        return sum(
            (
                c.estimated_cost_usd or 0.0
                for c in self.calls
                if c.cache_status == "hit"
            ),
            0.0,
        )

    @property
    def has_unknown_costs(self) -> bool:
        """True if any non-cache-hit call has no cost estimate.

        Use this to refuse to gate on a budget when the estimate is incomplete.
        """
        return any(
            c.estimated_cost_usd is None and c.cache_status != "hit" for c in self.calls
        )

    @property
    def known_cost_usd(self) -> float:
        """The priced part of :attr:`total_cost_usd` — same number today,
        but honest by construction.

        ``total_cost_usd`` coerces unpriced calls to ``$0.00`` so sums stay
        well-defined; a cumulative budget gate that reads it alone will
        under-quote (400 unpriceable video calls total $0.00). Read this
        together with :attr:`unknown_call_count`: the true cost is
        ``known_cost_usd`` *plus an unknown amount* spread over that many
        calls, and a correct gate refuses when the count is nonzero rather
        than pretending the unknown part is free (falaw#18).
        """
        return sum(
            (
                c.estimated_cost_usd
                for c in self.calls
                if c.cache_status != "hit" and c.estimated_cost_usd is not None
            ),
            0.0,
        )

    @property
    def unknown_call_count(self) -> int:
        """How many billable calls carry no price at all.

        The countable form of :attr:`has_unknown_costs` — see
        :attr:`known_cost_usd` for the budget-gate arithmetic it enables.
        """
        return sum(
            1
            for c in self.calls
            if c.cache_status != "hit" and c.estimated_cost_usd is None
        )

    def with_call_replaced(self, index: int, new_call: CallPlan) -> "Plan":
        """Return a new Plan with ``calls[index]`` replaced."""
        new_calls = list(self.calls)
        new_calls[index] = new_call
        return Plan(calls=tuple(new_calls))


# --- serialization ----------------------------------------------------------

PLAN_DICT_SCHEMA = "falaw.plan/v1"
"""The ``schema`` tag :func:`plan_to_dict` writes and :func:`plan_from_dict`
expects. Bumped only on a breaking change to the dict shape."""


def call_plan_to_dict(call: CallPlan) -> dict:
    """Convert a :class:`CallPlan` to a plain JSON-serializable dict.

    The inverse of :func:`call_plan_from_dict`. ``expected_duration_s`` (a
    ``tuple``) becomes a 2-element list since JSON has no tuple type;
    everything else is already JSON-native.

    ``backend`` (falaw#15) is a **tolerated-default addition**, not a
    :data:`PLAN_DICT_SCHEMA` bump: it is always written, but
    :func:`call_plan_from_dict` defaults it to :data:`DFLT_BACKEND` when
    absent, so a dict from before this field existed still parses, and a
    dict written by this version still parses under older falaw (the extra
    key is simply never read there). No migration needed either direction.

    ``cost_basis`` (falaw#60) is the same kind of addition under a stricter
    rule — **omit-when-unset**: the key is written only when a basis exists, so
    a plan built without one serializes to the exact bytes it did before the
    field existed, and every stored plan, fixture and cassette is unmoved.
    """
    out = {
        "tool": call.tool,
        "application": call.application,
        "backend": call.backend,
        "arguments": call.arguments,
        "output_kind": call.output_kind,
        "estimated_cost_usd": call.estimated_cost_usd,
        "cache_status": call.cache_status,
        "expected_duration_s": (
            list(call.expected_duration_s)
            if call.expected_duration_s is not None
            else None
        ),
        "metadata": call.metadata,
        "key_extra": call.key_extra,
    }
    if call.cost_basis is not None:
        out["cost_basis"] = cost_basis_to_dict(call.cost_basis)
    return out


def cost_basis_to_dict(basis: CostBasis) -> dict:
    """Convert a :class:`CostBasis` to a plain JSON-serializable dict.

    ``table`` / ``table_version`` are omitted when empty, matching the
    omit-when-unset discipline the rest of the wire shape follows — a basis
    that names no table writes no key rather than a pair of ``""``.
    """
    out: dict = {
        "pricer": basis.pricer,
        "priced": basis.priced,
        "quantities": dict(basis.quantities),
    }
    if basis.table:
        out["table"] = basis.table
    if basis.table_version:
        out["table_version"] = basis.table_version
    return out


def cost_basis_from_dict(d: dict) -> CostBasis:
    """Rebuild a :class:`CostBasis` from a :func:`cost_basis_to_dict` dict."""
    return CostBasis(
        pricer=d["pricer"],
        priced=d["priced"],
        quantities=dict(d.get("quantities") or {}),
        table=d.get("table", ""),
        table_version=d.get("table_version", ""),
    )


def call_plan_from_dict(d: dict) -> CallPlan:
    """Rebuild a :class:`CallPlan` from a :func:`call_plan_to_dict` dict.

    ``arguments`` / ``metadata`` are copied (a deserialized plan owns its own
    data); ``expected_duration_s`` is re-tupled. ``backend`` defaults to
    :data:`DFLT_BACKEND` when absent — a dict written before falaw#15 names no
    backend, and it always meant ``"fal"``.

    ``cost_basis`` is absent on any plan written before falaw#60 and on any
    call nothing stamped; it comes back as ``None``, which
    :func:`falaw.reprice_plan` reports as ``"no_basis"`` — never as a quote
    that is still current.
    """
    duration = d.get("expected_duration_s")
    return CallPlan(
        tool=d["tool"],
        application=d["application"],
        backend=d.get("backend", DFLT_BACKEND),
        arguments=dict(d["arguments"]),
        output_kind=d["output_kind"],
        estimated_cost_usd=d.get("estimated_cost_usd"),
        cache_status=d.get("cache_status", "unknown"),
        expected_duration_s=(tuple(duration) if duration is not None else None),
        metadata=dict(d.get("metadata") or {}),
        key_extra=dict(d.get("key_extra") or {}),
        cost_basis=(
            cost_basis_from_dict(basis)
            if (basis := d.get("cost_basis")) is not None
            else None
        ),
    )


def plan_to_dict(plan: Plan) -> dict:
    """Convert a :class:`Plan` to a plain JSON-serializable dict.

    The result round-trips through :func:`plan_from_dict`. This is the
    substrate primitive a consumer (a persistence layer, an MCP transport, a
    plan-diff tool) builds on — falaw owns the wire shape of its own Plan so
    every consumer agrees on it. Carries a ``schema`` tag (:data:`PLAN_DICT_SCHEMA`)
    so a future breaking change is detectable.
    """
    return {
        "schema": PLAN_DICT_SCHEMA,
        "calls": [call_plan_to_dict(c) for c in plan.calls],
    }


def plan_from_dict(d: dict) -> Plan:
    """Rebuild a :class:`Plan` from a :func:`plan_to_dict` dict.

    Raises ``ValueError`` if ``d`` carries an unrecognized ``schema`` tag — a
    plan written by an incompatible future version should fail loudly, not
    silently lose calls. A missing ``schema`` is tolerated (treated as v1) so
    hand-written plans stay easy.
    """
    schema = d.get("schema")
    if schema is not None and schema != PLAN_DICT_SCHEMA:
        raise ValueError(
            f"Cannot deserialize Plan: unknown schema {schema!r} "
            f"(this falaw understands {PLAN_DICT_SCHEMA!r})."
        )
    return Plan(calls=tuple(call_plan_from_dict(c) for c in d.get("calls", ())))


def plan_hash(plan: Plan) -> str:
    """Stable, plan-scoped **structural idempotency key** for a whole :class:`Plan`.

    Answers "does this whole plan match one I already ran?" — the handle a job
    manager (its first customer, :mod:`nw.jobs`) uses to dedup double-submits and
    to replay a resumed render for free. It is computed *before* execution and
    with ``<from N>`` placeholders intact, so it is stable across re-plans of the
    same structural request.

    The digest canonicalizes each call over ``{app, args, tool}``
    (:func:`falaw.canonical.plan_identity_payload`) — matching
    :func:`_synthetic_artifact`'s canonicalization, and deliberately **not** the
    per-call content-addressed cache key (:func:`falaw.cache._key`, which keys on
    ``{app, args}`` with no ``tool``). ``plan_hash`` and the per-call cache key
    therefore key on *different* bytes and must not be assumed to agree
    call-for-call. Both projections live side by side in :mod:`falaw.canonical`
    with one shared byte-form (:func:`falaw.canonical.canonical_blob` — sorted
    keys, **no** ``default=str`` fallback, no NaN), so an argument the form
    cannot represent faithfully raises
    :class:`falaw.errors.FalNonCanonicalArgument` instead of colliding, and a
    new identity-bearing field is an explicit decision about both hashes.

    Two structurally-identical plans hash equal; changing any call's ``app``,
    ``args``, or ``tool`` — or the *order* of calls — changes the hash.

    >>> a = CallPlan(tool="generate_image", application="fal-ai/flux/dev",
    ...              arguments={"prompt": "a tiger"}, output_kind="image")
    >>> b = CallPlan(tool="image_to_video", application="fal-ai/svd",
    ...              arguments={"image_url": "<from 0>"}, output_kind="video")
    >>> plan_hash(Plan(calls=(a, b))) == plan_hash(Plan(calls=(a, b)))
    True
    >>> plan_hash(Plan(calls=(a, b))) == plan_hash(Plan(calls=(b, a)))
    False

    ``backend`` (falaw#15) joins the hashed payload too, so a plan built for
    one backend never dedups against the structurally-identical plan for
    another — and, since it is included only when non-default, every plan
    made of today's (all-``"fal"``) calls hashes exactly as it did before:

    >>> comfy = CallPlan(tool="generate_image", application="fal-ai/flux/dev",
    ...                   arguments={"prompt": "a tiger"}, output_kind="image",
    ...                   backend="comfyui")
    >>> plan_hash(Plan(calls=(a,))) == plan_hash(Plan(calls=(comfy,)))
    False
    """
    import hashlib

    from .canonical import canonical_blob, plan_identity_payload

    blob = canonical_blob(
        [
            plan_identity_payload(
                c.application,
                c.arguments,
                tool=c.tool,
                backend=c.backend,
                key_extra=c.key_extra or None,
            )
            for c in plan.calls
        ]
    )
    return hashlib.sha256(blob).hexdigest()


# --- planning helpers -------------------------------------------------------


def make_call_plan(
    *,
    tool: str,
    application: str,
    arguments: dict,
    output_kind: OutputKind,
    backend: str = DFLT_BACKEND,
    estimated_cost_usd: Optional[float] = None,
    expected_duration_s: Optional[tuple[float, float]] = None,
    metadata: Optional[dict] = None,
    consult_cache: bool = True,
    cost_basis: Optional[CostBasis] = None,
) -> CallPlan:
    """Build a :class:`CallPlan` and (optionally) check the cache.

    When ``consult_cache=True`` (the default), the cache is peeked using the
    same key the eventual call would produce; ``cache_status`` is set to
    ``"hit"`` if a cached entry exists, ``"miss"`` otherwise. This makes
    ``Plan.total_cost_usd`` honest: a fully-cached Plan reports $0.

    When ``consult_cache=False`` (e.g. for unit tests or "what would a fresh
    run cost?" reporting), ``cache_status`` is ``"unknown"``.

    A **chained call** — arguments still holding a ``"<from N>"`` placeholder,
    because the upstream call has not executed yet — is never peeked
    (falaw#15, D2): its resolved key is not knowable at plan time, and the
    unresolved key is never written by anything (:func:`execute` always keys
    on the resolved form), so peeking it can only ever report a false
    ``"miss"`` — never a real ``"hit"``. That silently over-quotes cost and
    under-reports the plan's ``cache_hit_savings_usd`` on every chained call,
    which under prepaid billing (a quote that may be *deducted*) is a billing
    bug. ``cache_status`` is ``"unknown"`` here instead, exactly the case
    :data:`CacheStatus` documents it for.

    ``cost_basis`` records how ``estimated_cost_usd`` was arrived at so the
    quote can be re-run later (falaw#60). It is descriptive only: it never
    reaches the cache key or :func:`plan_hash`, and a plan built without one
    is byte-identical to one built before the field existed.

    Raises:
        falaw.errors.FalNonCanonicalArgument: an argument cannot be hashed
            faithfully (non-JSON object, non-finite float, non-string mapping
            key). Raised here — while planning is still free — rather than at
            key-composition time on the way to the network (falaw#17).
    """
    from .canonical import ensure_canonical
    from .upload import has_local_files, localize_paths, resolve_local_files

    # A local file (``os.PathLike``) becomes a "<file ...>" marker: the Plan
    # stays pure data, and execute() uploads it on a miss and keys on its bytes
    # (falaw#92).
    arguments = localize_paths(arguments)

    # Validate before the cache peek: the peek's `except Exception` fallback
    # (best-effort by design) would otherwise swallow the refusal into a
    # silent `"unknown"`. `extra=` is the documented escape hatch for
    # model-specific params, so arbitrary Python values genuinely reach here.
    ensure_canonical(dict(arguments), context="arguments")

    status: CacheStatus = "unknown"
    if consult_cache:
        if _has_placeholder(arguments):
            # D2: the resolved key isn't knowable yet, and the unresolved key
            # is never written by anything — peeking it can only ever
            # fabricate a "miss". "unknown" is honest; a "hit" or "miss" here
            # would be a guess dressed up as an observation.
            status = "unknown"
        else:
            # Local import to avoid a cycle: cache imports from core, core
            # imports from errors, none of which need plan.
            try:
                from .cache import cache_get  # type: ignore[import-not-found]

                peek = (
                    resolve_local_files(arguments, mode="key")
                    if has_local_files(arguments)
                    else arguments
                )
                status = (
                    "hit"
                    if cache_get(application, peek, backend=backend) is not None
                    else "miss"
                )
            except Exception:
                # Cache lookup is best-effort — if it errors (corrupted
                # manifest, etc.) fall back to "unknown" rather than fail
                # the planner.
                status = "unknown"
    return CallPlan(
        tool=tool,
        application=application,
        backend=backend,
        arguments=arguments,
        output_kind=output_kind,
        estimated_cost_usd=estimated_cost_usd,
        cache_status=status,
        expected_duration_s=expected_duration_s,
        metadata=metadata or {},
        cost_basis=cost_basis,
    )


# --- execution --------------------------------------------------------------


# Type for the per-call result-to-Artifact converter. Converters own the
# artifact's *content* fields; ``cost_usd`` is not theirs to set — the executor
# stamps it from the observed run outcome after conversion (falaw#26), because
# only the executor knows whether the response was served from cache.
ResultToArtifact = Callable[[dict, CallPlan], "Artifact"]  # noqa: F821


DFLT_FETCH_BYTES = True
"""Whether :func:`execute` downloads media results to content-address them.

True — an artifact whose ``asset_id`` is not the SHA-256 of its bytes breaks
``lacing.Artifact``'s contract and puts an expiring location into every
downstream cache key.
"""

FETCH_BYTES_ENVVAR = "FALAW_FETCH_ARTIFACT_BYTES"
"""Env var overriding :data:`DFLT_FETCH_BYTES` process-wide.

Not a production setting — see the ``fetch_bytes`` argument of :func:`execute`
for what opting out costs. Read at call time, so it can be set after import.

**Do not reach for this to make a test suite offline.** It works, and that is
the trap: it silences the network by turning content addressing **off**, so the
suite becomes hermetic and simultaneously stops exercising the feature. Every
``asset_id`` becomes a digest of the response rather than the SHA-256 of the
bytes, chained calls key on URLs, and no test then covers the path production
actually takes. Install a fake transport instead —
:func:`falaw.testing.fake_assets` is one line in a ``conftest.py`` — and the
suite stays offline *with* content addressing under test, on bytes it controls.
Both consumers that hit this chose the fake for exactly that reason
(thorwhalen/falaw#27).
"""


def _fetch_bytes_default() -> bool:
    """Resolve the effective ``fetch_bytes`` default from the environment."""
    import os

    raw = os.environ.get(FETCH_BYTES_ENVVAR)
    if raw is None:
        return DFLT_FETCH_BYTES
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


DFLT_CONCURRENCY = 1
"""How many calls of a Plan run at once by default.

One — a Plan executes sequentially unless the caller asks otherwise. Every call
is a paid vendor request, so parallelism is opt-in: it is the caller who knows
their rate limit, their budget, and whether they want 200 renders started at
once. (:func:`falaw.render_scene` makes the same choice for the same reason.)
"""


def _resolved_cache_mode(use_cache: bool, refresh: bool) -> tuple[bool, bool]:
    """Validate the ``(use_cache, refresh)`` pair, returning it unchanged.

    Three modes, one of which is new (falaw#49):

    ============================  ==========  ===========  ==========
    ``(use_cache, refresh)``      cache read  cache write  meaning
    ============================  ==========  ===========  ==========
    ``(True, False)`` — default   yes         yes          reuse, then keep
    ``(True, True)``  — new       no          yes          re-run, but keep
    ``(False, False)``            no          no           do not touch it
    ============================  ==========  ===========  ==========

    ``(False, True)`` is the fourth corner and it has no meaning: the write
    needs a key, and the key args are only resolved when ``use_cache`` is on
    (the key ref is stricter than the wire ref — see :func:`execute`). Picking
    one of the two intents silently would hand the caller a spend policy they
    did not ask for, so it raises.
    """
    if refresh and not use_cache:
        raise ValueError(
            "refresh=True requires use_cache=True. refresh means 'skip the "
            "cache read, keep the cache write', so it needs the cache on; "
            "use_cache=False means 'do not touch the cache at all' and writes "
            "nothing. Pass use_cache=True, refresh=True to re-run a plan and "
            "keep what the re-run paid for."
        )
    return use_cache, refresh


def execute(
    plan: Plan,
    *,
    on_event: Optional[Callable] = None,
    dry_run: bool = False,
    use_cache: bool = True,
    refresh: bool = False,
    artifact_converter: Optional[ResultToArtifact] = None,
    content_store=None,
    fetch_bytes: Optional[bool] = None,
    asset_fetcher=None,
    concurrency: int = DFLT_CONCURRENCY,
) -> list:
    """Execute a Plan, returning a list of materialized :class:`lacing.Artifact`s.

    This is the **halt** policy: the first call that raises ends the run, and its
    exception propagates unchanged (falaw's typed hierarchy — see
    :mod:`falaw.errors` — is what a caller classifies on, so it is never
    wrapped). Use :func:`execute_isolated` when one bad call must not discard
    the rest of a fan-out; it returns an :class:`~falaw.ExecutionReport` with one
    outcome per call instead of raising.

    Args:
        plan: The Plan to execute.
        on_event: Optional per-call event subscriber (passed to ``call_fal``).
        dry_run: When True, no fal calls are made; synthetic Artifacts are
            returned with placeholder ``asset_id`` and ``url=None``. Useful
            for exercising downstream composition without an API key.
        use_cache: When True (default), executes via ``cached_call_fal`` so
            cache hits skip the network. When False, the cache is not touched
            **at all** — neither read nor written. That is the historical
            meaning and it is unchanged: a caller who genuinely wants no cache
            interaction still has it. To re-run a plan and *keep* what the
            re-run paid for, leave ``use_cache=True`` and pass ``refresh``.
        refresh: When True, skip the cache **read** and keep the cache
            **write** — the third mode (falaw#49). Every call executes fresh,
            and every fresh result is stored under the key it would have been
            read from, so the next run (or a downstream consumer) hits it.
            Requires ``use_cache=True``, since there is no key to write under
            when the cache is off; the contradictory combination raises rather
            than silently picking one. This is the mode to reach for behind a
            ``force`` / "re-verify this" switch: without it, forcing a re-run
            discards the result it just paid for and guarantees the next
            consumer re-bills.
        artifact_converter: Per-CallPlan converter from raw fal response to
            :class:`lacing.Artifact`. When ``None`` (default), a built-in
            converter handles the common shapes (``{images: [{url}]}``,
            ``{video: {url}}``, ``{audio: {url}}``). Mutually exclusive with
            ``content_store`` / ``fetch_bytes`` / ``asset_fetcher``, which
            configure the built-in converter only — passing both raises, rather
            than silently ignoring the ones a custom converter cannot honour.
            Converters do not own ``cost_usd``: the executor stamps it from
            the observed run outcome after conversion, overwriting whatever
            the converter set (falaw#26).
        content_store: Injected :class:`lacing.ArtifactStore` that media bytes
            are materialized into. Defaults to
            :func:`falaw.content.default_content_store` (a directory store
            rooted in the falaw cache). Point this at an S3-backed store to
            share content — and therefore cache hits — across machines.
        fetch_bytes: Whether to download each media result so its ``asset_id``
            is the SHA-256 of its bytes. Defaults to :data:`DFLT_FETCH_BYTES`
            (true), overridable process-wide via :data:`FETCH_BYTES_ENVVAR`.
            **Opting out forfeits caching for chained calls**: without bytes
            there is no content hash, so downstream calls fall back to keying
            on the upstream URL — which fal mints fresh per upload, so the
            downstream entry can never be reused across runs or machines. It
            also means ``asset_id`` is *not* a content hash, in violation of
            ``lacing.Artifact``'s contract. Use it only when you genuinely
            want URL-only artifacts and no reuse.
        asset_fetcher: Injected byte source (``url -> Iterable[bytes]``) used to
            read media results; defaults to
            :func:`falaw.content.default_url_fetcher`. This is the per-call
            transport seam. A **hermetic test suite** usually wants the
            process-wide one instead — :func:`falaw.testing.fake_assets`, built
            on :func:`falaw.content.using_url_fetcher` — because a suite
            reaching falaw *through* its own public API has no ``execute``
            call site to pass this to. Passing it here still wins over any
            installed default. (``$FALAW_FETCH_ARTIFACT_BYTES=0`` also silences
            the network, but by turning content addressing off — see
            :data:`FETCH_BYTES_ENVVAR`.)
        concurrency: How many calls may be in flight at once. ``1``
            (:data:`DFLT_CONCURRENCY`) runs the Plan sequentially, on the
            calling thread, exactly as it always has. Above 1, independent calls
            run on a thread pool bounded by this number — a Plan is I/O-bound
            (an HTTP request that fal takes tens of seconds to answer), so
            threads are the right tool and the bound is what keeps a 200-call
            fan-out from becoming 200 simultaneous paid requests. **Chained
            calls are never parallelised with their producers**: a call holding
            a ``"<from N>"`` placeholder waits for call ``N``. Two things to
            weigh before raising it: the vendor's rate limit, and memory —
            materializing a media result peaks at roughly twice the asset's size
            (thorwhalen/lacing#25), so ``concurrency`` multiplies the peak.

    Failure handling — a paid result is never discarded
    ---------------------------------------------------
    Two different things can go wrong when reading a result's bytes, and they
    get two different answers:

    - **A fresh call whose bytes cannot be fetched.** fal has already run — and
      billed — the generation. Raising would throw away a result we paid for,
      typically over a transient network failure. So the artifact **degrades**:
      ``url`` is kept, ``bytes_size`` stays 0, ``asset_id`` is a digest of the
      response and is *not* claimed to be a content hash, and a
      :class:`UserWarning` is emitted. Downstream key resolution reads
      ``bytes_size == 0`` and falls back to the URL — a guaranteed cache
      *miss*, never a wrong hit.
    - **A cache hit that cannot be materialized** — fal deleted the URL and the
      bytes are not in the content store. The entry is unusable, so it is
      treated as a **miss**: it is invalidated and the call re-executed once.
      A cache must never become a trap whose only escape is re-billing the
      whole plan with ``use_cache=False``.

    Placeholder resolution — the wire/key split
    -------------------------------------------
    Any string argument equal to ``"<from N>"`` (for an integer ``N``) is
    rewritten *just before* the call is made — so a multi-step plan (e.g.
    generate_image → image_to_video) can reference the upstream output without
    the planner needing to know its URL. The rewrite happens after the upstream
    call has executed; planning itself is unaffected.

    It happens **twice**, into two different argument sets, because the same
    value cannot serve both jobs:

    - the **wire** arguments get ``artifacts[N].url`` — what fal needs in order
      to fetch the input;
    - the **key** arguments get ``sha256:<artifacts[N].asset_id>`` — the
      upstream's content hash, so a byte-identical upstream regeneration
      produces a downstream cache *hit* instead of re-billing the expensive
      call. Keying on the URL instead is the defect this split exists to fix
      (falaw#14): fal mints a unique URL per upload, so a URL-keyed downstream
      entry is unreachable the moment the upstream genuinely re-runs.

    An upstream artifact with no materialized bytes has no content hash, so its
    key ref falls back to the URL — a guaranteed miss, never a wrong hit.

    Returns:
        One :class:`lacing.Artifact` per :class:`CallPlan` in ``plan.calls``,
        in the same order.
    """
    return execute_isolated(
        plan,
        on_event=on_event,
        dry_run=dry_run,
        use_cache=use_cache,
        refresh=refresh,
        artifact_converter=artifact_converter,
        content_store=content_store,
        fetch_bytes=fetch_bytes,
        asset_fetcher=asset_fetcher,
        concurrency=concurrency,
        halt_on_failure=True,
    ).artifacts_or_raise()


def execute_isolated(
    plan: Plan,
    *,
    on_event: Optional[Callable] = None,
    dry_run: bool = False,
    use_cache: bool = True,
    refresh: bool = False,
    artifact_converter: Optional[ResultToArtifact] = None,
    content_store=None,
    fetch_bytes: Optional[bool] = None,
    asset_fetcher=None,
    concurrency: int = DFLT_CONCURRENCY,
    halt_on_failure: bool = False,
) -> ExecutionReport:
    """Execute a Plan with **per-call failure isolation**, returning a report.

    The fan-out counterpart of :func:`execute`. Where ``execute`` raises on the
    first failure — discarding every artifact produced before it, each of which
    fal has already billed — this returns an :class:`~falaw.ExecutionReport`
    carrying one :class:`~falaw.CallOutcome` per call: the successes with their
    artifacts, the failures with their exceptions, and the calls that never ran
    with the reason why.

    ``len(report.outcomes) == len(plan.calls)`` always, so a caller that built
    something per call can zip against ``report.outcomes`` and stay aligned.

    Args:
        halt_on_failure: When True, stop *submitting* work as soon as any call
            fails; everything not yet started is reported ``blocked`` with a
            run-level reason. This is what :func:`execute` uses, and at
            ``concurrency=1`` it reproduces the historical sequential
            behaviour exactly. Note that at ``concurrency > 1`` calls already
            in flight are **not** cancelled — a fal request cannot be recalled
            once made, and pretending otherwise would discard results that were
            billed anyway.

        All other arguments are as :func:`execute`.

    Three outcome states, not two
    -----------------------------
    ``failed`` and ``blocked`` are different questions for the caller. A failed
    call can be retried verbatim. A blocked one cannot: its input does not
    exist, so it has to be re-planned after its producer succeeds. Any call
    holding a ``"<from N>"`` placeholder whose call ``N`` did not succeed is
    blocked, transitively.

    Examples:
        >>> from falaw import CallPlan, Plan, execute_plan_isolated
        >>> plan = Plan(calls=(CallPlan(tool="t", application="m",
        ...                             arguments={}, output_kind="image"),))
        >>> report = execute_plan_isolated(plan, dry_run=True)
        >>> report.is_complete, len(report.outcomes)
        (True, 1)
    """
    if concurrency < 1:
        raise ValueError(
            f"concurrency must be at least 1, got {concurrency!r}. "
            "It bounds how many calls are in flight at once; 1 is sequential."
        )
    use_cache, refresh = _resolved_cache_mode(use_cache, refresh)

    if dry_run:
        # Per-call isolation applies to dry runs too: a hand-built CallPlan
        # whose arguments cannot be canonicalised makes _synthetic_artifact
        # raise, and the report's "always one outcome per call" guarantee must
        # survive that — one junk call is that call's failure, not the run's.
        # (`execute` still raises, via artifacts_or_raise, as it always has.)
        def _dry_outcome(i: int, call: CallPlan) -> CallOutcome:
            try:
                artifact = _synthetic_artifact(call)
            except Exception as e:
                return CallOutcome(index=i, call=call, status="failed", error=e)
            return CallOutcome(
                index=i, call=call, status="succeeded", artifact=artifact
            )

        return ExecutionReport(
            outcomes=tuple(_dry_outcome(i, call) for i, call in enumerate(plan.calls))
        )

    if artifact_converter is not None:
        _refuse_converter_configuration(content_store, fetch_bytes, asset_fetcher)
        converter = artifact_converter
        # A custom converter defines its own notion of a usable artifact, so we
        # do not second-guess its cache hits.
        usable_from_cache = _always_usable
    else:
        wants_bytes = _fetch_bytes_default() if fetch_bytes is None else fetch_bytes
        converter = _make_artifact_converter(
            content_store=content_store,
            fetch_bytes=wants_bytes,
            asset_fetcher=asset_fetcher,
        )
        usable_from_cache = _make_usability_check(fetch_bytes=wants_bytes)

    return _run_plan(
        plan,
        converter=converter,
        usable_from_cache=usable_from_cache,
        use_cache=use_cache,
        refresh=refresh,
        on_event=on_event,
        concurrency=concurrency,
        halt_on_failure=halt_on_failure,
    )


# --- the scheduler ----------------------------------------------------------


def _run_plan(
    plan: Plan,
    *,
    converter: "ResultToArtifact",
    usable_from_cache,
    use_cache: bool,
    refresh: bool = False,
    on_event,
    concurrency: int,
    halt_on_failure: bool,
) -> ExecutionReport:
    """Run every call of ``plan``, honouring its ``<from N>`` dependencies.

    The Plan is a DAG whose only edges are ``"<from N>"`` placeholders, and
    :func:`plan_dependencies` has already proved every edge points *backwards*.
    So the schedule is: a call is runnable once all its producers have
    succeeded, blocked once any of them has not, and at most ``concurrency``
    calls are ever in flight.

    Termination, since a scheduler that can wedge is worse than a slow one: let
    ``m`` be the lowest still-pending index. Every dependency of ``m`` is
    ``< m``, hence already resolved or in flight. If one did not succeed, ``m``
    is marked blocked; if all succeeded, ``m`` is submitted (or the in-flight
    bound is saturated, so there is something to wait for); if one is still in
    flight, there is something to wait for. Every iteration therefore resolves a
    call, starts a call, or waits on one — and ``concurrency >= 1`` is validated
    by the caller, so "starts a call" is always eventually possible.
    """
    deps = plan_dependencies(plan)
    n = len(plan.calls)
    artifacts: list = [None] * n
    outcomes: list[Optional[CallOutcome]] = [None] * n
    succeeded: set[int] = set()
    unusable: set[int] = set()  # failed or blocked — nothing downstream may run
    pending: set[int] = set(range(n))
    halted = False

    def record(outcome: CallOutcome) -> None:
        outcomes[outcome.index] = outcome
        if outcome.status == "succeeded":
            succeeded.add(outcome.index)
            artifacts[outcome.index] = outcome.artifact
        else:
            unusable.add(outcome.index)

    def unit(index: int):
        """The whole per-call job: resolve this call's inputs, then run it.

        Placeholder resolution lives *inside* the isolated unit on purpose. It
        can fail at run time even on a well-formed plan — an upstream that
        succeeded but produced no URL — and that is this call's failure, not the
        run's.
        """
        from .upload import has_local_files, resolve_local_files

        call = plan.calls[index]
        wire_args = _resolve_placeholders(call.arguments, artifacts, ref=_wire_ref)
        # Only resolved when it will be used — the key ref is stricter than the
        # wire ref (it needs bytes *or* a URL), and an uncached run must not
        # inherit that stricter requirement.
        key_args = (
            _resolve_placeholders(call.arguments, artifacts, ref=_key_ref)
            if use_cache
            else wire_args
        )
        if has_local_files(wire_args):
            # Key on the files' bytes; upload only if the call misses the cache.
            template = wire_args
            key_args = (
                resolve_local_files(key_args, mode="key") if use_cache else template
            )
            wire_args = lambda: resolve_local_files(template, mode="wire")  # noqa: E731
        return _execute_call(
            call,
            wire_args,
            key_args,
            converter=converter,
            usable_from_cache=usable_from_cache,
            use_cache=use_cache,
            refresh=refresh,
            on_event=on_event,
        )

    with _bounded_executor(concurrency) as pool:
        in_flight: dict = {}
        while pending or in_flight:
            for index in sorted(pending):
                blockers = tuple(d for d in sorted(deps[index]) if d in unusable)
                if blockers:
                    pending.discard(index)
                    record(_blocked_outcome(plan.calls[index], index, blockers))
                elif halted:
                    pending.discard(index)
                    record(_halted_outcome(plan.calls[index], index))
            for index in sorted(pending):
                if len(in_flight) >= concurrency:
                    break
                if deps[index] <= succeeded:
                    pending.discard(index)
                    in_flight[pool.submit(copy_context().run, unit, index)] = index
            if not in_flight:
                if not pending:
                    break  # the last calls all resolved without running
                # Unreachable given the termination argument above; a wedged
                # scheduler must be loud rather than a silent hang.
                raise RuntimeError(
                    f"falaw scheduler stalled with {len(pending)} call(s) "
                    "pending and none runnable. This is a falaw bug — please "
                    "report the Plan that produced it."
                )
            done, _ = _wait_first(in_flight)
            for future in done:
                index = in_flight.pop(future)
                outcome = _outcome_from_future(plan.calls[index], index, future)
                if outcome.artifact is not None and deps[index]:
                    outcome = _outcome_with_lineage(
                        outcome,
                        upstream=tuple(artifacts[j] for j in sorted(deps[index])),
                    )
                record(outcome)
                if outcomes[index].status == "failed" and halt_on_failure:
                    halted = True

    return ExecutionReport(outcomes=tuple(outcomes))  # type: ignore[arg-type]


def _outcome_with_lineage(outcome: CallOutcome, *, upstream: tuple) -> CallOutcome:
    """Stamp the outcome's artifact with its upstream artifact lineage.

    The D5 payoff (lacing#14): ``was_derived_from`` gains the ``asset_id`` of
    every artifact this call consumed via ``"<from N>"`` placeholders, read
    straight off the Plan's dependency DAG. Executor-owned like the cost
    stamp — the converter contract ``(raw, call)`` cannot know the plan
    graph. A degraded upstream's ``asset_id`` (a response digest) is still
    the identity of that upstream record and is included; its
    ``bytes_size == 0`` remains the degradation marker. Dry runs are not
    stamped (their placeholders are never resolved).

    Content-addressed by construction: a byte-identical upstream
    regeneration produces the same ``asset_id``, so the recorded edge — and
    anything comparing along it (nw's freshness, once it consumes artifact
    edges) — survives regeneration. That is the property URL-based
    references could never have (falaw#14).
    """
    from dataclasses import replace as _dc_replace

    ids = [a.asset_id for a in upstream if a is not None]
    artifact = outcome.artifact
    if not ids or artifact is None:
        return outcome
    prov = artifact.provenance
    present = {str(ref) for ref in prov.was_derived_from}
    merged = list(prov.was_derived_from) + [i for i in ids if i not in present]
    if merged == list(prov.was_derived_from):
        return outcome
    stamped = artifact.model_copy(
        update={"provenance": prov.model_copy(update={"was_derived_from": merged})}
    )
    return _dc_replace(outcome, artifact=stamped)


def _outcome_from_future(call: CallPlan, index: int, future) -> CallOutcome:
    """Turn one finished unit of work into its :class:`CallOutcome`.

    A ``BaseException`` that is not an ``Exception`` — ``KeyboardInterrupt``,
    ``SystemExit``, a test framework's abort — is **not** a call failure and is
    re-raised. Isolating it would mean carrying on and billing the rest of the
    plan after the operator asked the process to stop.
    """
    error = future.exception()
    if error is not None:
        if not isinstance(error, Exception):
            raise error
        return CallOutcome(index=index, call=call, status="failed", error=error)
    artifact, cache_hit = future.result()
    return CallOutcome(
        index=index,
        call=call,
        status="succeeded",
        artifact=artifact,
        cache_hit=cache_hit,
    )


def _blocked_outcome(
    call: CallPlan, index: int, blockers: tuple[int, ...]
) -> CallOutcome:
    listed = ", ".join(str(b) for b in blockers)
    return CallOutcome(
        index=index,
        call=call,
        status="blocked",
        blocked_by=blockers,
        reason=(
            f"depends on call(s) {listed} via a '<from N>' placeholder, and "
            "they did not succeed — this call must be re-planned once they do, "
            "not retried as-is"
        ),
    )


def _halted_outcome(call: CallPlan, index: int) -> CallOutcome:
    return CallOutcome(
        index=index,
        call=call,
        status="blocked",
        reason=(
            "never started: an earlier call failed and the run was halted "
            "(halt_on_failure=True)"
        ),
    )


class _InlineExecutor:
    """A ``submit``/``Future`` surface that runs the work immediately, inline.

    The ``concurrency=1`` path. A ``ThreadPoolExecutor(max_workers=1)`` would
    also serialise the calls, but it would move them off the calling thread —
    changing where exceptions are raised from, which thread holds the fal
    client, and what a debugger sees. The default execution path should be the
    plain one, so it is.

    It captures ``BaseException`` because that is exactly what
    ``ThreadPoolExecutor`` does. Emulating the pool faithfully is the whole job:
    the moment the two executors differ, the sequential and concurrent paths
    diverge in behaviour, and only one of them is covered by any given test.
    Which exceptions are *call failures* rather than run-level aborts is decided
    in one place — :func:`_outcome_from_future` — for both.
    """

    def submit(self, fn, *args, **kwargs):
        from concurrent.futures import Future

        future: "Future" = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as e:  # noqa: BLE001 — classified by _outcome_from_future
            future.set_exception(e)
        return future


@contextmanager
def _bounded_executor(concurrency: int) -> Iterator[Any]:
    """Yield an executor bounded to ``concurrency`` in-flight calls."""
    if concurrency == 1:
        yield _InlineExecutor()
        return
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(
        max_workers=concurrency, thread_name_prefix="falaw-plan"
    ) as pool:
        yield pool


def _wait_first(in_flight: dict):
    """Block until at least one future in ``in_flight`` is done."""
    from concurrent.futures import FIRST_COMPLETED, wait

    return wait(list(in_flight), return_when=FIRST_COMPLETED)


def _execute_call(
    call: CallPlan,
    wire_args: dict,
    key_args: dict,
    *,
    converter: "ResultToArtifact",
    usable_from_cache,
    use_cache: bool,
    refresh: bool = False,
    on_event,
) -> tuple:
    """Run one :class:`CallPlan`, returning ``(artifact, cache_hit)``.

    ``cache_hit`` is *observed*, not predicted: it says this call was served
    from a cache entry that proved usable, which is what run-level cost
    accounting must be based on (a plan-time ``cache_status`` can be wrong in
    both directions). The returned artifact's ``cost_usd`` is stamped from
    this observed outcome too — see :func:`_stamp_observed_cost`.

    ``use_cache`` and ``refresh`` are read/write halves, not one switch
    (falaw#49). ``refresh=True`` suppresses the ``cache_get`` and falls
    straight through to ``cached_call_fal(..., refresh=True)`` — the same
    executing-and-writing path a miss already takes — so a deliberate re-run
    still leaves its paid result in the cache. ``use_cache=False`` remains the
    only mode that bypasses ``cached_call_fal`` and therefore writes nothing.

    Split out of the loop because a cache hit is not unconditionally usable:
    the response may name an asset fal has since deleted, whose bytes are not
    in the content store. That entry can never become an artifact again, so it
    is dropped and the call re-executed — the alternative is a cache entry that
    fails forever and can only be escaped by re-billing the entire plan.
    """
    from .backends import get_backend_executor
    from .cache import cached_call_fal, drop_cache_entry, emit_cache_hit

    key_arguments = None if key_args is wire_args else key_args
    # A callable stands for wire arguments not yet resolved (a local file is
    # uploaded only when the call actually goes out, not on a cache hit).
    wire = lambda: wire_args() if callable(wire_args) else wire_args  # noqa: E731
    if use_cache:
        from .cache import cache_get

        # ``refresh`` suppresses the read and nothing else: execution falls
        # through to ``cached_call_fal`` below, which still writes (falaw#49).
        hit = None
        if not refresh:
            hit = cache_get(
                call.application,
                key_args,
                backend=call.backend,
                key_extra=call.key_extra or None,
            )
        if hit is not None:
            # Speculative: the conversion may turn out to be unusable, in which
            # case its own complaints are noise the caller must not see (we are
            # about to discard the artifact and say something more useful). Any
            # warning from a conversion we *keep* is replayed.
            with _deferred_degrade_warnings() as deferred:
                artifact = converter(hit, call)
            if usable_from_cache(artifact, hit):
                for message in deferred:
                    warnings.warn(message, UserWarning, stacklevel=3)
                emit_cache_hit(call.application, on_event)
                return _stamp_observed_cost(artifact, call, cache_hit=True), True
            warnings.warn(
                f"Dropping the falaw cache entry for {call.application!r}: its "
                "recorded result names an asset that can no longer be read "
                "(fal-served URLs expire and are permanently deleted, and the "
                "bytes are not in the content store). Re-executing the call — "
                "this one costs money.",
                UserWarning,
                stacklevel=3,
            )
            drop_cache_entry(
                call.application,
                key_args,
                backend=call.backend,
                key_extra=call.key_extra or None,
            )
        raw = cached_call_fal(
            call.application,
            wire(),
            key_arguments=key_arguments,
            refresh=True,
            on_event=on_event,
            backend=call.backend,
            key_extra=call.key_extra or None,
        )
    else:
        raw = get_backend_executor(call.backend)(
            call.application, wire(), on_event=on_event
        )
    return _stamp_observed_cost(converter(raw, call), call, cache_hit=False), False


def _stamp_observed_cost(artifact, call: CallPlan, *, cache_hit: bool):
    """Return ``artifact`` with ``cost_usd`` set from the run's *observed* outcome.

    The converter cannot know whether its response came from the cache — its
    contract is ``(raw, call)`` and nothing more — so the executor owns the
    stamp, overwriting whatever any converter (custom ones included) wrote.
    Before this, ``cost_usd`` was the plan-time ``billable_cost_usd`` peek: a
    call planned as a miss that ran as a hit carried the full price of a call
    that cost nothing, and a planned hit whose entry had to be dropped and
    re-billed carried ``None`` (falaw#26).

    - observed cache hit → ``0.0`` — a *known* zero, nothing was billed;
    - observed miss, priced model → ``call.estimated_cost_usd``;
    - observed miss, unpriced model → ``None`` — unknown, never "free".

    Still an estimate on a miss (prices come from the cost tables, not a
    vendor receipt) — run-level truth with the unknown-price flag lives on
    :class:`~falaw.ExecutionReport`.
    """
    cost = 0.0 if cache_hit else call.estimated_cost_usd
    return artifact.model_copy(update={"cost_usd": cost})


# The sink lives in `falaw.degrade` because `falaw.content` degrades too and
# cannot import this module at scope. Re-bound here as the historical names so
# the surrounding code and its tests keep reading the same way.
_DEGRADE_WARNING_SINK = DEGRADE_WARNING_SINK
_deferred_degrade_warnings = deferred_degrade_warnings


def _content_ref_or_none(url: str, content_store, asset_fetcher):
    """``(ContentRef | None, store)`` for ``url`` — ``None`` on a fetch failure.

    fal has already run and **billed** the generation by the time we get here,
    so a failure to read the bytes must not throw the result away: a transient
    network error would turn a paid render into nothing at all. The caller
    degrades to a URL-only artifact instead, and this function makes the
    failure loud rather than silent.
    """
    from .content import content_ref_for_url, default_content_store
    from .errors import FalAssetFetchError

    store = default_content_store() if content_store is None else content_store
    try:
        return content_ref_for_url(url, store=store, fetcher=asset_fetcher), store
    except FalAssetFetchError as e:
        message = (
            f"{e} Falling back to a URL-only artifact: `asset_id` is a digest "
            "of the response, NOT a content hash, and `bytes_size` is 0. "
            "Chained calls downstream of it cannot be cache-reused, and the "
            "artifact dies with the URL."
        )
        emit_degradation(message, stacklevel=4)
        return None, store


def _always_usable(artifact, raw: dict) -> bool:
    return True


def _make_usability_check(*, fetch_bytes: bool):
    """Whether a cache hit converted by the **built-in** converter is usable.

    Unusable means exactly one thing: bytes were wanted, the recorded response
    names an asset, and the artifact came back with none — so the bytes are
    neither behind the URL nor in the content store, and no amount of retrying
    the *cache* will produce them.
    """

    def usable(artifact, raw: dict) -> bool:
        if not fetch_bytes:
            return True
        if artifact.bytes_size > 0:
            return True
        return extract_first_url(raw) is None

    return usable


def _refuse_converter_configuration(content_store, fetch_bytes, asset_fetcher) -> None:
    """Reject ``artifact_converter=`` combined with built-in-converter knobs.

    ``content_store`` / ``fetch_bytes`` / ``asset_fetcher`` configure the
    built-in converter and are structurally unreachable from a custom one.
    Accepting them silently is worse than useless: a caller pointing falaw at a
    shared S3 content store *and* supplying a converter would get an empty
    store and no indication why.
    """
    supplied = [
        name
        for name, value in (
            ("content_store", content_store),
            ("fetch_bytes", fetch_bytes),
            ("asset_fetcher", asset_fetcher),
        )
        if value is not None
    ]
    if supplied:
        raise ValueError(
            f"execute(artifact_converter=...) cannot be combined with "
            f"{', '.join(supplied)} — those configure the built-in converter "
            "and a custom converter cannot honour them. Configure your "
            "converter directly (see falaw.plan._artifact_from_response for "
            "the built-in one), or drop artifact_converter."
        )


_PLACEHOLDER_PREFIX = "<from "

CONTENT_REF_PREFIX = "sha256:"
"""Prefix marking a content hash where a cache key would otherwise hold a URL.

Self-describing on purpose: a reader of a cache manifest can tell at a glance
that an argument was keyed on *what the upstream produced* rather than *where
it was served from*, and the prefixed form can never be confused with a
literal URL argument.
"""


def _wire_ref(artifact, idx: int, placeholder: str) -> str:
    """What a ``<from N>`` reference becomes **on the wire** — the upstream URL."""
    if not artifact.url:
        raise ValueError(
            f"Placeholder {placeholder!r} references artifact[{idx}] but it has no URL."
        )
    return artifact.url


def _key_ref(artifact, idx: int, placeholder: str) -> str:
    """What a ``<from N>`` reference becomes **in the cache key**.

    The upstream's content hash (``sha256:<hex>``) whenever its bytes were
    materialized — that is what makes a byte-identical upstream regeneration
    hit downstream. ``bytes_size > 0`` is the signal that ``asset_id`` really
    is the SHA-256 of those bytes; it holds for falaw's own converter and is
    the contract a custom ``artifact_converter`` must honour.

    With no bytes there is no content identity, so we fall back to the URL:
    sound but unreusable (a fresh URL each upload ⇒ a guaranteed miss), which
    is strictly better than inventing an id that could produce a *wrong* hit.
    """
    if artifact.bytes_size > 0:
        return f"{CONTENT_REF_PREFIX}{artifact.asset_id}"
    if artifact.url:
        return artifact.url
    raise ValueError(
        f"Placeholder {placeholder!r} references artifact[{idx}] but it has "
        "neither materialized bytes nor a URL."
    )


def plan_dependencies(plan: Plan) -> tuple[frozenset[int], ...]:
    """Per-call set of the call indices it references via ``"<from N>"``.

    The Plan's dependency DAG, read straight off the placeholders — one
    ``frozenset`` per call, in plan order, so ``deps[3] == {1}`` means call 3
    consumes call 1's output. An empty set means the call is **independent** and
    may run concurrently with any other independent call, which is what
    :func:`execute_isolated` schedules on.

    Also the plan's structural validator, and it runs **before a cent is
    spent**: a malformed reference used to surface only when execution reached
    the offending call, i.e. after every call before it had been billed.

    Raises:
        ValueError: a placeholder that is not ``"<from N>"`` for an integer
            ``N``; an ``N`` outside the plan; or an ``N`` that does not run
            *before* the referencing call (including a self-reference) — the
            output would not exist yet, so it can only ever be a bug.

    >>> a = CallPlan(tool="t", application="m", arguments={}, output_kind="image")
    >>> b = CallPlan(tool="t", application="m",
    ...              arguments={"image_url": "<from 0>"}, output_kind="video")
    >>> plan_dependencies(Plan(calls=(a, b)))
    (frozenset(), frozenset({0}))
    >>> plan_dependencies(Plan(calls=(b,)))
    Traceback (most recent call last):
        ...
    ValueError: Placeholder '<from 0>' in call 0 references call 0, which does not run before it. ...
    """
    total = len(plan.calls)
    dependencies: list[frozenset[int]] = []
    for position, call in enumerate(plan.calls):
        referenced: set[int] = set()
        for placeholder in _iter_placeholders(call.arguments):
            index = _parse_placeholder_index(placeholder)
            if index < 0 or index >= total:
                raise ValueError(
                    f"Placeholder {placeholder!r} in call {position} references "
                    f"artifact index {index}, but the plan has only {total} call(s)."
                )
            if index >= position:
                reachable = (
                    "it is the first call, so it can reference nothing"
                    if position == 0
                    else f"it may only reference calls 0..{position - 1}"
                )
                raise ValueError(
                    f"Placeholder {placeholder!r} in call {position} references "
                    f"call {index}, which does not run before it. A '<from N>' "
                    f"placeholder consumes an earlier call's output — {reachable}."
                )
            referenced.add(index)
        dependencies.append(frozenset(referenced))
    return tuple(dependencies)


def _iter_placeholders(value) -> Iterator[str]:
    """Yield every ``"<from ...>"`` string anywhere inside ``value``."""
    if isinstance(value, str):
        if value.startswith(_PLACEHOLDER_PREFIX):
            yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_placeholders(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_placeholders(item)


def _parse_placeholder_index(placeholder: str) -> int:
    """``"<from 3>"`` -> ``3``. Raises ``ValueError`` on anything else."""
    body = placeholder[len(_PLACEHOLDER_PREFIX) :].rstrip(">").strip()
    try:
        return int(body)
    except ValueError as e:
        raise ValueError(
            f"Bad placeholder {placeholder!r} — expected '<from N>' where N is an integer."
        ) from e


def _resolve_placeholders(arguments: dict, artifacts: list, *, ref) -> dict:
    """Rewrite ``<from N>`` strings in ``arguments`` via ``ref(artifact, idx, ph)``.

    Only string values are rewritten; nested dicts/lists/tuples are recursed
    into. ``arguments`` is not modified — a new dict is returned when any
    rewrite happens, otherwise the original object is returned (identity that
    :func:`execute` uses to detect "wire and key arguments are the same").
    """
    if not _has_placeholder(arguments):
        return arguments
    return _resolve(arguments, artifacts, ref)


def _has_placeholder(value) -> bool:
    if isinstance(value, str):
        return value.startswith(_PLACEHOLDER_PREFIX)
    if isinstance(value, dict):
        return any(_has_placeholder(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_placeholder(v) for v in value)
    return False


def _resolve(value, artifacts: list, ref):
    if isinstance(value, str) and value.startswith(_PLACEHOLDER_PREFIX):
        return _lookup_artifact_ref(value, artifacts, ref)
    if isinstance(value, dict):
        return {k: _resolve(v, artifacts, ref) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, artifacts, ref) for v in value]
    if isinstance(value, tuple):
        return tuple(_resolve(v, artifacts, ref) for v in value)
    return value


def _lookup_artifact_ref(placeholder: str, artifacts: list, ref) -> str:
    """Parse ``"<from N>"`` and return ``ref(artifacts[N], N, placeholder)``.

    ``artifacts`` is a slot list the length of the Plan, so a slot may be
    ``None`` — the call that fills it has not run, or did not succeed. That is
    an error here rather than an ``AttributeError`` three frames down.
    """
    idx = _parse_placeholder_index(placeholder)
    if idx < 0 or idx >= len(artifacts):
        raise ValueError(
            f"Placeholder {placeholder!r} references artifact index {idx}, "
            f"but only {len(artifacts)} artifact slot(s) exist."
        )
    if artifacts[idx] is None:
        raise ValueError(
            f"Placeholder {placeholder!r} references artifact index {idx}, "
            "which has not been produced."
        )
    return ref(artifacts[idx], idx, placeholder)


def _synthetic_artifact(call: CallPlan):
    """A placeholder Artifact for ``dry_run=True``. Not byte-stable across runs."""
    from lacing import Artifact, hash_bytes

    # Deterministic asset_id from the call's identity, so dry-run twice over
    # the same Plan yields the same Artifact.id pair (helpful for testing).
    from .canonical import canonical_blob, plan_identity_payload

    blob = canonical_blob(
        plan_identity_payload(
            call.application,
            call.arguments,
            tool=call.tool,
            backend=call.backend,
            key_extra=call.key_extra or None,
        )
    )
    synthetic_id = hash_bytes(blob)
    return Artifact(
        asset_id=synthetic_id,
        kind=call.output_kind,
        path=None,
        url=None,
        bytes_size=0,
        duration_s=None,
        mime=None,
        provenance=_dry_run_provenance(call),
        cost_usd=0.0,
        producer_call_id=f"dry-run:{synthetic_id[:12]}",
    )


def _dry_run_provenance(call: CallPlan):
    from lacing.artifact import _now_rt
    from lacing.model import Provenance

    return Provenance(
        was_generated_by=f"agent:falaw-plan@{call.application}",
        was_attributed_to="dry-run",
        was_derived_from=[],
        generated_at_time=_now_rt(),
        activity="infer",
    )


def _make_artifact_converter(
    *, content_store=None, fetch_bytes: bool = True, asset_fetcher=None
) -> ResultToArtifact:
    """Build the default raw-response → :class:`lacing.Artifact` converter.

    A factory rather than a plain function because the conversion needs three
    injected decisions — *which* content store the bytes land in, *how* they
    are read, and whether to read them at all — while :data:`ResultToArtifact`
    (the pluggable converter contract every caller may implement) stays a
    two-argument callable.
    """

    def convert(raw: dict, call: CallPlan):
        return _artifact_from_response(
            raw,
            call,
            content_store=content_store,
            fetch_bytes=fetch_bytes,
            asset_fetcher=asset_fetcher,
        )

    return convert


def _artifact_from_response(
    raw: dict,
    call: CallPlan,
    *,
    content_store=None,
    fetch_bytes: bool = True,
    asset_fetcher=None,
):
    """Convert a fal response to an Artifact using the common response shapes.

    Handles these patterns observed across fal models:

    - ``{"images": [{"url": ..., "content_type": ...}, ...]}`` — flux family
    - ``{"image": {"url": ..., "content_type": ...}}``        — some edits
    - ``{"video": {"url": ..., "content_type": ...}}``        — i2v / t2v / lipsync
    - ``{"audio": {"url": ..., "content_type": ...}}``        — TTS
    - ``{"audio_url": "..."}``                                — voice-clone
    - ``{"output": "..."}`` (string)                          — LLM endpoints

    The first matching pattern wins. For multi-asset responses (e.g. flux
    with ``num_images > 1``), only the first asset becomes an Artifact —
    callers wanting all assets should provide their own converter.

    Every Artifact is **content-addressed**: ``asset_id`` is the SHA-256 of the
    artifact's bytes, as ``lacing.Artifact`` contractually requires.

    - Media calls: the bytes are streamed once into ``content_store`` (see
      :mod:`falaw.content`), ``bytes_size`` is their real length, ``url`` is
      kept as a *hint*, and the artifact survives fal deleting the URL because
      the bytes are in the store. ``path`` is set when the store exposes a
      local file for the blob (the directory-backed default does; an in-memory
      or object-store one returns ``None`` — read those through
      ``ArtifactStore.iter_blob(asset_id)``). Re-converting the same response
      later is download-free (the ``url -> content hash`` index).
    - ``json`` / ``text`` calls with **no URL** — the ``fal-ai/any-llm`` case:
      the textual response is materialized to a content-addressed file in the
      falaw cache and ``Artifact.path`` points at it.

    Degraded (URL-only) artifacts
    -----------------------------
    Two cases produce an Artifact whose ``asset_id`` is a digest of the whole
    response rather than a content hash, with ``bytes_size == 0``: an explicit
    ``fetch_bytes=False``, and a fetch that failed (which also emits a
    :class:`UserWarning` — see :func:`execute` for why a *billed* result is
    degraded rather than discarded).

    The response digest is deliberately **not** the SHA-256 of the URL. Hashing
    the URL is the falaw#14 defect: it looks like a content hash, so it makes
    two byte-identical renders appear different while satisfying every check
    that only tests "is this 64 hex chars". ``bytes_size == 0`` is the honest
    signal, and it is what downstream key resolution reads to fall back to the
    URL rather than trust the id.

    Note that ``path``/``url`` are location *hints*, machine-local in the
    ``path`` case. Only ``asset_id`` + the content store are portable.
    """
    from lacing import Artifact
    from lacing.artifact import _now_rt
    from lacing.model import Provenance

    url = extract_first_url(raw)
    duration = _extract_duration_s(raw)
    mime = _extract_content_type(raw)
    path = None
    bytes_size = 0

    if url and fetch_bytes:
        ref, store = _content_ref_or_none(url, content_store, asset_fetcher)
        if ref is None:
            # A degraded, honestly-labelled artifact — never a lost paid result.
            asset_id = _response_digest(raw)
        else:
            asset_id = ref.content_hash
            bytes_size = ref.bytes_size
            path = store.blob_path(asset_id)
    elif url:
        # No bytes ⇒ no content identity. Digest the response rather than the
        # URL so nothing pretends to be a content hash; see the docstring.
        asset_id = _response_digest(raw)
    elif call.output_kind in ("json", "text"):
        # LLM-style response: no URL, the content *is* the text. Materialize
        # it to a content-addressed cache file so the Artifact is usable.
        content = _extract_text_content(raw)
        if call.output_kind == "json":
            # ``output_kind="json"`` promises a parseable JSON artifact,
            # but real models wrap it in a ```json fence anyway.
            content = _unwrap_json_fence(content)
        path, asset_id = _materialize_text_to_cache(content, call.output_kind)
        bytes_size = len(content.encode("utf-8"))
        mime = mime or (
            "application/json" if call.output_kind == "json" else "text/plain"
        )
    else:
        # Last-resort: hash the response itself.
        asset_id = _response_digest(raw)

    prov = Provenance(
        was_generated_by=f"agent:fal@{call.application}",
        was_attributed_to=call.metadata.get("attributed_to", "user:unknown"),
        was_derived_from=[],
        generated_at_time=_now_rt(),
        activity="create",
    )

    return Artifact(
        asset_id=asset_id,
        kind=call.output_kind,
        path=path,
        url=url,
        bytes_size=bytes_size,
        duration_s=duration,
        mime=mime,
        provenance=prov,
        # ``None`` = unknown. The executor overwrites this with the observed
        # outcome (see ``_stamp_observed_cost``); a direct conversion outside
        # ``execute`` has no run outcome, and honestly reports "unknown"
        # rather than the plan-time guess it used to carry (falaw#26).
        cost_usd=None,
        producer_call_id=None,  # set by orchestrators that thread through call_id
    )


def _response_digest(raw) -> str:
    """SHA-256 of the canonicalized response — a last-resort, non-content id.

    Used only where falaw has no bytes to hash. It is *not* a content hash and
    must never be treated as one: it changes whenever any field of the response
    changes (including a re-minted URL), which is exactly what makes it safe —
    it can only ever cause a cache *miss*, never a wrong hit.
    """
    import json as _json

    from lacing import hash_bytes

    return hash_bytes(_json.dumps(raw, sort_keys=True, default=str).encode("utf-8"))


def _unwrap_json_fence(text: str) -> str:
    """Strip a Markdown code fence an LLM wrapped a JSON response in.

    ``output_kind="json"`` promises the materialized artifact is a
    parseable JSON document, but real models routinely answer with
    ```` ```json … ``` ```` even when the prompt forbids it. Drop a
    leading ```` ``` ```` / ```` ```json ```` line and a trailing
    ```` ``` ```` line; a clean (non-fenced) body is returned unchanged
    apart from surrounding whitespace. This normalizes — it does not
    validate — so unparseable text passes through untouched.
    """
    s = text.strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()
    lines = lines[1:]  # drop the opening ``` / ```json line
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_text_content(raw) -> str:
    """Pull plain text out of an LLM response shape (any-llm / OpenAI-style).

    Mirrors the extraction in ``falaw.operations.llm``; kept here so the
    converter has no dependency on the operations layer.
    """
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        for key in ("output", "text", "response", "completion", "content"):
            v = raw.get(key)
            if isinstance(v, str) and v.strip():
                return v
        choices = raw.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            msg = choices[0].get("message")
            if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                return msg["content"]
    return str(raw)


def _materialize_text_to_cache(content: str, kind: str) -> tuple[str, str]:
    """Write ``content`` to a content-addressed file in the falaw cache.

    Returns ``(path, asset_id)`` where ``asset_id`` is the SHA-256 hex of the
    content bytes. Idempotent: the same content writes the same file.
    """
    import os

    from lacing import hash_bytes

    from .cache import ASSETS_DIRNAME, _cache_dir

    data = content.encode("utf-8")
    asset_id = hash_bytes(data)
    ext = ".json" if kind == "json" else ".txt"
    assets_dir = os.path.join(_cache_dir(), ASSETS_DIRNAME)
    os.makedirs(assets_dir, exist_ok=True)
    path = os.path.join(assets_dir, f"llm-{asset_id}{ext}")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    return path, asset_id


def _first_media(raw: dict, key: str) -> Any:
    """``raw[key]`` as one file: the entry itself, or the first of a list."""
    v = raw.get(key)
    if isinstance(v, list):
        return v[0] if v else None
    return v


def extract_first_url(raw: dict) -> Optional[str]:
    """Find the first asset URL in a fal response, regardless of shape.

    Public (no underscore) because it is now used from :mod:`falaw.prune` as
    well: deciding whether pruning a blob makes a cache entry unmaterializable
    is the *same* question this answers for ``execute``, and the two must not
    drift into two opinions about what a response's asset is.
    """
    if not isinstance(raw, dict):
        return None
    for key in ("images", "video", "audio", "image"):
        v = _first_media(raw, key)
        if isinstance(v, dict) and "url" in v:
            return v["url"]
        if isinstance(v, str):
            return v
    for key in ("audio_url", "video_url", "image_url"):
        if isinstance(raw.get(key), str):
            return raw[key]
    return None


def _extract_duration_s(raw: dict) -> Optional[float]:
    if not isinstance(raw, dict):
        return None
    for key in ("video", "audio"):
        v = _first_media(raw, key)
        if isinstance(v, dict):
            d = v.get("duration") or v.get("duration_s")
            if isinstance(d, (int, float)):
                return float(d)
    return None


def _extract_content_type(raw: dict) -> Optional[str]:
    if not isinstance(raw, dict):
        return None
    for key in ("video", "audio", "image"):
        v = _first_media(raw, key)
        if isinstance(v, dict) and isinstance(v.get("content_type"), str):
            return v["content_type"]
    images = raw.get("images")
    if isinstance(images, list) and images and isinstance(images[0], dict):
        return images[0].get("content_type")
    return None
