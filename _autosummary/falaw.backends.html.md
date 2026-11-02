# falaw.backends

Execution backend registry — where `CallPlan.backend` dispatches (falaw#15).

Until this module existed, “make the vendor call” meant one hardcoded path:
`falaw.core.call_fal`. That is a budget bypass waiting to happen — the
video_gen research programme’s decisions of record (§3.2) put it plainly:
 *“Do not write a ComfyUI Transform before this lands. A flavor without a
priceable Plan is a budget bypass.”* A backend reachable only by overriding
`Transform.execute` wholesale returns `Plan(calls=())`, so
`Plan.total_cost_usd` reads $0.00 on a real spend and every downstream
consumer of `Plan` — the cache, the dry-run converter, the cost gate — never
sees the call happen.

The fix is the smallest one that closes that gap: `CallPlan` gains a
`backend: str` field (default [`falaw.canonical.DFLT_BACKEND`](falaw.canonical.html.md#falaw.canonical.DFLT_BACKEND), i.e.
`"fal"`), and `execute_isolated` resolves it through this module’s `backends`
registry instead of calling `call_fal` directly. Everything else about a
`CallPlan` — its cost estimate, its cache key, its artifact conversion —
stays exactly what it already is, because the executor’s contract is
narrow: turn `(application, arguments)` into the vendor’s *raw* response,
in the same shape [`falaw.core.call_fal()`](falaw.core.html.md#falaw.core.call_fal) already returns. Converting
that raw response into a `lacing.Artifact` remains `execute`’s job, uniform
across backends.

Nothing above `falaw.Plan` may know a specific backend exists. A module that
imports a backend type, references a vendor node name, or assumes a
backend’s execution semantics is an architecture bug regardless of whether
it works — this registry is the one seam allowed to know backends exist at
all.

Register a second backend with `backends.register(name, executor)`, then
build `CallPlan(..., backend=name)`. See
`docs/comfyui_integration_plan.md` (video_gen research programme) for the
two-tier ruling this registry is the executor half of: a `nw.Transform`
comfy *flavor* is the graph **template** and never opens a socket; a
`GraphExecutionBackend` registered here is the **executor**.

### Module Attributes

| [`BackendExecutor`](#falaw.backends.BackendExecutor)   | `executor(application, arguments, *, on_event=None) -> dict` — the same shape [`falaw.core.call_fal()`](falaw.core.html.md#falaw.core.call_fal) returns: the vendor's raw response, ready for the existing artifact converter.   |
|--------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`backends`](#falaw.backends.backends)          | Public registry of execution backends, keyed by `CallPlan.backend`.                                                                                                                                                                                       |

### Functions

| [`get_backend_executor`](#falaw.backends.get_backend_executor)(name)   | Look up a backend executor by name; raises with the known names.   |
|-------------------------------------------------------------------------------|--------------------------------------------------------------------|

### falaw.backends.BackendExecutor

`executor(application, arguments, *, on_event=None) -> dict` — the same
shape [`falaw.core.call_fal()`](falaw.core.html.md#falaw.core.call_fal) returns: the vendor’s raw response, ready
for the existing artifact converter. An executor’s only job is \*making the
call\*; it must not attempt caching (the registry sits below the cache) or
artifact conversion (`execute` owns that, uniformly across backends).
A run’s metrics reach a plan’s [`CallOutcome`](falaw.html.md#falaw.CallOutcome) only when the
executor emits its `done` event through [`falaw.events.emit()`](falaw.events.html.md#falaw.events.emit) on the
calling thread (as `call_fal` does); calling only the passed `on_event`
is not heard by [`falaw.events.listening()`](falaw.events.html.md#falaw.events.listening) (falaw#127).

alias of `Callable`[[…], [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### falaw.backends.backends *: Registry* *= <Registry falaw.backends>*

Public registry of execution backends, keyed by `CallPlan.backend`.
`on_conflict="error"` so a misconfigured plugin fails loudly instead of
silently shadowing the built-in fal executor.

### falaw.backends.get_backend_executor(name)

Look up a backend executor by name; raises with the known names.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
