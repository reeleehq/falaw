"""The deployment-manifest checker (checklist rows 1-4, 6-9, L).

A manifest is one committed file; this reads it as a dict. Two rules: a missing
field is a failure, and **a bare boolean is not evidence** — a claim is checked
against what backs it (a file digest, a pinned commit proven to sit at or after
the floor tag, an allowlist of arguments). Everything the checker would have to
reach for is a keyword argument: ``base_dir`` (where evidence files live),
``commit_floor`` (the git ancestry test), ``allowed_args`` and the blocked
endpoint set. A wrong-typed field is a :class:`Problem`, never an exception.

Limit worth knowing: a proxy config's digest proves the file is the one the
manifest names, not that it enforces ``client_endpoints``. The endpoint lists
are claims about that config until a parser for the deployment's proxy is
plugged in.

>>> from falaw.comfyui import check_manifest
>>> [str(p) for p in check_manifest({})][:1]
['2: comfyui.commit must be a 40-hex commit sha']
"""

from __future__ import annotations

import hashlib
import ipaddress
import posixpath
import re
import subprocess
import urllib.parse
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any, Optional

from .licences import RESTRICTED_FAMILY, LicenceScreen, nodes_digest
from .problems import Problem

FLOOR_TAG = "v0.28.0"
"""The ComfyUI release a pinned commit must be at or after (it carries the
CVE-2026-68771 fix and PR #14939; see reelee's deployment checklist row 2)."""

_SHA1 = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_HOSTNAME = re.compile(
    r"(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}", re.IGNORECASE
)
_INTERNAL_HOST = re.compile(
    r"(^|\.)(internal|local|localhost|localdomain)$", re.IGNORECASE
)

BLOCKED_ENDPOINTS = (
    "/internal",
    "/userdata",
    "/v2/userdata",
    "/users",
    "/settings",
    "/system_stats",
    "/experiment",
)
"""Prefixes no caller of ComfyUI may reach, through any proxy list."""

FACADE_ONLY_ENDPOINTS = ("/object_info",)
"""Reachable by the facade's identity only: never in ``client_endpoints``."""

API_PREFIX = "/api"
"""ComfyUI serves every route again under this prefix; both spellings are one."""

DEFAULT_ALLOWED_ARGS: Mapping[str, tuple[int, int]] = {
    "--listen": (1, 1),
    "--port": (1, 1),
    "--disable-all-custom-nodes": (0, 0),
    "--whitelist-custom-nodes": (1, 1000),
    "--output-directory": (1, 1),
    "--temp-directory": (1, 1),
    "--input-directory": (1, 1),
    "--cpu": (0, 0),
    "--disable-auto-launch": (0, 0),
    "--disable-metadata": (0, 0),
    "--dont-print-server": (0, 0),
    "--max-upload-size": (1, 1),
}
"""Arguments a deployment may pass, each with its ``(min, max)`` value count.
An allowlist, not a secret-shaped scan: ``/system_stats`` returns ``sys.argv``,
so a stray value after a flag that takes none (``--cpu sk-...``) is as much a
leak as a ``--api-key`` flag. A bare ``--listen`` is refused by its count: in
ComfyUI it means every interface."""

#: flag -> (checklist row, why). Named so the failure says *why*.
EXPLICITLY_FORBIDDEN_ARGS = {
    "--enable-manager": (
        "4",
        "installs arbitrary code from HTTP requests (CVSS 10.0 RCE of its own)",
    ),
    "--enable-cors-header": ("7", "lets any web page drive the unauthenticated API"),
}

DIRECTORY_FLAGS = {
    "--output-directory": ("/output",),
    "--temp-directory": ("/temp",),
    "--input-directory": ("/temp",),
}
"""Directory flags may only point at the quota'd mounts, never at host paths."""

HOST_SYSTEM_DIRS = frozenset(
    {"etc", "proc", "sys", "root", "home", "var", "usr", "bin", "dev", "boot", "run"}
)
"""First path segments a mount ``source`` may not start with."""

REQUIRED_MOUNTS = ("/models", "/output", "/temp")
"""The only paths a deployment may mount (row 6: no other host path)."""


# --- shape normalisation ------------------------------------------------------


def _mapping(value: Any) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _mappings(value: Any) -> list[Mapping]:
    """The mapping entries of a list; wrong-typed entries are reported by the
    caller's own presence checks (they simply contribute nothing)."""
    return (
        [v for v in value if isinstance(v, Mapping)] if isinstance(value, list) else []
    )


