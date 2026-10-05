"""Per-context fal credential threading — :func:`falaw.using_fal_credentials`.

A server-side bring-your-own-key flow needs every nested fal call to
authenticate with the caller's key without threading a credential through
every intermediate signature. :func:`falaw.using_fal_credentials` binds the
key to a :class:`contextvars.ContextVar`; :func:`falaw.call_fal` resolves it
(explicit arg > context > SDK default) and routes a resolved key through a
dedicated ``fal_client.SyncClient`` — never a global or env mutation.

These tests stub ``fal_client`` with a fake exposing both the module-level
``subscribe`` (the default path) and a ``SyncClient`` (the BYO path) so we can
assert *which* path a call took and *which* key it carried.
"""

from __future__ import annotations

import sys
import types

import pytest

from falaw import call_fal, current_fal_key, using_fal_credentials


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FALAW_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FALAW_CACHE_DIR", str(tmp_path / "cache"))
    from falaw.journal import _default_journal

    _default_journal.cache_clear()
    yield
    _default_journal.cache_clear()


def _install_fake_fal(monkeypatch, *, response=None):
    """Stub ``fal_client`` recording how each call was authenticated.

    ``calls`` accumulates ``(path, key)`` tuples — ``path`` is ``"module"``
    for the module-level ``subscribe`` (SDK env/global resolution) and
    ``"client"`` for a per-call ``SyncClient(key=...)``.
    """
    response = response or {"output": "ok"}
    calls: list[tuple[str, str | None]] = []

    def module_subscribe(application, *, arguments, with_logs, on_queue_update):
        calls.append(("module", None))
        return response

    class SyncClient:
        def __init__(self, key=None, default_timeout=120.0):
            self.key = key

        def subscribe(self, application, *, arguments, with_logs, on_queue_update):
            calls.append(("client", self.key))
            return response

    fake = types.SimpleNamespace(
        InProgress=type("InProgress", (), {"__init__": lambda self, logs: None}),
        subscribe=module_subscribe,
        SyncClient=SyncClient,
    )
    monkeypatch.setitem(sys.modules, "fal_client", fake)
    return calls


def test_no_context_uses_module_subscribe(monkeypatch):
    """With no bound key and no explicit arg, the module-level subscribe
    runs — preserving the SDK's own env/global key resolution."""
    calls = _install_fake_fal(monkeypatch)
    call_fal("fal-ai/flux/dev", {"prompt": "x"})
    assert calls == [("module", None)]


def test_context_key_routes_through_sync_client(monkeypatch):
    """A key bound via ``using_fal_credentials`` is used per-call via a
    dedicated ``SyncClient`` — the BYO path."""
    calls = _install_fake_fal(monkeypatch)
    with using_fal_credentials("byo-key-123"):
        assert current_fal_key() == "byo-key-123"
        call_fal("fal-ai/flux/dev", {"prompt": "x"})
    assert calls == [("client", "byo-key-123")]
    # The binding is scoped to the context — it does not leak out.
    assert current_fal_key() is None


def test_explicit_api_key_wins_over_context(monkeypatch):
    calls = _install_fake_fal(monkeypatch)
    with using_fal_credentials("context-key"):
        call_fal("fal-ai/flux/dev", {"prompt": "x"}, api_key="explicit-key")
    assert calls == [("client", "explicit-key")]


def test_falsy_key_is_a_noop(monkeypatch):
    """An empty/None key leaves the context untouched, so callers can pass an
    optional header value straight through."""
    calls = _install_fake_fal(monkeypatch)
    with using_fal_credentials(None):
        assert current_fal_key() is None
        call_fal("fal-ai/flux/dev", {"prompt": "x"})
    assert calls == [("module", None)]


def test_nested_contexts_restore_outer_key(monkeypatch):
    _install_fake_fal(monkeypatch)
    with using_fal_credentials("outer"):
        assert current_fal_key() == "outer"
        with using_fal_credentials("inner"):
            assert current_fal_key() == "inner"
        assert current_fal_key() == "outer"
    assert current_fal_key() is None


def test_pricing_key_resolution_honours_the_binding(monkeypatch):
    """The pricing probe resolves explicit > bound > FAL_KEY > FAL_API_KEY."""
    from falaw.pricing import _resolve_api_key

    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.setenv("FAL_API_KEY", "server-key")
    assert _resolve_api_key(None) == "server-key"
    with using_fal_credentials("byo"):
        assert _resolve_api_key(None) == "byo"
        assert _resolve_api_key("explicit") == "explicit"
    monkeypatch.delenv("FAL_API_KEY")
    with pytest.raises(RuntimeError, match="FAL_KEY"):
        _resolve_api_key(None)
