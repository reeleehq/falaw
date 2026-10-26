# falaw.licences

One licence vocabulary for every falaw ledger (falaw#110).

Licences are named by an SPDX identifier where one exists and by a
`LicenseRef-*` identifier (SPDX’s own convention for bespoke terms) where it
does not. The terms ledger ([`falaw.terms`](falaw.terms.html.md#module-falaw.terms)) and the ComfyUI licence screen
([`falaw.comfyui.licences`](falaw.comfyui.licences.html.md#module-falaw.comfyui.licences)) validate against this one definition, so the
same licence is never spelled two ways.

The SPDX list is deliberately a curated subset ([`SPDX_IDS`](#falaw.licences.SPDX_IDS)): the ids the
ledgers actually use. Add one here when a row needs it, rather than pulling in
the full list as a dependency.

```pycon
>>> is_valid_licence("Apache-2.0")
True
>>> is_valid_licence("MIT OR Apache-2.0")
True
>>> is_valid_licence("flux-1-dev-non-commercial-license")
False
```

### Module Attributes

| [`SPDX_IDS`](#falaw.licences.SPDX_IDS)   | //spdx.org/licenses/).                                      |
|-------------------------------------------------------------|-------------------------------------------------------------|
| [`UNKNOWN`](#falaw.licences.UNKNOWN)    | The licence nobody has read yet; a ledger row may carry it. |

### Functions

| [`is_valid_licence`](#falaw.licences.is_valid_licence)(expression, \*[, known])   | Whether *expression* is `unknown`, or ids from *known* / `LicenseRef-*` joined by `AND` / `OR`.   |
|----------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------|
| [`validate_licence`](#falaw.licences.validate_licence)(expression, \*[, known])   | *expression* itself, or `ValueError` saying how to spell it.                                      |

### falaw.licences.SPDX_IDS *= frozenset({'AGPL-3.0-only', 'Apache-2.0', 'BSD-2-Clause', 'BSD-3-Clause', 'CC-BY-4.0', 'CC-BY-NC-4.0', 'CC-BY-SA-4.0', 'CC0-1.0', 'GPL-2.0-only', 'GPL-3.0-only', 'GPL-3.0-or-later', 'ISC', 'LGPL-2.1-only', 'LGPL-3.0-only', 'MIT', 'MPL-2.0', 'Unlicense', 'WTFPL'})*

//spdx.org/licenses/).

* **Type:**
  Standard SPDX ids falaw’s ledgers use (https

### falaw.licences.UNKNOWN *= 'unknown'*

The licence nobody has read yet; a ledger row may carry it.

### falaw.licences.is_valid_licence(expression, , known=frozenset({'AGPL-3.0-only', 'Apache-2.0', 'BSD-2-Clause', 'BSD-3-Clause', 'CC-BY-4.0', 'CC-BY-NC-4.0', 'CC-BY-SA-4.0', 'CC0-1.0', 'GPL-2.0-only', 'GPL-3.0-only', 'GPL-3.0-or-later', 'ISC', 'LGPL-2.1-only', 'LGPL-3.0-only', 'MIT', 'MPL-2.0', 'Unlicense', 'WTFPL'}))

Whether *expression* is `unknown`, or ids from *known* / `LicenseRef-*`
joined by `AND` / `OR`.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### falaw.licences.validate_licence(expression, , known=frozenset({'AGPL-3.0-only', 'Apache-2.0', 'BSD-2-Clause', 'BSD-3-Clause', 'CC-BY-4.0', 'CC-BY-NC-4.0', 'CC-BY-SA-4.0', 'CC0-1.0', 'GPL-2.0-only', 'GPL-3.0-only', 'GPL-3.0-or-later', 'ISC', 'LGPL-2.1-only', 'LGPL-3.0-only', 'MIT', 'MPL-2.0', 'Unlicense', 'WTFPL'}))

*expression* itself, or `ValueError` saying how to spell it.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