def _strings(value: Any) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


# --- evidence -----------------------------------------------------------------


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


def _evidence(
    item: str, label: str, evidence: Any, base: Optional[Path]
) -> Iterator[Problem]:
    """``{"path", "sha256"}`` evidence: a file inside ``base`` matching its digest."""
    ev = _mapping(evidence)
    path, claimed = ev.get("path"), str(ev.get("sha256", ""))
    if not isinstance(path, str) or not path or not _SHA256.fullmatch(claimed):
        yield Problem(item, f"{label} must be {{path, sha256}} evidence")
        return
    if base is None:
        yield Problem(item, f"{label}: no base_dir given to verify {path!r}")
        return
    target = (base / path).resolve()
    if not target.is_relative_to(base.resolve()):
        yield Problem(item, f"{label}: {path!r} points outside base_dir")
    elif not target.is_file():
        yield Problem(item, f"{label}: {path!r} not found under base_dir")
    elif _digest_of(target) != claimed:
        yield Problem(item, f"{label}: {path!r} does not match its sha256")


# --- arguments ----------------------------------------------------------------


def _flags(args: list[str]) -> tuple[dict[str, list[str]], list[Problem]]:
    """Group argv into ``{flag: [values]}``; shape errors come back as Problems."""
    out: dict[str, list[str]] = {}
    problems: list[Problem] = []
    flag = None
    for token in args:
        if token.startswith("--"):
            if "=" in token:
                problems.append(
                    Problem(
                        "7",
                        f"{token!r}: write a flag and its value as separate arguments",
                    )
                )
            if token in out:
                problems.append(Problem("7", f"{token} is given twice"))
            flag = token
            out.setdefault(flag, [])
        elif flag is None:
            problems.append(Problem("7", f"{token!r} is a value with no flag"))
        else:
            out[flag].append(token)
    return out, problems


def _check_args(
    manifest: Mapping, allowed: Mapping[str, tuple[int, int]]
) -> Iterator[Problem]:
    raw = manifest.get("args")
    if not isinstance(raw, list) or not all(isinstance(a, str) for a in raw):
        yield Problem("7", "args must be a list of strings")
        return
    flags, problems = _flags(raw)
    yield from problems
    if "--disable-all-custom-nodes" not in flags:
        yield Problem("4", "--disable-all-custom-nodes is required")
    names = {n.get("name") for n in _mappings(manifest.get("custom_nodes"))}
    for flag, values in flags.items():
        if flag in EXPLICITLY_FORBIDDEN_ARGS:
            item, why = EXPLICITLY_FORBIDDEN_ARGS[flag]
            yield Problem(item, f"never {flag}: {why}")
        elif flag not in allowed:
            yield Problem("7", f"argument {flag!r} is not on the allowlist")
        else:
            lo, hi = allowed[flag]
            if not lo <= len(values) <= hi:
                yield Problem("7", f"{flag} takes {lo}..{hi} values, got {len(values)}")
    if (
        "--whitelist-custom-nodes" in flags
        and set(flags["--whitelist-custom-nodes"]) != names
    ):
        yield Problem("4", "--whitelist-custom-nodes must equal custom_nodes names")
    for flag, mounts in DIRECTORY_FLAGS.items():
        for value in flags.get(flag, ()):
            if value not in mounts:
                yield Problem("6", f"{flag} {value!r} must be one of {list(mounts)}")
    for port in flags.get("--port", ()):
        if not port.isdigit():
            yield Problem("1", f"--port {port!r} is not a number")


# --- rows ---------------------------------------------------------------------


def _check_commits(manifest: Mapping, commit_floor) -> Iterator[Problem]:
    commit = str(_mapping(manifest.get("comfyui")).get("commit", ""))
    if not _SHA1.fullmatch(commit):
        yield Problem("2", "comfyui.commit must be a 40-hex commit sha")
    elif commit_floor is None:
        yield Problem(
            "2",
            f"cannot verify the commit is at or after {FLOOR_TAG} (no commit_floor given)",
        )
    elif not commit_floor(commit):
        yield Problem("2", f"comfyui.commit is not at or after {FLOOR_TAG}")


