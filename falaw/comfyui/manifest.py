"""The deployment-manifest checker (checklist rows 1-4, 6-9, L).

A manifest is one committed file; this reads it as a dict. Two rules: a missing
field is a failure, and **a bare boolean is not evidence** — a claim is checked
against what backs it (a file digest, a pinned commit proven to sit at or after
the floor tag, an allowlist of arguments). Everything the checker would have to
reach for is a keyword argument: ``base_dir`` (where evidence files live),
``commit_floor`` (the git ancestry test), ``allowed_args`` and the blocked
endpoint set.

>>> from falaw.comfyui import check_manifest
>>> [str(p) for p in check_manifest({})][:1]
['2: comfyui.commit must be a 40-hex commit sha']
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import subprocess
from collections.abc import Callable, Collection, Mapping
from pathlib import Path
from typing import Any, Optional

from .licences import nodes_digest
from .problems import Problem

FLOOR_TAG = "v0.28.0"
"""The ComfyUI release a pinned commit must be at or after (it carries the
CVE-2026-68771 fix and PR #14939; see reelee's deployment checklist row 2)."""

_SHA1 = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_HOSTNAME = re.compile(
    r"(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}", re.IGNORECASE
)

BLOCKED_ENDPOINTS = (
    "/internal",
    "/userdata",
    "/users",
    "/settings",
    "/system_stats",
    "/experiment",
)
"""Prefixes no caller of ComfyUI may reach, through any proxy list."""

FACADE_ONLY_ENDPOINTS = ("/object_info",)
"""Reachable by the facade's identity only: never in ``client_endpoints``."""

DEFAULT_ALLOWED_ARGS = frozenset(
    {
        "--listen",
        "--port",
        "--disable-all-custom-nodes",
        "--whitelist-custom-nodes",
        "--output-directory",
        "--temp-directory",
        "--input-directory",
        "--cpu",
        "--disable-auto-launch",
        "--disable-metadata",
        "--dont-print-server",
        "--max-upload-size",
    }
)
"""Arguments a deployment may pass. An allowlist, not a secret-shaped scan:
``/system_stats`` returns ``sys.argv``, so only known-benign flags are allowed
(a secret-looking scan stays a backstop, never the rule)."""

EXPLICITLY_FORBIDDEN_ARGS = {
    "--enable-manager": "installs arbitrary code from HTTP requests (CVSS 10.0 RCE of its own)",
    "--enable-cors-header": "lets any web page drive the unauthenticated API",
}
"""Named so the failure says *why*, rather than only 'not on the allowlist'."""

REQUIRED_MOUNTS = ("/models", "/output", "/temp")
"""The only paths a deployment may mount (row 6: no other host path)."""


def _digest_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_commit_floor(
    repo: str | Path, *, tag: str = FLOOR_TAG
) -> Callable[[str], bool]:
    """A ``commit_floor`` that asks a local ComfyUI checkout whether the tag is
    an ancestor of (or equal to) the commit: ``git merge-base --is-ancestor``."""

    def at_or_after(commit: str) -> bool:
        done = subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", tag, commit],
            capture_output=True,
        )
        return done.returncode == 0

    return at_or_after


def _args_by_flag(args: list[str]) -> dict[str, list[str]]:
    """``["--port", "8188", "--cpu"]`` -> ``{"--port": ["8188"], "--cpu": []}``."""
    out: dict[str, list[str]] = {}
    flag = None
    for token in args:
        if token.startswith("--"):
            flag = token
            out.setdefault(flag, [])
        elif flag is not None:
            out[flag].append(token)
        else:
            out.setdefault(token, [])  # a stray value: surfaces as not allowed
    return out


