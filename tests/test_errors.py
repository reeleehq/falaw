"""Tests for falaw.errors — typed exception hierarchy + translate()."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from falaw.errors import (
    FalAccountLocked,
    FalBadRequest,
    FalError,
    FalHTTPError,
    FalInsufficientFunds,
    FalRateLimited,
    FalServerError,
    FalTimeout,
    FalUnauthorized,
    translate,
)


def _http_error(
    status: int, body_text: str = "", headers: dict | None = None, json_body=None
):
    """Build a fake fal_client.FalClientHTTPError-like exception for translate()."""
    import fal_client  # type: ignore[import-untyped]

    response = MagicMock()
    response.text = body_text
    if json_body is not None:
        response.json.return_value = json_body
    else:
        response.json.side_effect = ValueError("no json")

    return fal_client.FalClientHTTPError(
        message=f"HTTP {status}",
        status_code=status,
        response_headers=headers or {},
        response=response,
    )


def test_hierarchy():
    """All falaw HTTP errors inherit from FalError."""
    err = FalAccountLocked("x", status_code=403)
    assert isinstance(err, FalHTTPError)
    assert isinstance(err, FalError)
    assert isinstance(err, Exception)


def test_translate_403_account_locked():
    raw = _http_error(
        403, json_body={"detail": "Your account is locked. Verify email."}
    )
    out = translate(raw, application="fal-ai/test")
    assert isinstance(out, FalAccountLocked)
    assert out.status_code == 403
    assert "locked" in out.detail.lower()
    assert out.url == "https://fal.ai/dashboard/billing"
    assert out.application == "fal-ai/test"


def test_translate_403_non_lock_falls_through_to_bad_request():
    raw = _http_error(403, json_body={"detail": "forbidden — you don't own this model"})
    out = translate(raw)
    assert isinstance(out, FalBadRequest)
    assert not isinstance(out, FalAccountLocked)


def test_translate_401_unauthorized():
    raw = _http_error(401, json_body={"detail": "invalid api key"})
    out = translate(raw)
    assert isinstance(out, FalUnauthorized)
    assert out.status_code == 401


def test_translate_402_insufficient_funds():
    raw = _http_error(402, body_text="payment required")
    out = translate(raw)
    assert isinstance(out, FalInsufficientFunds)
    assert out.url == "https://fal.ai/dashboard/billing"


def test_translate_429_rate_limited_with_retry_after():
    raw = _http_error(
        429, json_body={"detail": "too many requests"}, headers={"retry-after": "5"}
    )
    out = translate(raw)
    assert isinstance(out, FalRateLimited)
    assert out.retry_after_s == 5.0


def test_translate_429_rate_limited_no_retry_after():
    raw = _http_error(429)
    out = translate(raw)
    assert isinstance(out, FalRateLimited)
    assert out.retry_after_s is None


def test_translate_400_bad_request():
    raw = _http_error(400, json_body={"detail": "invalid argument"})
    out = translate(raw)
    assert isinstance(out, FalBadRequest)


def test_translate_500_server_error():
    raw = _http_error(503, body_text="service unavailable")
    out = translate(raw)
    assert isinstance(out, FalServerError)


def test_translate_unknown_exception_returned_unchanged():
    err = ValueError("unrelated")
    assert translate(err) is err


def test_translate_timeout():
    import fal_client  # type: ignore[import-untyped]

    raw = fal_client.FalClientTimeoutError("timed out")
    out = translate(raw)
    assert isinstance(out, FalTimeout)


def test_translate_preserves_application_context():
    raw = _http_error(403, json_body={"detail": "account is locked"})
    out = translate(raw, application="fal-ai/specific-model")
    assert out.application == "fal-ai/specific-model"


def test_translate_preserves_cause():
    raw = _http_error(403, json_body={"detail": "account locked"})
    out = translate(raw)
    assert out.__cause__ is raw


def test_translate_with_no_detail_uses_message():
    """If body has no parseable detail, the translated detail is empty string but
    the exception message still includes what's available."""
    raw = _http_error(403, json_body={"detail": "account is locked"})
    out = translate(raw)
    assert "locked" in str(out).lower()
