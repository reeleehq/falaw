# falaw.comfyui.graph

Facade item 5: no graph parameter reaches a path unsanitised.

ComfyUI’s own input validation is not a defence: a node that defines
`VALIDATE_INPUTS` switches the engine’s checks off for that node, and
CVE-2026-56673 is an arbitrary file read through a `LoadImage` parameter. So
the facade checks every literal parameter of a submitted graph itself, against
the `/object_info` the engine declared, before anything is sent:

* a **combo** input (a closed list of choices) must hold one of its options;
* any other **string** must carry no path hazard: a NUL, a backslash, a drive
  letter, a leading `/`, or a `..` path segment (leading whitespace is
  ignored, dictionary keys are screened too).

Prose boxes legitimately contain such characters, so a **multiline** `STRING`
input (the engine’s own marker for a text area) is exempt, as is anything in
the `free_text` seam (`(class_type, input)` pairs). The exemption is
withdrawn for a node whose output is wired into any non-exempt input: a prompt
node feeding a path is a path. The default is the safe one: any other string is
screened, because which strings reach a filesystem is the custom node’s secret,
not the schema’s.

The facade must re-fetch `/object_info` after each `/upload/image`, or every
newly uploaded `LoadImage` filename is (correctly) absent from its combo.

### Module Attributes

| [`FREE_TEXT`](#falaw.comfyui.graph.FREE_TEXT)   | Extra `(class_type, input)` pairs to exempt beyond multiline strings.   |
|--------------------------------------------------------------|-------------------------------------------------------------------------|

### Functions

| [`assert_safe_graph`](#falaw.comfyui.graph.assert_safe_graph)(graph, object_info, \*[, ...])   | Raise [`UnsafeGraphError`](#falaw.comfyui.graph.UnsafeGraphError) unless [`check_graph_paths()`](#falaw.comfyui.graph.check_graph_paths) is empty.   |
|-----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`check_graph_paths`](#falaw.comfyui.graph.check_graph_paths)(graph, object_info, \*[, ...])   | Problems that make `graph` unsafe to submit; empty means it may go.                                                                                             |

### Exceptions

| [`UnsafeGraphError`](#falaw.comfyui.graph.UnsafeGraphError)(problems)   | A graph failed the path screen; `.problems` lists why.   |
|-------------------------------------------------------------------------------|----------------------------------------------------------|

### falaw.comfyui.graph.FREE_TEXT *: [frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset)[[tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [str](https://docs.python.org/3/builtins/stdtypes.html#str)]]* *= frozenset({})*

Extra `(class_type, input)` pairs to exempt beyond multiline strings.

### *exception* falaw.comfyui.graph.UnsafeGraphError(problems)

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

A graph failed the path screen; `.problems` lists why.

### falaw.comfyui.graph.assert_safe_graph(graph, object_info, , free_text=frozenset({}))

Raise [`UnsafeGraphError`](#falaw.comfyui.graph.UnsafeGraphError) unless [`check_graph_paths()`](#falaw.comfyui.graph.check_graph_paths) is empty.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### falaw.comfyui.graph.check_graph_paths(graph, object_info, , free_text=frozenset({}))

Problems that make `graph` unsafe to submit; empty means it may go.

`graph` is ComfyUI’s API format `{node_id: {"class_type", "inputs"}}`;
`object_info` is the engine’s `GET /object_info` (the facade is the one
identity allowed to read it).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Problem`](falaw.comfyui.problems.html.md#falaw.comfyui.problems.Problem)]
