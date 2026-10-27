---
name: falaw
description: >-
  Generate and manage AI media (images, video, audio) via fal.ai. Use this
  skill whenever the user wants to generate, edit, upscale, or compose media,
  or asks about fal.ai or fal-client. Also use it for *directorial* workflows:
  the user defines a Scene as data (characters, beats, shots) and falaw renders
  it with caching, so a single edit re-renders only what changed.
---

# falaw

Two ways to use `falaw`:

1. **Single-shot operations** --- `generate_image`, `text_to_speech`, etc. for
   one-off media generation.
2. **Directorial workflow** --- author a Scene as data, render it, give notes
   that re-edit the Scene, re-render only the affected beats. This is the path
   to *direct* a film instead of just *generate* clips.

## Directorial workflow (when the user wants to "plan, parametrize, render")

The thesis: keep the film in *editable structure* all the way down to the
pixels. The creator authors a Scene as data; a directorial note becomes a
single IR edit; the renderer caches everything content-addressed so unchanged
beats don't re-render.

### Phase 1: Plan (LLM-assisted or hand-built)

```python
from falaw import parse_screenplay, Scene, Character, Environment, make_beat, make_shot

# Option A: feed prose / treatment text and let any-llm draft the structure.
scene = parse_screenplay(
    prose_text, title="Diner Encounter", style="Wes-Anderson pastel"
)

# Option B: build the Scene directly.
scene = Scene(
    title="Diner Encounter",
    style="Wes-Anderson symmetrical pastel",
    characters=(Character(name="Sarah", description="mid-30s, dark curly hair"),),
    environments=(
        Environment(
            name="diner", description="1950s chrome diner", time_of_day="midnight"
        ),
    ),
    shots=(
        make_shot(
            "two-shot at the booth",
            framing="medium",
            environment="diner",
            characters=("Sarah", "Tom"),
            index=0,
        ),
    ),
    beats=(
        make_beat("Sarah", "Why are you here?", shot_id="...", emotion="wary", index=0),
        make_beat("Tom", "I came to apologize.", index=1),
    ),
)
```

### Phase 2: Parametrize (set identity anchors)

Cast each character with a *canonical* face and voice. These anchors get
reused for every shot/beat that character appears in --- this is what gives
identity continuity.

```python
from falaw import cast_character, establish_environment

sarah = cast_character(
    "Sarah",
    "mid-30s, dark curly hair, wary eyes",
    reference_audio_url="https://.../sarah_sample.wav",
)
diner = establish_environment(
    "diner",
    "1950s chrome diner, neon outside, half-empty booths",
    time_of_day="midnight",
    lighting="cool fluorescents",
)
scene = scene.with_character(sarah).with_environment(diner)
```

### Phase 3: Render (caches; re-edits are cheap)

```python
from falaw import render_scene, save_scene

manifest = render_scene(scene)  # all beats + shots
save_scene(scene, "out/diner_v1.json")  # snapshot the IR alongside
```

### Phase 4: Direct (notes -> IR edits -> re-render)

```python
from falaw import apply_note_to_beat

# Pick the beat to direct.
beat = scene.beat("002-tom-...")
edited = apply_note_to_beat(beat, "He cracks on this line; tries to hide it.")
scene2 = scene.with_beat(edited)
manifest2 = render_scene(scene2)  # only the edited beat re-renders;
# the rest are cache hits.
```

For cross-cutting notes like "tighten the pacing", use
`apply_note_to_scene(scene, note)`. For non-LLM edits, just construct the
new dataclass yourself --- everything is frozen so `dataclasses.replace`
works.

### Local stitching

`falaw.local` (requires ffmpeg) stitches the per-beat lipsynced clips into
a watchable scene:

```python
from falaw.local import concatenate_clips

concatenate_clips(
    [m["url"] for m in manifest["beats"]], output_path="out/scene.mp4", transition_s=0.2
)
```

### Reference images and local files: falaw checks, you don't have to

falaw caches `url -> content hash`, but only a **fal** URL can be trusted
outright (fal mints one per upload, so it never re-points at other bytes).
Anything else --- a reference image on your own server, a `file://` clip you
re-rendered to the same path --- is **revalidated** before reuse:

