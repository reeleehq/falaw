# falaw.events

Structured progress events for fal calls.

Replaces the implicit “stream raw log strings to stdout” model with a
small, machine-readable event stream that orchestrators can subscribe
to (UI progress bars, cost telemetry, billing dashboards, etc.).

A `ProgressEvent` is emitted at every major lifecycle transition of
a single `call_fal` invocation:

- `queued`      — call submitted to fal
- `progress`    — fal pushed an InProgress update with no message body
- `log`         — fal pushed an InProgress update with a log line
- `done`        — call returned a result
- `error`       — call raised
- `cache_hit`   — [`falaw.cached_call_fal()`](falaw.html.md#falaw.cached_call_fal) found a hit and skipped the network

Subscribers can be registered globally via [`subscribe()`](#falaw.events.subscribe) or
per-call via the `on_event=` argument on `call_fal()` /
`cached_call_fal()`. The `on_log` parameter still works
(legacy: a string-only stream); see `call_fal()` for compatibility
notes.

### Functions

| [`clear_subscribers`](#falaw.events.clear_subscribers)()     | Drop all registered subscribers.                                                             |
|--------------------------------------------------------------------------|----------------------------------------------------------------------------------------------|
| [`emit`](#falaw.events.emit)(event, \*[, also]) | Send `event` to every registered subscriber + the `also` list.                               |
| [`subscribe`](#falaw.events.subscribe)(callback)     | Register `callback` to receive every emitted ProgressEvent.                                  |
| [`unsubscribe`](#falaw.events.unsubscribe)(callback)   | Remove a previously [`subscribe()`](#falaw.events.subscribe)'d callback. |

### Classes

| [`ProgressEvent`](#falaw.events.ProgressEvent)(\*, kind, application, call_id)   | One step in the lifecycle of a fal call.   |
|--------------------------------------------------------------------------------------------------|--------------------------------------------|

### *class* falaw.events.ProgressEvent(, kind, application, call_id, message='', pct=None, elapsed_s=0.0)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One step in the lifecycle of a fal call.

#### kind

Lifecycle stage. See `EventKind`.

* **Type:**
  [`Literal`](https://docs.python.org/3/library/typing.html#typing.Literal)[`'queued'`, `'progress'`, `'log'`, `'done'`, `'error'`, `'cache_hit'`]

#### application

fal model id (e.g. `"fal-ai/flux/dev"`).

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### call_id

A short hex string that uniquely identifies the call.
All events for one `call_fal` invocation share the same
`call_id`.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### message

Free-form text. For `"log"` events this is the log
line; for `"error"` it’s `repr(exc)`; otherwise empty.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### pct

Optional progress percentage in [0.0, 100.0]. fal’s
current API doesn’t surface this; included for forward
compatibility.

* **Type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

#### elapsed_s

Seconds since the call started.

* **Type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### falaw.events.clear_subscribers()

Drop all registered subscribers. Mostly for tests.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### falaw.events.emit(event, , also=())

Send `event` to every registered subscriber + the `also` list.

Subscriber exceptions are swallowed (with a printed warning) so a
misbehaving UI hook can’t bring the rendering pipeline down.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### falaw.events.subscribe(callback)

Register `callback` to receive every emitted ProgressEvent.

Returns the callback unchanged so it can be used as a decorator:

```default
@subscribe
def log_to_file(ev: ProgressEvent) -> None:
    ...
```

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`ProgressEvent`](#falaw.events.ProgressEvent)], [`None`](https://docs.python.org/3/builtins/constants.html#None)]

### falaw.events.unsubscribe(callback)

Remove a previously [`subscribe()`](#falaw.events.subscribe)’d callback. No-op if absent.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)
