# falaw.bridges.mcp

MCP bridge: expose every falaw tool as an MCP tool.

Like `bridges/skill.py`, this is a thin adapter over
`falaw.registry.list_tools()` — adding a new falaw tool automatically adds
an MCP tool, no edit here. Built on `fastmcp` (the federation’s MCP library;
see `lookbook/mcp.py` for the canonical pattern).

Two entry points:

- [`register_tools()`](#falaw.bridges.mcp.register_tools) — add falaw’s tools to an *existing* `FastMCP`
  server. This is what an **aggregating** server (reelee’s MCP server, which
  composes falaw + nw + artful + lacing) calls.
- [`build_mcp_server()`](#falaw.bridges.mcp.build_mcp_server) — build a *standalone* `FastMCP` server exposing
  just falaw. [`serve()`](#falaw.bridges.mcp.serve) runs it over stdio.

The server’s `instructions` reach the model before any tool call, so they are
behaviour-driving text and are guarded like code:
[`unresolved_tool_references()`](#falaw.bridges.mcp.unresolved_tool_references) reports every tool name or `name_*` family
a piece of prose names that the registry does not hold. An aggregating server
should run it over its own composed preamble too.

`fastmcp` is an optional dependency: `pip install falaw[mcp]`.

### Module Attributes

| [`FREE_TAG`](#falaw.bridges.mcp.FREE_TAG)     | Tag marking a tool that makes **no** vendor call — docs/registry upkeep only.                                   |
|---------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------|
| [`COSTED_TOOLS`](#falaw.bridges.mcp.COSTED_TOOLS) | Snapshot of [`costed_tools()`](#falaw.bridges.mcp.costed_tools) for consumers that want a constant. |

### Functions

| [`build_mcp_server`](#falaw.bridges.mcp.build_mcp_server)(\*[, name, tools])                | Build a standalone `FastMCP` server exposing every falaw tool.      |
|-----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------|
| [`costed_tools`](#falaw.bridges.mcp.costed_tools)()                                     | Names of the falaw tools that spend money — the metering SSOT.      |
| [`register_tools`](#falaw.bridges.mcp.register_tools)(server, \*[, tools, prefix])        | Register every falaw `ToolSpec` on `server` (a `FastMCP`).          |
| [`serve`](#falaw.bridges.mcp.serve)(\*[, transport])                             | Run the standalone falaw MCP server.                                |
| [`unresolved_tool_references`](#falaw.bridges.mcp.unresolved_tool_references)(text, \*[, tool_names]) | Tool names and `name_*` families named in `text` that do not exist. |

### falaw.bridges.mcp.COSTED_TOOLS *= ('animate_face', 'apply_note_to_beat', 'apply_note_to_scene', 'cast_character', 'cast_voice', 'composite_character_in_environment', 'edit_image', 'establish_environment', 'generate_audio', 'generate_image', 'generate_image_with_control', 'generate_image_with_refs', 'image_to_video', 'lipsync', 'llm_complete', 'parse_screenplay', 'remove_background', 'render_beat', 'render_scene', 'render_shot', 'storyboard_shot', 'talking_avatar_from_text', 'text_to_speech', 'text_to_video', 'upscale_image', 'voice_clone')*

Snapshot of [`costed_tools()`](#falaw.bridges.mcp.costed_tools) for consumers that want a constant. Prefer
the function when tools may be registered after import.

### falaw.bridges.mcp.FREE_TAG *= 'maintenance'*

Tag marking a tool that makes **no** vendor call — docs/registry upkeep only.
Everything else reaches fal.ai or an LLM and therefore spends money.

### falaw.bridges.mcp.build_mcp_server(, name='falaw', tools=None)

Build a standalone `FastMCP` server exposing every falaw tool.

Raises `ImportError` with an install hint if `fastmcp` is missing.

### falaw.bridges.mcp.costed_tools()

Names of the falaw tools that spend money — the metering SSOT.

Every genre package in the federation exposes this so an aggregating
connector can gate spend from one source of truth per package
(`braidio.mcp.COSTED_TOOLS`, `muvid.mcp.COSTED_TOOLS`). falaw had
none, so its 24 money-spending tools — the *raw* fal.ai operations,
including `text_to_video` and `render_scene` — reached an aggregating
connector completely unmetered (thorwhalen/reelee#265).

**Derived from the registry, not hand-listed**, matching this module’s
existing contract that adding a falaw tool needs no edit here. The
consequence is the safe one: a newly-registered tool is \*\*costed by
default\*\* and must be explicitly tagged [`FREE_TAG`](#falaw.bridges.mcp.FREE_TAG) to be exempt.
Forgetting the tag over-meters a free tool (annoying); the inverse would
let a new money-spender through a credit cap (a billing hole).

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

### falaw.bridges.mcp.register_tools(server, , tools=None, prefix='')

Register every falaw `ToolSpec` on `server` (a `FastMCP`).

* **Parameters:**
  * **server** ([`Any`](https://docs.python.org/3/library/typing.html#typing.Any)) – A `fastmcp.FastMCP` instance (or anything with a compatible
    `.tool(fn, *, name, description, tags)` method).
  * **tools** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`ToolSpec`](falaw.base.html.md#falaw.base.ToolSpec)]]) – The tools to register; defaults to the whole falaw registry.
  * **prefix** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Optional name prefix (e.g. `"falaw_"`) so an aggregating
    server can namespace falaw’s tools away from another package’s.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
* **Returns:**
  The MCP tool names registered (in registry order).

### falaw.bridges.mcp.serve(, transport='stdio', \*\*kwargs)

Run the standalone falaw MCP server.

stdio is the default transport — what Claude Desktop and the Anthropic SDK
expect when launching an MCP server as a subprocess.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### falaw.bridges.mcp.unresolved_tool_references(text, , tool_names=None)

Tool names and `name_*` families named in `text` that do not exist.

Behaviour-driving prose — the server `instructions`, a tool description,
an aggregating connector’s composed preamble — names tools, and a call-site
sweep cannot see prose. Nothing derives one from the other, so nothing
failed when `_INSTRUCTIONS` spent months telling every model to
“use the `plan_*` tools to inspect cost before spending” while the
registry held no such tool (thorwhalen/falaw#47). This is the check that
now fails instead.

* **Parameters:**
  * **text** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The prose to scan.
  * **tool_names** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – The names that count as existing; defaults to the falaw
    registry. An aggregating server that registered falaw under a
    prefix should pass what [`register_tools()`](#falaw.bridges.mcp.register_tools) returned, so
    `falaw_generate_image` resolves.
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]
* **Returns:**
  The unresolved references, deduplicated, in order of first appearance.

```pycon
>>> unresolved_tool_references("Use the refresh_* tools.")
()
>>> unresolved_tool_references("Use the plan_* tools to inspect cost.")
('plan_*',)
```
