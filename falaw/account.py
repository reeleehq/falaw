"""Account health probe.

``fal_client`` swallows the JSON body of its 403s, so a locked-account error
looks identical to "wrong API key" or "model is busy." :func:`health_check`
makes a tiny, idempotent request to the fal storage endpoint and returns a
typed :class:`AccountStatus` so the caller can distinguish:

- account is locked / unverified  → :attr:`AccountStatus.locked` is True
- bad credentials                 → :attr:`AccountStatus.unauthorized` is True
- everything looks fine            → :attr:`AccountStatus.ok` is True
- network / unknown error          → all flags False, ``error`` populated

Use this *before* a long render to fail fast with a useful message:

.. code-block:: python

    from falaw.account import health_check
    status = health_check()
    if not status.ok:
        raise SystemExit(status.message_for_user())
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import _LOCK_PATTERNS


_DEFAULT_PROBE_URL = "https://rest.fal.ai/storage/auth/token?storage_type=fal-cdn-v3"
"""Endpoint used by fal_client for upload tokens (storage_type=fal-cdn-v3 as
of fal-client 2025; the older 'fal-cdn' value rejects healthy accounts).
Small, idempotent, requires auth, and reflects account health (returns 403
on lock, 401 on bad key)."""


@dataclass(frozen=True)
class AccountStatus:
    """Outcome of :func:`health_check`."""

    ok: bool
    """True iff the account responded without an auth/lock error."""

    locked: bool
    """True iff the response indicated a locked / unverified account."""

    unauthorized: bool
    """True iff credentials are missing or invalid."""

    status_code: int | None
    """HTTP status from the probe (None if no HTTP exchange happened)."""

    detail: str
    """Server-supplied detail string (best-effort), or '' if unavailable."""

    url: str | None
    """If actionable (e.g. billing dashboard), URL the user should visit."""

    error: str | None
    """``repr`` of the underlying exception when ``ok`` is False
    and the failure isn't a recognized lock/unauth (e.g. network error)."""

    def message_for_user(self) -> str:
        """Single human-readable line explaining the status. Stable for logging."""
        if self.ok:
            return "fal account is healthy."
        if self.locked:
            base = "fal account is locked / unverified."
            if self.detail:
                base += f" Detail: {self.detail}"
            if self.url:
                base += f" Visit {self.url} to resolve."
            return base
        if self.unauthorized:
            return (
                "fal credentials are missing or invalid. "
                "Set FAL_KEY env var (or fal_client.api_key) and try again."
            )
        if self.status_code is not None:
            return f"fal probe returned HTTP {self.status_code}: {self.detail or '(no detail)'}"
        if self.error:
            return f"fal probe failed: {self.error}"
        return "fal probe failed for an unknown reason."


def health_check(
    *,
    probe_url: str = _DEFAULT_PROBE_URL,
    timeout_s: float = 10.0,
    api_key: str | None = None,
) -> AccountStatus:
    """Probe the fal storage endpoint and return a typed :class:`AccountStatus`.

    Args:
        probe_url: Endpoint to probe. Default is the storage-auth-token endpoint
            ``fal_client`` uses internally; small, idempotent, requires auth.
        timeout_s: Network timeout.
        api_key: Optional override of ``FAL_KEY``. Falls back to a key bound with
            :func:`falaw.using_fal_credentials`, then the env var.

    Returns:
        :class:`AccountStatus` with ``ok=True`` when the probe succeeded.
    """
    from ocracy.kit import resolve_credential

    from .core import FAL_KEY_ENVVARS, FAL_PROVIDER

    key = resolve_credential(
        FAL_PROVIDER, api_key=api_key, env_var=FAL_KEY_ENVVARS, required=False
    )
    if not key:
        return AccountStatus(
            ok=False,
            locked=False,
            unauthorized=True,
            status_code=None,
            detail="FAL_KEY environment variable is not set.",
            url=None,
            error=None,
        )

    try:
        import httpx  # type: ignore[import-untyped]
    except ImportError:
        return AccountStatus(
            ok=False,
            locked=False,
            unauthorized=False,
            status_code=None,
            detail="httpx is not installed; cannot probe.",
            url=None,
            error="ImportError: httpx",
        )

    try:
        with httpx.Client(timeout=timeout_s) as client:
            r = client.post(
                probe_url,
                headers={"Authorization": f"Key {key}"},
                json={"file_name": "probe.txt", "content_type": "text/plain"},
            )
    except Exception as exc:
        return AccountStatus(
            ok=False,
            locked=False,
            unauthorized=False,
            status_code=None,
            detail="",
            url=None,
            error=repr(exc),
        )

    return _classify_response(r)


def _classify_response(response) -> AccountStatus:
    """Classify a probe HTTP response into an :class:`AccountStatus`.

    Separated out so tests can drive it with mock responses without standing
    up an HTTP server.
    """
    status = response.status_code

    if 200 <= status < 300:
        return AccountStatus(
            ok=True,
            locked=False,
            unauthorized=False,
            status_code=status,
            detail="",
            url=None,
            error=None,
        )

    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            for key in ("detail", "message", "error"):
                value = body.get(key)
                if isinstance(value, str):
                    detail = value
                    break
    except Exception:
        try:
            detail = response.text or ""
        except Exception:
            detail = ""

    detail_lower = detail.lower()

    if status == 403 and any(p in detail_lower for p in _LOCK_PATTERNS):
        return AccountStatus(
            ok=False,
            locked=True,
            unauthorized=False,
            status_code=status,
            detail=detail,
            url="https://fal.ai/dashboard/billing",
            error=None,
        )
    if status == 401:
        return AccountStatus(
            ok=False,
            locked=False,
            unauthorized=True,
            status_code=status,
            detail=detail,
            url=None,
            error=None,
        )
    return AccountStatus(
        ok=False,
        locked=False,
        unauthorized=False,
        status_code=status,
        detail=detail,
        url="https://fal.ai/dashboard/billing" if status == 402 else None,
        error=None,
    )
