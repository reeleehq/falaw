"""falaw's one import point for the fleet's shared credential chain (``ocracy.kit``).

``ocracy`` is a declared dependency, and when it is installed this module simply
re-exports :func:`ocracy.kit.using_credentials`, :func:`ocracy.kit.current_credentials`
and :func:`ocracy.kit.resolve_credential`, so a fal key bound by any facade is seen by
falaw and vice versa.

Some environments update falaw without resolving its dependencies (an editable
checkout that is ``git pull``-ed, a wheel installed with ``pip install --no-deps``).
There, a module-level ``import ocracy`` would make ``import falaw`` fail outright, so
this module falls back to a minimal stdlib chain with the same semantics for the
three calls falaw makes (explicit -> bound -> env), and warns once that the shared
binding is not active. The fallback is deliberately small: it is a bridge until every
environment has ``ocracy``, not a second implementation to grow.
"""

from __future__ import annotations

import contextlib
import os
import warnings
from contextvars import ContextVar
from typing import Callable, Iterator, Mapping, Optional, Sequence, Union

try:
    from ocracy.kit import current_credentials, resolve_credential, using_credentials

    SHARED_KIT = True
except ImportError:  # ocracy missing: an env installed without falaw's dependencies
    SHARED_KIT = False

    warnings.warn(
        "falaw: the 'ocracy' package (a declared dependency) is not installed, so "
        "fal keys bound with falaw.using_fal_credentials are not shared with other "
        "facades. falaw itself works; install ocracy>=0.1.12 to share the binding.",
        RuntimeWarning,
        stacklevel=2,
    )

    _BOUND: "ContextVar[Optional[Mapping[str, str]]]" = ContextVar(
        "falaw_bound_credentials", default=None
    )

    def current_credentials() -> dict:
        """The provider keys bound in this context (a copy)."""
        return dict(_BOUND.get() or {})

    @contextlib.contextmanager
    def using_credentials(
        keys: Optional[Mapping[str, Optional[str]]] = None,
        /,
        **provider_keys: Optional[str],
    ) -> Iterator[dict]:
        """Bind provider keys for the block, overlaying any outer binding; falsy
        values are ignored."""
        merged = current_credentials()
        merged.update(
            {k: v for k, v in {**dict(keys or {}), **provider_keys}.items() if v}
        )
        token = _BOUND.set(merged)
        try:
            yield dict(merged)
        finally:
            _BOUND.reset(token)

    def resolve_credential(
        provider: Optional[str] = None,
        *,
        api_key: Optional[str] = None,
        env_var: Union[str, Sequence[str], None] = None,
        required: bool = True,
        error: Callable[[str], BaseException] = RuntimeError,
        hint: str = "",
    ) -> Optional[str]:
        """Explicit -> bound -> env; raise ``error`` (or return ``None``) on a miss."""
        if api_key:
            return api_key
        bound = current_credentials().get(provider) if provider else None
        if bound:
            return bound
        names = [env_var] if isinstance(env_var, str) else list(env_var or ())
        value = next((os.environ[n] for n in names if os.environ.get(n)), None)
        if value or not required:
            return value
        tried = f" (set one of: {', '.join(names)})" if names else ""
        raise error(
            f"No credential found for {provider or 'backend'}{tried}. {hint}".rstrip()
        )


__all__ = [
    "SHARED_KIT",
    "current_credentials",
    "resolve_credential",
    "using_credentials",
]
