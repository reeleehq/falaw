# falaw

Agent-friendly Python facade over fal.ai for AI media generation (image, video,
audio, avatar) — single-shot calls, a directorial `Scene` IR with per-beat caching,
cost estimation/repricing, and an agent journal for cross-session notes.

## Module map (`falaw/`)

- `core.py` — `call_fal`: the one wrapper over `fal_client.subscribe` every
  operation should call (progress events, auto-journaling).
- `operations/` — the actual generation calls: `images.py`, `video.py`, `audio.py`,
  `avatar.py`, `llm.py`, `preproduction.py`, `render.py`, `_plan.py`.
- `plan.py` / `outcomes.py` — Plan/Execute: separates planning (data,
  `CallPlan`/`Plan`) from execution (effects); `execute_plan` reads back asset
  bytes for content addressing.
- `scene.py` — the Scene IR: an editable structure (characters/beats/shots) that
  survives to the pixels; `cost.py` rolls up per-model cost estimates over it.
- `cache.py` — content-addressed cache for fal calls (the "edit one beat,
  re-render only that beat" property). `canonical.py` is the one canonical
  byte-form falaw hashes from (falaw#17). `content.py` is content addressing for
  fal-produced media. `prune.py` manages cache disk capacity (falaw#14).
- `backends.py` — execution backend registry `CallPlan.backend` dispatches
  through (falaw#15) — not a single hardcoded vendor-call path.
- `base.py` — `ToolSpec`/`ModelRecord`, the SSOT every external surface derives from.
- `registry.py` — tool/model registries, queryable by tags/categories.
- `pricing.py` / `llm_rates.py` / `reprice.py` — cost-estimate ingestion from
  fal's pricing API, per-routed-model LLM rate ceilings (falaw#50), and
  re-quoting a persisted Plan at today's rates (falaw#60).
- `account.py` — account health probe (works around `fal_client` swallowing 403 bodies).
- `journal.py` — append-only agent notes log.
- `terms.py` — the terms ledger (falaw#16): per-`(model, backend)` rows in `data/model_terms.json`, `check_terms` at plan time via `plan_*(..., terms_context=TermsContext(...))` and at execution via `execute(..., terms_context=)`; `unknown` and *no row* refuse. `using_terms_context(ctx)` gates every eager verb (enforced in `cached_call_fal`/`call_fal`); routers are judged by the routed model; cleared plans carry `metadata["terms_cleared"]` (`is_cleared`).
- `licences.py` — the one SPDX/`LicenseRef-*` vocabulary the terms ledger and `comfyui/licences.py` validate against (falaw#110). `unreviewed_models()` lists what still needs a human read.
- `degrade.py` — the one collection point for "carried on, but you should know".
- `testing.py` — **the fake asset transport** (see Invariants).
- `comfyui/` — the executable ComfyUI deployment gate (falaw#94): `check_manifest`, `screen_licences`, `check_graph_paths`, `submit_graph` + audit sink. Pure checks; every external fact is a keyword seam.
- `bridges/` — `mcp.py`, `service.py`, `skill.py` — non-Python-import surfaces.

## Tests & lint (verified)

```bash
uv venv .venv && uv pip install -e . pytest ruff
env -u FAL_KEY .venv/bin/pytest -q    # 605 passed, 2 skipped — no network, no key needed
.venv/bin/ruff check .
```
Or `wads ci-local` (Python 3.10+3.12, Windows included).

## Invariants

- **Every media result is content-addressed** (`falaw.content`): fal URLs are
  neither unique nor durable, so `execute_plan` reads the actual bytes.
- **Never write a test that stubs the fal response but not the asset transport**
  — it will silently reach the real network for the (made-up) URL and pass
  anyway. Use `falaw.testing.fake_assets` / `isolated_falaw_cache` (autouse
  fixtures, re-exportable in one line) — see `falaw/testing.py`'s module
  docstring and the `reelee-live-api-testing` skill for the general pattern.
  A failed asset fetch degrades to a URL-only artifact with a `UserWarning`
  rather than raising, so this failure mode is easy to miss without the guard.

## Docs & skills

- `.claude/skills/falaw` — shipped operator/agent skill.
- `misc/docs/roadmap.md`, `misc/docs/fal_ai_docs_*` — fal.ai API reference + roadmap.

## Dependents

`nw` and `reelee` import this package — check their tests before changing any
public operation's signature or return shape.
