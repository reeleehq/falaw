"""Wrapper over `fal_client.subscribe` with progress events and auto-journaling.

Operations should call `call_fal` rather than `fal_client.subscribe` directly,
so we get one place to:

* publish structured progress events to subscribers (UI, telemetry),
* auto-journal failures (so the next agent learns from them),
* layer retries / backoff later without changing call sites.

See :mod:`falaw.events` for the event model. ``on_log`` (a
string-only callback) still works for backward compatibility — when
both ``on_log`` and ``on_event`` are given, both fire.
"""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Mapping, Optional

from ._credentials import current_credentials, resolve_credential, using_credentials
from .errors import import_fal_client as _import_fal_client
from .errors import translate as _translate_error
from .events import EventCallback, ProgressEvent, emit
from .journal import _default_journal


# --------------------------------------------------------------------------- #
# Per-context fal credential (bring-your-own-key support)
# --------------------------------------------------------------------------- #

#: The provider id a fal key is bound under, in the fleet's facade kit
#: (:func:`ocracy.kit.using_credentials`). The binding is a
#: :class:`contextvars.ContextVar` (rather than an ``os.environ`` mutation), so it is
#: scoped to the entering context, the asyncio tasks it spawns and work run in a copy
#: of it (``contextvars.copy_context().run``; a bare thread pool does not copy it):
#: concurrent requests are
#: unaffected and no process-wide lock is needed. Because the kit is shared, a server
#: that binds ``fal`` once reaches every facade that calls fal, not only falaw. This
#: is the seam reelee's HTTP server uses to forward a BYO key into server-side fal
#: calls (reelee#159) without threading a credential argument through every
#: intermediate signature (plan → execute → cached_call_fal → call_fal).
#: Where ``ocracy`` is not installed, :mod:`falaw._credentials` falls back to a local
#: binding with the same semantics (not shared with other facades) and warns once.
FAL_PROVIDER = "fal"

#: The env vars falaw itself reads for a fal key, in order (the pricing and account
#: probes). :func:`call_fal` reads none: it leaves the env lookup to the fal SDK.
FAL_KEY_ENVVARS = ("FAL_KEY", "FAL_API_KEY")


def current_fal_key() -> Optional[str]:
    """The fal API key bound for the current context, or ``None``.

    Resolution order callers should mirror: an explicit ``api_key`` argument
    to :func:`call_fal` wins over this context value, which in turn wins over
    the fal SDK's own ``FAL_KEY`` env-var lookup.
    """
    return current_credentials().get(FAL_PROVIDER)


@contextmanager
def using_fal_credentials(key: Optional[str]) -> Iterator[None]:
    """Bind ``key`` as the fal credential for every :func:`call_fal` in this context.

    Intended for server-side bring-your-own-key flows: wrap a unit of work
    that will make one or more fal calls, and they all authenticate with
    ``key`` instead of the server's ``FAL_KEY`` env var — without any
    intermediate function needing a credential parameter.

    A falsy ``key`` is a deliberate no-op (the context is left untouched), so
    a caller can pass an optional header value straight through without
    special-casing "no BYO key — fall back to the server/env key".

    Thread/async safe: this is ``ocracy.kit.using_credentials(fal=key)``, backed
    by a :class:`contextvars.ContextVar`, so the binding is visible only within
    the entering context (and asyncio tasks or copied contexts it spawns),
    never to concurrent
    requests.
    """
    with using_credentials({FAL_PROVIDER: key}):
        yield


def fal_client_for(api_key: Optional[str] = None) -> Any:
    """The object whose ``subscribe`` / ``upload_file`` falaw calls fal through.

    Credential order: explicit ``api_key`` > the key bound via
    :func:`using_fal_credentials` > the SDK's own ``FAL_KEY`` lookup. Only a
    *resolved* key routes through a dedicated ``fal_client.SyncClient`` (never
    written to a global or env var); otherwise the module itself is returned so
    the SDK's own resolution is preserved exactly.
    """
    # Lazy: `fal_client` is the optional `falaw[fal]` extra.
    fal_client = _import_fal_client()
    key = resolve_credential(FAL_PROVIDER, api_key=api_key, required=False)
    client_cls = getattr(fal_client, "SyncClient", None)
    return client_cls(key=key) if key and client_cls is not None else fal_client