```python
falaw.materialize_asset("https://mysite.com/reference.png")
# changed on the server? you get the new bytes and a new content hash.
# unchanged? one conditional request, no download.
```

You do **not** need to pass `refresh=True` for a mutable URL any more. If falaw
cannot check (the origin offers no `ETag`/`Last-Modified`, or you injected a
transport with no conditional-request support) it re-downloads rather than
trusting a hint it cannot verify. If the origin is *gone*, it falls back to the
bytes it already stored and warns.

Serving your own media from an immutable-by-construction store? Add the host so
falaw skips the check:

```python
from falaw.content import IMMUTABLE_URL_HOSTS

IMMUTABLE_URL_HOSTS.add("cdn.mysite.com")  # only if you mint URLs per upload
```

### The cache holds bytes now --- keep an eye on the disk

Since falaw#14 the cache content-addresses every result, so it stores the
**bytes** of every image, clip and audio track, not just JSON manifests. On a
machine that has rendered a real project that is gigabytes.

```python
import falaw

print(falaw.cache_usage().summary())  # per-area breakdown, largest first
```

Six areas, and only one of them is cheap to reclaim:

| area | dropping one costs | prunable |
|---|---|---|
| `assets` | **nothing**, while the blob survives (it is a *copy*) --- reclaim here first | yes |
| `content` | a **re-render**, for any call whose fal URL has since expired | yes |
| `manifests` | a **re-billed call**, unconditionally | yes |
| `url_index` | **the whole content area.** Blobs are reachable *only* through this index, so deleting it orphans them: expired-URL entries re-render while their bytes sit unreachable on disk | no |
| `scenes` | authored Scene IR --- lost work, not a re-render | no |
| `other` | unknown; falaw did not put it there | no |

So eviction is a spending decision, and nothing runs automatically. Every
prune is a dry run unless you say otherwise, and refuses to run unbounded
(or with a non-positive `older_than`, which is almost always a computed-zero
bug that would wipe the area):

```python
from datetime import timedelta

report = falaw.prune_assets(older_than=timedelta(days=30))  # dry run
print(report.summary())
falaw.prune_assets(older_than=timedelta(days=30), dry_run=False)
```

**Read the two warning numbers before passing `dry_run=False`:**

- `report.rebillable_entries` --- cache entries the prune puts back on the
  invoice (an upper bound).
- `report.unreferenced_candidates` --- blobs **no cache entry points at**.
  falaw cannot tell garbage from the last copy of a reference image you
  materialized, so it reports them rather than calling the prune free.

`report.freed_bytes` counts what was actually deleted, so a failed deletion
does not read as reclaimed space. `prune_content` and `prune_manifests` take
the same arguments; `max_bytes=N` evicts oldest-first until the area fits.

### execute_plan: three cache modes --- a re-run is not a cache bypass

`execute_plan(plan)` reads the cache and writes it. `execute_plan(plan, refresh=True)`
skips the read and **keeps the write** --- this is the one to use behind a "redo it"
or "re-verify this" switch. `execute_plan(plan, use_cache=False)` does neither, so it
throws away the result it just paid for and the next caller re-bills; reach for it only
when you truly want no cache interaction. Both together raises: nothing to key a write on.

### plan_llm_complete quotes a ceiling for the *routed* model

`fal-ai/any-llm` is one endpoint routing thirty models at two published request
tiers, so its single registry price under-quotes every premium model tenfold ---
including falaw's own default, `anthropic/claude-sonnet-4.5`. Planned LLM calls
price the `model` argument against `falaw/data/llm_rates.json` instead:

```python
from falaw import plan_llm_complete, llm_ceiling_usd

plan_llm_complete(prompt).estimated_cost_usd  # fal's request price for the model
plan_llm_complete(prompt, input_tokens=180_000, max_output_tokens=8_000)
# -> max(request price, upstream per-token cost of that prompt capped there)
```

Give both hints or neither. Half a bound is not a ceiling, so one hint alone ---
and a model the table does not price --- yields `estimated_cost_usd=None`, which
lights up `Plan.has_unknown_costs` and forces approval rather than quietly
quoting the router's flat price. `input_tokens` is what opts in: pass it and
`max_output_tokens` defaults to the `max_tokens` already in your `extra`; pass
neither and a capped call still quotes the request price. Hints are
estimator-only: adding one never moves the cache key or the plan hash.

