# falaw.errors

Typed exceptions for falaw operations.

The bare `fal_client` exposes `FalClientError`, `FalClientHTTPError`, and
`FalClientTimeoutError`. These are correct but coarse — every 403, 429,
402, and timeout looks the same to a caller. This module wraps fal_client
errors in a more specific hierarchy so:

- An agent can catch [`FalAccountLocked`](#falaw.errors.FalAccountLocked) and surface a “go fix billing”
  message instead of debugging a generic 403.
- A retry layer can catch [`FalRateLimited`](#falaw.errors.FalRateLimited) and back off, but let
  [`FalAccountLocked`](#falaw.errors.FalAccountLocked) propagate (no amount of retry will fix it).
- Scripts can catch [`FalDurationOutOfRange`](#falaw.errors.FalDurationOutOfRange) to fall back to splitting
  a shot, instead of silently truncating to whatever the model produced.

Use [`translate()`](#falaw.errors.translate) to convert a fal_client exception to the appropriate
typed subclass — [`falaw.core.call_fal()`](falaw.core.html.md#falaw.core.call_fal) does this automatically.

### Examples

```pycon
>>> err = FalAccountLocked(
...     "account locked",
...     status_code=403,
...     detail="Verify your email at fal.ai/settings",
...     url="https://fal.ai/dashboard/billing",
... )
>>> err.url
'https://fal.ai/dashboard/billing'
>>> isinstance(err, FalError)
True
```

### Functions

| [`import_fal_client`](#falaw.errors.import_fal_client)()               | Import and return `fal_client`, or raise [`FalClientNotInstalled`](#falaw.errors.FalClientNotInstalled).                      |
|------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------|
| [`import_httpx`](#falaw.errors.import_httpx)([what])              | Import and return `httpx` (part of the `fal` extra), or raise [`FalClientNotInstalled`](#falaw.errors.FalClientNotInstalled). |
| [`translate`](#falaw.errors.translate)(exc, \*[, application]) | Convert an underlying fal_client / network exception to a typed falaw exception.                                                      |

### Exceptions

| [`FalAccountLocked`](#falaw.errors.FalAccountLocked)(message, \*, status_code[, ...])   | fal account is locked / suspended / awaiting verification.                   |
|------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| [`FalAssetFetchError`](#falaw.errors.FalAssetFetchError)(message, \*, url[, cause])       | The bytes behind a fal-served asset URL could not be retrieved.              |
| [`FalBadRequest`](#falaw.errors.FalBadRequest)(message, \*, status_code[, ...])      | Server rejected the request payload — typical 400 / 422.                     |
| [`FalClientNotInstalled`](#falaw.errors.FalClientNotInstalled)([what, missing])              | A real network call was attempted but the fal.ai client is not installed.    |
| [`FalDurationOutOfRange`](#falaw.errors.FalDurationOutOfRange)(message, \*, model_id, ...)   | The requested duration is outside what the model can produce.                |
| [`FalError`](#falaw.errors.FalError)                                            | Base for all falaw-raised exceptions.                                        |
| [`FalHTTPError`](#falaw.errors.FalHTTPError)(message, \*, status_code[, ...])       | Wraps an HTTP error from fal.ai with the original status, body, and headers. |
| [`FalInsufficientFunds`](#falaw.errors.FalInsufficientFunds)(message, \*, status_code)      | Account balance is insufficient — typical 402.                               |
| [`FalModelHung`](#falaw.errors.FalModelHung)(message, \*, model_id, elapsed_s)      | A model was queued but never returned — distinct from a network timeout.     |
| [`FalNonCanonicalArgument`](#falaw.errors.FalNonCanonicalArgument)(message, \*, path)          | An argument cannot be canonicalised into falaw's hashed JSON form.           |
| [`FalPromptTooLong`](#falaw.errors.FalPromptTooLong)(message, \*, model, limit, ...)    | The prompt exceeds the model's hard length cap (falaw#76).                   |
| [`FalRateLimited`](#falaw.errors.FalRateLimited)(message, \*[, retry_after_s])        | fal is throttling requests — typical 429.                                    |
| [`FalServerError`](#falaw.errors.FalServerError)(message, \*, status_code[, ...])     | fal-side server error — typical 5xx.                                         |
| [`FalTermsViolation`](#falaw.errors.FalTermsViolation)(message, \*, model_id, ...)       | The model's terms of service forbid (or leave unknown) this use.             |
| [`FalTimeout`](#falaw.errors.FalTimeout)(message, \*, elapsed_s[, application])   | The fal call timed out before producing a result.                            |
| [`FalUnauthorized`](#falaw.errors.FalUnauthorized)(message, \*, status_code[, ...])    | Missing or invalid API credentials — typical 401.                            |

### *exception* falaw.errors.FalAccountLocked(message, , status_code, detail='', body=None, headers=None, application=None, url=None, cause=None)

Bases: [`FalHTTPError`](#falaw.errors.FalHTTPError)

fal account is locked / suspended / awaiting verification.

Typical 403 with a body indicating the account is not in good standing.
No amount of retrying or model-switching will fix this — the user has
to act (verify email, top up billing, contact support).

### *exception* falaw.errors.FalAssetFetchError(message, , url, cause=None)

Bases: [`FalError`](#falaw.errors.FalError)

The bytes behind a fal-served asset URL could not be retrieved.

Raised by [`falaw.content`](falaw.content.html.md#module-falaw.content) when content-addressing an artifact fails —
the URL 404s (fal deletes expired files permanently), the transfer errors,
or the response is empty. It is deliberately **loud**: returning an
Artifact whose `asset_id` is not the SHA-256 of any bytes would break
`lacing.Artifact`’s content-hash contract and poison every downstream
cache key derived from it.

### *exception* falaw.errors.FalBadRequest(message, , status_code, detail='', body=None, headers=None, application=None, url=None, cause=None)

Bases: [`FalHTTPError`](#falaw.errors.FalHTTPError)

Server rejected the request payload — typical 400 / 422.

### *exception* falaw.errors.FalClientNotInstalled(what='calling fal.ai', , missing='fal_client')

Bases: [`FalError`](#falaw.errors.FalError), [`ImportError`](https://docs.python.org/3/builtins/exceptions.html#ImportError)

A real network call was attempted but the fal.ai client is not installed.

`pip install falaw` carries no fal.ai client, so that callers that only
build, price, hash and cache plans install none. Anything that actually
reaches fal.ai needs the `fal` extra: `pip install 'falaw[fal]'`.
It is an [`ImportError`](https://docs.python.org/3/builtins/exceptions.html#ImportError), so `except ImportError` still matches.

### *exception* falaw.errors.FalDurationOutOfRange(message, , model_id, requested, valid_range)

Bases: [`FalError`](#falaw.errors.FalError)

The requested duration is outside what the model can produce.

Raised by Plan/Execute when the caller asks for `duration_s` that the
model’s declared `expected_duration_range` cannot satisfy. Callers can
catch this to split the shot, repeat it, or pick a different model.

### *exception* falaw.errors.FalError

Bases: [`Exception`](https://docs.python.org/3/builtins/exceptions.html#Exception)

Base for all falaw-raised exceptions.

### *exception* falaw.errors.FalHTTPError(message, , status_code, detail='', body=None, headers=None, application=None, url=None, cause=None)

Bases: [`FalError`](#falaw.errors.FalError)

Wraps an HTTP error from fal.ai with the original status, body, and headers.

Subclasses pick out specific status codes / patterns. Use this base when
you want to catch any HTTP failure (e.g. for retry).

### *exception* falaw.errors.FalInsufficientFunds(message, , status_code, detail='', body=None, headers=None, application=None, url=None, cause=None)

Bases: [`FalHTTPError`](#falaw.errors.FalHTTPError)

Account balance is insufficient — typical 402.

### *exception* falaw.errors.FalModelHung(message, , model_id, elapsed_s)

Bases: [`FalError`](#falaw.errors.FalError)

A model was queued but never returned — distinct from a network timeout.

Raised by higher-level orchestration that sets a per-call wall-clock
budget (e.g. “give up on this lipsync after 5 minutes and pick another model”).

### *exception* falaw.errors.FalNonCanonicalArgument(message, , path)

Bases: [`FalError`](#falaw.errors.FalError)

An argument cannot be canonicalised into falaw’s hashed JSON form.

Raised by [`falaw.canonical`](falaw.canonical.html.md#module-falaw.canonical) when a value reaches a key-composition
site (the per-call cache key, `plan_hash`, the dry-run artifact id) that
JSON cannot represent faithfully: a non-JSON object, a non-finite float,
or a non-string mapping key. Deliberately **loud**: the old behaviour —
`json.dumps(..., default=str)` — silently collided structurally
different calls into one cache key, handing back the *wrong artifact* as
a supposed saving (falaw#17).

`path` names the offending node, e.g. `arguments.extra.ref`.

### *exception* falaw.errors.FalPromptTooLong(message, , model, limit, length)

Bases: [`FalError`](#falaw.errors.FalError), [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

The prompt exceeds the model’s hard length cap (falaw#76).

Raised before any call is queued: fal answers an over-long prompt with an
HTTP 422 only after the request round-trips. `limit`/`length` are in
characters.

### *exception* falaw.errors.FalRateLimited(message, , retry_after_s=None, \*\*kwargs)

Bases: [`FalHTTPError`](#falaw.errors.FalHTTPError)

fal is throttling requests — typical 429.

`retry_after_s` is parsed from the `Retry-After` header if present,
else `None` (caller decides backoff).

### *exception* falaw.errors.FalServerError(message, , status_code, detail='', body=None, headers=None, application=None, url=None, cause=None)

Bases: [`FalHTTPError`](#falaw.errors.FalHTTPError)

fal-side server error — typical 5xx. Generally retryable.

### *exception* falaw.errors.FalTermsViolation(message, , model_id, backend, clause, source_url='')

Bases: [`FalError`](#falaw.errors.FalError)

The model’s terms of service forbid (or leave unknown) this use.

Raised by [`falaw.terms.check_terms()`](falaw.terms.html.md#falaw.terms.check_terms) at plan time (`plan_*`) and, opt-in, at
execution time (`execute(..., terms_context=)`) — before any call,
not audited after. `unknown` refuses, like `has_unknown_costs` does
for money. The message names the model, the backend, the clause and the
ledger row’s `source_url`; the same fields are attributes.

### *exception* falaw.errors.FalTimeout(message, , elapsed_s, application=None)

Bases: [`FalError`](#falaw.errors.FalError)

The fal call timed out before producing a result.

### *exception* falaw.errors.FalUnauthorized(message, , status_code, detail='', body=None, headers=None, application=None, url=None, cause=None)

Bases: [`FalHTTPError`](#falaw.errors.FalHTTPError)

Missing or invalid API credentials — typical 401.

### falaw.errors.import_fal_client()

Import and return `fal_client`, or raise [`FalClientNotInstalled`](#falaw.errors.FalClientNotInstalled).

### falaw.errors.import_httpx(what='fetching from fal.ai')

Import and return `httpx` (part of the `fal` extra), or raise
[`FalClientNotInstalled`](#falaw.errors.FalClientNotInstalled).

### falaw.errors.translate(exc, , application=None)

Convert an underlying fal_client / network exception to a typed falaw exception.

Returns the original exception unchanged if no specific subclass applies
(so callers always get *something* — never silently swallowed).

Logic:

- `FalClientHTTPError` with 403 + lock-pattern body → [`FalAccountLocked`](#falaw.errors.FalAccountLocked)
- `FalClientHTTPError` with 401 → [`FalUnauthorized`](#falaw.errors.FalUnauthorized)
- `FalClientHTTPError` with 402 → [`FalInsufficientFunds`](#falaw.errors.FalInsufficientFunds)
- `FalClientHTTPError` with 429 → [`FalRateLimited`](#falaw.errors.FalRateLimited) (parses Retry-After)
- `FalClientHTTPError` with 4xx → [`FalBadRequest`](#falaw.errors.FalBadRequest)
- `FalClientHTTPError` with 5xx → [`FalServerError`](#falaw.errors.FalServerError)
- `FalClientTimeoutError` → [`FalTimeout`](#falaw.errors.FalTimeout)
- anything else → returned unchanged

* **Return type:**
  [`BaseException`](https://docs.python.org/3/builtins/exceptions.html#BaseException)