def _check_custom_nodes(manifest: Mapping) -> Iterator[Problem]:
    nodes = manifest.get("custom_nodes") or []
    if not isinstance(nodes, list):
        yield Problem("4", "custom_nodes must be a list")
        return
    for node in nodes:
        node = _mapping(node)
        label = node.get("name") or "?"
        if not node.get("name") or not node.get("repo"):
            yield Problem("4", f"custom node {label!r} needs name and repo")
        if not _SHA1.fullmatch(str(node.get("commit", ""))):
            yield Problem("4", f"custom node {label!r} is not pinned by commit")


def _check_listen(manifest: Mapping) -> Iterator[Problem]:
    flags, _ = _flags(_strings(manifest.get("args")))
    if _mapping(manifest.get("network")).get("public_ingress") is not False:
        yield Problem("1", "network.public_ingress must be false")
    for value in flags.get("--listen", ()):
        try:
            ip = ipaddress.ip_address(value)
        except ValueError:
            yield Problem("1", f"--listen {value!r} is not an IP address")
            continue
        if ip.is_unspecified or not (ip.is_loopback or ip.is_private):
            yield Problem("1", f"--listen {value} is not a private address")


def _normalise_endpoint(endpoint: str) -> str:
    """``//API/./%49nternal/`` -> ``/internal``: what the engine would route it as."""
    path = urllib.parse.unquote(endpoint.lower()).split("?")[0]
    path = posixpath.normpath("/" + path.lstrip("/")).replace("//", "/")
    if path == API_PREFIX or path.startswith(API_PREFIX + "/"):
        path = path[len(API_PREFIX) :] or "/"
    return path


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def _check_proxy(
    manifest: Mapping, blocked: Collection[str], base
) -> Iterator[Problem]:
    proxy = _mapping(manifest.get("proxy"))
    yield from _evidence("3", "proxy.config", proxy.get("config"), base)
    facade, client = (
        _strings(proxy.get("facade_only_endpoints")),
        _strings(proxy.get("client_endpoints")),
    )
    if not client:
        yield Problem("3", "proxy.client_endpoints must list the allowed endpoints")
    for ep in (*facade, *client):
        norm = _normalise_endpoint(ep)
        if "*" in ep or norm == "/":
            yield Problem(
                "3", f"endpoint {ep!r} must name a route (no wildcard, no root)"
            )
        elif any(_under(norm, b) for b in blocked):
            yield Problem("3", f"endpoint {ep!r} must not be exposed")
    for ep in client:
        if any(_under(_normalise_endpoint(ep), f) for f in FACADE_ONLY_ENDPOINTS):
            yield Problem("3", f"{ep!r} may be reachable by the facade only")


def _bad_source(source: Any) -> bool:
    """Whether a mount ``source`` could expose the host: not a string, or the
    root, a parent escape, or a system directory."""
    if not isinstance(source, str) or not source.strip():
        return True
    norm = posixpath.normpath(source)
    first = norm.lstrip("/").split("/")[0]
    return (
        norm in ("/", ".")
        or norm.startswith("..")
        or (norm.startswith("/") and first in HOST_SYSTEM_DIRS)
    )


def _check_mounts(manifest: Mapping) -> Iterator[Problem]:
    raw = manifest.get("mounts")
    entries = raw if isinstance(raw, list) else []
    if not isinstance(raw, list) or not all(isinstance(m, Mapping) for m in entries):
        yield Problem("6", "mounts must be a list of mappings")
    mounts = [m for m in entries if isinstance(m, Mapping)]
    for mount in mounts:
        path, quota = str(mount.get("path", "")), mount.get("quota_gb")
        if path not in REQUIRED_MOUNTS:
            yield Problem(
                "6",
                f"mount {path!r}: no host path other than {list(REQUIRED_MOUNTS)} may be mounted",
            )
            continue
        if _bad_source(mount.get("source")):
            yield Problem(
                "6",
                f"mount {path}: source must name a dedicated volume or directory (not '/', '..' or a system directory)",
            )
        if path == "/models" and mount.get("mode") != "ro":
            yield Problem("6", "/models must be mounted read-only")
        elif path != "/models" and not (
            isinstance(quota, (int, float))
            and not isinstance(quota, bool)
            and quota > 0
        ):
            yield Problem("6", f"{path} needs a quota_gb")
    present = {str(m.get("path")) for m in mounts}
    for required in REQUIRED_MOUNTS:
        if required not in present:
            yield Problem("6", f"missing mount {required}")


