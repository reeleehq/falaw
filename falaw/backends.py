"""Execution backend registry — where `CallPlan.backend` dispatches (falaw#15).

Until this module existed, "make the vendor call" meant one hardcoded path:
`falaw.core.call_fal`. That is a budget bypass waiting to happen — the
video_gen research programme's decisions of record (§3.2) put it plainly:
*"Do not write a ComfyUI Transform before this lands. A flavor without a
priceable Plan is a budget bypass."* A backend reachable only by overriding
`Transform.execute` wholesale returns `Plan(calls=())`, so
`Plan.total_cost_usd` reads $0.00 on a real spend and every downstream
consumer of `Plan` — the cache, the dry-run converter, the cost gate — never
sees the call happen.

The fix is the smallest one that closes that gap: `CallPlan` gains a
`backend: str` field (default :data:`falaw.canonical.DFLT_BACKEND`, i.e.
`"fal"`), and `execute_isolated` resolves it through this module's `backends`
registry instead of calling `call_fal` directly. Everything else about a
`CallPlan` — its cost estimate, its cache key, its artifact conversion —
stays exactly what it already is, because the executor's contract is
narrow: turn `(application, arguments)` into the vendor's *raw* response,
in the same shape :func:`falaw.core.call_fal` already returns. Converting
that raw response into a `lacing.Artifact` remains `execute`'s job, uniform
across backends.

Nothing above `falaw.Plan` may know a specific backend exists. A module that
imports a backend type, references a vendor node name, or assumes a
backend's execution semantics is an architecture bug regardless of whether
it works — this registry is the one seam allowed to know backends exist at
all.

Register a second backend with ``backends.register(name, executor)``, then
build ``CallPlan(..., backend=name)``. See
``docs/comfyui_integration_plan.md`` (video_gen research programme) for the
two-tier ruling this registry is the executor half of: a ``nw.Transform``
comfy *flavor* is the graph **template** and never opens a socket; a
`GraphExecutionBackend` registered here is the **executor**.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from xdol import Registry

from .canonical import DFLT_BACKEND

BackendExecutor = Callable[..., dict]
"""``executor(application, arguments, *, on_event=None) -> dict`` — the same
shape :func:`falaw.core.call_fal` returns: the vendor's raw response, ready
for the existing artifact converter. An executor's only job is *making the
call*; it must not attempt caching (the registry sits below the cache) or
artifact conversion (``execute`` owns that, uniformly across backends).
A run's metrics reach a plan's :class:`~falaw.CallOutcome` only when the
executor emits its ``done`` event through :func:`falaw.events.emit` on the
calling thread (as ``call_fal`` does); calling only the passed ``on_event``
is not heard by :func:`falaw.events.listening` (falaw#127)."""


def _fal_executor(
    application: str,
    arguments: Mapping[str, Any],
    *,
    on_event: Optional[Callable] = None,
) -> dict:
    """The only backend until a second one lands: today's ``call_fal`` path,
    unchanged in behaviour — this module adds a seam, not a rewrite."""
    from .core import call_fal

    return call_fal(application, dict(arguments), on_event=on_event)


backends: Registry = Registry(name="falaw.backends", on_conflict="error")
"""Public registry of execution backends, keyed by :attr:`CallPlan.backend`.
``on_conflict="error"`` so a misconfigured plugin fails loudly instead of
silently shadowing the built-in fal executor."""
backends.register(DFLT_BACKEND, _fal_executor)


def get_backend_executor(name: str) -> BackendExecutor:
    """Look up a backend executor by name; raises with the known names."""
    if name not in backends:
        known = sorted(backends.keys())
        raise KeyError(
            f"No falaw execution backend {name!r} is registered; known: "
            f"{known}. Register one with "
            "falaw.backends.backends.register(name, executor)."
        )
    return backends[name]
