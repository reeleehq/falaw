# falaw.comfyui

The ComfyUI deployment gate, executable (falaw#94, from reelee#241).

ComfyUI has no authentication and a code-execution surface, so standing one up
safely is a checklist. Nothing above `falaw.Plan` may know ComfyUI exists
(working rule 1), so the checks live here, next to the backend:

* [`check_manifest()`](#falaw.comfyui.check_manifest) — a deployment manifest against the checklist, asking
  for *evidence* (file digests, a pinned commit proven to be at or after the
  floor tag), never bare booleans;
* [`screen_licences()`](#falaw.comfyui.screen_licences) — read each pinned node pack’s own `LICENSE`/
  `COPYING` and fail on AGPL-family or undeterminable; [`nodes_digest()`](#falaw.comfyui.nodes_digest)
  ties the screen to the manifest’s `custom_nodes`;
* [`check_graph_paths()`](#falaw.comfyui.check_graph_paths) / [`assert_safe_graph()`](#falaw.comfyui.assert_safe_graph) — facade item 5: no
  graph parameter reaches a path unsanitised, even after schema validation;
* [`submit_graph()`](#falaw.comfyui.submit_graph) + [`GraphAuditSink`](#falaw.comfyui.GraphAuditSink) — facade item 10: every graph
  is written to a caller-owned durable sink *before* the request leaves the
  process.

Every check returns [`Problem`](#falaw.comfyui.Problem) s (empty list = passes); the `assert_*`
forms raise. Each external fact (file reads, the git ancestry test, the clock,
the transport) is a keyword argument, so none of this touches a network.

### Functions

| [`assert_safe_graph`](#falaw.comfyui.assert_safe_graph)(graph, object_info, \*[, ...])   | Raise [`UnsafeGraphError`](#falaw.comfyui.UnsafeGraphError) unless [`check_graph_paths()`](#falaw.comfyui.check_graph_paths) is empty.   |
|-----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`check_graph_paths`](#falaw.comfyui.check_graph_paths)(graph, object_info, \*[, ...])   | Problems that make `graph` unsafe to submit; empty means it may go.                                                                                             |
| [`check_manifest`](#falaw.comfyui.check_manifest)(manifest, \*[, base_dir, ...])      | Problems with a deployment manifest; an empty list means it passes.                                                                                             |
| [`git_commit_floor`](#falaw.comfyui.git_commit_floor)(repo, \*[, tag])                  | A `commit_floor` that asks a local ComfyUI checkout whether the tag is an ancestor of (or equal to) the commit: `git merge-base --is-ancestor`.                 |
| [`nodes_digest`](#falaw.comfyui.nodes_digest)(nodes)                                | SHA-256 over the `(pack name, commit)` pairs, order-independent.                                                                                                |
| [`screen_licences`](#falaw.comfyui.screen_licences)(nodes_dir, \*[, only, ...])        | Screen every node pack (a directory, or a single `.py` file) under `nodes_dir`.                                                                                 |
| [`submit_graph`](#falaw.comfyui.submit_graph)(graph, \*, send, sink, object_info)   | Screen, audit, then send `graph`; returns whatever `send` returns.                                                                                              |

### Classes

| [`FileAuditSink`](#falaw.comfyui.FileAuditSink)(directory, \*[, filename])       | A durable JSON-lines sink: one record per line, `fsync` before return.                                |
|-------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------|
| [`GraphAuditSink`](#falaw.comfyui.GraphAuditSink)(\*args, \*\*kwargs)             | Where audit records go.                                                                               |
| [`LicenceScreen`](#falaw.comfyui.LicenceScreen)(checked_at, nodes_digest[, ...]) | The outcome of [`screen_licences()`](#falaw.comfyui.screen_licences), in manifest shape. |
| [`Problem`](#falaw.comfyui.Problem)(item, message)                         | One reason a deployment or a graph does not pass.                                                     |

### Exceptions

| [`UnsafeGraphError`](#falaw.comfyui.UnsafeGraphError)(problems)   | A graph failed the path screen; `.problems` lists why.   |
|-------------------------------------------------------------------------------|----------------------------------------------------------|

### *class* falaw.comfyui.FileAuditSink(directory, , filename='graphs.jsonl')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A durable JSON-lines sink: one record per line, `fsync` before return.

### *class* falaw.comfyui.GraphAuditSink(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Where audit records go. `write` must not return until the record is
durable (or must raise): the caller sends the graph only after it returns.

### *class* falaw.comfyui.LicenceScreen(checked_at, nodes_digest, agpl_packs=(), undeterminable=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The outcome of [`screen_licences()`](#falaw.comfyui.screen_licences), in manifest shape.

#### to_dict()

The `licence_screen` block of the deployment manifest.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### *class* falaw.comfyui.Problem(item, message)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One reason a deployment or a graph does not pass.

`item` is the checklist row it belongs to (`"1"`..\`\`”11”`, ``"L"`),
so a failure points back at the requirement it breaks.

### *exception* falaw.comfyui.UnsafeGraphError(problems)

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

A graph failed the path screen; `.problems` lists why.

### falaw.comfyui.assert_safe_graph(graph, object_info, , free_text=frozenset({}))

Raise [`UnsafeGraphError`](#falaw.comfyui.UnsafeGraphError) unless [`check_graph_paths()`](#falaw.comfyui.check_graph_paths) is empty.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### falaw.comfyui.check_graph_paths(graph, object_info, , free_text=frozenset({}))

Problems that make `graph` unsafe to submit; empty means it may go.

`graph` is ComfyUI’s API format `{node_id: {"class_type", "inputs"}}`;
`object_info` is the engine’s `GET /object_info` (the facade is the one
identity allowed to read it).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Problem`](falaw.comfyui.problems.html.md#falaw.comfyui.problems.Problem)]

### falaw.comfyui.check_manifest(manifest, , base_dir=None, commit_floor=None, allowed_args={'--cpu': (0, 0), '--disable-all-custom-nodes': (0, 0), '--disable-auto-launch': (0, 0), '--disable-metadata': (0, 0), '--dont-print-server': (0, 0), '--input-directory': (1, 1), '--listen': (1, 1), '--max-upload-size': (1, 1), '--output-directory': (1, 1), '--port': (1, 1), '--temp-directory': (1, 1), '--whitelist-custom-nodes': (1, 1000)}, blocked_endpoints=('/internal', '/userdata', '/v2/userdata', '/users', '/settings', '/system_stats', '/experiment'), allow_shared=False, licence_screen=None)

Problems with a deployment manifest; an empty list means it passes.

`base_dir` is where evidence files (proxy config, network policy) are
resolved and their sha256 verified; `commit_floor(commit) -> bool` answers
whether the commit is at or after `FLOOR_TAG` (see
[`git_commit_floor()`](#falaw.comfyui.git_commit_floor)); `licence_screen(names) -> LicenceScreen`
re-runs the screen on the pinned checkout (e.g.
`lambda names: screen_licences(nodes_dir, only=names)`). Without
them those claims cannot be verified, which is a problem, not a pass.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Problem`](falaw.comfyui.problems.html.md#falaw.comfyui.problems.Problem)]

### falaw.comfyui.git_commit_floor(repo, , tag='v0.28.0')

A `commit_floor` that asks a local ComfyUI checkout whether the tag is
an ancestor of (or equal to) the commit: `git merge-base --is-ancestor`.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]

### falaw.comfyui.nodes_digest(nodes)

SHA-256 over the `(pack name, commit)` pairs, order-independent.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### falaw.comfyui.screen_licences(nodes_dir, \*, only=None, commit_of=<function git_head>, clock=<function <lambda>>)

Screen every node pack (a directory, or a single `.py` file) under `nodes_dir`.

`only` restricts the screen to the manifest’s declared packs (a stock
ComfyUI checkout also carries unrelated example nodes under
`custom_nodes/`). `commit_of` reads each pack’s pinned commit (default: its git `HEAD`)
so the returned `nodes_digest` matches
[`nodes_digest()`](#falaw.comfyui.nodes_digest) of the manifest’s `custom_nodes`.

* **Return type:**
  [`LicenceScreen`](falaw.comfyui.licences.html.md#falaw.comfyui.licences.LicenceScreen)

### falaw.comfyui.submit_graph(graph, \*, send, sink, object_info, context=None, free_text=frozenset({}), clock=<function <lambda>>)

Screen, audit, then send `graph`; returns whatever `send` returns.

Order is the contract: the graph is frozen to a private copy, the path
screen runs, the record (graph, its sha256, time, `context` and the
verdict) is written to `sink`, and only then — if the screen passed — is
`send(copy)` called. A raising sink stops everything. A graph that fails
the screen, or is not even canonical JSON, is recorded and raises
[`UnsafeGraphError`](#falaw.comfyui.UnsafeGraphError).

* **Return type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)

### Modules

| [`audit`](falaw.comfyui.audit.html.md#module-falaw.comfyui.audit)       | Facade item 10: every submitted graph is audited before it leaves the process.   |
|-----------------------------------------------------------------------------------------|----------------------------------------------------------------------------------|
| [`graph`](falaw.comfyui.graph.html.md#module-falaw.comfyui.graph)       | Facade item 5: no graph parameter reaches a path unsanitised.                    |
| [`licences`](falaw.comfyui.licences.html.md#module-falaw.comfyui.licences) | Licence screen for ComfyUI node packs (checklist row L).                         |
| [`manifest`](falaw.comfyui.manifest.html.md#module-falaw.comfyui.manifest) | The deployment-manifest checker (checklist rows 1-4, 6-9, L).                    |
| [`problems`](falaw.comfyui.problems.html.md#module-falaw.comfyui.problems) | The one result type every gate check returns.                                    |
