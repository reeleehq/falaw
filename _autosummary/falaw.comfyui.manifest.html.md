# falaw.comfyui.manifest

The deployment-manifest checker (checklist rows 1-4, 6-9, L).

A manifest is one committed file; this reads it as a dict. Two rules: a missing
field is a failure, and **a bare boolean is not evidence** — a claim is checked
against what backs it (a file digest, a pinned commit proven to sit at or after
the floor tag, an allowlist of arguments). Everything the checker would have to
reach for is a keyword argument: `base_dir` (where evidence files live),
`commit_floor` (the git ancestry test), `allowed_args` and the blocked
endpoint set. A wrong-typed field is a `Problem`, never an exception.

Limit worth knowing: a proxy config’s digest proves the file is the one the
manifest names, not that it enforces `client_endpoints`. The endpoint lists
are claims about that config until a parser for the deployment’s proxy is
plugged in.

```pycon
>>> from falaw.comfyui import check_manifest
>>> [str(p) for p in check_manifest({})][:1]
['2: comfyui.commit must be a 40-hex commit sha']
```

### Module Attributes

| [`FLOOR_TAG`](#falaw.comfyui.manifest.FLOOR_TAG)                 | The ComfyUI release a pinned commit must be at or after (it carries the CVE-2026-68771 fix and PR #14939; see reelee's deployment checklist row 2).   |
|----------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`BLOCKED_ENDPOINTS`](#falaw.comfyui.manifest.BLOCKED_ENDPOINTS)         | Prefixes no caller of ComfyUI may reach, through any proxy list.                                                                                      |
| [`FACADE_ONLY_ENDPOINTS`](#falaw.comfyui.manifest.FACADE_ONLY_ENDPOINTS)     | never in `client_endpoints`.                                                                                                                          |
| [`API_PREFIX`](#falaw.comfyui.manifest.API_PREFIX)                | ComfyUI serves every route again under this prefix; both spellings are one.                                                                           |
| [`DEFAULT_ALLOWED_ARGS`](#falaw.comfyui.manifest.DEFAULT_ALLOWED_ARGS)      | Arguments a deployment may pass, each with its `(min, max)` value count.                                                                              |
| [`EXPLICITLY_FORBIDDEN_ARGS`](#falaw.comfyui.manifest.EXPLICITLY_FORBIDDEN_ARGS) | flag -> (checklist row, why).                                                                                                                         |
| [`DIRECTORY_FLAGS`](#falaw.comfyui.manifest.DIRECTORY_FLAGS)           | Directory flags may only point at the quota'd mounts, never at host paths.                                                                            |
| [`HOST_SYSTEM_DIRS`](#falaw.comfyui.manifest.HOST_SYSTEM_DIRS)          | First path segments a mount `source` may not start with.                                                                                              |
| [`REQUIRED_MOUNTS`](#falaw.comfyui.manifest.REQUIRED_MOUNTS)           | no other host path).                                                                                                                                  |

### Functions

| [`check_manifest`](#falaw.comfyui.manifest.check_manifest)(manifest, \*[, base_dir, ...])   | Problems with a deployment manifest; an empty list means it passes.                                                                             |
|--------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------|
| [`git_commit_floor`](#falaw.comfyui.manifest.git_commit_floor)(repo, \*[, tag])               | A `commit_floor` that asks a local ComfyUI checkout whether the tag is an ancestor of (or equal to) the commit: `git merge-base --is-ancestor`. |

### falaw.comfyui.manifest.API_PREFIX *= '/api'*

ComfyUI serves every route again under this prefix; both spellings are one.

### falaw.comfyui.manifest.BLOCKED_ENDPOINTS *= ('/internal', '/userdata', '/v2/userdata', '/users', '/settings', '/system_stats', '/experiment')*

Prefixes no caller of ComfyUI may reach, through any proxy list.

### falaw.comfyui.manifest.DEFAULT_ALLOWED_ARGS *: [Mapping](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[int](https://docs.python.org/3/builtins/functions.html#int), [int](https://docs.python.org/3/builtins/functions.html#int)]]* *= {'--cpu': (0, 0), '--disable-all-custom-nodes': (0, 0), '--disable-auto-launch': (0, 0), '--disable-metadata': (0, 0), '--dont-print-server': (0, 0), '--input-directory': (1, 1), '--listen': (1, 1), '--max-upload-size': (1, 1), '--output-directory': (1, 1), '--port': (1, 1), '--temp-directory': (1, 1), '--whitelist-custom-nodes': (1, 1000)}*

Arguments a deployment may pass, each with its `(min, max)` value count.
An allowlist, not a secret-shaped scan: `/system_stats` returns `sys.argv`,
so a stray value after a flag that takes none (`--cpu sk-...`) is as much a
leak as a `--api-key` flag. A bare `--listen` is refused by its count: in
ComfyUI it means every interface.

### falaw.comfyui.manifest.DIRECTORY_FLAGS *= {'--input-directory': ('/temp',), '--output-directory': ('/output',), '--temp-directory': ('/temp',)}*

Directory flags may only point at the quota’d mounts, never at host paths.

### falaw.comfyui.manifest.EXPLICITLY_FORBIDDEN_ARGS *= {'--enable-cors-header': ('7', 'lets any web page drive the unauthenticated API'), '--enable-manager': ('4', 'installs arbitrary code from HTTP requests (CVSS 10.0 RCE of its own)')}*

flag -> (checklist row, why). Named so the failure says *why*.

### falaw.comfyui.manifest.FACADE_ONLY_ENDPOINTS *= ('/object_info',)*

never in `client_endpoints`.

* **Type:**
  Reachable by the facade’s identity only

### falaw.comfyui.manifest.FLOOR_TAG *= 'v0.28.0'*

The ComfyUI release a pinned commit must be at or after (it carries the
CVE-2026-68771 fix and PR #14939; see reelee’s deployment checklist row 2).

### falaw.comfyui.manifest.HOST_SYSTEM_DIRS *= frozenset({'bin', 'boot', 'dev', 'etc', 'home', 'proc', 'root', 'run', 'sys', 'usr', 'var'})*

First path segments a mount `source` may not start with.

### falaw.comfyui.manifest.REQUIRED_MOUNTS *= ('/models', '/output', '/temp')*

no other host path).

* **Type:**
  The only paths a deployment may mount (row 6

### falaw.comfyui.manifest.check_manifest(manifest, , base_dir=None, commit_floor=None, allowed_args={'--cpu': (0, 0), '--disable-all-custom-nodes': (0, 0), '--disable-auto-launch': (0, 0), '--disable-metadata': (0, 0), '--dont-print-server': (0, 0), '--input-directory': (1, 1), '--listen': (1, 1), '--max-upload-size': (1, 1), '--output-directory': (1, 1), '--port': (1, 1), '--temp-directory': (1, 1), '--whitelist-custom-nodes': (1, 1000)}, blocked_endpoints=('/internal', '/userdata', '/v2/userdata', '/users', '/settings', '/system_stats', '/experiment'), allow_shared=False, licence_screen=None)

Problems with a deployment manifest; an empty list means it passes.

`base_dir` is where evidence files (proxy config, network policy) are
resolved and their sha256 verified; `commit_floor(commit) -> bool` answers
whether the commit is at or after [`FLOOR_TAG`](#falaw.comfyui.manifest.FLOOR_TAG) (see
[`git_commit_floor()`](#falaw.comfyui.manifest.git_commit_floor)); `licence_screen(names) -> LicenceScreen`
re-runs the screen on the pinned checkout (e.g.
`lambda names: screen_licences(nodes_dir, only=names)`). Without
them those claims cannot be verified, which is a problem, not a pass.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Problem`](falaw.comfyui.problems.html.md#falaw.comfyui.problems.Problem)]

### falaw.comfyui.manifest.git_commit_floor(repo, , tag='v0.28.0')

A `commit_floor` that asks a local ComfyUI checkout whether the tag is
an ancestor of (or equal to) the commit: `git merge-base --is-ancestor`.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]