The eager `llm_complete_with_receipt` prices the same way --- a receipt for a
premium routed model reads $0.01 with `cost_source="rate_table:per_call"`, or more
with `cost_source="rate_table:upstream_tokens"` when the response reports usage and
those tokens at the routed model's upstream rates exceed that, so a ledger that sums
receipts and a gate that reads quotes agree. That figure is an upstream-rate
estimate (fal publishes no per-token price), and fal's documented any-llm output
carries no `usage`, so receipts read the request price until a response reports it.

Rates move. Every row carries its own `source` and `date` (`llm_rates.json`);
### A saved plan's price is a past fact --- re-quote it before you gate on it

Rates move, and 0.0.46 moved the LLM table **tenfold upward**. A plan you
persisted last month still carries last month's `estimated_cost_usd`, so
gating today's spend on it under-quotes --- the one direction a cost gate must
never err in. Every `plan_*` records how it priced each call in
`CallPlan.cost_basis` (which pricer, which rate table and version, and the
quantity hints --- a clip's `duration_s`, a prompt's token bounds --- that
never enter `arguments`), so the quote can be re-run:

```python
from falaw import plan_from_dict, reprice_plan

# frozen figures from plan time; re-quoting is pure data (no network, no cache peek)
out = reprice_plan(plan_from_dict(saved_row))

out.plan  # same calls, same plan_hash, today's costs
out.known_delta_usd  # how much the priced part moved
[(c.index, c.status, c.old_cost_usd, c.new_cost_usd) for c in out.changed]
```

