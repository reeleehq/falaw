# falaw.operations.llm

LLM-driven tools: text completion, screenplay → Scene IR, IR editing.

These wrap fal-ai/any-llm so the agent (or the user) can invoke an LLM
inline as part of a falaw workflow — e.g. parsing a treatment into a
structured Scene, or rewriting a Beat from a directorial note.

We intentionally keep these thin. The contract is: any-llm is the
universal LLM endpoint, you pick the model via `model`, and we return
plain Python (str or parsed dict).

### Functions

| [`apply_note_to_beat`](#falaw.operations.llm.apply_note_to_beat)(beat, note, \*[, model])       | Use the LLM to apply a directorial note to a Beat.                      |
|----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------|
| [`apply_note_to_scene`](#falaw.operations.llm.apply_note_to_scene)(scene, note, \*[, model])     | Apply a cross-cutting note: LLM proposes per-beat edits, we apply them. |
| [`llm_complete`](#falaw.operations.llm.llm_complete)(prompt, \*[, system, model, ...])    | Single-shot LLM completion.                                             |
| [`llm_complete_with_receipt`](#falaw.operations.llm.llm_complete_with_receipt)(prompt, \*[, ...])      | Single-shot LLM completion that also reports what it cost.              |
| [`parse_screenplay`](#falaw.operations.llm.parse_screenplay)(text, \*[, title, style, model]) | Convert prose screenplay text into a Scene IR via an LLM call.          |

### Classes

| [`LlmReceipt`](#falaw.operations.llm.LlmReceipt)(application, model, cache_hit, ...)   | What one eager LLM call cost — the record the eager path never kept.   |
|---------------------------------------------------------------------------------------------------|------------------------------------------------------------------------|

### *class* falaw.operations.llm.LlmReceipt(application, model, cache_hit, chars_in, chars_out, tokens_in=None, tokens_out=None, estimated_cost_usd=None, cost_source='unknown')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What one eager LLM call cost — the record the eager path never kept.

The falaw half of falaw#50’s option B: the eager [`llm_complete()`](#falaw.operations.llm.llm_complete)
returned a bare string, so LLM spend was invisible to every accounting
surface — not because estimates were `None`, but because \*nothing was
recorded at all\* (the field signature: real dollars spent beside
`plans: 0`). A caller that books receipts uses
[`llm_complete_with_receipt()`](#falaw.operations.llm.llm_complete_with_receipt) and gets this alongside the text.

Field semantics, honest by construction:

- `chars_in` / `chars_out` are **measured facts** (prompt+system in,
  response text out).
- `tokens_in` / `tokens_out` are **best-effort** from the raw
  response’s usage block (OpenAI `prompt_tokens`/`completion_tokens`
  and Anthropic `input_tokens`/`output_tokens` shapes, normalized by
  [`falaw.llm_token_counts()`](falaw.html.md#falaw.llm_token_counts), so an Anthropic `tokens_in` counts
  > its cache reads and writes too). `None` means \*unrecorded by the
  > provider response\* (absent or nonsense, e.g. negative), never zero.
- `estimated_cost_usd` is `0.0` on a cache hit (nothing was billed),
  else fal’s published per-request price **for the routed model**, read
  off the rate table ([`falaw.llm_ceiling_usd()`](falaw.html.md#falaw.llm_ceiling_usd)) — an estimate, not
  an observed bill. When the response reports both token counts and the
  routed model has upstream token rates, it is the greater of that price
  and those tokens at the upstream rates (long-prompt tier included,
  falaw#130), the same max-over-bases a plan-time quote takes, so a long
  prompt is not recorded at the flat request price. fal publishes no
  per-token price for any-llm, so that figure is an upstream-rate
  estimate. fal’s documented any-llm output schema (`output`,
  `reasoning`, `partial`, `error`) carries no `usage` block, so
  an any-llm receipt stays at the request price unless a response
  reports usage, which is priced the moment one does. The rate rows carry
  no cache rates, so cache-read tokens are priced at the full input rate:
  for a cached prompt the figure is an upper estimate. It is the routed
  model and not the `fal-ai/any-llm` record because the record carries fal’s *standard* tier, and a premium
  routed model bills ten times that: pricing every turn from the record
  under-reported premium spend tenfold in the ledger a consumer sums
  (falaw#55). `None` only when nothing can price it at all.
- `cost_source` says which of those cases produced the number, so a
  receipt consumer never has to guess: `"cache_hit"`,
  `"rate_table:per_call"`, `"rate_table:upstream_tokens"` (the
  reported tokens at upstream rates exceeded the request price: an
  upstream-rate estimate, not a fal-published price),
  `"registry:<kind>"` (the fallback for a model the table does not
  price), or `"unknown"`.

### falaw.operations.llm.apply_note_to_beat(beat, note, , model='anthropic/claude-sonnet-4.5')

Use the LLM to apply a directorial note to a Beat.

* **Return type:**
  [`Beat`](falaw.scene.html.md#falaw.scene.Beat)

### falaw.operations.llm.apply_note_to_scene(scene, note, , model='anthropic/claude-sonnet-4.5')

Apply a cross-cutting note: LLM proposes per-beat edits, we apply them.

* **Return type:**
  [`Scene`](falaw.scene.html.md#falaw.scene.Scene)

### falaw.operations.llm.llm_complete(prompt, , system='', model='anthropic/claude-sonnet-4.5', temperature=0.7, extra=None)

Single-shot LLM completion. Returns the assistant text.

Delegates to [`llm_complete_with_receipt()`](#falaw.operations.llm.llm_complete_with_receipt) (one argument-construction
site, so the two spellings share one cache identity) and discards the
receipt. A caller that accounts for spend wants the receipt variant.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### falaw.operations.llm.llm_complete_with_receipt(prompt, , system='', model='anthropic/claude-sonnet-4.5', temperature=0.7, extra=None)

Single-shot LLM completion that also reports what it cost.

Same arguments, same wire call, same cache identity as
[`llm_complete()`](#falaw.operations.llm.llm_complete) — the receipt is a side channel, observed from the
call this function was making anyway (the cache layer’s `cache_hit`
event, the response’s usage block, the registry’s estimate). Library
surface only — deliberately NOT a registered tool: the tool surface
keeps the one string-returning `llm_complete`.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`LlmReceipt`](#falaw.operations.llm.LlmReceipt)]

### falaw.operations.llm.parse_screenplay(text, , title='', style='', model='anthropic/claude-sonnet-4.5')

Convert prose screenplay text into a Scene IR via an LLM call.

* **Return type:**
  [`Scene`](falaw.scene.html.md#falaw.scene.Scene)