def _check_egress(manifest: Mapping, base) -> Iterator[Problem]:
    net = _mapping(manifest.get("network"))
    hosts = net.get("egress_allow")
    if not isinstance(hosts, list) or not hosts:
        yield Problem("8", "network.egress_allow must name the allowed hosts")
    for host in hosts if isinstance(hosts, list) else ():
        if not isinstance(host, str) or not _HOSTNAME.fullmatch(host):
            yield Problem(
                "8",
                f"egress host {host!r} must be a named host (no '*', CIDR or bare IP)",
            )
        elif _INTERNAL_HOST.search(host):
            yield Problem(
                "8",
                f"egress host {host!r} is an internal name (cloud metadata lives there)",
            )
    yield from _evidence(
        "8", "network.metadata_blocked_by", net.get("metadata_blocked_by"), base
    )


def _check_tenancy(manifest: Mapping, allow_shared: bool) -> Iterator[Problem]:
    tenancy = manifest.get("tenancy")
    if tenancy not in ("per_tenant", "shared"):
        yield Problem("9", "tenancy must be recorded (per_tenant | shared)")
    elif tenancy == "shared" and not allow_shared:
        yield Problem(
            "9",
            "tenancy 'shared' is incompatible with a multi-tenant host (pass allow_shared=True for a single-owner dev instance)",
        )


def _check_licences(
    manifest: Mapping,
    licence_screen: Optional[Callable[[Collection[str]], LicenceScreen]],
) -> Iterator[Problem]:
    screen = _mapping(manifest.get("licence_screen"))
    nodes = _mappings(manifest.get("custom_nodes"))
    if not screen.get("checked_at"):
        yield Problem("L", "the licence screen has not been run")
    if screen.get("agpl_packs") or screen.get("undeterminable"):
        yield Problem(
            "L", "the licence screen found AGPL-family or undeterminable packs"
        )
    expected = nodes_digest((n.get("name"), n.get("commit")) for n in nodes)
    if screen.get("nodes_digest") != expected:
        yield Problem(
            "L", "licence_screen.nodes_digest does not match the current custom_nodes"
        )
    if licence_screen is None:
        yield Problem(
            "L",
            "the licence screen is self-asserted: pass licence_screen= to re-run it on the pinned checkout",
        )
    else:
        fresh = licence_screen([str(n.get("name")) for n in nodes])
        yield from fresh.problems()
        if fresh.nodes_digest != expected:
            yield Problem(
                "L",
                "the pinned checkout does not match custom_nodes (names/commits differ)",
            )
    for worker in _mappings(manifest.get("third_party_workers")):
        restricted = RESTRICTED_FAMILY.search(str(worker.get("licence", "")))
        if restricted and worker.get("use") != "black box only":
            yield Problem(
                "L",
                f"AGPL-family worker {worker.get('name')!r} may only be used as a black box",
            )


def check_manifest(
    manifest: Mapping,
    *,
    base_dir: str | Path | None = None,
    commit_floor: Optional[Callable[[str], bool]] = None,
    allowed_args: Mapping[str, tuple[int, int]] = DEFAULT_ALLOWED_ARGS,
    blocked_endpoints: Collection[str] = BLOCKED_ENDPOINTS,
    allow_shared: bool = False,
    licence_screen: Optional[Callable[[Collection[str]], LicenceScreen]] = None,
) -> list[Problem]:
    """Problems with a deployment manifest; an empty list means it passes.

    ``base_dir`` is where evidence files (proxy config, network policy) are
    resolved and their sha256 verified; ``commit_floor(commit) -> bool`` answers
    whether the commit is at or after :data:`FLOOR_TAG` (see
    :func:`git_commit_floor`); ``licence_screen(names) -> LicenceScreen``
    re-runs the screen on the pinned checkout (e.g.
    ``lambda names: screen_licences(nodes_dir, only=names)``). Without
    them those claims cannot be verified, which is a problem, not a pass.
    """
    if not isinstance(manifest, Mapping):
        return [Problem("*", "the manifest must be a JSON object")]
    base = Path(base_dir) if base_dir is not None else None
    checks: Iterable[Iterator[Problem]] = (
        _check_commits(manifest, commit_floor),
        _check_listen(manifest),
        _check_proxy(manifest, blocked_endpoints, base),
        _check_custom_nodes(manifest),
        _check_args(manifest, allowed_args),
        _check_mounts(manifest),
        _check_egress(manifest, base),
        _check_tenancy(manifest, allow_shared),
        _check_licences(manifest, licence_screen),
    )
    return [problem for check in checks for problem in check]