Four per-call statuses: `unchanged`, `changed`, `unknown` (a basis that
today's tables cannot price --- a retired model, an unregistered pricer), and
`no_basis` (a plan saved before falaw#60, or built by something that recorded
nothing). **The last two clear the call's cost to `None`.** A stale number
re-presented as a current quote is the bug this exists to fix, so `no_basis`
is reported, never trusted --- read `out.unpriced` and refuse the gate, the
same judgement `Plan.has_unknown_costs` asks for.

`c.basis_changed` answers the audit question the frozen number never could:
did the price move because the *rate table* moved?

Quoted a call against your own `llm_rates=` table? Its basis says so, and
falaw's table will **not** re-quote it --- it comes back `unknown`. Two tables
are two sets of books, and re-pricing your reconciled $0.50 row at falaw's
published $0.01 would be a 50x under-quote wearing the clothes of a price
drop. Bring your own books instead:

```python
from falaw import DFLT_PRICERS, Pricer, llm_ceiling_usd
from falaw.llm_rates import CUSTOM_LLM_RATES_TABLE

mine = Pricer(
    quote=lambda b: llm_ceiling_usd(b.priced, rates=my_table, **b.quantities),
    table=CUSTOM_LLM_RATES_TABLE,  # must match the basis, or it is refused
    version=lambda: "2026-09",
)
reprice_plan(plan, pricers={**DFLT_PRICERS, "llm_rates": mine})
```

Rates move. Every row carries its own `source` and `date` (`llm_rates.json`);
a caller who has reconciled real numbers against their fal invoice passes their
own table as `llm_rates=`. `llm_rates.json` has no refresh job that runs
itself, so a quote is only as fresh as its last check --- run
`falaw.refresh_llm_rates()` (or `python -m falaw refresh-llm-rates`) to diff
it against fal's any-llm doc and OpenRouter's catalogue; it never overwrites
the committed table, only proposes one for a human to review.

## Read the journal first

Before novel work, glance at recent entries --- past sessions may have
left notes that save you time:

```python
from falaw import journal

for e in journal.recent(20):
    print(e.kind, "-", e.text[:120])
```

## Leave a journal entry when something surprises you

```python
from falaw import journal

journal.issue(
    "FLUX dev returned NSFW=True for a benign prompt",
    suggestion="Try guidance_scale=2.0",
    tags=("flux", "safety"),
)
journal.improvement(
    "Pass beat.emotion as a TTS prompt arg for emotion-aware models",
    tags=("backlog", "directorial"),
)
journal.note("schnell at quality='fast' returns 1024x1024 by default")
```

## Pick a model without memorizing IDs

```python
from falaw import list_models, pick_model

[m.id for m in list_models(category="image_to_video")]
pick_model(category="image_edit", quality_tier="ultra").id
```

## Tools

Every function below is a registered tool; bridges (MCP server, HTTP
service, UI) derive their surfaces from the same registry.


### `falaw.refresh_models_from_corpus`

Parse `misc/docs/llms-full.txt` and merge any newly-discovered models into `falaw/data/models.json`. Hand-curated entries are preserved; only previously-unknown ids are added. Pass `write=True` to persist; otherwise returns a dry-run summary.


### `falaw.text_to_speech`

Synthesize speech from text. Picks a TTS model by quality tier; pass `voice` and `extra` for model-specific knobs. Returns a falaw.Result whose .first asset is the audio URL.

Examples:
  - `falaw.text_to_speech(**{'text': 'Hello world', 'quality': 'balanced'})`
  - `falaw.text_to_speech(**{'text': 'Bonjour le monde', 'quality': 'high', 'voice': 'fr-FR-female-1'})`


### `falaw.voice_clone`

Synthesize speech in a cloned voice. Provide a `reference_audio_url` (a few seconds of the target voice) and the text to speak. Returns a falaw.Result whose .first asset is the cloned-voice audio URL.

Examples:
  - `falaw.voice_clone(**{'reference_audio_url': 'https://example.com/me.wav', 'text': 'Hello, this is in my voice.'})`


### `falaw.generate_audio`

Generate ambient sound, an SFX bed, or music from a text prompt — the 'city night' / 'rain on a tin roof' bed a cut needs, without leaving the editor. `kind` picks the model family: 'ambient'/'sfx' → Stable Audio 3 SFX (commercially usable), 'music' → Lyria 2. Returns a falaw.Result whose .first asset is the audio URL.

Examples:
  - `falaw.generate_audio(**{'prompt': 'city street at night, distant traffic', 'kind': 'ambient'})`
  - `falaw.generate_audio(**{'prompt': 'gentle acoustic guitar, hopeful', 'kind': 'music'})`


### `falaw.animate_face`

Animate a still face image to speak an audio track. Returns a falaw.Result whose .first asset is the talking-head video URL. Use this when you have a portrait + audio but NOT an existing video. Picks ai-avatar (balanced) or omnihuman v1.5 (high).

Examples:
  - `falaw.animate_face(**{'image_url': 'https://...', 'audio_url': 'https://...', 'prompt': 'warm, attentive listener'})`


### `falaw.lipsync`

Re-sync an existing VIDEO clip to a new audio track. Pass `video_url` (NOT a still image) and `audio_url`. The model replaces mouth motion to match the audio while keeping body and motion from the original video. Use `animate_face` if you only have a still image.

Examples:
  - `falaw.lipsync(**{'video_url': 'https://...', 'audio_url': 'https://...'})`


### `falaw.talking_avatar_from_text`

Composer: text + face IMAGE → talking-head video. Internally runs `text_to_speech(text)` then `animate_face(image_url, audio_url, prompt)`. Returns the animate_face Result. Use this when you have text and a portrait but no audio.

Examples:
  - `falaw.talking_avatar_from_text(**{'text': 'Welcome to the demo.', 'image_url': 'https://example.com/host.jpg'})`


### `falaw.generate_image`

Generate an image from a text prompt. Picks a sensible FLUX model based on the requested quality tier ('fast', 'balanced', 'high', 'ultra'). Returns a falaw.Result whose .first asset has a URL you can .download(to=...).

Examples:
  - `falaw.generate_image(**{'prompt': 'A red panda eating bamboo', 'quality': 'fast'})`
  - `falaw.generate_image(**{'prompt': 'Cinematic portrait, 35mm film', 'quality': 'ultra'})`


### `falaw.edit_image`

Edit an image using a natural-language instruction. Picks a FLUX Kontext / SeedEdit model by quality tier. Returns a falaw.Result with the edited image.

Examples:
  - `falaw.edit_image(**{'image_url': 'https://...', 'prompt': 'make the sky orange'})`
  - `falaw.edit_image(**{'image_url': 'https://...', 'prompt': 'remove the person on the left', 'quality': 'ultra'})`


### `falaw.generate_image_with_refs`

Generate a NEW image from a text prompt while conditioning on one or more reference images, so a recurring subject (a character's face, a location, a prop) stays consistent across renders. Unlike generate_image (pure text-to-image — reference images have no effect), this routes to a reference-capable image model (Flux Kontext / OmniGen / SeedEdit) that actually ingests the references. The first reference anchors the primary subject; all references are also passed together. Returns a falaw.Result with the generated image.

Examples:
  - `falaw.generate_image_with_refs(**{'prompt': 'Alex looks up at the bell, candlelight on his face', 'reference_image_urls': ['https://x/alex-modelsheet.png'], 'quality': 'balanced'})`


### `falaw.composite_character_in_environment`

Place a specific character into a specific environment as a single still image, preserving the character's identity. Uses an image-edit model that accepts multiple reference images (Flux Kontext, OmniGen v2, SeedEdit). The character image anchors identity; the environment image anchors location, lighting, and palette. Returns a falaw.Result with the composited still.

Examples:
  - `falaw.composite_character_in_environment(**{'character_image_url': 'https://x/thor.png', 'environment_image_url': 'https://x/bell_tower.png', 'prompt': 'Thor stands in the bell tower, contemplative gaze, candlelight on his face', 'quality': 'high'})`


### `falaw.upscale_image`

Upscale an image to higher resolution while preserving fidelity. Defaults to clarity-upscaler. Returns a falaw.Result with the upscaled image.

Examples:
  - `falaw.upscale_image(**{'image_url': 'https://...', 'scale': 2.0})`
  - `falaw.upscale_image(**{'image_url': 'https://...', 'scale': 4.0, 'extra': {'creativity': 0.35}})`


### `falaw.remove_background`

Remove the background from an image, returning a transparent PNG. Defaults to BiRefNet v2 (quality='high') or Bria (quality='balanced'). Returns a falaw.Result.

Examples:
  - `falaw.remove_background(**{'image_url': 'https://example.com/photo.jpg'})`


### `falaw.llm_complete`

Run a single LLM completion via fal-ai/any-llm. Returns the raw text output. Use `system` for instruction prompts, `prompt` for the user message. Cached by content.

Examples:
  - `falaw.llm_complete(**{'prompt': 'summarize this scene in one line', 'system': 'you are a script consultant'})`


### `falaw.parse_screenplay`

Parse prose screenplay/treatment text into a structured Scene (via any-llm). Returns a falaw.Scene you can render directly. Use `model_hint` to pick a stronger LLM for nuanced material.


### `falaw.apply_note_to_beat`

Apply a directorial note to a single Beat using an LLM. Returns an updated Beat (same id; modified content fields). Use this to implement 'he cracks on this line; she softens but hides it' without manually rewriting the structure.

Examples:
  - `falaw.apply_note_to_beat(**{'beat': {'id': '001-john-abcd', 'speaker': 'John', 'line': "It's fine.", 'emotion': ''}, 'note': 'He cracks on this line --- voice goes up.'})`


### `falaw.apply_note_to_scene`

Apply a directorial note to the whole Scene by asking the LLM for a JSON patch (which beats/shots to edit, with new content). Returns a new Scene. Use for cross-cutting notes like 'tighten the pacing in the middle' or 'add a reaction shot after beat 5'.


### `falaw.cast_character`

Generate or attach a canonical face image for a character, plus an optional voice. Returns an updated Character with `reference_image_url` set --- the anchor used by every later lipsync render. Pass an existing image_url to skip generation.

Examples:
  - `falaw.cast_character(**{'name': 'Sarah', 'description': 'mid-30s, sharp features, dark curly hair, wary eyes'})`


### `falaw.cast_voice`

Attach or refine a Voice for an existing Character. Provide a `reference_audio_url` (for cloning) or a `voice_id` (model-side preset). Returns the updated Character.


### `falaw.establish_environment`

Generate or attach a canonical establishing image for a location. Used as visual anchor and lighting reference for every shot in that environment. Returns an Environment.

Examples:
  - `falaw.establish_environment(**{'name': 'diner', 'description': '1950s American chrome diner, neon outside, half-empty booths', 'time_of_day': 'midnight'})`


### `falaw.storyboard_shot`

Render a still preview (storyboard frame) for a single Shot, composited with its Environment and the Characters in view. Returns the URL of the still --- use it as a reference image for downstream image-to-video.


### `falaw.render_beat`

Render one Beat: TTS (using the speaker's Voice) → lipsync to the speaker's reference image. Cached by content hash --- re-rendering an unchanged Beat is a no-op. Returns {url, cache_hit, hash, audio_url}.


### `falaw.render_shot`

Render a Shot: a still (storyboard) or short clip if `as_video=True` (image-to-video). Cached by content hash. Returns {url, cache_hit, hash, kind}.


### `falaw.render_scene`

Render an entire Scene: every Shot + every Beat, with caching so unchanged units are no-ops. Returns a manifest dict with per-beat and per-shot results, plus aggregate counts. Pass `force=True` to bypass the cache.


### `falaw.text_to_video`

Generate a video from a text prompt. Picks a tier-appropriate model (Veo 3 for ultra, Seedance Pro for high). Use `extra` to pass through model-specific knobs like duration, aspect_ratio, negative_prompt.

Examples:
  - `falaw.text_to_video(**{'prompt': 'A drone shot over a misty pine forest at dawn'})`
  - `falaw.text_to_video(**{'prompt': 'Macro: a single dewdrop on a spider web', 'quality': 'ultra'})`


### `falaw.image_to_video`

Animate a still image into a short video. Optional prompt steers the motion. Picks a tier-appropriate i2v model (Kling Master for ultra, Seedance for high, Hailuo for balanced).

Examples:
  - `falaw.image_to_video(**{'image_url': 'https://...', 'prompt': 'the camera slowly zooms in'})`
  - `falaw.image_to_video(**{'image_url': 'https://...', 'quality': 'balanced'})`


### `falaw.refresh_llms`

Refresh `llms.txt` and `llms-full.txt` from fal.ai using conditional GETs (ETag-based). Cheap: returns immediately if nothing changed. On change, snapshots the previous version and journals the diff. Returns a summary dict like {'llms': {'changed': False}, ...}.


### `falaw.refresh_full_docs`

Re-crawl every per-page .md endpoint listed in `fal_ai_docs_index.md` with conditional GETs, then reassemble `fal_ai_docs_full.md`. Heavy. Gated on `is_stale(llms-full)` by default --- pass `force=True` to skip the gate. Pages that 304 are skipped; only changed pages re-download. Logs a single journal entry summarizing the run.


### `falaw.refresh_model_prices`

Fetch fal's unit pricing for every model in `falaw/data/models.json` and write structured cost_estimates with source='api'. Hand-written prices the API disagrees with are overwritten and the delta reported. Units with no CostKind mapping (GPU/compute units) are recorded, not guessed. Reads the vendor's free pricing endpoint; makes no billed call. Pass `write=True` to persist; default is a dry-run summary.


### `falaw.refresh_llm_rates`

Fetch fal's any-llm doc and OpenRouter's model catalogue and diff them against `falaw/data/llm_rates.json`. Never overwrites the committed table -- a repriced or retiered model is a decision, not an auto-apply. Pass `write=True` to persist a proposed table (`llm_rates.proposed.json`) plus a human-readable diff (`llm_rates.diff.txt`) for a human to review and promote; default is a dry-run summary. Reads two free, unauthenticated endpoints; makes no billed call.


## Models known to falaw

The model registry lives at `falaw/data/models.json`. Refresh it from
`misc/docs/fal_ai_docs_full.md` when fal ships new models. Quick view:

```
  audio                balanced   fal-ai/elevenlabs/audio-isolation
  avatar               balanced   fal-ai/ai-avatar
  avatar               high       fal-ai/bytedance/omnihuman/v1.5
  background_removal   balanced   fal-ai/bria/background/remove
  background_removal   balanced   fal-ai/ideogram/v3/reframe
  background_removal   high       fal-ai/birefnet/v2
  image                balanced   fal-ai/flux/dev
  image                balanced   fal-ai/ideogram/v3
  image                balanced   fal-ai/recraft/v3/text-to-image
  image                fast       fal-ai/flux/schnell
  image                fast       fal-ai/hidream-i1-fast
  image                fast       fal-ai/sana/sprint
  image                high       fal-ai/flux-pro/v1.1
  image                high       fal-ai/bytedance/seedream/v4.5/text-to-image
  image                ultra      fal-ai/flux-pro/v1.1-ultra
  image                ultra      fal-ai/nano-banana-pro
  image                unranked   fal-ai/flux-pro
  image_edit           balanced   fal-ai/flux-kontext/dev
  image_edit           balanced   fal-ai/omnigen-v2
  image_edit           high       fal-ai/bytedance/seededit/v3/edit-image
  image_edit           high       fal-ai/bytedance/seedream/v4.5/edit
  image_edit           ultra      fal-ai/flux-pro/kontext/max
  image_to_video       balanced   fal-ai/minimax/hailuo-02/pro/image-to-video
  image_to_video       balanced   fal-ai/pixverse/v4.5/image-to-video
  image_to_video       balanced   bytedance/seedance-2.0/fast/image-to-video
  image_to_video       high       fal-ai/bytedance/seedance/v1/pro/image-to-video
  image_to_video       high       bytedance/seedance-2.0/image-to-video
  image_to_video       high       fal-ai/bytedance/seedance/v1.5/pro/image-to-video
  image_to_video       ultra      fal-ai/kling-video/v2.1/master/image-to-video
  image_to_video       unranked   fal-ai/ltx-video/image-to-video
  image_to_video       unranked   fal-ai/kling-video/v1.5/pro/image-to-video
  image_to_video       unranked   fal-ai/kling-video/v1.5/standard
  lipsync              balanced   fal-ai/ai-avatar/multi
  lipsync              balanced   fal-ai/kling-video/lipsync/audio-to-video
  lipsync              high       fal-ai/sync-lipsync/v2
  llm                  balanced   fal-ai/any-llm
  llm                  balanced   fal-ai/any-llm/vision
  music                balanced   fal-ai/diffrhythm
  music                balanced   fal-ai/mmaudio-v2/text-to-audio
  music                balanced   fal-ai/stable-audio-3/small/sfx/text-to-audio
  music                balanced   fal-ai/stable-audio-3/medium/text-to-audio
  music                balanced   mirelo-ai/sfx2.0/text-to-audio
  music                balanced   fal-ai/elevenlabs/sound-effects/v2
  music                balanced   sonilo/v1.1/text-to-sound-effects
  music                high       fal-ai/lyria2
  reference_to_video   balanced   bytedance/seedance-2.0/fast/reference-to-video
  reference_to_video   high       bytedance/seedance-2.0/reference-to-video
  text_to_video        balanced   bytedance/seedance-2.0/fast/text-to-video
  text_to_video        high       fal-ai/bytedance/seedance/v1/pro/text-to-video
  text_to_video        high       bytedance/seedance-2.0/text-to-video
  text_to_video        high       fal-ai/bytedance/seedance/v1.5/pro/text-to-video
  text_to_video        ultra      fal-ai/veo3
  text_to_video        unranked   fal-ai/ltx-video
  text_to_video        unranked   fal-ai/mochi-v1
  text_to_video        unranked   fal-ai/kling-video/v1.5/pro/text-to-video
  training             balanced   fal-ai/flux-lora-portrait-trainer
  training             fast       fal-ai/flux-lora-fast-training
  training             high       fal-ai/flux-pro-trainer
  tts                  high       fal-ai/elevenlabs/tts/multilingual-v2
  tts                  high       fal-ai/minimax/speech-02-hd
  upscale              high       fal-ai/clarity-upscaler
  voice_clone          high       fal-ai/minimax/voice-clone
```

## When you can't find what you need

* Check `falaw/misc/docs/llms-full.txt` for a structured fal.ai overview.
* Check `falaw/misc/docs/fal_ai_docs_full.md` for the full corpus (~3MB).
* Drop into `falaw.call_fal(application, arguments)` for any model not
  yet wrapped --- this is the escape hatch. Then leave a `journal.improvement`
  asking for a proper tool wrapper.
