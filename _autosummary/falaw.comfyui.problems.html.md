# falaw.comfyui.problems

The one result type every gate check returns.

### Classes

| [`Problem`](#falaw.comfyui.problems.Problem)(item, message)   | One reason a deployment or a graph does not pass.   |
|---------------------------------------------------------------------------|-----------------------------------------------------|

### *class* falaw.comfyui.problems.Problem(item, message)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One reason a deployment or a graph does not pass.

`item` is the checklist row it belongs to (`"1"`..\`\`”11”`, ``"L"`),
so a failure points back at the requirement it breaks.
