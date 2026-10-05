"""Tests for falaw.account — health_check probe + AccountStatus classification."""

from __future__ import annotations

from unittest.mock import MagicMock

from falaw.account import AccountStatus, _classify_response, health_check


def _response(status: int, json_body=None, text: str = ""):
    r = MagicMock()
    r.status_code = status
    r.text = text
    if json_body is not None:
        r.json.return_value = json_body
    else:
        r.json.side_effect = ValueError("no json")
    return r


def test_classify_2xx_is_ok():
    s = _classify_response(_response(200))
    assert s.ok is True
    assert not s.locked
    assert not s.unauthorized


def test_classify_403_with_lock_pattern_is_locked():
    s = _classify_response(_response(403, json_body={"detail": "Your account is locked"}))
    assert s.ok is False
    assert s.locked is True
    assert s.unauthorized is False
    assert s.url == "https://fal.ai/dashboard/billing"
    assert "locked" in s.detail.lower()


def test_classify_403_without_lock_pattern_is_generic_failure():
    s = _classify_response(_response(403, json_body={"detail": "forbidden"}))
    assert s.ok is False
    assert s.locked is False
    assert s.status_code == 403


def test_classify_401_is_unauthorized():
    s = _classify_response(_response(401, json_body={"detail": "invalid key"}))
    assert s.ok is False
    assert s.unauthorized is True
    assert s.locked is False


def test_classify_402_points_at_billing():
    s = _classify_response(_response(402, text="payment required"))
    assert s.ok is False
    assert s.url == "https://fal.ai/dashboard/billing"


def test_classify_500_is_generic_failure():
    s = _classify_response(_response(500, text="oops"))
    assert s.ok is False
    assert s.status_code == 500


def test_message_for_user_ok():
    s = AccountStatus(ok=True, locked=False, unauthorized=False, status_code=200,
                      detail="", url=None, error=None)
    assert "healthy" in s.message_for_user().lower()


def test_message_for_user_locked_includes_url():
    s = AccountStatus(ok=False, locked=True, unauthorized=False, status_code=403,
                      detail="account is locked", url="https://fal.ai/dashboard/billing",
                      error=None)
    msg = s.message_for_user()
    assert "locked" in msg.lower()
    assert "fal.ai/dashboard/billing" in msg


def test_message_for_user_unauthorized_mentions_FAL_KEY():
    s = AccountStatus(ok=False, locked=False, unauthorized=True, status_code=401,
                      detail="bad key", url=None, error=None)
    msg = s.message_for_user()
    assert "FAL_KEY" in msg


def test_health_check_no_api_key_returns_unauthorized(monkeypatch):
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.delenv("FAL_API_KEY", raising=False)
    s = health_check()
    assert not s.ok
    assert s.unauthorized
    assert "FAL_KEY" in s.detail


def test_health_check_with_explicit_key_overrides_env(monkeypatch):
    """When api_key is passed explicitly we don't hit the unauthorized-no-key branch."""
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.delenv("FAL_API_KEY", raising=False)

    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def post(self, *a, **k):
            r = MagicMock()
            r.status_code = 200
            r.headers = {}
            r.text = ""
            r.json.return_value = {}
            return r

    # health_check does `import httpx` inside; patching httpx.Client globally
    # is enough because that import binds to the same module object.
    import httpx
    monkeypatch.setattr(httpx, "Client", FakeClient)

    s = health_check(api_key="fake-key")
    assert s.ok is True


def test_health_check_uses_a_bound_byo_key(monkeypatch):
    """A key bound with using_fal_credentials reaches the probe (it used to be ignored)."""
    from falaw import using_fal_credentials

    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.delenv("FAL_API_KEY", raising=False)
    sent = []

    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def post(self, url, headers=None, **k):
            sent.append(headers["Authorization"])
            r = MagicMock()
            r.status_code = 200
            r.headers = {}
            r.text = ""
            r.json.return_value = {}
            return r

    import httpx
    monkeypatch.setattr(httpx, "Client", FakeClient)

    with using_fal_credentials("byo-key-123"):
        s = health_check()
    assert s.ok is True
    assert sent == ["Key byo-key-123"]


def test_health_check_classifies_403_lock(monkeypatch):
    """End-to-end: bad key → fake locked-403 → AccountStatus(locked=True)."""
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.delenv("FAL_API_KEY", raising=False)

    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def post(self, *a, **k):
            r = MagicMock()
            r.status_code = 403
            r.headers = {}
            r.text = ""
            r.json.return_value = {"detail": "Your account is locked. Please verify."}
            return r

    import httpx
    monkeypatch.setattr(httpx, "Client", FakeClient)

    s = health_check(api_key="fake-key")
    assert s.ok is False
    assert s.locked is True
    assert s.url == "https://fal.ai/dashboard/billing"