def _check_evidence(
    item: str,
    label: str,
    evidence: Any,
    base_dir: Optional[Path],
    out: list[Problem],
) -> None:
    """``{"path", "sha256"}`` evidence: the file must exist and match its digest."""
    ev = evidence if isinstance(evidence, Mapping) else {}
    path, claimed = ev.get("path"), str(ev.get("sha256", ""))
    if not path or not _SHA256.fullmatch(claimed):
        out.append(Problem(item, f"{label} must be {{path, sha256}} evidence"))
        return
    if base_dir is None:
        out.append(Problem(item, f"{label}: no base_dir given to verify {path!r}"))
        return
    target = base_dir / path
    if not target.is_file():
        out.append(Problem(item, f"{label}: {path!r} not found under base_dir"))
    elif _digest_of(target) != claimed:
        out.append(Problem(item, f"{label}: {path!r} does not match its sha256"))


def _check_network(m: Mapping, args: Mapping[str, list[str]], base, out) -> None:
    net = m.get("network") or {}
    if net.get("public_ingress") is not False:
        out.append(Problem("1", "network.public_ingress must be false"))
    for value in args.get("--listen", ()):
        try:
            ip = ipaddress.ip_address(value)
        except ValueError:
            out.append(Problem("1", f"--listen {value!r} is not an IP address"))
            continue
        if ip.is_unspecified or not (ip.is_loopback or ip.is_private):
            out.append(Problem("1", f"--listen {value} is not a private address"))
    hosts = net.get("egress_allow") or []
    if not hosts:
        out.append(Problem("8", "network.egress_allow must name the allowed hosts"))
    for host in hosts:
        if not _HOSTNAME.fullmatch(str(host)):
            out.append(
                Problem(
                    "8",
                    f"egress host {host!r} must be a named host (no '*', CIDR or bare IP)",
                )
            )
    _check_evidence(
        "8", "network.metadata_blocked_by", net.get("metadata_blocked_by"), base, out
    )


def _check_proxy(m: Mapping, blocked: Collection[str], base, out) -> None:
    proxy = m.get("proxy") or {}
    _check_evidence("3", "proxy.config", proxy.get("config"), base, out)
    facade = [str(e) for e in proxy.get("facade_only_endpoints") or ()]
    client = [str(e) for e in proxy.get("client_endpoints") or ()]
    if not client:
        out.append(
            Problem("3", "proxy.client_endpoints must list the allowed endpoints")
        )
    for ep in (*facade, *client):
        if any(ep == b or ep.startswith(b + "/") for b in blocked):
            out.append(Problem("3", f"endpoint {ep!r} must not be exposed"))
    for ep in client:
        if any(ep == f or ep.startswith(f + "/") for f in FACADE_ONLY_ENDPOINTS):
            out.append(Problem("3", f"{ep!r} may be reachable by the facade only"))


def _check_args(m: Mapping, allowed: Collection[str], flags, out) -> None:
    names = {
        n["name"]
        for n in m.get("custom_nodes") or ()
        if isinstance(n, Mapping) and "name" in n
    }
    if "--disable-all-custom-nodes" not in flags:
        out.append(Problem("4", "--disable-all-custom-nodes is required"))
    for flag, values in flags.items():
        if flag in EXPLICITLY_FORBIDDEN_ARGS:
            out.append(
                Problem(
                    "4" if "manager" in flag else "7",
                    f"never {flag}: {EXPLICITLY_FORBIDDEN_ARGS[flag]}",
                )
            )
        elif flag not in allowed:
            out.append(Problem("7", f"argument {flag!r} is not on the allowlist"))
    if (
        flags.get("--whitelist-custom-nodes") is not None
        and set(flags["--whitelist-custom-nodes"]) != names
    ):
        out.append(
            Problem("4", "--whitelist-custom-nodes must equal custom_nodes names")
        )
    for port in flags.get("--port", ()):
        if not port.isdigit():
            out.append(Problem("1", f"--port {port!r} is not a number"))


def _check_commits(m: Mapping, commit_floor, out) -> None:
    commit = str((m.get("comfyui") or {}).get("commit", ""))
    if not _SHA1.fullmatch(commit):
        out.append(Problem("2", "comfyui.commit must be a 40-hex commit sha"))
    elif commit_floor is None:
        out.append(
            Problem(
                "2",
                f"cannot verify the commit is at or after {FLOOR_TAG} (no commit_floor given)",
            )
        )
    elif not commit_floor(commit):
        out.append(Problem("2", f"comfyui.commit is not at or after {FLOOR_TAG}"))
    for node in m.get("custom_nodes") or ():
        node = node if isinstance(node, Mapping) else {}
        label = node.get("name") or "?"
        if not node.get("name") or not node.get("repo"):
            out.append(Problem("4", f"custom node {label!r} needs name and repo"))
        if not _SHA1.fullmatch(str(node.get("commit", ""))):
            out.append(Problem("4", f"custom node {label!r} is not pinned by commit"))


