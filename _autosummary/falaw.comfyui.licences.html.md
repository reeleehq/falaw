# falaw.comfyui.licences

Licence screen for ComfyUI node packs (checklist row L).

Reads each pack’s own `LICENSE` / `LICENCE` / `COPYING` file in the
pinned checkout — never registry metadata, which 85.5% of packs leave empty —
and fails on AGPL-family or *undeterminable*. The screen records a digest of
the screened set ([`nodes_digest()`](#falaw.comfyui.licences.nodes_digest)) so a manifest can prove the screen was
run on the nodes it actually deploys.

AGPL is recognised from the licence’s **title** (its first lines) or an SPDX
tag, not from the word “Affero” anywhere in the text: GPLv3 section 13 names
the AGPL, so a substring scan would reject every GPLv3 pack.

### Module Attributes

| [`LICENCE_FILE_PREFIXES`](#falaw.comfyui.licences.LICENCE_FILE_PREFIXES)   | any root-level file whose name starts with one.                                                                            |
|--------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------|
| [`TITLE_LINES`](#falaw.comfyui.licences.TITLE_LINES)             | How many leading non-blank lines count as a licence's title (room for a copyright line or three above the licence's name). |
| [`RESTRICTED_FAMILY`](#falaw.comfyui.licences.RESTRICTED_FAMILY)       | The AGPL family plus SSPL (same network-copyleft reach).                                                                   |
| [`AGPL_TITLE`](#falaw.comfyui.licences.AGPL_TITLE)              | The AGPL's own upper-case title, flagged wherever it sits in a file.                                                       |
| [`KNOWN_LICENCES`](#falaw.comfyui.licences.KNOWN_LICENCES)          | Licences recognised as *determinable*, looked for in a file's title lines.                                                 |

### Functions

| [`git_head`](#falaw.comfyui.licences.git_head)(pack)                              | The commit checked out in `pack` (`git rev-parse HEAD`); `""` when `pack` is not a git checkout (it cannot be pinned, so it cannot pass).   |
|----------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------|
| [`nodes_digest`](#falaw.comfyui.licences.nodes_digest)(nodes)                         | SHA-256 over the `(pack name, commit)` pairs, order-independent.                                                                            |
| [`screen_licences`](#falaw.comfyui.licences.screen_licences)(nodes_dir, \*[, only, ...]) | Screen every node pack (a directory, or a single `.py` file) under `nodes_dir`.                                                             |

### Classes

| [`LicenceScreen`](#falaw.comfyui.licences.LicenceScreen)(checked_at, nodes_digest[, ...])   | The outcome of [`screen_licences()`](#falaw.comfyui.licences.screen_licences), in manifest shape.   |
|---------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------|

### falaw.comfyui.licences.AGPL_TITLE *= 'GNU AFFERO GENERAL PUBLIC LICENSE'*

The AGPL’s own upper-case title, flagged wherever it sits in a file. GPLv3
section 13 names the licence in mixed case, so this does not flag GPLv3.

### falaw.comfyui.licences.KNOWN_LICENCES *= {'Apache-2.0': 'Apache License,?\\\\s+Version 2', 'BSD': 'Redistribution and use in source and binary forms', 'CC0': 'CC0 1\\\\.0|Creative Commons Zero', 'GPL': 'GNU (?:LESSER |LIBRARY )?GENERAL PUBLIC LICENSE', 'ISC': '\\\\bISC License\\\\b|Permission to use, copy, modify, and/or distribute', 'MIT': '\\\\bMIT License\\\\b|Permission is hereby granted, free of charge', 'MPL-2.0': 'Mozilla Public License', 'Unlicense': 'This is free and unencumbered software', 'WTFPL': 'DO WHAT THE FUCK YOU WANT'}*

Licences recognised as *determinable*, looked for in a file’s title lines.
Text matching none of these is undeterminable, which fails the screen: terms
we cannot read are not a pass. A heuristic by design; what it cannot place
goes to a human.

### falaw.comfyui.licences.LICENCE_FILE_PREFIXES *= ('LICENSE', 'LICENCE', 'COPYING')*

any root-level file whose name starts with one.

* **Type:**
  A pack’s licence files

### *class* falaw.comfyui.licences.LicenceScreen(checked_at, nodes_digest, agpl_packs=(), undeterminable=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The outcome of [`screen_licences()`](#falaw.comfyui.licences.screen_licences), in manifest shape.

#### to_dict()

The `licence_screen` block of the deployment manifest.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### falaw.comfyui.licences.RESTRICTED_FAMILY *= re.compile('AGPL|AFFERO|\\\\bSSPL\\\\b|SERVER SIDE PUBLIC LICENSE', re.IGNORECASE)*

The AGPL family plus SSPL (same network-copyleft reach). Matched against a
file’s title lines and SPDX tags, not its whole text; see `_is_restricted()`.

### falaw.comfyui.licences.TITLE_LINES *= 12*

How many leading non-blank lines count as a licence’s title (room for a
copyright line or three above the licence’s name).

### falaw.comfyui.licences.git_head(pack)

The commit checked out in `pack` (`git rev-parse HEAD`); `""` when
`pack` is not a git checkout (it cannot be pinned, so it cannot pass).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### falaw.comfyui.licences.nodes_digest(nodes)

SHA-256 over the `(pack name, commit)` pairs, order-independent.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### falaw.comfyui.licences.screen_licences(nodes_dir, \*, only=None, commit_of=<function git_head>, clock=<function <lambda>>)

Screen every node pack (a directory, or a single `.py` file) under `nodes_dir`.

`only` restricts the screen to the manifest’s declared packs (a stock
ComfyUI checkout also carries unrelated example nodes under
`custom_nodes/`). `commit_of` reads each pack’s pinned commit (default: its git `HEAD`)
so the returned `nodes_digest` matches
[`nodes_digest()`](#falaw.comfyui.licences.nodes_digest) of the manifest’s `custom_nodes`.

* **Return type:**
  [`LicenceScreen`](#falaw.comfyui.licences.LicenceScreen)
