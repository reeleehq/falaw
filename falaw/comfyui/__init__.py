"""The ComfyUI deployment gate, executable (falaw#94, from reelee#241).

ComfyUI has no authentication and a code-execution surface, so standing one up
safely is a checklist. Nothing above ``falaw.Plan`` may know ComfyUI exists
(working rule 1), so the checks live here, next to the backend:

* :func:`check_manifest` — a deployment manifest against the checklist, asking
  for *evidence* (file digests, a pinned commit proven to be at or after the
  floor tag), never bare booleans;
* :func:`screen_licences` — read each pinned node pack's own ``LICENSE``/
  ``COPYING`` and fail on AGPL-family or undeterminable; :func:`nodes_digest`
  ties the screen to the manifest's ``custom_nodes``;
* :func:`check_graph_paths` / :func:`assert_safe_graph` — facade item 5: no
  graph parameter reaches a path unsanitised, even after schema validation;
* :func:`submit_graph` + :class:`GraphAuditSink` — facade item 10: every graph
  is written to a caller-owned durable sink *before* the request leaves the
  process.

Every check returns :class:`Problem` s (empty list = passes); the ``assert_*``
forms raise. Each external fact (file reads, the git ancestry test, the clock,
the transport) is a keyword argument, so none of this touches a network.
"""

from .audit import FileAuditSink, GraphAuditSink, submit_graph
from .graph import UnsafeGraphError, assert_safe_graph, check_graph_paths
from .licences import LicenceScreen, nodes_digest, screen_licences
from .manifest import check_manifest, git_commit_floor
from .problems import Problem

__all__ = [
    "FileAuditSink",
    "GraphAuditSink",
    "LicenceScreen",
    "Problem",
    "UnsafeGraphError",
    "assert_safe_graph",
    "check_graph_paths",
    "check_manifest",
    "git_commit_floor",
    "nodes_digest",
    "screen_licences",
    "submit_graph",
]