def _check_mounts(m: Mapping, out) -> None:
    for mount in m.get("mounts") or ():
        path, mode = str(mount.get("path", "")), mount.get("mode")
        if path not in REQUIRED_MOUNTS:
            out.append(
                Problem(
                    "6",
                    f"mount {path!r}: no host path other than {list(REQUIRED_MOUNTS)} may be mounted",
                )
            )
        elif path == "/models" and mode != "ro":
            out.append(Problem("6", "/models must be mounted read-only"))
        elif path != "/models" and not (
            isinstance(mount.get("quota_gb"), (int, float)) and mount["quota_gb"] > 0
        ):
            out.append(Problem("6", f"{path} needs a quota_gb"))
    present = {str(mt.get("path")) for mt in m.get("mounts") or ()}
    for required in REQUIRED_MOUNTS:
        if required not in present:
            out.append(Problem("6", f"missing mount {required}"))


def _check_tenancy_and_licences(m: Mapping, allow_shared, out) -> None:
    tenancy = m.get("tenancy")
    if tenancy not in ("per_tenant", "shared"):
        out.append(Problem("9", "tenancy must be recorded (per_tenant | shared)"))
    elif tenancy == "shared" and not allow_shared:
        out.append(
            Problem(
                "9",
                "tenancy 'shared' is incompatible with a multi-tenant host (pass allow_shared=True for a single-owner dev instance)",
            )
        )
    screen = m.get("licence_screen") or {}
    if not screen.get("checked_at"):
        out.append(Problem("L", "the licence screen has not been run"))
    if screen.get("agpl_packs") or screen.get("undeterminable"):
        out.append(
            Problem("L", "the licence screen found AGPL-family or undeterminable packs")
        )
    expected = nodes_digest(
        (n.get("name"), n.get("commit"))
        for n in m.get("custom_nodes") or ()
        if isinstance(n, Mapping)
    )
    if screen.get("nodes_digest") != expected:
        out.append(
            Problem(
                "L",
                "licence_screen.nodes_digest does not match the current custom_nodes",
            )
        )
    for worker in m.get("third_party_workers") or ():
        if (
            "AGPL" in str(worker.get("licence", "")).upper()
            and worker.get("use") != "black box only"
        ):
            out.append(
                Problem(
                    "L",
                    f"AGPL worker {worker.get('name')!r} may only be used as a black box",
                )
            )


def check_manifest(
    manifest: Mapping,
    *,
    base_dir: str | Path | None = None,
    commit_floor: Optional[Callable[[str], bool]] = None,
    allowed_args: Collection[str] = DEFAULT_ALLOWED_ARGS,
    blocked_endpoints: Collection[str] = BLOCKED_ENDPOINTS,
    allow_shared: bool = False,
) -> list[Problem]:
    """Problems with a deployment manifest; an empty list means it passes.

    ``base_dir`` is where evidence files (proxy config, network policy) are
    resolved and their sha256 verified; ``commit_floor(commit) -> bool`` answers
    whether the commit is at or after :data:`FLOOR_TAG` (see
    :func:`git_commit_floor`). Without them those claims cannot be verified,
    which is a problem, not a pass.
    """
    out: list[Problem] = []
    base = Path(base_dir) if base_dir is not None else None
    flags = _args_by_flag([str(a) for a in manifest.get("args") or ()])
    _check_commits(manifest, commit_floor, out)
    _check_network(manifest, flags, base, out)
    _check_proxy(manifest, blocked_endpoints, base, out)
    _check_args(manifest, allowed_args, flags, out)
    _check_mounts(manifest, out)
    _check_tenancy_and_licences(manifest, allow_shared, out)
    return out
