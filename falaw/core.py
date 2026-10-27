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
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Mapping, Optional

from ._credentials import current_credentials, resolve_credential, using_credentials
from .errors import import_fal_client as _import_fal_client
from .errors import translate as _translate_error
from .degrade import emit_degradation
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


#: ``_FalStatusTranslator.last_position`` before any queue position was reported.
_NO_POSITION = object()


@dataclass(kw_only=True)
class _FalStatusTranslator:
    """Turns fal's queue statuses into falaw events, for one :func:`call_fal`.

    Passed to ``fal_client.subscribe`` as ``on_queue_update``. It runs inside
    subscribe, before the result is read, so it never raises: an exception here
    would lose a run fal may already have billed. What it learns from the final
    ``Completed`` status (``metrics``, ``provider_error``) is read back by
    :func:`call_fal` once subscribe returns or raises.
    """

    emit: Callable[..., None]  # call_fal's event emitter: ``emit(kind, **fields)``
    log: Callable[[str], None]  # the legacy ``on_log`` line callback
    application: str
    fal_client: Any  # for its status classes; test stubs may lack Queued / Completed
    last_position: Any = field(default=_NO_POSITION, init=False)
    metrics: dict = field(default_factory=dict, init=False)
    provider_error: dict = field(default_factory=dict, init=False)
    seen_logs: set = field(default_factory=set, init=False)

    def __call__(self, update: Any) -> None:
        queued_cls = getattr(self.fal_client, "Queued", None)
        completed_cls = getattr(self.fal_client, "Completed", None)
        if completed_cls is not None and isinstance(update, completed_cls):
            self._on_completed(update)
        elif queued_cls is not None and isinstance(update, queued_cls):
            self._on_queued(update)
        elif isinstance(update, self.fal_client.InProgress):
            self._on_in_progress(update)

    def _on_queued(self, update: Any) -> None:
        # fal re-reports the queue ~10x/s: say it on a change only.
        position = getattr(update, "position", None)
        if position != self.last_position:
            self.last_position = position
            self.emit(
                "provider_queued", provider_phase="in_queue", queue_position=position
            )

    def _on_in_progress(self, update: Any) -> None:
        # A runner failure sends the call back to IN_QUEUE (fal retries it): forget
        # the position, so the retry's wait is reported even at the same position.
        self.last_position = _NO_POSITION
        lines = self._new_log_lines(update)
        if not lines:
            # IN_PROGRESS is reported even when it carries no (new) log line.
            self.emit("progress", provider_phase="in_progress")
            return
        self._emit_log_lines(lines)

    def _on_completed(self, update: Any) -> None:
        reported = getattr(update, "metrics", None)
        if isinstance(reported, Mapping):
            self.metrics.update(reported)
        elif reported is not None:
            emit_degradation(
                f"fal reported non-mapping metrics for {self.application!r}: "
                f"{reported!r}; the done event carries none."
            )
        for name in ("error", "error_type"):
            value = getattr(update, name, None)
            if value:
                self.provider_error[name] = (
                    value if isinstance(value, str) else repr(value)
                )
        # The run's last lines arrive with COMPLETED; they were written while it ran.
        self._emit_log_lines(self._new_log_lines(update))

    def _new_log_lines(self, update: Any) -> list:
        """The messages in ``update.logs`` not reported yet.

        fal may re-send earlier lines with a later status (IN_PROGRESS polls, then
        COMPLETED). A line is known by its ``(timestamp, message)``, and only when
        the timestamp is a string: a line without one is always reported. An entry
        whose message is not a string is skipped.
        """
        logs = getattr(update, "logs", None)
        lines = []
        for entry in logs if isinstance(logs, (list, tuple)) else ():
            message = entry.get("message") if isinstance(entry, Mapping) else None
            if not isinstance(message, str) or not message:
                continue
            timestamp = entry.get("timestamp")
            if isinstance(timestamp, str):
                key = (timestamp, message)
                if key in self.seen_logs:
                    continue
                self.seen_logs.add(key)
            lines.append(message)
        return lines

    def _emit_log_lines(self, lines: list) -> None:
        for msg in lines:
            self.log(msg)
            self.emit("log", message=msg, provider_phase="in_progress")


def _describe_provider_error(provider_error: Mapping[str, str]) -> str:
    """fal's own ``Completed.error`` as ``"<error_type>: <error>"``."""
    return f"{provider_error.get('error_type') or 'error'}: {provider_error['error']}"


def _error_message(exc: BaseException, provider_error: Mapping[str, str]) -> str:
    """The ``error`` event's message: falaw's exception, plus fal's own error when
    it reported one the exception does not already say."""
    message = repr(exc)
    error = provider_error.get("error")
    if error and error not in message:
        message += f" (fal: {_describe_provider_error(provider_error)})"
    return message


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
        The raw response dict from the model. fal's run metrics (its final
        ``Completed`` status, e.g. ``inference_time``) are not in it: they ride
        the ``done`` event's ``metrics`` (see :mod:`falaw.events`).
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

    def _ev(
        kind: str,
        *,
        message: str = "",
        pct: float | None = None,
        provider_phase: str | None = None,
        queue_position: int | None = None,
        metrics: dict | None = None,
    ) -> None:
        emit(
            ProgressEvent(
                kind=kind,  # type: ignore[arg-type]
                application=application,
                call_id=call_id,
                message=message,
                pct=pct,
                elapsed_s=time.time() - started,
                provider_phase=provider_phase,  # type: ignore[arg-type]
                queue_position=queue_position,
                metrics=metrics,
            ),
            also=(on_event,) if on_event else (),
        )

    translator = _FalStatusTranslator(
        emit=_ev,
        log=on_log if on_log is not None else (lambda _msg: None),
        application=application,
        fal_client=fal_client,
    )

    _ev("queued")
    try:
        # NB: the queue updates must be delivered on THIS thread's context for
        # `events.listening` to hear them; fal's `client_timeout=` runs the polling
        # on its own executor, which does not copy the context. Not passed today.
        result = subscribe(
            application,
            arguments=dict(arguments),
            with_logs=with_logs,
            on_queue_update=translator,
        )
    except Exception as raw_exc:
        # Translate fal_client errors into typed falaw exceptions so callers
        # can catch FalAccountLocked / FalRateLimited / etc. specifically.
        exc = _translate_error(raw_exc, application=application)
        _ev(
            "error",
            message=_error_message(exc, translator.provider_error),
            metrics=translator.metrics or None,
        )
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
                    **{
                        f"provider_{k}": v for k, v in translator.provider_error.items()
                    },
                },
            )
        raise exc from raw_exc
    if translator.provider_error.get("error"):
        # fal said the run failed, yet handed back a result: keep it (it is billed),
        # and say so rather than raising over a result the caller can still use.
        emit_degradation(
            f"fal reported an error for {application!r} "
            f"({_describe_provider_error(translator.provider_error)}) but returned "
            "a result; falaw kept it."
        )
    _ev("done", metrics=translator.metrics or None)
    return result
