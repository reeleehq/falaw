"""Facade item 5: no graph parameter reaches a path unsanitised.

ComfyUI's own input validation is not a defence: a node that defines
``VALIDATE_INPUTS`` switches the engine's checks off for that node, and
CVE-2026-56673 is an arbitrary file read through a ``LoadImage`` parameter. So
the facade checks every literal parameter of a submitted graph itself, against
the ``/object_info`` the engine declared, before anything is sent:

* a **combo** input (a closed list of choices) must hold one of its options;
* any other **string** must carry no path hazard: a NUL, a backslash, a drive
  letter, a leading ``/``, or a ``..`` path segment.

Free-text inputs (a prompt) legitimately contain such characters, so they are
exempt by *name* (:data:`FREE_TEXT_INPUTS`, overridable). The default is the
safe one: any other string is screened, because which strings reach a
filesystem is the custom node's secret, not the schema's.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterator, Mapping
from typing import Any, Optional

from .problems import Problem

FREE_TEXT_INPUTS = frozenset({"text", "prompt", "positive", "negative", "string"})
"""Input names that carry prose, not a path; exempt from the hazard scan."""

_DRIVE_LETTER = re.compile(r"[A-Za-z]:")


class UnsafeGraphError(ValueError):
    """A graph failed the path screen; ``.problems`` lists why."""

    def __init__(self, problems: list[Problem]):
        self.problems = problems
        super().__init__("unsafe ComfyUI graph: " + "; ".join(map(str, problems)))


def _path_hazard(value: str) -> Optional[str]:
    if "\x00" in value:
        return "contains a NUL byte"
    if "\\" in value:
        return "contains a backslash"
    if _DRIVE_LETTER.match(value):
        return "starts with a drive letter"
    if value.startswith("/"):
        return "starts with '/'"
    if ".." in value.split("/"):
        return "has a '..' path segment"
    return None


def _combo_options(spec: Any) -> Optional[list]:
    """The option list of an ``/object_info`` input spec, or ``None`` if not a combo.

    Both spellings occur: the legacy ``[[opt, ...], {...}]`` and the current
    ``["COMBO", {"options": [...]}]``.
    """
    if not isinstance(spec, (list, tuple)) or not spec:
        return None
    head = spec[0]
    if isinstance(head, (list, tuple)):
        return list(head)
    if head == "COMBO" and len(spec) > 1 and isinstance(spec[1], Mapping):
        return list(spec[1].get("options") or ())
    return None


def _is_link(value: Any) -> bool:
    """``[node_id, output_index]``: a wire to another node, not a literal."""
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], (str, int))
        and isinstance(value[1], int)
    )


def _literal_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, (list, tuple)) and not _is_link(value):
        for item in value:
            yield from _literal_strings(item)
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _literal_strings(item)


def _input_specs(node_info: Mapping) -> dict:
    declared = node_info.get("input") or {}
    return {**(declared.get("optional") or {}), **(declared.get("required") or {})}


def check_graph_paths(
    graph: Mapping,
    object_info: Mapping,
    *,
    free_text_inputs: Collection[str] = FREE_TEXT_INPUTS,
) -> list[Problem]:
    """Problems that make ``graph`` unsafe to submit; empty means it may go.

    ``graph`` is ComfyUI's API format ``{node_id: {"class_type", "inputs"}}``;
    ``object_info`` is the engine's ``GET /object_info`` (the facade is the one
    identity allowed to read it).
    """
    out: list[Problem] = []
    for node_id, node in graph.items():
        where = f"node {node_id}"
        node = node if isinstance(node, Mapping) else {}
        class_type = node.get("class_type")
        if class_type not in object_info:
            out.append(Problem("5", f"{where}: unknown class_type {class_type!r}"))
            continue
        specs = _input_specs(object_info[class_type])
        for name, value in (node.get("inputs") or {}).items():
            if _is_link(value):
                continue
            if name not in specs:
                out.append(
                    Problem(
                        "5", f"{where} ({class_type}): input {name!r} is not declared"
                    )
                )
                continue
            options = _combo_options(specs[name])
            if options is not None and value not in options:
                out.append(
                    Problem(
                        "5",
                        f"{where} ({class_type}).{name}: {value!r} is not one of the declared options",
                    )
                )
                continue
            if name in free_text_inputs and options is None:
                continue
            for text in _literal_strings(value):
                hazard = _path_hazard(text)
                if hazard:
                    out.append(
                        Problem(
                            "5", f"{where} ({class_type}).{name}: {text!r} {hazard}"
                        )
                    )
    return out


def assert_safe_graph(
    graph: Mapping,
    object_info: Mapping,
    *,
    free_text_inputs: Collection[str] = FREE_TEXT_INPUTS,
) -> None:
    """Raise :class:`UnsafeGraphError` unless :func:`check_graph_paths` is empty."""
    problems = check_graph_paths(graph, object_info, free_text_inputs=free_text_inputs)
    if problems:
        raise UnsafeGraphError(problems)
