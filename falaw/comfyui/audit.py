"""Facade item 10: every submitted graph is audited before it leaves the process.

ComfyUI's ``/history`` is in-process, capped at 10 000 entries, writable by
prompt handlers and gone on restart, so it is not an audit record. The record
is made here, on the caller's side, in a sink the *caller owns* and has made
durable, **before** the request is sent: if the sink raises, nothing is sent.
A graph that fails the path screen (:mod:`falaw.comfyui.graph`) is audited too
(marked rejected) — an attempt is exactly what an audit log is for.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Protocol


from ..canonical import canonical_blob
from .graph import UnsafeGraphError, check_graph_paths

AUDIT_FILENAME = "graphs.jsonl"


class GraphAuditSink(Protocol):
    """Where audit records go. ``write`` must not return until the record is
    durable (or must raise): the caller sends the graph only after it returns."""

    def write(self, record: Mapping) -> None: ...


class FileAuditSink:
    """A durable JSON-lines sink: one record per line, ``fsync`` before return."""

    def __init__(self, directory: str | Path, *, filename: str = AUDIT_FILENAME):
        self.path = Path(directory) / filename
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: Mapping) -> None:
        line = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line)  # one write: appends of a line do not interleave
            os.fsync(fd)
        finally:
            os.close(fd)


def submit_graph(
    graph: Mapping,
    *,
    send: Callable[[Mapping], Any],
    sink: GraphAuditSink,
    object_info: Mapping,
    context: Optional[Mapping] = None,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> Any:
    """Screen, audit, then send ``graph``; returns whatever ``send`` returns.

    Order is the contract: the path screen runs, the record (graph, its
    sha256, time, ``context`` and the verdict) is written to ``sink``, and only
    then — if the screen passed — is ``send(graph)`` called. A raising sink
    stops everything; an unsafe graph is recorded and raises
    :class:`UnsafeGraphError`.
    """
    problems = check_graph_paths(graph, object_info)
    sink.write(
        {
            "submitted_at": clock().isoformat(),
            "graph_sha256": hashlib.sha256(canonical_blob(dict(graph))).hexdigest(),
            "graph": graph,
            "context": dict(context or {}),
            "rejected": [str(p) for p in problems],
        }
    )
    if problems:
        raise UnsafeGraphError(problems)
    return send(graph)
