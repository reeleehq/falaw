# falaw.comfyui.audit

Facade item 10: every submitted graph is audited before it leaves the process.

ComfyUI’s `/history` is in-process, capped at 10 000 entries, writable by
prompt handlers and gone on restart, so it is not an audit record. The record
is made here, on the caller’s side, in a sink the *caller owns* and has made
durable, **before** the request is sent: if the sink raises, nothing is sent.
A graph that fails the path screen ([`falaw.comfyui.graph`](falaw.comfyui.graph.html.md#module-falaw.comfyui.graph)) is audited too
(marked rejected) — an attempt is exactly what an audit log is for.

### Module Attributes

| [`REPR_LIMIT`](#falaw.comfyui.audit.REPR_LIMIT)   | Characters of an un-serialisable graph's `repr` kept in its audit record.   |
|---------------------------------------------------------------|-----------------------------------------------------------------------------|

### Functions

| [`submit_graph`](#falaw.comfyui.audit.submit_graph)(graph, \*, send, sink, object_info)   | Screen, audit, then send `graph`; returns whatever `send` returns.   |
|-----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------|

### Classes

| [`FileAuditSink`](#falaw.comfyui.audit.FileAuditSink)(directory, \*[, filename])   | A durable JSON-lines sink: one record per line, `fsync` before return.   |
|---------------------------------------------------------------------------------------------|--------------------------------------------------------------------------|
| [`GraphAuditSink`](#falaw.comfyui.audit.GraphAuditSink)(\*args, \*\*kwargs)         | Where audit records go.                                                  |

### *class* falaw.comfyui.audit.FileAuditSink(directory, , filename='graphs.jsonl')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A durable JSON-lines sink: one record per line, `fsync` before return.

### *class* falaw.comfyui.audit.GraphAuditSink(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Where audit records go. `write` must not return until the record is
durable (or must raise): the caller sends the graph only after it returns.

### falaw.comfyui.audit.REPR_LIMIT *= 4000*

Characters of an un-serialisable graph’s `repr` kept in its audit record.

### falaw.comfyui.audit.submit_graph(graph, \*, send, sink, object_info, context=None, free_text=frozenset({}), clock=<function <lambda>>)

Screen, audit, then send `graph`; returns whatever `send` returns.

Order is the contract: the graph is frozen to a private copy, the path
screen runs, the record (graph, its sha256, time, `context` and the
verdict) is written to `sink`, and only then — if the screen passed — is
`send(copy)` called. A raising sink stops everything. A graph that fails
the screen, or is not even canonical JSON, is recorded and raises
`UnsafeGraphError`.

* **Return type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)
