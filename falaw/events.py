"""Structured progress events for fal calls.

Replaces the implicit "stream raw log strings to stdout" model with a
small, machine-readable event stream that orchestrators can subscribe
to (UI progress bars, cost telemetry, billing dashboards, etc.).

A ``ProgressEvent`` is emitted at every major lifecycle transition of
a single ``call_fal`` invocation:

- ``queued``      — call submitted to fal
- ``progress``    — fal pushed an InProgress update with no message body
- ``log``         — fal pushed an InProgress update with a log line
- ``done``        — call returned a result; ``metrics`` carries fal's ``Completed.metrics``
- ``error``       — call raised
- ``cache_hit``   — :func:`falaw.cached_call_fal` found a hit and skipped the network
- ``provider_queued`` — fal reported the call waiting in ITS line (``queue_position``)

``queued`` is falaw's own (the call was submitted). ``provider_phase`` is fal's word on
where the call is: ``"in_queue"`` on a ``provider_queued`` event, ``"in_progress"`` on the
``progress`` / ``log`` events fal's IN_PROGRESS updates produce. It is ``None`` on every
event fal said nothing about (a cache hit, ``queued``, ``done``), so a consumer that sees
no phase knows nothing, which is not the same as "in progress".

``metrics`` is fal's own account of the finished run, as its final ``Completed`` status
reported it (e.g. ``{"inference_time": 3.2}``, seconds the runner spent processing). It
rides the ``done`` event only, and stays out of the model's response so a cached response
is still exactly what the model returned. It is ``None`` when fal reported none, and on a
``cache_hit`` (nothing ran, nothing was billed). fal does not say whether
``inference_time`` is the billed quantity: a cost derived from it is an observed run time.

Subscribers can be registered globally via :func:`subscribe` or
per-call via the ``on_event=`` argument on :func:`call_fal` /
:func:`cached_call_fal`. The ``on_log`` parameter still works
(legacy: a string-only stream); see :func:`call_fal` for compatibility
notes.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal, Optional


EventKind = Literal[
    "queued", "progress", "log", "done", "error", "cache_hit", "provider_queued"
]
ProviderPhase = Literal["in_queue", "in_progress"]

EventCallback = Callable[["ProgressEvent"], None]


@dataclass(frozen=True, slots=True, kw_only=True)
class ProgressEvent:
    """One step in the lifecycle of a fal call.

    Attributes:
        kind: Lifecycle stage. See :data:`EventKind`.
        application: fal model id (e.g. ``"fal-ai/flux/dev"``).
        call_id: A short hex string that uniquely identifies the call.
            All events for one ``call_fal`` invocation share the same
            ``call_id``.
        message: Free-form text. For ``"log"`` events this is the log
            line; for ``"error"`` it's ``repr(exc)``; otherwise empty.
        pct: Optional progress percentage in [0.0, 100.0]. fal's
            current API doesn't surface this; included for forward
            compatibility.
        elapsed_s: Seconds since the call started.
        provider_phase: fal's reported phase (see the module docstring), or ``None``.
        queue_position: fal's ``queue_position`` on a ``"provider_queued"`` event
            (0 = next); ``None`` on every other event.
        metrics: fal's ``Completed.metrics`` on a ``"done"`` event, or ``None``
            (see the module docstring). A plain ``dict``, so the event stays
            serialisable (``dataclasses.asdict``, pickle, JSON); subscribers share
            it and must not edit it.
    """

    kind: EventKind
    application: str
    call_id: str
    message: str = ""
    pct: Optional[float] = None
    elapsed_s: float = 0.0
    provider_phase: Optional[ProviderPhase] = None
    queue_position: Optional[int] = None
    metrics: Optional[dict[str, Any]] = field(default=None, hash=False)


# --- subscriber registry ---------------------------------------------------

_subscribers: list[EventCallback] = []


def subscribe(callback: EventCallback) -> EventCallback:
    """Register ``callback`` to receive every emitted ProgressEvent.

    Returns the callback unchanged so it can be used as a decorator::

        @subscribe
        def log_to_file(ev: ProgressEvent) -> None:
            ...
    """
    if callback not in _subscribers:
        _subscribers.append(callback)
    return callback


def unsubscribe(callback: EventCallback) -> None:
    """Remove a previously :func:`subscribe`'d callback. No-op if absent."""
    try:
        _subscribers.remove(callback)
    except ValueError:
        pass


def clear_subscribers() -> None:
    """Drop all registered subscribers. Mostly for tests."""
    _subscribers.clear()


#: Callbacks bound to the current context (see :func:`listening`). A ContextVar, not
#: another global list: two jobs on two worker threads each hear only their own calls.
_AMBIENT: ContextVar[tuple[EventCallback, ...]] = ContextVar(
    "falaw_ambient_event_callbacks", default=()
)


@contextmanager
def listening(callback: Optional[EventCallback]) -> Iterator[None]:
    """Deliver every event emitted in this context to ``callback``, then stop.

    The scoped sibling of :func:`subscribe`: where ``subscribe`` hears every call in
    the process, ``listening`` hears only the calls made inside the ``with`` block (and
    the contexts copied from it, as :mod:`falaw.plan` does for its worker threads). It
    is how a host that runs one unit of work per thread, such as a job worker, gets
    that unit's events without threading ``on_event=`` through every layer between.
    ``None`` binds nothing, so a caller with no sink needs no ``if``.
    """
    if callback is None:
        yield
        return
    token = _AMBIENT.set(_AMBIENT.get() + (callback,))
    try:
        yield
    finally:
        _AMBIENT.reset(token)


def emit(event: ProgressEvent, *, also: Iterable[EventCallback] = ()) -> None:
    """Send ``event`` to every registered subscriber, the callbacks bound with
    :func:`listening`, and the ``also`` list.

    Subscriber exceptions are swallowed (with a printed warning) so a
    misbehaving UI hook can't bring the rendering pipeline down.
    """
    # One delivery per callback however many routes name it (subscribe, listening, on_event).
    for cb in dict.fromkeys([*_subscribers, *_AMBIENT.get(), *also]):
        try:
            cb(event)
        except Exception as exc:  # pragma: no cover — defensive
            import warnings

            warnings.warn(f"falaw progress subscriber {cb!r} raised: {exc!r}")
