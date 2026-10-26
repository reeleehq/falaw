"""Facade item 5: no graph parameter reaches a path unsanitised.

ComfyUI's own input validation is not a defence: a node that defines
``VALIDATE_INPUTS`` switches the engine's checks off for that node, and
CVE-2026-56673 is an arbitrary file read through a ``LoadImage`` parameter. So
the facade checks every literal parameter of a submitted graph itself, against
the ``/object_info`` the engine declared, before anything is sent:

* a **combo** input (a closed list of choices) must hold one of its options;
* any other **string** must carry no path hazard: a NUL, a backslash, a drive
  letter, a leading ``/``, or a ``..`` path segment (leading whitespace is
  ignored, dictionary keys are screened too).

Prose boxes legitimately contain such characters, so a **multiline** ``STRING``
input (the engine's own marker for a text area) is exempt, as is anything in
the ``free_text`` seam (``(class_type, input)`` pairs). The exemption is
withdrawn for a node whose output is wired into any non-exempt input: a prompt
node feeding a path is a path. The default is the safe one: any other string is
screened, because which strings reach a filesystem is the custom node's secret,
not the schema's.

The facade must re-fetch ``/object_info`` after each ``/upload/image``, or every
newly uploaded ``LoadImage`` filename is (correctly) absent from its combo.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterator, Mapping
from typing import Any, Optional

from .problems import Problem

FREE_TEXT: frozenset[tuple[str, str]] = frozenset()
"""Extra ``(class_type, input)`` pairs to exempt beyond multiline strings."""

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
    value = value.lstrip()
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


def _link_source(value: Any, node_ids: Collection[str]) -> Optional[str]:
    """The node id a ``[node_id, output_index]`` wire points at, or ``None``.

    Only a list whose first element is a node *of this graph* is a wire; any
    other two-element list is a literal and is screened like one.
    """
    if (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], (str, int))
        and not isinstance(value[0], bool)
        and isinstance(value[1], int)
        and str(value[0]) in node_ids
    ):
        return str(value[0])
    return None


def _literal_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _literal_strings(item)
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from _literal_strings(key)
            yield from _literal_strings(item)


def _input_specs(node_info: Any) -> dict:
    declared = node_info.get("input") if isinstance(node_info, Mapping) else None
    declared = declared if isinstance(declared, Mapping) else {}
    return {
        **_mapping(declared.get("optional")),
        **_mapping(declared.get("required")),
    }


def _mapping(value: Any) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _takes_strings(spec: Any) -> bool:
    """Whether an input could receive a wired string: a STRING, a wildcard, a
    combo, or one the engine did not declare."""
    if spec is None or _combo_options(spec) is not None:
        return True
    return isinstance(spec, (list, tuple)) and bool(spec) and spec[0] in ("STRING", "*")


def _is_multiline(spec: Any) -> bool:
    return (
        isinstance(spec, (list, tuple))
        and len(spec) > 1
        and spec[0] == "STRING"
        and isinstance(spec[1], Mapping)
        and spec[1].get("multiline") is True
    )


def _nodes(graph: Mapping) -> Iterator[tuple[str, str, Any]]:
    """``(node_id, class_type, inputs)`` for each node with a string class_type."""
    for node_id, node in graph.items():
        if isinstance(node, Mapping) and isinstance(node.get("class_type"), str):
            yield str(node_id), node["class_type"], node.get("inputs")


def _prose_and_taint(nodes, object_info, node_ids, free_text):
    """``(exempt, tainted)``: which ``(node, input)`` hold prose, and which nodes'
    output ends up in a screened input, directly or through other string nodes.

    A wire only carries a path if the input receiving it takes strings, so a
    prompt wired into a sampler's CONDITIONING stays prose.
    """
    exempt: set[tuple[str, str]] = set()
    edges: list[tuple[str, str, str]] = []  # (source, receiving node, input)
    for node_id, class_type, inputs in nodes:
        specs = _input_specs(object_info.get(class_type))
        for name, value in inputs.items():
            if _is_multiline(specs.get(name)) or (class_type, name) in free_text:
                exempt.add((node_id, name))
            source = _link_source(value, node_ids)
            if source is not None and _takes_strings(specs.get(name)):
                edges.append((source, node_id, name))
    tainted = {src for src, dst, name in edges if (dst, name) not in exempt}
    while grew := {src for src, dst, _ in edges if dst in tainted} - tainted:
        tainted |= grew
    return exempt, tainted


def check_graph_paths(
    graph: Mapping,
    object_info: Mapping,
    *,
    free_text: Collection[tuple[str, str]] = FREE_TEXT,
) -> list[Problem]:
    """Problems that make ``graph`` unsafe to submit; empty means it may go.

    ``graph`` is ComfyUI's API format ``{node_id: {"class_type", "inputs"}}``;
    ``object_info`` is the engine's ``GET /object_info`` (the facade is the one
    identity allowed to read it).
    """
    if not isinstance(graph, Mapping):
        return [Problem("5", "a graph must be a mapping of node ids to nodes")]
    if not isinstance(object_info, Mapping):
        return [Problem("5", "object_info must be the engine's /object_info mapping")]
    out: list[Problem] = []
    node_ids = {str(k) for k in graph}
    nodes = list(_nodes(graph))
    for node_id in node_ids - {n[0] for n in nodes}:
        out.append(Problem("5", f"node {node_id}: needs a string class_type"))
    for node_id, class_type, inputs in nodes:
        if not isinstance(inputs, Mapping):
            out.append(
                Problem("5", f"node {node_id} ({class_type}): inputs must be a mapping")
            )
    nodes = [(i, c, inp) for i, c, inp in nodes if isinstance(inp, Mapping)]

    exempt, tainted = _prose_and_taint(nodes, object_info, node_ids, free_text)

    for node_id, class_type, inputs in nodes:
        where = f"node {node_id} ({class_type})"
        if class_type not in object_info:
            out.append(Problem("5", f"{where}: unknown class_type"))
            continue
        specs = _input_specs(object_info[class_type])
        for name, value in inputs.items():
            if _link_source(value, node_ids) is not None:
                continue
            if name not in specs:
                out.append(Problem("5", f"{where}: input {name!r} is not declared"))
                continue
            options = _combo_options(specs[name])
            if options is not None and value not in options:
                out.append(
                    Problem(
                        "5",
                        f"{where}.{name}: {value!r} is not one of the declared options",
                    )
                )
                continue
            if (node_id, name) in exempt and node_id not in tainted:
                continue
            for text in _literal_strings(value):
                hazard = _path_hazard(text)
                if hazard:
                    out.append(Problem("5", f"{where}.{name}: {text!r} {hazard}"))
    return out


def assert_safe_graph(
    graph: Mapping,
    object_info: Mapping,
    *,
    free_text: Collection[tuple[str, str]] = FREE_TEXT,
) -> None:
    """Raise :class:`UnsafeGraphError` unless :func:`check_graph_paths` is empty."""
    problems = check_graph_paths(graph, object_info, free_text=free_text)
    if problems:
        raise UnsafeGraphError(problems)