def _check_against_catalogue(application: str, arguments: Mapping[str, Any]) -> None:
    """Refuse, before any network, arguments that break a limit the catalogue
    states for the model (:mod:`falaw.validation`)."""
    from .registry import get_model
    from .validation import check_call_arguments

    try:
        record = get_model(application)
    except KeyError:
        return
    check_call_arguments(record, arguments)


def call_fal(
    application: str,
    arguments: Mapping[str, Any],
    *,
    on_log: Optional[Callable[[str], None]] = None,
    on_event: Optional[EventCallback] = None,
    with_logs: bool = True,
    journal_errors: bool = True,
    api_key: Optional[str] = None,
) -> dict:
    """Call a fal model via fal_client.subscribe.

    Args:
        application: fal model id (e.g. ``"fal-ai/flux/dev"``).
        arguments: Input arguments. Keys depend on the model.
        on_log: Legacy log callback — receives raw log lines as strings.
            Defaults to no-op (use ``on_event`` for structured access).
        on_event: Per-call subscriber for :class:`ProgressEvent`s. Fires
            in addition to the global subscribers registered via
            :func:`falaw.events.subscribe`.
        with_logs: Pass through to fal_client; when True the model streams logs.
        journal_errors: When True, exceptions are recorded as journal issues
            before being re-raised. The journal entry includes the application
            id and arguments so future agents can recognize the same trap.
        api_key: Explicit fal key for this call. When ``None`` (default) the
            key bound via :func:`using_fal_credentials` is used; when that is
            also unset, the fal SDK's own ``FAL_KEY`` env-var lookup applies
            (the historical behaviour). A resolved key is used per-call via a
            dedicated ``fal_client.SyncClient`` — it is never written to a
            global or an env var.

    Returns:
        The raw response dict from the model.
    """
    _check_against_catalogue(application, arguments)  # refuse before any network
    from .terms import check_terms, current_terms_context

    check_terms(application, "fal", current_terms_context(), arguments=arguments)
    # Lazy: `fal_client` is the optional `falaw[fal]` extra, so importing falaw
    # (and planning, pricing, hashing, cache hits) must not need it.
    fal_client = _import_fal_client()

    # Resolve the per-call credential: explicit arg > context binding > SDK
    # default. Only when a key is resolved do we route through a dedicated
    # ``SyncClient`` — otherwise we call the module-level ``subscribe`` so the
    # SDK's own env/global resolution is preserved exactly as before.
    subscribe = fal_client_for(api_key).subscribe

    call_id = uuid.uuid4().hex[:12]
    started = time.time()

    def _ev(kind: str, *, message: str = "", pct: float | None = None) -> None:
        emit(
            ProgressEvent(
                kind=kind,  # type: ignore[arg-type]
                application=application,
                call_id=call_id,
                message=message,
                pct=pct,
                elapsed_s=time.time() - started,
            ),
            also=(on_event,) if on_event else (),
        )

    log = on_log if on_log is not None else (lambda _msg: None)

    def _on_queue_update(update):
        if isinstance(update, fal_client.InProgress):
            entries = update.logs or ()
            if not entries:
                _ev("progress")
                return
            for entry in entries:
                msg = entry.get("message") if isinstance(entry, dict) else None
                if msg:
                    log(msg)
                    _ev("log", message=msg)

    _ev("queued")
    try:
        result = subscribe(
            application,
            arguments=dict(arguments),
            with_logs=with_logs,
            on_queue_update=_on_queue_update,
        )
    except Exception as raw_exc:
        # Translate fal_client errors into typed falaw exceptions so callers
        # can catch FalAccountLocked / FalRateLimited / etc. specifically.
        exc = _translate_error(raw_exc, application=application)
        _ev("error", message=repr(exc))
        if journal_errors:
            _default_journal().append(
                kind="issue",
                text=f"call_fal({application!r}) failed: {exc!r}",
                tags=("call_fal", "error", type(exc).__name__),
                context={
                    "application": application,
                    "arguments": dict(arguments),
                    "duration_s": time.time() - started,
                    "status_code": getattr(exc, "status_code", None),
                },
            )
        raise exc from raw_exc
    _ev("done")
    return result
