# falaw.account

Account health probe.

`fal_client` swallows the JSON body of its 403s, so a locked-account error
looks identical to “wrong API key” or “model is busy.” [`health_check()`](#falaw.account.health_check)
makes a tiny, idempotent request to the fal storage endpoint and returns a
typed [`AccountStatus`](#falaw.account.AccountStatus) so the caller can distinguish:

- account is locked / unverified  → [`AccountStatus.locked`](#falaw.account.AccountStatus.locked) is True
- bad credentials                 → [`AccountStatus.unauthorized`](#falaw.account.AccountStatus.unauthorized) is True
- everything looks fine            → [`AccountStatus.ok`](#falaw.account.AccountStatus.ok) is True
- network / unknown error          → all flags False, `error` populated

Use this *before* a long render to fail fast with a useful message:

```python
from falaw.account import health_check
status = health_check()
if not status.ok:
    raise SystemExit(status.message_for_user())
```

### Functions

| [`health_check`](#falaw.account.health_check)(\*[, probe_url, timeout_s, api_key])   | Probe the fal storage endpoint and return a typed [`AccountStatus`](#falaw.account.AccountStatus).   |
|------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------|

### Classes

| [`AccountStatus`](#falaw.account.AccountStatus)(ok, locked, unauthorized, ...)   | Outcome of [`health_check()`](#falaw.account.health_check).   |
|-------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------|

### *class* falaw.account.AccountStatus(ok, locked, unauthorized, status_code, detail, url, error)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Outcome of [`health_check()`](#falaw.account.health_check).

#### detail *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

Server-supplied detail string (best-effort), or ‘’ if unavailable.

#### error *: [str](https://docs.python.org/3/builtins/stdtypes.html#str) | [None](https://docs.python.org/3/builtins/constants.html#None)*

`repr` of the underlying exception when `ok` is False
and the failure isn’t a recognized lock/unauth (e.g. network error).

#### locked *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True iff the response indicated a locked / unverified account.

#### message_for_user()

Single human-readable line explaining the status. Stable for logging.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### ok *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True iff the account responded without an auth/lock error.

#### status_code *: [int](https://docs.python.org/3/builtins/functions.html#int) | [None](https://docs.python.org/3/builtins/constants.html#None)*

HTTP status from the probe (None if no HTTP exchange happened).

#### unauthorized *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True iff credentials are missing or invalid.

#### url *: [str](https://docs.python.org/3/builtins/stdtypes.html#str) | [None](https://docs.python.org/3/builtins/constants.html#None)*

If actionable (e.g. billing dashboard), URL the user should visit.

### falaw.account.health_check(, probe_url='https://rest.fal.ai/storage/auth/token?storage_type=fal-cdn-v3', timeout_s=10.0, api_key=None)

Probe the fal storage endpoint and return a typed [`AccountStatus`](#falaw.account.AccountStatus).

* **Parameters:**
  * **probe_url** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Endpoint to probe. Default is the storage-auth-token endpoint
    `fal_client` uses internally; small, idempotent, requires auth.
  * **timeout_s** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Network timeout.
  * **api_key** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Optional override of `FAL_KEY`. Falls back to a key bound with
    [`falaw.using_fal_credentials()`](falaw.md#falaw.using_fal_credentials), then the env var.
* **Return type:**
  [`AccountStatus`](#falaw.account.AccountStatus)
* **Returns:**
  [`AccountStatus`](#falaw.account.AccountStatus) with `ok=True` when the probe succeeded.
