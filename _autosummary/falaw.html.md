# falaw

falaw: agent-friendly Python facade over fal.ai for AI media generation.

Quick start (single-shot generation):

```pycon
>>> from falaw import generate_image
>>> r = generate_image("a tiger eye, macro, 35mm", quality="fast")
>>> r.first.download(to="./tiger.png")
```

Directorial workflow (Scene IR + caching):

```pycon
>>> from falaw import Scene, cast_character, render_scene
>>> sarah = cast_character("Sarah", "mid-30s, dark curly hair")
>>> # ... build a Scene with characters/beats/shots ...
>>> manifest = render_scene(scene)            # caches per-beat
>>> # edit one beat, re-render: only that beat re-fires.
```

Leave notes for future sessions:

```pycon
>>> from falaw import journal
>>> journal.note("Sarah's voice clone needs ~10s reference for stability")
```

### Functions

| [`get_llm_price`](#falaw.get_llm_price)(provider, model, \*[, prices])       | The row for `model` (exact id), or `None` when the table does not list it.                                                                                                                                         |
|-----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`list_llm_prices`](#falaw.list_llm_prices)([provider, prices])                | Every row, or the rows of one `provider`.                                                                                                                                                                          |
| [`llm_call_cost_usd`](#falaw.llm_call_cost_usd)(provider, model, usage, \*)      | `(USD, known)` for one first-party call from the vendor's reported `usage`.                                                                                                                                        |
| [`llm_token_counts`](#falaw.llm_token_counts)(provider, usage)                  | The [`LlmTokenCounts`](#falaw.LlmTokenCounts) of a vendor `usage`, in the shapes [`llm_call_cost_usd()`](#falaw.llm_call_cost_usd) accepts (a mapping or an SDK object).  |
| [`llm_prices_table_version`](#falaw.llm_prices_table_version)()                         | The table's version, a digest of its bytes (see [`falaw.base.data_table_version()`](falaw.base.html.md#falaw.base.data_table_version)).                                                   |
| [`check_terms`](#falaw.check_terms)(model_id, backend, context, \*[, ...]) | Raise [`FalTermsViolation`](#falaw.FalTermsViolation) unless `(model_id, backend)` is usable for *context*.                                                                                     |
| [`using_terms_context`](#falaw.using_terms_context)(context)                       | Scope *context* over every call made inside the block, eager or planned.                                                                                                                                           |
| [`third_party_tenancy_ok`](#falaw.third_party_tenancy_ok)(model_id, backend, \*)      | The routing-visible projection: may a router send third-party work to `(model_id, backend)` without consulting the full ledger? `False` when unsure — the cheap 80%, so a router can drop an incompatible backend. |
| [`call_plan_from_dict`](#falaw.call_plan_from_dict)(d)                             | Rebuild a [`CallPlan`](#falaw.CallPlan) from a [`call_plan_to_dict()`](#falaw.call_plan_to_dict) dict.                                                              |
| [`call_plan_to_dict`](#falaw.call_plan_to_dict)(call)                            | Convert a [`CallPlan`](#falaw.CallPlan) to a plain JSON-serializable dict.                                                                                                             |
| [`plan_dependencies`](#falaw.plan_dependencies)(plan)                            | Per-call set of the call indices it references via `"<from N>"`.                                                                                                                                                   |
| [`plan_from_dict`](#falaw.plan_from_dict)(d)                                  | Rebuild a [`Plan`](#falaw.Plan) from a [`plan_to_dict()`](#falaw.plan_to_dict) dict.                                                                       |
| [`plan_hash`](#falaw.plan_hash)(plan)                                    | Stable, plan-scoped **structural idempotency key** for a whole [`Plan`](#falaw.Plan).                                                                                              |
| [`plan_to_dict`](#falaw.plan_to_dict)(plan)                                 | Convert a [`Plan`](#falaw.Plan) to a plain JSON-serializable dict.                                                                                                                 |
| [`catalogue_cost_basis`](#falaw.catalogue_cost_basis)(model_id, \*\*quantities)     | A [`falaw.CostBasis`](#falaw.CostBasis) for a call priced from `models.json`.                                                                                                           |
| [`cost_basis_from_dict`](#falaw.cost_basis_from_dict)(d)                            | Rebuild a [`CostBasis`](#falaw.CostBasis) from a [`cost_basis_to_dict()`](#falaw.cost_basis_to_dict) dict.                                                            |
| [`cost_basis_to_dict`](#falaw.cost_basis_to_dict)(basis)                          | Convert a [`CostBasis`](#falaw.CostBasis) to a plain JSON-serializable dict.                                                                                                            |
| [`llm_cost_basis`](#falaw.llm_cost_basis)(routed_model, \*[, ...])            | A [`falaw.CostBasis`](#falaw.CostBasis) for a routed LLM call priced from the rate table.                                                                                               |
| [`reprice_plan`](#falaw.reprice_plan)(plan, \*[, pricers])                  | Re-quote every call in `plan` against today's rate tables.                                                                                                                                                         |
| [`upload`](#falaw.upload)(path, \*[, uploader, index, ttl_s, ...])    | A fal-fetchable URL for the local file at `path`.                                                                                                                                                                  |
| [`using_uploader`](#falaw.using_uploader)(uploader, \*[, namespace])          | Make `uploader` the transfer for every [`upload()`](#falaw.upload) (and every local file in an executed Plan) for the duration: an S3 uploader, or a fake in a test suite.           |
| [`clear_subscribers`](#falaw.clear_subscribers)()                                | Drop all registered subscribers.                                                                                                                                                                                   |
| [`estimate_call_cost`](#falaw.estimate_call_cost)(record, \*[, count, ...])       | Cost of one fal call against `record`.                                                                                                                                                                             |
| [`estimate_scene_cost`](#falaw.estimate_scene_cost)(scene, \*[, tts_quality, ...]) | Estimate the USD cost of a full [`render_scene()`](#falaw.render_scene) invocation.                                                                                                        |
| [`get_llm_rate`](#falaw.get_llm_rate)(model, \*[, rates])                   | The row for `model`, or `None` when the table does not price it.                                                                                                                                                   |
| [`list_llm_rates`](#falaw.list_llm_rates)(\*[, rates])                        | Every row in the table, in file order — the catalogue view.                                                                                                                                                        |
| [`llm_ceiling_usd`](#falaw.llm_ceiling_usd)(model, \*[, input_tokens, ...])    | Ceiling cost in USD of `count` calls routing `model`, or `None`.                                                                                                                                                   |
| [`listening`](#falaw.listening)(callback)                                | Deliver every event emitted in this context to `callback`, then stop.                                                                                                                                              |
| [`subscribe`](#falaw.subscribe)(callback)                                | Register `callback` to receive every emitted ProgressEvent.                                                                                                                                                        |
| [`unsubscribe`](#falaw.unsubscribe)(callback)                              | Remove a previously [`subscribe()`](#falaw.subscribe)'d callback.                                                                                                                       |
| [`animate_face`](#falaw.animate_face)(image_url, audio_url, \*[, ...])      | Animate a still face from audio.                                                                                                                                                                                   |
| [`apply_note_to_beat`](#falaw.apply_note_to_beat)(beat, note, \*[, model])        | Use the LLM to apply a directorial note to a Beat.                                                                                                                                                                 |
| [`apply_note_to_scene`](#falaw.apply_note_to_scene)(scene, note, \*[, model])      | Apply a cross-cutting note: LLM proposes per-beat edits, we apply them.                                                                                                                                            |
| [`beat_content_hash`](#falaw.beat_content_hash)(beat, \*[, character])           | Hash everything that affects how the beat *renders*.                                                                                                                                                               |
| [`cache_get`](#falaw.cache_get)(application, arguments, \*[, ...])       | Return the raw fal response if cached, else None.                                                                                                                                                                  |
| [`cache_put`](#falaw.cache_put)(application, arguments, raw, \*[, ...])  | Persist a fal response.                                                                                                                                                                                            |
| [`cache_stats`](#falaw.cache_stats)()                                      | Quick summary of the cache: entry count, disk usage, and where it went.                                                                                                                                            |
| [`cache_usage`](#falaw.cache_usage)()                                      | Disk usage of the falaw cache, broken down by area.                                                                                                                                                                |
| [`prune_assets`](#falaw.prune_assets)(\*[, older_than, max_bytes, ...])     | Reclaim materialized asset copies — the cheapest disk in the cache (falaw#22).                                                                                                                                     |
| [`prune_uploads`](#falaw.prune_uploads)(\*[, older_than, max_bytes, ...])    | Drop upload-index entries (falaw#92): digest -> fal URL hints.                                                                                                                                                     |
| [`prune_content`](#falaw.prune_content)(\*[, older_than, max_bytes, ...])    | Reclaim content-addressed blobs — the gigabytes (falaw#22).                                                                                                                                                        |
| [`prune_manifests`](#falaw.prune_manifests)(\*[, older_than, max_bytes, ...])  | Reclaim cache entries — the fal responses themselves (falaw#22).                                                                                                                                                   |
| [`drop_cache_entry`](#falaw.drop_cache_entry)(application, arguments, \*)       | Delete the cache entry for `(application, arguments)`.                                                                                                                                                             |
| [`cached_call_fal`](#falaw.cached_call_fal)(application, arguments, \*[, ...]) | Call a fal model, but reuse the cached response when present.                                                                                                                                                      |
| [`content_ref_for_url`](#falaw.content_ref_for_url)(url, \*[, store, ...])         | Materialize `url`'s bytes into `store` and return their content hash.                                                                                                                                              |
| [`default_content_store`](#falaw.default_content_store)()                            | The falaw-cache-rooted `lacing.ArtifactStore`.                                                                                                                                                                     |
| [`default_url_fetcher`](#falaw.default_url_fetcher)()                              | The transport used when no `fetcher=` argument is given.                                                                                                                                                           |
| [`using_url_fetcher`](#falaw.using_url_fetcher)(fetcher)                         | Make `fetcher` falaw's default asset transport for the duration.                                                                                                                                                   |
| [`call_fal`](#falaw.call_fal)(application, arguments, \*[, ...])        | Call a fal model via fal_client.subscribe.                                                                                                                                                                         |
| [`cast_character`](#falaw.cast_character)(name, description, \*[, ...])       | Create a Character with a canonical face (and optional voice).                                                                                                                                                     |
| [`current_fal_key`](#falaw.current_fal_key)()                                  | The fal API key bound for the current context, or `None`.                                                                                                                                                          |
| [`cast_voice`](#falaw.cast_voice)(character, \*[, voice_id, ...])         | Attach or update the Voice on a Character.                                                                                                                                                                         |
| [`composite_character_in_environment`](#falaw.composite_character_in_environment)(...[, ...])     | Place a character into an environment as one composited still.                                                                                                                                                     |
| [`edit_image`](#falaw.edit_image)(image_url, prompt, \*[, quality, ...])  | Edit an image with a natural-language instruction.                                                                                                                                                                 |
| [`establish_environment`](#falaw.establish_environment)(name, description, \*)       | Create an Environment with a canonical establishing image.                                                                                                                                                         |
| [`execute_plan`](#falaw.execute_plan)(plan, \*[, on_event, dry_run, ...])   | Execute a Plan, returning a list of materialized :class:<br/><br/>```<br/>`<br/>```<br/><br/>lacing.Artifact\`s.                                                                                                   |
| [`execute_plan_isolated`](#falaw.execute_plan_isolated)(plan, \*[, on_event, ...])   | Execute a Plan with **per-call failure isolation**, returning a report.                                                                                                                                            |
| [`extract_models_from_corpus`](#falaw.extract_models_from_corpus)(path)                   | Yield ModelRecord-shaped dicts parsed from llms-full.txt.                                                                                                                                                          |
| [`generate_image`](#falaw.generate_image)(prompt, \*[, quality, ...])         | Generate an image from a text prompt.                                                                                                                                                                              |
| [`generate_image_with_refs`](#falaw.generate_image_with_refs)(prompt, ...[, ...])       | Generate a new image conditioned on one or more reference images.                                                                                                                                                  |
| `get_model`(id)                                                                                     |                                                                                                                                                                                                                    |
| `get_tool`(name)                                                                                    |                                                                                                                                                                                                                    |
| [`image_to_video`](#falaw.image_to_video)(image_url[, prompt, quality, ...])  | Animate a still image into a video.                                                                                                                                                                                |
| [`iter_render_scene`](#falaw.iter_render_scene)(scene, \*[, tts_quality, ...])   | Yield `(kind, result)` pairs as each shot/beat finishes.                                                                                                                                                           |
| [`lipsync`](#falaw.lipsync)(video_url, audio_url, \*[, quality, ...])  | Re-sync mouth motion in an existing video to a new audio track.                                                                                                                                                    |
| `list_models`(\*[, category, quality_tier])                                                         |                                                                                                                                                                                                                    |
| `list_tools`(\*[, tag])                                                                             |                                                                                                                                                                                                                    |
| [`llm_complete`](#falaw.llm_complete)(prompt, \*[, system, model, ...])     | Single-shot LLM completion.                                                                                                                                                                                        |
| [`llm_complete_with_receipt`](#falaw.llm_complete_with_receipt)(prompt, \*[, ...])       | Single-shot LLM completion that also reports what it cost.                                                                                                                                                         |
| `load_scene`(path)                                                                                  |                                                                                                                                                                                                                    |
| `make_beat`(speaker[, line, action, emotion, ...])                                                  |                                                                                                                                                                                                                    |
| [`make_call_plan`](#falaw.make_call_plan)(\*, tool, application, ...[, ...])  | Build a [`CallPlan`](#falaw.CallPlan) and (optionally) check the cache.                                                                                                                |
| `make_shot`(description, \*[, framing, ...])                                                        |                                                                                                                                                                                                                    |
| [`materialize_asset`](#falaw.materialize_asset)(url, \*[, key_hint, store, ...]) | Download a remote asset to the cache and return the local path.                                                                                                                                                    |
| [`parse_response`](#falaw.parse_response)(raw, \*, application, arguments)    | Best-effort parser over the common fal response shapes.                                                                                                                                                            |
| [`parse_screenplay`](#falaw.parse_screenplay)(text, \*[, title, style, model])  | Convert prose screenplay text into a Scene IR via an LLM call.                                                                                                                                                     |
| [`pick_model`](#falaw.pick_model)(\*, category[, quality_tier])           | Pick a sensible fal model for a (category, quality) request.                                                                                                                                                       |
| [`model_constraints`](#falaw.model_constraints)(id)                              | The capability/limit fields for a model — the "static reminder of limitations" a shot-list builder surfaces.                                                                                                       |
| [`model_params`](#falaw.model_params)(id)                                   | Per-model parameters worth knowing before a call, `{name: spec}`.                                                                                                                                                  |
| [`video_model_constraints`](#falaw.video_model_constraints)()                          | `model_constraints` for every video model in the catalog — the data a shot-list builder shows as its model-limits reference.                                                                                       |
| [`plan_animate_face`](#falaw.plan_animate_face)(image_url, audio_url, \*[, ...]) | Plan a [`falaw.animate_face()`](#falaw.animate_face) call (image + audio → talking video).                                                                                                 |
| [`plan_composite_character_in_environment`](#falaw.plan_composite_character_in_environment)(...)       | Plan a [`falaw.composite_character_in_environment()`](#falaw.composite_character_in_environment) call.                                                                                                           |
| [`plan_edit_image`](#falaw.plan_edit_image)(image_url, prompt, \*[, ...])      | Plan a [`falaw.edit_image()`](#falaw.edit_image) call (Flux Kontext / SeedEdit / OmniGen).                                                                                               |
| [`plan_generate_image`](#falaw.plan_generate_image)(prompt, \*[, quality, ...])    | Plan a [`falaw.generate_image()`](#falaw.generate_image) call without executing it.                                                                                                          |
| [`plan_generate_image_with_refs`](#falaw.plan_generate_image_with_refs)(prompt, ...[, ...])  | Plan a [`falaw.generate_image_with_refs()`](#falaw.generate_image_with_refs) call.                                                                                                                     |
| [`plan_image_to_video`](#falaw.plan_image_to_video)(image_url[, prompt, ...])      | Plan a [`falaw.image_to_video()`](#falaw.image_to_video) call.                                                                                                                               |
| [`plan_reference_to_video`](#falaw.plan_reference_to_video)(prompt, \*[, ...])         | Plan a reference-to-video call (Seedance 2.0): a prompt steered by reference images, videos and audio.                                                                                                             |
| [`plan_text_to_video`](#falaw.plan_text_to_video)(prompt, \*[, quality, ...])     | Plan a [`falaw.text_to_video()`](#falaw.text_to_video) call — the sibling of [`plan_image_to_video()`](#falaw.plan_image_to_video) (same duration and cost rules).         |
| [`plan_lipsync`](#falaw.plan_lipsync)(video_url, audio_url, \*[, ...])      | Plan a [`falaw.lipsync()`](#falaw.lipsync) call (existing video + new audio → re-synced video).                                                                                       |
| [`plan_llm_complete`](#falaw.plan_llm_complete)(prompt, \*[, system, ...])       | Plan a [`falaw.llm_complete()`](#falaw.llm_complete) call without executing it.                                                                                                            |
| [`plan_generate_audio`](#falaw.plan_generate_audio)(prompt, \*[, kind, ...])       | Plan a [`falaw.generate_audio()`](#falaw.generate_audio) call (prompt → ambient/SFX/music).                                                                                                  |
| [`plan_text_to_speech`](#falaw.plan_text_to_speech)(text, \*[, quality, ...])      | Plan a [`falaw.text_to_speech()`](#falaw.text_to_speech) call (text → audio Artifact).                                                                                                       |
| [`refresh_full_docs`](#falaw.refresh_full_docs)(\*[, docs_dir, ...])             | Re-crawl per-page docs and rebuild `fal_ai_docs_full.md`.                                                                                                                                                          |
| [`refresh_llms`](#falaw.refresh_llms)(\*[, docs_dir, journal])              | Refresh `llms.txt` and `llms-full.txt`; return a summary dict.                                                                                                                                                     |
| [`refresh_models_from_corpus`](#falaw.refresh_models_from_corpus)(\*[, path, write])      | Merge corpus-discovered models into models.json (additive).                                                                                                                                                        |
| [`refresh_model_prices`](#falaw.refresh_model_prices)(\*[, write, api_key, ...])    | Refresh `models.json` cost estimates from fal's pricing API.                                                                                                                                                       |
| [`check_model_liveness`](#falaw.check_model_liveness)([ids, status_of])             | `{endpoint_id: is_live}` for `ids` (default: every catalogued model).                                                                                                                                              |
| [`dead_models`](#falaw.dead_models)([ids, status_of])                      | The ids from [`check_model_liveness()`](#falaw.check_model_liveness) that are no longer deployed.                                                                                                  |
| [`fetch_model_prices`](#falaw.fetch_model_prices)(endpoint_ids, \*[, ...])        | `{endpoint_id: {"unit_price", "unit", "currency"}}` from fal's API.                                                                                                                                                |
| [`refresh_llm_rates`](#falaw.refresh_llm_rates)(\*[, write, ...])                | Fetch both sources, propose a fresh table, diff it — never overwrite.                                                                                                                                              |
| [`refresh_state`](#falaw.refresh_state)()                                    | Return the saved per-source refresh state (etags, last fetch times).                                                                                                                                               |
| [`register_tool`](#falaw.register_tool)(\*\*spec_kwargs)                     | Decorator: register the wrapped function as a falaw tool.                                                                                                                                                          |
| [`remove_background`](#falaw.remove_background)(image_url, \*[, quality, ...])   | Remove the background from an image.                                                                                                                                                                               |
| [`render_beat`](#falaw.render_beat)(beat, character, \*[, ...])            | Render one Beat to a lipsynced video.                                                                                                                                                                              |
| [`render_scene`](#falaw.render_scene)(scene, \*[, tts_quality, ...])        | Render every shot and beat.                                                                                                                                                                                        |
| [`render_shot`](#falaw.render_shot)(shot, \*[, environment, ...])          | Render a Shot as a still (default) or a short clip.                                                                                                                                                                |
| `save_scene`(scene, path)                                                                           |                                                                                                                                                                                                                    |
| [`scene_from_dict`](#falaw.scene_from_dict)(d)                                 | Inverse of asdict: reconstruct a Scene from a plain dict.                                                                                                                                                          |
| `scene_to_dict`(scene)                                                                              |                                                                                                                                                                                                                    |
| `shot_content_hash`(shot, \*[, environment])                                                        |                                                                                                                                                                                                                    |
| [`storyboard_shot`](#falaw.storyboard_shot)(shot, \*[, environment, ...])      | Render a storyboard still for a Shot.                                                                                                                                                                              |
| [`talking_avatar_from_text`](#falaw.talking_avatar_from_text)(text, image_url, \*)      | text + face image → talking video.                                                                                                                                                                                 |
| [`generate_audio`](#falaw.generate_audio)(prompt, \*[, kind, ...])            | Generate ambient/SFX/music from a prompt.                                                                                                                                                                          |
| [`text_to_speech`](#falaw.text_to_speech)(text, \*[, quality, voice, ...])    | Synthesize speech.                                                                                                                                                                                                 |
| [`text_to_video`](#falaw.text_to_video)(prompt, \*[, quality, ...])          | Generate a video from a text prompt.                                                                                                                                                                               |
| [`upscale_image`](#falaw.upscale_image)(image_url, \*[, scale, ...])         | Upscale an image.                                                                                                                                                                                                  |
| [`using_fal_credentials`](#falaw.using_fal_credentials)(key)                         | Bind `key` as the fal credential for every [`call_fal()`](#falaw.call_fal) in this context.                                                                                            |
| [`voice_clone`](#falaw.voice_clone)(reference_audio_url, text, \*[, ...])  | Generate speech in a cloned voice.                                                                                                                                                                                 |

### Classes

| [`LlmPrice`](#falaw.LlmPrice)(\*, provider, model, rates[, ...])        | One row of the first-party table: a model's rates and where they came from.                                                                                                                                                                                         |
|-----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`LlmTokenCounts`](#falaw.LlmTokenCounts)(\*[, fresh_input, cache_read, ...]) | The token counts a first-party call's `usage` reports, normalized across providers: the very counts [`llm_call_cost_usd()`](#falaw.llm_call_cost_usd) prices, so a caller that records them next to the cost cannot disagree with it (falaw#89). |
| [`AccountStatus`](#falaw.AccountStatus)(ok, locked, unauthorized, ...)       | Outcome of `health_check()`.                                                                                                                                                                                                                                        |
| [`Asset`](#falaw.Asset)(url, kind[, content_type, width, ...])       | A single piece of generated media.                                                                                                                                                                                                                                  |
| [`Beat`](#falaw.Beat)(\*, id[, speaker, line, action, ...])         | The atomic unit of a scene: who, says what, with what intent.                                                                                                                                                                                                       |
| [`CallOutcome`](#falaw.CallOutcome)(\*, index, call, status[, ...])        | What happened to one [`CallPlan`](#falaw.CallPlan), at its position in the Plan.                                                                                                                                                        |
| [`CallPlan`](#falaw.CallPlan)(\*, tool, application[, backend, ...])    | A single planned fal call.                                                                                                                                                                                                                                          |
| [`Character`](#falaw.Character)(\*, name[, description, ...])            | A reusable character: stable face, stable voice, stable style.                                                                                                                                                                                                      |
| [`ContentRef`](#falaw.ContentRef)(content_hash, bytes_size)               | A content-addressed handle on some bytes falaw has materialized.                                                                                                                                                                                                    |
| [`Environment`](#falaw.Environment)(\*, name[, description, ...])          | A reusable location/setting.                                                                                                                                                                                                                                        |
| [`ExecutionReport`](#falaw.ExecutionReport)([outcomes])                        | The result of running a Plan: one [`CallOutcome`](#falaw.CallOutcome) per call, in order.                                                                                                                                                  |
| [`ModelTerms`](#falaw.ModelTerms)(\*, model_id, backend[, license, ...])  | One ledger row.                                                                                                                                                                                                                                                     |
| [`TermsContext`](#falaw.TermsContext)(\*[, commercial, third_party, c2pa])  | What the job needs from the terms — supplied by the caller, never process-global (an explicit argument, or scoped to a block by [`using_terms_context()`](#falaw.using_terms_context)).                                                            |
| [`ModelRecord`](#falaw.ModelRecord)(\*, id, category[, description, ...])  | One entry in the fal model catalog.                                                                                                                                                                                                                                 |
| [`Plan`](#falaw.Plan)([calls])                                      | An ordered sequence of [`CallPlan`](#falaw.CallPlan) — a render plan, in essence.                                                                                                                                                       |
| [`CallRepricing`](#falaw.CallRepricing)(\*, index, call, old_cost_usd, ...)  | The before/after for one call in a re-priced plan.                                                                                                                                                                                                                  |
| [`CostBasis`](#falaw.CostBasis)(\*, pricer, priced[, quantities, ...])   | How a [`CallPlan.estimated_cost_usd`](#falaw.CallPlan.estimated_cost_usd) was arrived at (falaw#60).                                                                                                                                                       |
| [`Pricer`](#falaw.Pricer)(\*, quote, table[, version])                | One pricing rule, and the table that backs it.                                                                                                                                                                                                                      |
| [`RepricedPlan`](#falaw.RepricedPlan)(\*, plan[, calls])                    | Result of [`reprice_plan()`](#falaw.reprice_plan) — the new Plan plus the per-call diff.                                                                                                                                                    |
| [`Result`](#falaw.Result)([assets, raw, application, arguments])      | A fal call result with parsed assets and the original raw response.                                                                                                                                                                                                 |
| [`CostEstimate`](#falaw.CostEstimate)(\*, kind, amount[, currency, ...])    | Quantitative cost of one fal call against this model.                                                                                                                                                                                                               |
| [`CostLine`](#falaw.CostLine)(\*, kind, item_id, model_id, amount, ...) | One line item in a scene rollup.                                                                                                                                                                                                                                    |
| [`CostRollup`](#falaw.CostRollup)(\*, total_amount[, currency, ...])      | Result of [`estimate_scene_cost()`](#falaw.estimate_scene_cost).                                                                                                                                                                                   |
| [`ProgressEvent`](#falaw.ProgressEvent)(\*, kind, application, call_id)      | One step in the lifecycle of a fal call.                                                                                                                                                                                                                            |
| [`Scene`](#falaw.Scene)(\*, title[, style, characters, ...])         | The whole editable structure: cast, locations, shots, beats.                                                                                                                                                                                                        |
| [`Session`](#falaw.Session)([output_dir, journal, history])            | A working session for a sequence of falaw operations.                                                                                                                                                                                                               |
| [`Shot`](#falaw.Shot)(\*, id[, description, framing, ...])          | A visual frame: framing + environment + characters in view.                                                                                                                                                                                                         |
| [`ToolSpec`](#falaw.ToolSpec)(\*, name, description, func[, ...])       | Single source of truth for a tool exposed by falaw.                                                                                                                                                                                                                 |
| [`Voice`](#falaw.Voice)(\*, name[, voice_id, ...])                   | A character's voice spec.                                                                                                                                                                                                                                           |
| [`LlmRate`](#falaw.LlmRate)(\*, model, tier, per_call_usd[, ...])      | What one routed model costs, on every basis the table knows.                                                                                                                                                                                                        |
| [`AreaUsage`](#falaw.AreaUsage)(name, path, entries, bytes)              | Disk usage of one cache area.                                                                                                                                                                                                                                       |
| [`CacheUsage`](#falaw.CacheUsage)(root, areas)                            | Where the falaw cache's disk is going, by area.                                                                                                                                                                                                                     |
| [`PruneCandidate`](#falaw.PruneCandidate)(key, path, bytes[, last_modified])  | One thing a prune would delete (or did).                                                                                                                                                                                                                            |
| [`PruneReport`](#falaw.PruneReport)(area, dry_run[, candidates, ...])      | What a prune removed, or — with `dry_run=True` — would remove.                                                                                                                                                                                                      |
| [`LlmReceipt`](#falaw.LlmReceipt)(application, model, cache_hit, ...)     | What one eager LLM call cost — the record the eager path never kept.                                                                                                                                                                                                |

### Exceptions

| [`FalAccountLocked`](#falaw.FalAccountLocked)(message, \*, status_code[, ...])   | fal account is locked / suspended / awaiting verification.                   |
|------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| [`FalAssetFetchError`](#falaw.FalAssetFetchError)(message, \*, url[, cause])       | The bytes behind a fal-served asset URL could not be retrieved.              |
| [`FalClientNotInstalled`](#falaw.FalClientNotInstalled)([what, missing])              | A real network call was attempted but the fal.ai client is not installed.    |
| [`FalBadRequest`](#falaw.FalBadRequest)(message, \*, status_code[, ...])      | Server rejected the request payload — typical 400 / 422.                     |
| [`FalDurationOutOfRange`](#falaw.FalDurationOutOfRange)(message, \*, model_id, ...)   | The requested duration is outside what the model can produce.                |
| [`FalError`](#falaw.FalError)                                            | Base for all falaw-raised exceptions.                                        |
| [`FalTermsViolation`](#falaw.FalTermsViolation)(message, \*, model_id, ...)       | The model's terms of service forbid (or leave unknown) this use.             |
| [`FalHTTPError`](#falaw.FalHTTPError)(message, \*, status_code[, ...])       | Wraps an HTTP error from fal.ai with the original status, body, and headers. |
| [`FalInsufficientFunds`](#falaw.FalInsufficientFunds)(message, \*, status_code)      | Account balance is insufficient — typical 402.                               |
| [`FalModelHung`](#falaw.FalModelHung)(message, \*, model_id, elapsed_s)      | A model was queued but never returned — distinct from a network timeout.     |
| [`FalNonCanonicalArgument`](#falaw.FalNonCanonicalArgument)(message, \*, path)          | An argument cannot be canonicalised into falaw's hashed JSON form.           |
| [`FalPromptTooLong`](#falaw.FalPromptTooLong)(message, \*, model, limit, ...)    | The prompt exceeds the model's hard length cap (falaw#76).                   |
| [`FalRateLimited`](#falaw.FalRateLimited)(message, \*[, retry_after_s])        | fal is throttling requests — typical 429.                                    |
| [`FalServerError`](#falaw.FalServerError)(message, \*, status_code[, ...])     | fal-side server error — typical 5xx.                                         |
| [`FalTimeout`](#falaw.FalTimeout)(message, \*, elapsed_s[, application])   | The fal call timed out before producing a result.                            |
| [`FalUnauthorized`](#falaw.FalUnauthorized)(message, \*, status_code[, ...])    | Missing or invalid API credentials — typical 401.                            |

### *class* falaw.AccountStatus(ok, locked, unauthorized, status_code, detail, url, error)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Outcome of `health_check()`.

#### detail *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

Server-supplied detail string (best-effort), or ‘’ if unavailable.

#### error *: [str](https://docs.python.org/3/builtins/stdtypes.html#str) | [None](https://docs.python.org/3/builtins/constants.html#None)*

`repr` of the underlying exception when `ok` is False
and the failure isn’t a recognized lock/unauth (e.g. network error).

#### locked *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True iff the response indicated a locked / unverified account.

#### message_for_user()

Single human-readable line explaining the status. Stable for logging.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### ok *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True iff the account responded without an auth/lock error.

#### status_code *: [int](https://docs.python.org/3/builtins/functions.html#int) | [None](https://docs.python.org/3/builtins/constants.html#None)*

HTTP status from the probe (None if no HTTP exchange happened).

#### unauthorized *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True iff credentials are missing or invalid.

#### url *: [str](https://docs.python.org/3/builtins/stdtypes.html#str) | [None](https://docs.python.org/3/builtins/constants.html#None)*

If actionable (e.g. billing dashboard), URL the user should visit.

### *class* falaw.AreaUsage(name, path, entries, bytes)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Disk usage of one cache area.

`entries` counts the area’s own unit — cache entries for `manifests`,
blobs for `content`, files for `assets` and `url_index` — not files
on disk, which is why it is reported next to `bytes` rather than derived
from it.

`path` is `None` when the area has no directory of its own. That is the
case for `manifests` (scattered across two-character shard directories at
the cache root) and for `other`. It is deliberately not the cache root:
a caller reaching for `rmtree(usage.area(...).path)` would then destroy
the content store along with it.

### *class* falaw.Asset(url, kind, content_type='', width=0, height=0, duration_s=0.0, metadata=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A single piece of generated media.

Holds the URL plus minimal typed metadata. `download` materializes it.

#### download(, to=None, fix_suffix=False)

Download the asset to a file. Returns the local path.

The bytes are sniffed: some models return a different format than the
usual one (Recraft’s `vector_illustration/*` styles return SVG, not
PNG). If the suffix of `to` contradicts the content, a
`UserWarning` is issued; with `fix_suffix=True` the suffix is
corrected instead (so the returned path may differ from `to`).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### *class* falaw.Beat(, id, speaker='', line='', action='', emotion='', shot_id='', duration_s=None, notes='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The atomic unit of a scene: who, says what, with what intent.

A Beat that has only `action` (no `line`) is a non-verbal beat.

### *class* falaw.CacheUsage(root, areas)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Where the falaw cache’s disk is going, by area.

The whole point of the breakdown: `size_bytes` alone cannot tell you
whether you are looking at gigabytes of irreplaceable blobs or gigabytes of
`assets/` copies that cost nothing to regenerate.

#### area(name)

The [`AreaUsage`](#falaw.AreaUsage) named `name`.

* **Raises:**
  [**KeyError**](https://docs.python.org/3/builtins/exceptions.html#KeyError) – no such area. The valid names are `AREA_NAMES`.
* **Return type:**
  [`AreaUsage`](falaw.prune.html.md#falaw.prune.AreaUsage)

#### summary()

One human-readable line per area, largest first.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### *property* total_bytes *: [int](https://docs.python.org/3/builtins/functions.html#int)*

Every byte under the cache root.

Equal to a full walk of the root, because `other` absorbs whatever the
named areas do not claim. That identity is the point: a capacity report
whose total is “the sum of the areas I thought to enumerate” silently
under-reports the moment falaw grows a directory nobody added here, and
under-reporting is the one direction a capacity tool cannot afford.

### *class* falaw.CallOutcome(, index, call, status, artifact=None, error=None, cache_hit=False, blocked_by=(), reason='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What happened to one [`CallPlan`](#falaw.CallPlan), at its position in the Plan.

`index` is the call’s position in `plan.calls` and is the identity a
caller retries or re-plans by — a report always carries exactly one outcome
per call, in plan order, so `index` is also the safe key for zipping a
Plan against anything the caller built alongside it.

#### artifact *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[Artifact]*

The materialized artifact. Set if and only if `status == "succeeded"`.

#### blocked_by *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[int](https://docs.python.org/3/builtins/functions.html#int), ...]*

Indices of the calls whose non-success blocked this one. `()` when the
call was blocked for a run-level reason rather than a dependency.

#### cache_hit *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

Whether the result came from the cache **as observed at run time**.

Not the same thing as [`falaw.CallPlan.cache_status`](#falaw.CallPlan.cache_status), which is a
*prediction* made at plan time and can be wrong in both directions (a
concurrent run filled the entry; a hit turned out to be unusable and was
re-executed). Run-level cost accounting reads this one.

#### call *: [CallPlan](falaw.plan.html.md#falaw.plan.CallPlan)*

The call this outcome is about — enough to retry it verbatim.

#### error *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[BaseException](https://docs.python.org/3/builtins/exceptions.html#BaseException)]*

The exception the call raised. Set if and only if `status == "failed"`.

Kept as the exception object rather than a string so the caller can use
falaw’s typed hierarchy ([`falaw.errors`](falaw.errors.html.md#module-falaw.errors)) to decide between backing off,
switching models, and giving up.

#### index *: [int](https://docs.python.org/3/builtins/functions.html#int)*

Position in `plan.calls`. Stable, and unique within a report.

#### *property* ok *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

Shorthand for `status == "succeeded"`.

#### reason *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

Human-readable explanation. Required for `blocked`; free otherwise.

#### status *: [Literal](https://docs.python.org/3/library/typing.html#typing.Literal)['succeeded', 'failed', 'blocked']*

`"succeeded"` / `"failed"` / `"blocked"`. See the module docstring.

### *class* falaw.CallPlan(, tool, application, backend='fal', arguments, output_kind, estimated_cost_usd=None, cache_status='unknown', expected_duration_s=None, expected_wall_time_s=None, metadata=dict(), key_extra=dict(), local_files=(), cost_basis=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A single planned fal call. Pure data — no API contact yet.

`application` and `arguments` are the *exact* tuple
`cached_call_fal(application, arguments)` would take, so a Plan can be
cache-checked, executed, or replayed without ambiguity.

#### application *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The fal model id that will be invoked (e.g. `"fal-ai/flux/dev"`).
Backend-scoped: what it names depends on [`backend`](#falaw.CallPlan.backend).

#### arguments *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)*

Keyword arguments to pass to fal. Will be JSON-canonicalized for
cache key computation; should be JSON-serializable.

#### backend *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

Which execution backend [`execute_plan()`](#falaw.execute_plan) dispatches this call to
(falaw#15) — see [`falaw.backends`](falaw.backends.html.md#module-falaw.backends). Defaults to
[`falaw.canonical.DFLT_BACKEND`](falaw.canonical.html.md#falaw.canonical.DFLT_BACKEND) (`"fal"`), the only backend until a
second one lands. Enters the per-call cache key and `plan_hash` only
when it is **not** the default, so every call falaw has ever planned or
cached keeps its exact pre-#15 digest — see [`falaw.canonical`](falaw.canonical.html.md#module-falaw.canonical).

#### *property* billable_cost_usd *: [float](https://docs.python.org/3/builtins/functions.html#float)*

Cost that will actually be billed (0 on cache hit, estimate otherwise).

Returns `0.0` (not `None`) on cache hit or unknown estimate so
sums are well-defined; use [`estimated_cost_usd`](#falaw.CallPlan.estimated_cost_usd) `is None` to
check unknown status explicitly.

#### cache_status *: [Literal](https://docs.python.org/3/library/typing.html#typing.Literal)['hit', 'miss', 'stale', 'unknown']*

Whether the cache will short-circuit this call. `"hit"` means
`execute` won’t bill, so [`Plan.total_cost_usd`](#falaw.Plan.total_cost_usd) and
[`Plan.cache_hit_savings_usd`](#falaw.Plan.cache_hit_savings_usd) reflect that.

#### cost_basis *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[CostBasis](falaw.plan.html.md#falaw.plan.CostBasis)]*

How [`estimated_cost_usd`](#falaw.CallPlan.estimated_cost_usd) was computed, or `None` when nothing
recorded it (falaw#60). Present, the quote can be re-run against today’s
rate table by [`falaw.reprice_plan()`](#falaw.reprice_plan); absent, that function reports the
call as `"no_basis"` and clears its cost to unknown rather than passing a
stale figure off as current. Purely descriptive — it stays out of
[`plan_hash()`](#falaw.plan_hash) and the per-call cache key, and out of the serialized
dict entirely when unset, so every plan falaw has ever hashed or persisted
is unmoved.

#### estimated_cost_usd *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[float](https://docs.python.org/3/builtins/functions.html#float)]*

Predicted cost in USD. `None` when the model has no `cost_estimate`
populated (callers can distinguish “free” from “unknown”).

#### expected_duration_s *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[float](https://docs.python.org/3/builtins/functions.html#float), [float](https://docs.python.org/3/builtins/functions.html#float)]]*

`(min, max)` duration the model can produce, or `None` if no
duration contract is known. Plan-level validators can check that the
requested duration fits this range and raise [`FalDurationOutOfRange`](#falaw.FalDurationOutOfRange)
*before* the call instead of letting it silently truncate.

#### expected_wall_time_s *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[float](https://docs.python.org/3/builtins/functions.html#float), [float](https://docs.python.org/3/builtins/functions.html#float)]]*

`(low, high)` seconds the call is expected to take to come back (not
the clip length: see [`expected_duration_s`](#falaw.CallPlan.expected_duration_s)). From the catalogue’s
measured `typical_wall_time_s`; `None` when not measured. Left out of
[`call_plan_to_dict()`](#falaw.call_plan_to_dict) when `None`.

#### key_extra *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)*

Identity beyond the wire arguments — entries that change what the call
*produces* without appearing in `arguments`. Participates in the
per-call cache key AND `plan_hash`, under omit-if-empty (an empty dict
leaves every existing key byte-identical). Unlike `metadata`, which is
deliberately identity-free labelling, putting something here says “a
cached result minted without this value must not be reused”. First
customer: nw’s Transform `impl_version` (nw#27) — “same interface,
changed behaviour” must miss the cache without renaming anything.

#### local_files *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)*

one pointer
(a tuple of dict keys / list indices) per `os.PathLike` the caller passed.
Only these are resolved at execute time (uploaded on a cache miss, keyed on
the file’s sha256), so a string that merely looks like a marker is inert.
Omit-when-empty on the wire (like `cost_basis`): a plan with no local
file serializes to the bytes it did before the field existed; absent reads
as empty.

* **Type:**
  Where [`arguments`](#falaw.CallPlan.arguments) holds local-file markers (falaw#92)

#### metadata *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)*

Free-form labels for downstream consumers. Conventional keys:
`shot_id`, `beat_id`, `character_name`, `strategy`.

#### output_kind *: [Literal](https://docs.python.org/3/library/typing.html#typing.Literal)['image', 'video', 'audio', 'json', 'text', 'binary']*

What kind of Artifact this call will produce.

#### tool *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

High-level tool name — `"generate_image"`, `"image_to_video"`, etc.
Distinct from `application` because one tool may dispatch to several
fal models depending on quality tier.

### *class* falaw.CallRepricing(, index, call, old_cost_usd, new_cost_usd, status, reason='', basis_changed=False)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The before/after for one call in a re-priced plan.

#### basis_changed *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True when the rate table’s identity or version moved between the
persisted basis and today’s — the audit answer to “did the price change
because the *table* changed?”. Always `False` for `"no_basis"`, which
has nothing to compare against.

#### call *: [CallPlan](falaw.plan.html.md#falaw.plan.CallPlan)*

The re-priced call — the same call with today’s
`estimated_cost_usd` and a basis stamped with today’s table version.

#### *property* delta_usd *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[float](https://docs.python.org/3/builtins/functions.html#float)]*

`new - old`, or `None` when either side is unknown.

`None` rather than `0.0`: a call that lost or gained its price did
not move by zero, and a caller summing deltas must not be handed a
number that says it did.

#### index *: [int](https://docs.python.org/3/builtins/functions.html#int)*

Position in the original [`falaw.Plan`](#falaw.Plan).

#### new_cost_usd *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[float](https://docs.python.org/3/builtins/functions.html#float)]*

What today’s rates say, `None` for unknown or no-basis.

#### old_cost_usd *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[float](https://docs.python.org/3/builtins/functions.html#float)]*

What the persisted plan said, `None` if it said unknown.

#### reason *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

Why, when the status is `"unknown"` or `"no_basis"`. Empty otherwise.

#### status *: [Literal](https://docs.python.org/3/library/typing.html#typing.Literal)['unchanged', 'changed', 'unknown', 'no_basis']*

Which of the four cases this call fell into — see `RepriceStatus`.

### *class* falaw.Character(, name, description='', reference_image_url='', voice=None, style_notes='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A reusable character: stable face, stable voice, stable style.

### *class* falaw.ContentRef(content_hash, bytes_size)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A content-addressed handle on some bytes falaw has materialized.

`content_hash` is the SHA-256 hex digest of the bytes — the value
`lacing.Artifact.asset_id` is contractually required to hold, and the
value that goes into a downstream cache key in place of a URL.

### *class* falaw.CostBasis(, pricer, priced, quantities=dict(), table='', table_version='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

How a [`CallPlan.estimated_cost_usd`](#falaw.CallPlan.estimated_cost_usd) was arrived at (falaw#60).

A frozen quote goes stale the moment the rate table moves — 0.0.46 moved
falaw’s LLM prices tenfold — and a persisted plan cannot be re-quoted from
`application` and `arguments` alone: the quantity hints that priced it
(the clip’s duration, the prompt’s token bound) are estimator-only and
never enter the wire arguments. This records them, plus *which* table
priced them, so a saved plan can be re-quoted faithfully
([`falaw.reprice_plan()`](#falaw.reprice_plan)) and audited after the fact.

Pure data. Nothing here reaches the network, and nothing here enters
[`plan_hash()`](#falaw.plan_hash) or the per-call cache key: a basis says what a call
*cost*, never what it *produces*, so stamping one leaves every existing
digest byte-identical.

#### priced *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

a `falaw.ModelRecord.id` for the
catalogue pricer, the routed `model` argument for the LLM pricer.
Distinct from [`CallPlan.application`](#falaw.CallPlan.application), which for `fal-ai/any-llm`
names the router rather than the model that sets the price.

* **Type:**
  The entity that was priced

#### pricer *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

Which pricing rule produced the figure — a key into
[`falaw.reprice.DFLT_PRICERS`](falaw.reprice.html.md#falaw.reprice.DFLT_PRICERS). `"model_catalogue"` for a record
priced out of `models.json`, `"llm_rates"` for a routed LLM priced out
of `llm_rates.json`. An unrecognized name re-prices as *unknown*, never
as the old number.

#### quantities *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)*

The estimator-only shape hints fed to the pricer, by keyword —
`{"seconds": 6.0}`, `{"input_tokens": 20000, "max_output_tokens": 4000}`.
Absent keys mean the hint was not supplied, which is what made a
quantity-priced call unpriceable in the first place. Omit-when-unset: a
hint that was `None` at plan time is left out rather than written as
`null`.

#### table *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

Identity of the rate table consulted, e.g.
`"falaw/data/llm_rates.json"`. Free-form so a caller’s own reconciled
table can name itself.

#### table_version *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The version of that table at plan time — falaw stamps a short content
digest, so a table whose numbers moved gets a different value even when
its declared version did not. Empty means unversioned/unknown.

### *class* falaw.CostEstimate(, kind, amount, currency='USD', notes='', source='approximate')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Quantitative cost of one fal call against this model.

#### kind

How the price scales. `per_call` is the simplest:
constant per invocation regardless of size. `per_second`
applies to video / TTS where output length matters.
`per_image` covers batch image gen. `per_megapixel`
covers high-res image generation. `per_token` covers
LLM-style endpoints.

* **Type:**
  [`Literal`](https://docs.python.org/3/library/typing.html#typing.Literal)[`'per_call'`, `'per_image'`, `'per_second'`, `'per_token'`, `'per_megapixel'`]

#### amount

USD (or `currency`) per unit defined by `kind`.

* **Type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### currency

ISO 4217 code. `"USD"` is the only supported value
today; the field exists so we can extend without a schema
migration.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### notes

Free-form caveats — “rounded up to next second”, etc.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### source

How the estimate was obtained — `"docs"`,
`"empirical"`, `"approximate"`. Lets us flag stale or
unverified entries in audits.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### *class* falaw.CostLine(, kind, item_id, model_id, amount, currency, note='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One line item in a scene rollup.

### *class* falaw.CostRollup(, total_amount, currency='USD', lines=(), skipped=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Result of [`estimate_scene_cost()`](#falaw.estimate_scene_cost).

#### by_kind()

Sum per `kind` for quick inspection.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]

### *class* falaw.Environment(, name, description='', reference_image_url='', time_of_day='', lighting='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A reusable location/setting.

### *class* falaw.ExecutionReport(outcomes=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The result of running a Plan: one [`CallOutcome`](#falaw.CallOutcome) per call, in order.

`len(report.outcomes) == len(plan.calls)` **always**, including on a run
where most calls failed. That invariant is the whole point: a consumer that
built something per call (nw builds one skeleton annotation per call) can
zip against [`outcomes`](falaw.outcomes.html.md#module-falaw.outcomes) and stay aligned. Zipping against a
*shorter* list of successes is the silent mis-pairing this type exists to
prevent.

#### artifacts_or_raise()

Every artifact in plan order, or re-raise the first failure’s exception.

The bridge back to the plain `list[Artifact]` contract of
[`falaw.execute_plan()`](#falaw.execute_plan). The exception raised is the **original** one
the call raised, unwrapped — falaw’s typed error hierarchy
([`falaw.errors`](falaw.errors.html.md#module-falaw.errors)) is only useful to a caller if it survives the trip
through the executor.

A run with no failures but some blocked calls raises too: the list would
otherwise be short, and a short list is exactly the silent mis-pairing
this type exists to prevent.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[`Artifact`]

#### *property* blocked *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[CallOutcome](falaw.outcomes.html.md#falaw.outcomes.CallOutcome), ...]*

Outcomes whose call never ran, in plan order.

#### *property* cache_hit_savings_usd *: [float](https://docs.python.org/3/builtins/functions.html#float)*

Estimated USD *not* spent because a succeeded call was served from cache.

The run-time counterpart of [`falaw.Plan.cache_hit_savings_usd`](#falaw.Plan.cache_hit_savings_usd)
(which is a plan-time prediction).

#### *property* estimated_spend_usd *: [float](https://docs.python.org/3/builtins/functions.html#float)*

succeeded calls that were **not** cache hits.

Estimated, because it sums [`falaw.CallPlan.estimated_cost_usd`](#falaw.CallPlan.estimated_cost_usd) —
falaw does not read fal’s invoice. Two deliberate exclusions:

- **Cache hits cost nothing**, and this reads the *observed*
  [`CallOutcome.cache_hit`](#falaw.CallOutcome.cache_hit), not the plan-time prediction.
- **Failed calls are not counted.** The vendor may or may not have
  billed a call that raised, and falaw cannot know which; adding an
  estimate for it would be inventing a number. Read
  [`failed`](#falaw.ExecutionReport.failed) to see how many calls are unaccounted for.

* **Type:**
  Estimated USD billed by this run

#### *property* failed *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[CallOutcome](falaw.outcomes.html.md#falaw.outcomes.CallOutcome), ...]*

Outcomes whose call raised, in plan order.

#### *property* has_unknown_costs *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True when a call that actually billed has no price estimate.

The run-level twin of [`falaw.Plan.has_unknown_costs`](#falaw.Plan.has_unknown_costs), and the
reason [`estimated_spend_usd`](#falaw.ExecutionReport.estimated_spend_usd) must never be read on its own: an
unpriced call contributes `0.0` to the sum, so a report reading
`$0.00` means *either* “nothing was spent” *or* “we do not know what
was spent”. Those are not the same answer, and a budget gate that
cannot tell them apart approves the second one.

#### *property* is_complete *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True when every call succeeded.

#### *property* produced *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[Artifact, ...]*

The artifacts that were made, in plan order.

**Shorter than the Plan when anything failed** — deliberately named so
it does not read like something to zip a per-call sequence against. Use
[`outcomes`](falaw.outcomes.html.md#module-falaw.outcomes) for anything positional.

#### *property* succeeded *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[CallOutcome](falaw.outcomes.html.md#falaw.outcomes.CallOutcome), ...]*

Outcomes that produced an artifact, in plan order.

#### summary()

A small JSON-able digest — counts, spend, and which indices failed.

For logs, telemetry and run records, where the artifacts and exception
objects themselves are not serializable.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### *exception* falaw.FalAccountLocked(message, , status_code, detail='', body=None, headers=None, application=None, url=None, cause=None)

Bases: [`FalHTTPError`](falaw.errors.html.md#falaw.errors.FalHTTPError)

fal account is locked / suspended / awaiting verification.

Typical 403 with a body indicating the account is not in good standing.
No amount of retrying or model-switching will fix this — the user has
to act (verify email, top up billing, contact support).

### *exception* falaw.FalAssetFetchError(message, , url, cause=None)

Bases: [`FalError`](falaw.errors.html.md#falaw.errors.FalError)

The bytes behind a fal-served asset URL could not be retrieved.

Raised by [`falaw.content`](falaw.content.html.md#module-falaw.content) when content-addressing an artifact fails —
the URL 404s (fal deletes expired files permanently), the transfer errors,
or the response is empty. It is deliberately **loud**: returning an
Artifact whose `asset_id` is not the SHA-256 of any bytes would break
`lacing.Artifact`’s content-hash contract and poison every downstream
cache key derived from it.

### *exception* falaw.FalBadRequest(message, , status_code, detail='', body=None, headers=None, application=None, url=None, cause=None)

Bases: [`FalHTTPError`](falaw.errors.html.md#falaw.errors.FalHTTPError)

Server rejected the request payload — typical 400 / 422.

### *exception* falaw.FalClientNotInstalled(what='calling fal.ai', , missing='fal_client')

Bases: [`FalError`](falaw.errors.html.md#falaw.errors.FalError), [`ImportError`](https://docs.python.org/3/builtins/exceptions.html#ImportError)

A real network call was attempted but the fal.ai client is not installed.

`pip install falaw` carries no fal.ai client, so that callers that only
build, price, hash and cache plans install none. Anything that actually
reaches fal.ai needs the `fal` extra: `pip install 'falaw[fal]'`.
It is an [`ImportError`](https://docs.python.org/3/builtins/exceptions.html#ImportError), so `except ImportError` still matches.

### *exception* falaw.FalDurationOutOfRange(message, , model_id, requested, valid_range)

Bases: [`FalError`](falaw.errors.html.md#falaw.errors.FalError)

The requested duration is outside what the model can produce.

Raised by Plan/Execute when the caller asks for `duration_s` that the
model’s declared `expected_duration_range` cannot satisfy. Callers can
catch this to split the shot, repeat it, or pick a different model.

### *exception* falaw.FalError

Bases: [`Exception`](https://docs.python.org/3/builtins/exceptions.html#Exception)

Base for all falaw-raised exceptions.

### *exception* falaw.FalHTTPError(message, , status_code, detail='', body=None, headers=None, application=None, url=None, cause=None)

Bases: [`FalError`](falaw.errors.html.md#falaw.errors.FalError)

Wraps an HTTP error from fal.ai with the original status, body, and headers.

Subclasses pick out specific status codes / patterns. Use this base when
you want to catch any HTTP failure (e.g. for retry).

### *exception* falaw.FalInsufficientFunds(message, , status_code, detail='', body=None, headers=None, application=None, url=None, cause=None)

Bases: [`FalHTTPError`](falaw.errors.html.md#falaw.errors.FalHTTPError)

Account balance is insufficient — typical 402.

### *exception* falaw.FalModelHung(message, , model_id, elapsed_s)

Bases: [`FalError`](falaw.errors.html.md#falaw.errors.FalError)

A model was queued but never returned — distinct from a network timeout.

Raised by higher-level orchestration that sets a per-call wall-clock
budget (e.g. “give up on this lipsync after 5 minutes and pick another model”).

### *exception* falaw.FalNonCanonicalArgument(message, , path)

Bases: [`FalError`](falaw.errors.html.md#falaw.errors.FalError)

An argument cannot be canonicalised into falaw’s hashed JSON form.

Raised by [`falaw.canonical`](falaw.canonical.html.md#module-falaw.canonical) when a value reaches a key-composition
site (the per-call cache key, `plan_hash`, the dry-run artifact id) that
JSON cannot represent faithfully: a non-JSON object, a non-finite float,
or a non-string mapping key. Deliberately **loud**: the old behaviour —
`json.dumps(..., default=str)` — silently collided structurally
different calls into one cache key, handing back the *wrong artifact* as
a supposed saving (falaw#17).

`path` names the offending node, e.g. `arguments.extra.ref`.

### *exception* falaw.FalPromptTooLong(message, , model, limit, length)

Bases: [`FalError`](falaw.errors.html.md#falaw.errors.FalError), [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

The prompt exceeds the model’s hard length cap (falaw#76).

Raised before any call is queued: fal answers an over-long prompt with an
HTTP 422 only after the request round-trips. `limit`/`length` are in
characters.

### *exception* falaw.FalRateLimited(message, , retry_after_s=None, \*\*kwargs)

Bases: [`FalHTTPError`](falaw.errors.html.md#falaw.errors.FalHTTPError)

fal is throttling requests — typical 429.

`retry_after_s` is parsed from the `Retry-After` header if present,
else `None` (caller decides backoff).

### *exception* falaw.FalServerError(message, , status_code, detail='', body=None, headers=None, application=None, url=None, cause=None)

Bases: [`FalHTTPError`](falaw.errors.html.md#falaw.errors.FalHTTPError)

fal-side server error — typical 5xx. Generally retryable.

### *exception* falaw.FalTermsViolation(message, , model_id, backend, clause, source_url='')

Bases: [`FalError`](falaw.errors.html.md#falaw.errors.FalError)

The model’s terms of service forbid (or leave unknown) this use.

Raised by [`falaw.terms.check_terms()`](falaw.terms.html.md#falaw.terms.check_terms) at plan time (`plan_*`) and, opt-in, at
execution time (`execute(..., terms_context=)`) — before any call,
not audited after. `unknown` refuses, like `has_unknown_costs` does
for money. The message names the model, the backend, the clause and the
ledger row’s `source_url`; the same fields are attributes.

### *exception* falaw.FalTimeout(message, , elapsed_s, application=None)

Bases: [`FalError`](falaw.errors.html.md#falaw.errors.FalError)

The fal call timed out before producing a result.

### *exception* falaw.FalUnauthorized(message, , status_code, detail='', body=None, headers=None, application=None, url=None, cause=None)

Bases: [`FalHTTPError`](falaw.errors.html.md#falaw.errors.FalHTTPError)

Missing or invalid API credentials — typical 401.

### *class* falaw.LlmPrice(, provider, model, rates, long_prompt_over_tokens=None, long_prompt_rates=None, source='', date='', notes='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One row of the first-party table: a model’s rates and where they came from.

### *class* falaw.LlmRate(, model, tier, per_call_usd, input_usd_per_mtok=None, output_usd_per_mtok=None, source='', date='', notes='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What one routed model costs, on every basis the table knows.

#### model

The `model` argument value this row prices, e.g.
`"anthropic/claude-sonnet-4.5"`.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### tier

fal’s billing tier for the router — `"standard"` or
`"premium"`. Informational; `per_call_usd` is already
materialized, so no multiplier arithmetic happens in code.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### per_call_usd

What fal bills per request when this model is routed.

* **Type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### input_usd_per_mtok

Upstream list price per
`TOKENS_PER_RATE_UNIT` prompt tokens, or `None` when no
upstream rate is published for this id — unknown, never zero.

* **Type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

#### output_usd_per_mtok

The same for completion tokens.

* **Type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

#### source

Where these numbers came from.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### date

ISO date they were read on. Rates move; a quote is only as
fresh as its row.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### notes

Free-form caveats.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### *property* has_token_rates *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True when both token columns are populated, so a token quote is possible.

### *class* falaw.LlmReceipt(application, model, cache_hit, chars_in, chars_out, tokens_in=None, tokens_out=None, estimated_cost_usd=None, cost_source='unknown')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What one eager LLM call cost — the record the eager path never kept.

The falaw half of falaw#50’s option B: the eager [`llm_complete()`](#falaw.llm_complete)
returned a bare string, so LLM spend was invisible to every accounting
surface — not because estimates were `None`, but because \*nothing was
recorded at all\* (the field signature: real dollars spent beside
`plans: 0`). A caller that books receipts uses
[`llm_complete_with_receipt()`](#falaw.llm_complete_with_receipt) and gets this alongside the text.

Field semantics, honest by construction:

- `chars_in` / `chars_out` are **measured facts** (prompt+system in,
  response text out).
- `tokens_in` / `tokens_out` are **best-effort** from the raw
  response’s usage block (OpenAI `prompt_tokens`/`completion_tokens`
  and Anthropic `input_tokens`/`output_tokens` shapes). `None`
  means *unrecorded by the provider response*, never zero.
- `estimated_cost_usd` is `0.0` on a cache hit (nothing was billed),
  else fal’s published per-request price **for the routed model**, read
  off the rate table ([`falaw.llm_ceiling_usd()`](#falaw.llm_ceiling_usd)) — an estimate, not
  an observed bill. It is the routed model and not the `fal-ai/any-llm`
  record because the record carries fal’s *standard* tier, and a premium
  routed model bills ten times that: pricing every turn from the record
  under-reported premium spend tenfold in the ledger a consumer sums
  (falaw#55). `None` only when nothing can price it at all.
- `cost_source` says which of those cases produced the number, so a
  receipt consumer never has to guess: `"cache_hit"`,
  `"rate_table:per_call"`, `"registry:<kind>"` (the fallback for a
  model the table does not price), or `"unknown"`.

### *class* falaw.LlmTokenCounts(, fresh_input=0, cache_read=0, cache_write=0, cache_write_1h=0, output=0, reasoning=0)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The token counts a first-party call’s `usage` reports, normalized across
providers: the very counts [`llm_call_cost_usd()`](#falaw.llm_call_cost_usd) prices, so a caller that
records them next to the cost cannot disagree with it (falaw#89).

`fresh_input` is billed at the input rate, `cache_read` and
`cache_write` at their own; `cache_write_1h` is the part of
`cache_write` on the 1-hour tier (already included in it: do not add the two). `reasoning` is informational: it is
already inside `output`.

#### *property* input *: [int](https://docs.python.org/3/builtins/functions.html#int)*

Every prompt token, cached or not.

### *class* falaw.ModelRecord(, id, category, description='', aliases=(), quality_tier='', cost_hint='', cost_estimate=None, docs_url='', max_clip_seconds=None, single_character_recommended=False, supported_resolutions=(), default_negative_prompt='', default_pick=True, tokens_per_pixel_second=None, typical_wall_time_s=None, resolution_rate_factors=dict(), max_prompt_chars=None, size_param='image_size', param_specs=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One entry in the fal model catalog.

#### default_negative_prompt *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

Quality/realism negatives worth appending by default (e.g. to avoid the
plastic-skin look). Empty when none.

#### default_pick *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

Whether [`falaw.pick_model()`](#falaw.pick_model) may choose this record when a caller names
only a category and tier. `False` for a record that is catalogued, priced
and usable by id or alias but must never become the default — so its
`quality_tier` can state its real quality, and a price refresh’s re-sort
cannot promote it (falaw#95).

#### max_clip_seconds *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[float](https://docs.python.org/3/builtins/functions.html#float)]*

Practical max length of a single generated clip, in seconds (e.g. ~10
for Seedance). Drives the “this shot is too long, split it” warning.

#### max_prompt_chars *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[int](https://docs.python.org/3/builtins/functions.html#int)]*

Hard cap on `prompt` length, from the model’s OpenAPI schema. Calls
over it fail at fal with an HTTP 422 after queueing; falaw raises first.

#### param_specs *: [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Any](https://docs.python.org/3/library/typing.html#typing.Any)]]*

Discoverable per-model parameters that matter for choosing well, as
`{name: {"enum": [...], "default": ...}}` — e.g. Recraft’s `style`,
whose photoreal default silently overrides a woodcut prompt. See
[`falaw.model_params()`](#falaw.model_params).

#### resolution_rate_factors *: [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [float](https://docs.python.org/3/builtins/functions.html#float)]*

Per-resolution discounts off the recorded per-token rate, for a model
whose higher resolutions bill less per token (Seedance 2.0 at `"4k"`).
Each value is in (0, 1]: the fraction of the recorded rate fal bills, rounded
up so a quote stays a ceiling. The recorded rate is relative, so a price
refresh that moves it moves these quotes with it. A quote’s
`cost_basis.quantities["tokens"]` is then rate-equivalent tokens, not the
tokens fal counts. See [`falaw.cost.video_price_quantities()`](falaw.cost.html.md#falaw.cost.video_price_quantities).

#### single_character_recommended *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True when the model handles a single character per shot far better than
multiple interacting ones — drives the “two characters, consider
shot/reverse-shot” warning.

#### size_param *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

`"image_size"` (fal’s named
presets, the default) or `"aspect_ratio"` (+ `resolution`).

* **Type:**
  Which argument carries the output size

#### supported_resolutions *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]*

Resolutions the model offers, cheap→expensive (e.g. (“720p”, “1080p”)).

#### tokens_per_pixel_second *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[float](https://docs.python.org/3/builtins/functions.html#float)]*

tokens = width x height x seconds
x this (Seedance: 24/1024). With a `per_token` `cost_estimate` it lets
plan time quote an honest cost from a resolution and a duration
([`falaw.cost.video_price_quantities()`](falaw.cost.html.md#falaw.cost.video_price_quantities)). `None` for every other
model.

* **Type:**
  For a model billed per *video token*

#### typical_wall_time_s *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[float](https://docs.python.org/3/builtins/functions.html#float), [float](https://docs.python.org/3/builtins/functions.html#float)]]*

Measured wall-clock range `(low, high)` in seconds of one call, for a
model whose latency is worth telling the caller about (Seedance 2.0: minutes,
barely proportional to clip length). A video plan copies it to
`CallPlan.expected_wall_time_s`. `None` when not measured.

### *class* falaw.ModelTerms(, model_id, backend, license='unknown', license_binds_us='unknown', commercial_use='unknown', third_party_tenancy='unknown', c2pa_compatible='unknown', provenance_constraint='', notes='', source_url='', observed_on='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One ledger row. A field left `unknown` is a refusal when it matters.

### *class* falaw.Plan(calls=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

An ordered sequence of [`CallPlan`](#falaw.CallPlan) — a render plan, in essence.

Plans compose: `a + b` returns a new Plan with `a.calls` followed by
`b.calls`. `Plan(calls=())` is the identity. Plans are frozen, so
edits return new Plans (use [`with_call_replaced()`](#falaw.Plan.with_call_replaced) for in-place-feel).

#### *property* cache_hit_savings_usd *: [float](https://docs.python.org/3/builtins/functions.html#float)*

USD that would have been spent without the cache.

Equal to `sum(c.estimated_cost_usd for c in calls if c.cache_status == "hit"
and c.estimated_cost_usd is not None)`.

#### *property* has_unknown_costs *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True if any non-cache-hit call has no cost estimate.

Use this to refuse to gate on a budget when the estimate is incomplete.

#### *property* known_cost_usd *: [float](https://docs.python.org/3/builtins/functions.html#float)*

The priced part of [`total_cost_usd`](#falaw.Plan.total_cost_usd) — same number today,
but honest by construction.

`total_cost_usd` coerces unpriced calls to `$0.00` so sums stay
well-defined; a cumulative budget gate that reads it alone will
under-quote (400 unpriceable video calls total $0.00). Read this
together with [`unknown_call_count`](#falaw.Plan.unknown_call_count): the true cost is
`known_cost_usd` *plus an unknown amount* spread over that many
calls, and a correct gate refuses when the count is nonzero rather
than pretending the unknown part is free (falaw#18).

#### *property* total_cost_usd *: [float](https://docs.python.org/3/builtins/functions.html#float)*

Sum of [`CallPlan.billable_cost_usd`](#falaw.CallPlan.billable_cost_usd) across all calls.

#### *property* unknown_call_count *: [int](https://docs.python.org/3/builtins/functions.html#int)*

How many billable calls carry no price at all.

The countable form of [`has_unknown_costs`](#falaw.Plan.has_unknown_costs) — see
[`known_cost_usd`](#falaw.Plan.known_cost_usd) for the budget-gate arithmetic it enables.

#### with_call_replaced(index, new_call)

Return a new Plan with `calls[index]` replaced.

* **Return type:**
  [`Plan`](falaw.plan.html.md#falaw.plan.Plan)

### *class* falaw.Pricer(\*, quote, table, version=<function Pricer.<lambda>>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One pricing rule, and the table that backs it.

The seam for a caller with their own numbers: build a `Pricer` closing
over a reconciled rate table and pass `pricers={\*\*DFLT_PRICERS,
LLM_RATES_PRICER: mine}` to [`reprice_plan()`](#falaw.reprice_plan). The `table` /
`version` pair is stamped onto the re-priced call’s basis, so the next
audit can see which table produced which number.

`table` is also a **gate, not just a label**: a call whose basis names a
different table is reported as `unknown` rather than re-quoted, so a row
priced from your invoice is never silently re-quoted at falaw’s published
rate (or the reverse). Give your `Pricer` the same `table` string the
basis carries — [`falaw.llm_rates.CUSTOM_LLM_RATES_TABLE`](falaw.llm_rates.html.md#falaw.llm_rates.CUSTOM_LLM_RATES_TABLE) for anything
a `plan_*` priced with `llm_rates=`.

#### quote *: [Callable](https://docs.python.org/3/library/typing.html#typing.Callable)[[[CostBasis](falaw.plan.html.md#falaw.plan.CostBasis)], [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[float](https://docs.python.org/3/builtins/functions.html#float)]]*

Price `basis` in USD, or return `None` for *unknown*. May raise; a
raise is reported as `"unknown"` with the exception text as the reason,
so one unpriceable row never aborts a whole plan’s re-quote.

#### table *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

Identity of the table this pricer reads, for the refreshed basis.

#### version *: [Callable](https://docs.python.org/3/library/typing.html#typing.Callable)[[], [str](https://docs.python.org/3/builtins/stdtypes.html#str)]*

Today’s version of that table, for the refreshed basis.

### *class* falaw.ProgressEvent(, kind, application, call_id, message='', pct=None, elapsed_s=0.0, provider_phase=None, queue_position=None, metrics=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One step in the lifecycle of a fal call.

#### kind

Lifecycle stage. See `EventKind`.

* **Type:**
  [`Literal`](https://docs.python.org/3/library/typing.html#typing.Literal)[`'queued'`, `'progress'`, `'log'`, `'done'`, `'error'`, `'cache_hit'`, `'provider_queued'`]

#### application

fal model id (e.g. `"fal-ai/flux/dev"`).

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### call_id

A short hex string that uniquely identifies the call.
All events for one `call_fal` invocation share the same
`call_id`.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### message

Free-form text. For `"log"` events this is the log
line; for `"error"` it’s `repr(exc)`; otherwise empty.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### pct

Optional progress percentage in [0.0, 100.0]. fal’s
current API doesn’t surface this; included for forward
compatibility.

* **Type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

#### elapsed_s

Seconds since the call started.

* **Type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### provider_phase

fal’s reported phase (see the module docstring), or `None`.

* **Type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Literal`](https://docs.python.org/3/library/typing.html#typing.Literal)[`'in_queue'`, `'in_progress'`]]

#### queue_position

fal’s `queue_position` on a `"provider_queued"` event
(0 = next); `None` on every other event.

* **Type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]

#### metrics

fal’s `Completed.metrics` on a `"done"` event, or `None`
(see the module docstring). A plain `dict`, so the event stays
serialisable (`dataclasses.asdict`, pickle, JSON); subscribers share
it and must not edit it.

* **Type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]

### *class* falaw.PruneCandidate(key, path, bytes, last_modified=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One thing a prune would delete (or did).

`last_modified` is `None` when the age could not be determined — a
non-filesystem blob backend, or a manifest too corrupt to read. Such a
candidate is never selected by `older_than` (an unprovable age is not
evidence of staleness) and is evicted last under `max_bytes`.

### *class* falaw.PruneReport(area, dry_run, candidates=(), deleted=(), kept_entries=0, kept_bytes=0, rebillable_entries=0, unreferenced_candidates=0, errors=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What a prune removed, or — with `dry_run=True` — would remove.

`rebillable_entries` is the number this exists for: cache entries that
will **cost money again** because of this prune. Its meaning is exact per
area, and each is a different claim:

- `manifests` — every dropped entry re-bills, so it equals the candidate
  count.
- `content` — entries whose recorded response names an asset that resolves
  (through the `url -> hash` index) to a blob being dropped. Those become
  *unmaterializable* from cache; they re-download if fal still serves the
  URL and re-render if it does not, and falaw cannot tell which from here.
  It mirrors the predicate [`falaw.plan.execute()`](falaw.plan.html.md#falaw.plan.execute) applies to a hit from
  the **built-in** converter. It is therefore an *upper* bound, not an exact
  population: with a custom `artifact_converter=` the entry is never
  dropped (it returns a broken artifact instead), and with
  `fetch_bytes=False` dropping the blob changes nothing. Both errors are
  overcounts — the safe direction for a number you read before spending.
- `assets` — only the copies whose blob is *also* gone. While the blob
  survives, re-materializing is a local copy and costs nothing.

`unreferenced_candidates` is the other half of the story, and only
`content` populates it: blobs that **no manifest points at**. falaw cannot
tell whether such a blob is garbage or the last copy of something
irreplaceable — [`falaw.materialize_asset()`](#falaw.materialize_asset) puts reference images and
locally-rendered `file://` media in the same store, and those never had a
fal response behind them. Counting them as `rebillable` would be wrong
(no cache entry re-bills), but reporting nothing would tell an operator the
prune is free when it may be destroying the only copy of a reference image.

#### *property* freed_bytes *: [int](https://docs.python.org/3/builtins/functions.html#int)*

Bytes actually freed — or, under `dry_run`, that would be freed.

Sums `deleted`, **not** `candidates`. A deletion that failed (a
read-only volume, a permission error) leaves its bytes on disk, and a
capacity tool that reports them as reclaimed tells an operator staring
at a full disk that the problem is solved when it is not.

#### summary()

A human-readable line, phrased in the tense the run actually was.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### *class* falaw.RepricedPlan(, plan, calls=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Result of [`reprice_plan()`](#falaw.reprice_plan) — the new Plan plus the per-call diff.

Read [`plan`](falaw.plan.html.md#module-falaw.plan) for the re-quoted plan (it is an ordinary
[`falaw.Plan`](#falaw.Plan), so `known_cost_usd` / `unknown_call_count` /
`has_unknown_costs` mean what they always mean), and [`calls`](#falaw.RepricedPlan.calls) for
what changed and why.

#### calls *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[CallRepricing](falaw.reprice.html.md#falaw.reprice.CallRepricing), ...]*

One entry per call of the input plan, in order.

#### *property* changed *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[CallRepricing](falaw.reprice.html.md#falaw.reprice.CallRepricing), ...]*

Calls whose price moved — the ones a re-quote exists to surface.

#### *property* known_delta_usd *: [float](https://docs.python.org/3/builtins/functions.html#float)*

Sum of [`CallRepricing.delta_usd`](#falaw.CallRepricing.delta_usd) over calls priced both times.

The movement you can actually see. It says nothing about the calls in
[`unpriced`](#falaw.RepricedPlan.unpriced) — read that alongside it, never this alone.

#### plan *: [Plan](falaw.plan.html.md#falaw.plan.Plan)*

The re-priced plan. Structurally identical to the input — same calls,
same order, same arguments, so `plan_hash` is unmoved — with today’s
costs.

#### *property* unpriced *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[CallRepricing](falaw.reprice.html.md#falaw.reprice.CallRepricing), ...]*

`"unknown"` plus `"no_basis"`.

A budget gate refuses while this is non-empty, the same way it refuses
on [`falaw.Plan.has_unknown_costs`](#falaw.Plan.has_unknown_costs) — the two are the same
judgement, one made at re-quote time.

* **Type:**
  Calls today’s rates cannot price

### *class* falaw.Result(assets=list(), raw=dict(), application='', arguments=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A fal call result with parsed assets and the original raw response.

The raw response is kept so callers can inspect provider-specific fields
(timings, seed, has_nsfw_concepts, …) that we do not normalize.

### *class* falaw.Scene(, title, style='', characters=(), environments=(), shots=(), beats=(), notes='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The whole editable structure: cast, locations, shots, beats.

#### with_beat(beat)

Return a new Scene with `beat` replacing any existing beat with the same id.

* **Return type:**
  [`Scene`](falaw.scene.html.md#falaw.scene.Scene)

### *class* falaw.Session(output_dir=getcwd(), journal=\_default_journal(), history=list())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A working session for a sequence of falaw operations.

```pycon
>>> import tempfile
>>> s = Session(output_dir=tempfile.mkdtemp())
>>> s.history
[]
```

### *class* falaw.Shot(, id, description='', framing='medium', environment='', characters=(), camera='', notes='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A visual frame: framing + environment + characters in view.

Beats anchor to a Shot via `shot_id`. The Shot itself has its own
rendered output (still or short clip used as the anchor for beat
lipsync renders).

### *class* falaw.TermsContext(, commercial=True, third_party=False, c2pa=False)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What the job needs from the terms — supplied by the caller, never process-global
(an explicit argument, or scoped to a block by [`using_terms_context()`](#falaw.using_terms_context)).

The defaults describe the strictest ordinary use (commercial) without
claiming anything extra; `third_party` and `c2pa` are opt-in because
they are the facts only the deployment knows.

### *class* falaw.ToolSpec(, name, description, func, input_schema=dict(), output_schema=dict(), tags=(), examples=(), version='0.0.1')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Single source of truth for a tool exposed by falaw.

A ToolSpec is what the registry stores. Bridges read it to produce
Claude-skill instructions, MCP tool descriptors, HTTP endpoints, etc.

### *class* falaw.Voice(, name, voice_id='', reference_audio_url='', model_id='', style_notes='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A character’s voice spec.

Three modes, choose any:

* `voice_id` — model-side voice id (e.g. ElevenLabs voice).
* `reference_audio_url` — a few seconds of audio to clone.
* `model_id` — override the default TTS model for this voice.

Always provide `name` for stable, human-readable referencing.

### falaw.animate_face(image_url, audio_url, , prompt='', quality='balanced', model_id=None, extra=None)

Animate a still face from audio. Image + audio → talking video.

* **Return type:**
  [`Result`](falaw.results.html.md#falaw.results.Result)

### falaw.apply_note_to_beat(beat, note, , model='anthropic/claude-sonnet-4.5')

Use the LLM to apply a directorial note to a Beat.

* **Return type:**
  [`Beat`](falaw.scene.html.md#falaw.scene.Beat)

### falaw.apply_note_to_scene(scene, note, , model='anthropic/claude-sonnet-4.5')

Apply a cross-cutting note: LLM proposes per-beat edits, we apply them.

* **Return type:**
  [`Scene`](falaw.scene.html.md#falaw.scene.Scene)

### falaw.beat_content_hash(beat, , character=None)

Hash everything that affects how the beat *renders*.

Includes the beat’s content + the character’s identity anchors
(face image, voice spec). Style/emotion changes invalidate the
cache; pure id renames do not.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### falaw.cache_get(application, arguments, , backend='fal', key_extra=None)

Return the raw fal response if cached, else None.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### falaw.cache_put(application, arguments, raw, , note='', wire_arguments=None, backend='fal', key_extra=None)

Persist a fal response. Returns the entry directory path.

* **Parameters:**
  * **application** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – fal model id.
  * **arguments** ([`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]) – the arguments the entry is **keyed** on.
  * **raw** ([`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)) – the fal response to store.
  * **note** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – free-form label recorded in the manifest.
  * **wire_arguments** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]) – the arguments actually sent to fal, when they differ
    from the key arguments (chained calls send URLs but are keyed on
    content hashes). Recorded for debugging only — it never affects
    the key.
  * **backend** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – which execution backend produced `raw` (falaw#15). Joins
    the cache key only when non-default, same rule as
    [`falaw.canonical.cache_key_payload()`](falaw.canonical.html.md#falaw.canonical.cache_key_payload); recorded in the
    manifest under the same condition, for debugging.
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

The manifest is written to a temporary file and moved into place with
[`os.replace()`](https://docs.python.org/3/library/os.html#os.replace), so a reader never sees a half-written entry. That is not
hypothetical since `execute_plan(concurrency=N)`: two calls of one Plan
that are structurally identical land on the same key, and an interleaved
`json.dump` would leave a permanently unparseable entry — a cache that
poisons itself under exactly the fan-out it exists to make cheap.

### falaw.cache_stats()

Quick summary of the cache: entry count, disk usage, and where it went.

`areas` is the part worth reading. Since falaw#14 the cache holds the
*bytes* of every generated asset, so a total on its own cannot distinguish
gigabytes of irreplaceable blobs from gigabytes of `assets/` copies that
cost nothing to regenerate — and only the second is safe to reclaim without
thinking. Each area’s economics, and the primitives that reclaim it, are in
[`falaw.prune`](falaw.prune.html.md#module-falaw.prune).

`size_bytes` is every byte under the cache root, unchanged in meaning from
before the breakdown existed: the `other` area absorbs whatever the named
areas do not claim, so the areas always sum to the whole.

(`+SKIP`ed — it reads the caller’s real cache, a multi-gigabyte walk on
the production box. `tests.test_prune` pins this against a throwaway
cache instead.)

```pycon
>>> stats = cache_stats()
>>> sorted(stats["areas"])
['assets', 'content', 'manifests', 'other', 'scenes', 'url_index']
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### falaw.cache_usage()

Disk usage of the falaw cache, broken down by area.

The structured form behind [`falaw.cache_stats()`](#falaw.cache_stats). Read the module
docstring for what each area costs to reclaim.

* **Return type:**
  [`CacheUsage`](falaw.prune.html.md#falaw.prune.CacheUsage)

### falaw.cached_call_fal(application, arguments, , key_arguments=None, refresh=False, on_event=None, backend='fal', key_extra=None)

Call a fal model, but reuse the cached response when present.

* **Parameters:**
  * **application** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – fal model id.
  * **arguments** ([`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]) – model input dict — what is sent **on the wire**.
  * **key_arguments** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]) – what the cache entry is **keyed** on, when that differs
    from what goes on the wire. Defaults to `arguments`. The split
    exists because a chained call must send fal an expiring URL for its
    upstream input while being keyed on that input’s *content hash*, so
    a byte-identical upstream regeneration hits instead of re-billing.
  * **refresh** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – if True, bypass the cache and overwrite it with a fresh result.
  * **on_event** – Per-call subscriber for [`falaw.events.ProgressEvent`](falaw.events.html.md#falaw.events.ProgressEvent).
    On a cache hit, a synthetic `cache_hit` event is emitted so
    UIs can show “skipped” instead of “running”. On a call that ran, the
    `done` event’s `metrics` carries fal’s run metrics (e.g.
    `inference_time`); a hit has none, since nothing ran.
  * **backend** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – which execution backend serves this call (falaw#15) —
    resolved via [`falaw.backends`](falaw.backends.html.md#module-falaw.backends). Also joins the cache key
    (non-default only), so two backends never share an entry. Despite
    the name, this function is no longer fal-specific; the name is
    kept because “fal” is still the only backend and every existing
    call site already spells it this way.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
* **Returns:**
  Raw response (whether from cache or network).

### falaw.call_fal(application, arguments, , on_log=None, on_event=None, with_logs=True, journal_errors=True, api_key=None)

Call a fal model via fal_client.subscribe.

* **Parameters:**
  * **application** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – fal model id (e.g. `"fal-ai/flux/dev"`).
  * **arguments** ([`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]) – Input arguments. Keys depend on the model.
  * **on_log** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`None`](https://docs.python.org/3/builtins/constants.html#None)]]) – Legacy log callback — receives raw log lines as strings.
    Defaults to no-op (use `on_event` for structured access).
  * **on_event** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`ProgressEvent`](falaw.events.html.md#falaw.events.ProgressEvent)], [`None`](https://docs.python.org/3/builtins/constants.html#None)]]) – Per-call subscriber for `ProgressEvent`s. Fires
    in addition to the global subscribers registered via
    :func:`falaw.events.subscribe`.
  * **with_logs** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Pass through to fal_client; when True the model streams logs.
  * **journal_errors** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – When True, exceptions are recorded as journal issues
    before being re-raised. The journal entry includes the application
    id and arguments so future agents can recognize the same trap.
  * **api_key** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Explicit fal key for this call. When `None` (default) the
    key bound via [`using_fal_credentials()`](#falaw.using_fal_credentials) is used; when that is
    also unset, the fal SDK’s own `FAL_KEY` env-var lookup applies
    (the historical behaviour). A resolved key is used per-call via a
    dedicated `fal_client.SyncClient` — it is never written to a
    global or an env var.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
* **Returns:**
  The raw response dict from the model. fal’s run metrics (its final
  `Completed` status, e.g. `inference_time`) are not in it: they ride
  the `done` event’s `metrics` (see [`falaw.events`](falaw.events.html.md#module-falaw.events)).

### falaw.call_plan_from_dict(d)

Rebuild a [`CallPlan`](#falaw.CallPlan) from a [`call_plan_to_dict()`](#falaw.call_plan_to_dict) dict.

`arguments` / `metadata` are copied (a deserialized plan owns its own
data); `expected_duration_s` is re-tupled. `backend` defaults to
`DFLT_BACKEND` when absent — a dict written before falaw#15 names no
backend, and it always meant `"fal"`.

`cost_basis` is absent on any plan written before falaw#60 and on any
call nothing stamped; it comes back as `None`, which
[`falaw.reprice_plan()`](#falaw.reprice_plan) reports as `"no_basis"` — never as a quote
that is still current.

* **Return type:**
  [`CallPlan`](falaw.plan.html.md#falaw.plan.CallPlan)

### falaw.call_plan_to_dict(call)

Convert a [`CallPlan`](#falaw.CallPlan) to a plain JSON-serializable dict.

The inverse of [`call_plan_from_dict()`](#falaw.call_plan_from_dict). `expected_duration_s` (a
`tuple`) becomes a 2-element list since JSON has no tuple type;
everything else is already JSON-native.

`backend` (falaw#15) is a **tolerated-default addition**, not a
`PLAN_DICT_SCHEMA` bump: it is always written, but
[`call_plan_from_dict()`](#falaw.call_plan_from_dict) defaults it to `DFLT_BACKEND` when
absent, so a dict from before this field existed still parses, and a
dict written by this version still parses under older falaw (the extra
key is simply never read there). No migration needed either direction.

`cost_basis` (falaw#60) is the same kind of addition under a stricter
rule — **omit-when-unset**: the key is written only when a basis exists, so
a plan built without one serializes to the exact bytes it did before the
field existed, and every stored plan, fixture and cassette is unmoved.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### falaw.cast_character(name, description, , image_url='', style='', quality='high', voice_id='', reference_audio_url='', voice_style='')

Create a Character with a canonical face (and optional voice).

If `image_url` is given, we skip face generation and use that
image directly. Otherwise we run text-to-image with the description
(+ optional `style` suffix), cache the result, and use the URL.

* **Return type:**
  [`Character`](falaw.scene.html.md#falaw.scene.Character)

### falaw.cast_voice(character, , voice_id='', reference_audio_url='', style_notes='', model_id='')

Attach or update the Voice on a Character.

* **Return type:**
  [`Character`](falaw.scene.html.md#falaw.scene.Character)

### falaw.catalogue_cost_basis(model_id, \*\*quantities)

A [`falaw.CostBasis`](#falaw.CostBasis) for a call priced from `models.json`.

`quantities` are [`falaw.estimate_call_cost()`](#falaw.estimate_call_cost) keywords (`count`,
`seconds`, `megapixels`, `tokens`); `None` values are dropped, so a
hint that was never supplied is recorded as absent rather than as `null`
— the same thing the estimator saw.

```pycon
>>> catalogue_cost_basis("fal-ai/flux/dev", seconds=None).quantities
{}
```

* **Return type:**
  [`CostBasis`](falaw.plan.html.md#falaw.plan.CostBasis)

### falaw.check_model_liveness(ids=None, , status_of=None)

`{endpoint_id: is_live}` for `ids` (default: every catalogued model).

Only a 404 means dead; any other non-200 answer (rate limit, fal outage)
raises rather than report a live model as dead, which would get it deleted.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]

### falaw.check_terms(model_id, backend, context, , ledger=None, arguments=None)

Raise [`FalTermsViolation`](#falaw.FalTermsViolation) unless `(model_id, backend)` is
usable for *context*. `context=None` (the default everywhere) checks
nothing: the strict path is opt-in per deployment. Pass the call’s
`arguments` so a router is judged by the model it routes to
(`terms_subject()`).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### falaw.clear_subscribers()

Drop all registered subscribers. Mostly for tests.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### falaw.composite_character_in_environment(character_image_url, environment_image_url, , prompt='', quality='balanced', model_id=None, extra=None)

Place a character into an environment as one composited still.

The single most user-visible primitive missing from muvid (per
interface_design_plan item E). With this, an agent can produce
“Thor in a bell tower” — the character anchor for a downstream
omnihuman lipsync — without manually compositing in an image editor.

Defaults to `fal-ai/flux-kontext/dev` (image_edit category at
balanced/high tier). Pass `model_id` to override
(e.g. `"fal-ai/flux-pro/kontext/max"` for highest quality, or
`"fal-ai/bytedance/seededit/v3/edit-image"` for SeedEdit).

* **Return type:**
  [`Result`](falaw.results.html.md#falaw.results.Result)

### falaw.content_ref_for_url(url, , store=None, fetcher=None, refresh=False, assume_immutable=None)

Materialize `url`’s bytes into `store` and return their content hash.

Idempotent and cheap on repeat, but *how* cheap depends on whether the URL
can change behind falaw’s back — and falaw decides that rather than asking
the caller to know (thorwhalen/falaw#23):

1. **Immutable URL** (fal’s own — see `is_immutable_url()`) with a
   remembered hash whose blob is present: returned immediately, \*\*no
   network\*\*. This is what makes re-executing an already-cached plan free
   rather than re-downloading every clip.
2. **Mutable URL** with a remembered hash: falaw **revalidates** — a
   conditional `GET` replaying the recorded `ETag` / `Last-Modified`
   (for `file://`, a `(mtime, size)` comparison). A `304` costs one
   round-trip and no payload; a `200` means the bytes really changed and
   the new ones are stored, so the content hash changes with them.
3. **No usable answer** — nothing remembered, no validators recorded, or a
   transport that cannot make conditional requests: a plain fetch.

Step 3 is the important default. A transport that cannot revalidate makes
falaw **re-fetch**, never trust: an unverifiable hint is not evidence.

* **Parameters:**
  * **url** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The asset URL. `file://` is supported and treated as mutable.
  * **store** – Injected `lacing.ArtifactStore`; defaults to
    [`default_content_store()`](#falaw.default_content_store).
  * **fetcher** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]]]) – Injected byte source; defaults to [`default_url_fetcher()`](#falaw.default_url_fetcher)
    (the built-in `urllib` transport unless [`using_url_fetcher()`](#falaw.using_url_fetcher)
    has installed another). To support revalidation, a custom transport
    exposes a `conditional_fetch(url, validators) -> ConditionalOutcome`
    attribute; without one it is simply never asked.
  * **refresh** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Skip every shortcut and re-fetch unconditionally. Rarely needed
    now that mutable URLs revalidate on their own — keep it for a URL
    whose origin lies about its validators.
  * **assume_immutable** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool)]) – Override the host-based decision. `True` restores
    the old unconditional trust (use for a host you mint yourself, and
    prefer adding it to `IMMUTABLE_URL_HOSTS`); `False` forces
    revalidation even for fal.
* **Raises:**
  [**FalAssetFetchError**](#falaw.FalAssetFetchError) – the bytes could not be retrieved, or the response
      was empty. Never returns a reference it could not back with bytes —
      a silent zero-byte “artifact” is the failure mode this guards.
* **Return type:**
  [`ContentRef`](falaw.content.html.md#falaw.content.ContentRef)

### falaw.cost_basis_from_dict(d)

Rebuild a [`CostBasis`](#falaw.CostBasis) from a [`cost_basis_to_dict()`](#falaw.cost_basis_to_dict) dict.

* **Return type:**
  [`CostBasis`](falaw.plan.html.md#falaw.plan.CostBasis)

### falaw.cost_basis_to_dict(basis)

Convert a [`CostBasis`](#falaw.CostBasis) to a plain JSON-serializable dict.

`table` / `table_version` are omitted when empty, matching the
omit-when-unset discipline the rest of the wire shape follows — a basis
that names no table writes no key rather than a pair of `""`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### falaw.current_fal_key()

The fal API key bound for the current context, or `None`.

Resolution order callers should mirror: an explicit `api_key` argument
to [`call_fal()`](#falaw.call_fal) wins over this context value, which in turn wins over
the fal SDK’s own `FAL_KEY` env-var lookup.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### falaw.dead_models(ids=None, , status_of=None)

The ids from [`check_model_liveness()`](#falaw.check_model_liveness) that are no longer deployed.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### falaw.default_content_store()

The falaw-cache-rooted `lacing.ArtifactStore`.

Rooted at `<falaw cache dir>/content`, so it moves with
`$FALAW_CACHE_DIR` / `$FALAW_DATA_DIR` like every other piece of falaw
state. Constructed per call (the constructor only ensures directories
exist) so a test that re-points the cache dir gets a fresh store.

**Deleting a blob removes it from disk** rather than moving it to the OS
trash. `dol.Files` — the blob backend `from_directory` lays down —
trashes by default, including on Linux, which is a kind default for a
user’s own files and the wrong one here: every blob is derived data, and
the only thing in falaw that deletes one is [`falaw.prune.prune_content()`](falaw.prune.html.md#falaw.prune.prune_content),
whose whole job is to give the volume its space back. A trashed blob frees
nothing (the trash usually lives on the same volume) while the prune report
says it did (thorwhalen/falaw#66). The deletion is still an explicit,
`dry_run`-by-default operator act, so the trash was never the safety net.

### falaw.default_url_fetcher()

The transport used when no `fetcher=` argument is given.

[`using_url_fetcher()`](#falaw.using_url_fetcher)’s installed fetcher if there is one, else the
built-in `urllib`-based one. Resolved at call time, so every falaw entry
point that reads asset bytes — [`content_ref_for_url()`](#falaw.content_ref_for_url),
[`falaw.materialize_asset()`](#falaw.materialize_asset), [`falaw.execute_plan()`](#falaw.execute_plan) and
[`falaw.execute_plan_isolated()`](#falaw.execute_plan_isolated) — honours an override installed after
they were imported.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]]

### falaw.drop_cache_entry(application, arguments, , backend='fal', key_extra=None)

Delete the cache entry for `(application, arguments)`. Returns whether one existed.

The counterpart to [`cache_put()`](#falaw.cache_put), and the mechanism that keeps a cache
from becoming a *trap*. An entry whose response can no longer be turned
into a usable artifact — fal deleted the URL and the bytes are not in the
content store — must be a **miss**, not a permanent failure: without this,
escaping one dead call means re-running the whole plan.
[`falaw.plan.execute()`](falaw.plan.html.md#falaw.plan.execute) calls it.

The plan-level escapes are `execute_plan(plan, refresh=True)`, which
re-runs every call and **keeps** what it pays for, and
`execute_plan(plan, use_cache=False)`, which re-runs and keeps nothing —
so the second one bills again on the next run (falaw#49). Neither is a
substitute for this function: both re-bill *every* call in the plan, and
this drops the one entry that actually went bad.

Only the manifest is removed. Blobs in the content store are shared by
content hash across entries and are never dropped from here.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### falaw.edit_image(image_url, prompt, , quality='balanced', model_id=None, extra=None)

Edit an image with a natural-language instruction.

* **Return type:**
  [`Result`](falaw.results.html.md#falaw.results.Result)

### falaw.establish_environment(name, description, , time_of_day='', lighting='', image_url='', quality='high')

Create an Environment with a canonical establishing image.

* **Return type:**
  [`Environment`](falaw.scene.html.md#falaw.scene.Environment)

### falaw.estimate_call_cost(record, , count=1, seconds=None, megapixels=None, tokens=None)

Cost of one fal call against `record`.

Returns `None` when the cost is **unknown**, so callers can
distinguish “free” from “we can’t say”. That happens when the record
carries no `cost_estimate` at all, or when its pricing is
quantity-based (`per_second` / `per_token`) and the caller did
not supply the quantity — an unpriceable call, not a free one.

Returning `0.0` for a missing quantity would be actively dangerous:
a `per_second` clip is the single most expensive thing fal bills
for, and a caller gating a budget on the answer would read
“$0.00” and spend real money without a prompt. `None` instead
propagates to `CallPlan.estimated_cost_usd` and lights up
`Plan.has_unknown_costs`, which exists for exactly this case.
Callers that know the quantity should pass it; `per_second` callers
can fall back to `record.max_clip_seconds` for an upper bound.

`per_megapixel` is deliberately different: an image’s pixel budget
has a sane house default (below), so it stays priceable.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

### falaw.estimate_scene_cost(scene, , tts_quality='balanced', lipsync_quality='high', shot_quality='balanced', shots_as_video=False, shot_seconds=None)

Estimate the USD cost of a full [`render_scene()`](#falaw.render_scene) invocation.

Walks every shot + beat with the same `pick_model` semantics
the renderer uses, then sums per-call costs. Returns a structured
[`CostRollup`](#falaw.CostRollup) with per-line breakdowns, plus a list of
“skipped” entries the caller should surface (typically: a model
with no `cost_estimate` populated).

`shot_seconds` is the assumed clip length used to price
`shots_as_video`. A [`Shot`](#falaw.Shot) carries no duration of its own —
screen time comes from the renderer’s per-shot run — and
image-to-video models bill **per second**, so without this the video
lines are genuinely unpriceable and are reported in
`CostRollup.skipped` rather than silently priced at $0.00.
Pass the length you expect (the beat path has the same knob as
`estimated_seconds`).

* **Return type:**
  [`CostRollup`](falaw.cost.html.md#falaw.cost.CostRollup)

### falaw.execute_plan(plan, , on_event=None, dry_run=False, use_cache=True, refresh=False, artifact_converter=None, content_store=None, fetch_bytes=None, asset_fetcher=None, concurrency=1, terms_context=None)

Execute a Plan, returning a list of materialized :class:

```
`
```

lacing.Artifact\`s.

This is the **halt** policy: the first call that raises ends the run, and its
exception propagates unchanged (falaw’s typed hierarchy — see
[`falaw.errors`](falaw.errors.html.md#module-falaw.errors) — is what a caller classifies on, so it is never
wrapped). Use `execute_isolated()` when one bad call must not discard
the rest of a fan-out; it returns an [`ExecutionReport`](#falaw.ExecutionReport) with one
outcome per call instead of raising.

* **Parameters:**
  * **plan** ([`Plan`](falaw.plan.html.md#falaw.plan.Plan)) – The Plan to execute.
  * **on_event** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)]) – Optional per-call event subscriber (passed to `call_fal`).
  * **dry_run** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – When True, no fal calls are made; synthetic Artifacts are
    returned with placeholder `asset_id` and `url=None`. Useful
    for exercising downstream composition without an API key.
  * **use_cache** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – When True (default), executes via `cached_call_fal` so
    cache hits skip the network. When False, the cache is not touched
    **at all** — neither read nor written. That is the historical
    meaning and it is unchanged: a caller who genuinely wants no cache
    interaction still has it. To re-run a plan and *keep* what the
    re-run paid for, leave `use_cache=True` and pass `refresh`.
  * **refresh** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – When True, skip the cache **read** and keep the cache
    **write** — the third mode (falaw#49). Every call executes fresh,
    and every fresh result is stored under the key it would have been
    read from, so the next run (or a downstream consumer) hits it.
    Requires `use_cache=True`, since there is no key to write under
    when the cache is off; the contradictory combination raises rather
    than silently picking one. This is the mode to reach for behind a
    `force` / “re-verify this” switch: without it, forcing a re-run
    discards the result it just paid for and guarantees the next
    consumer re-bills.
  * **artifact_converter** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict), [`CallPlan`](falaw.plan.html.md#falaw.plan.CallPlan)], Artifact]]) – Per-CallPlan converter from raw fal response to
    `lacing.Artifact`. When `None` (default), a built-in
    converter handles the common shapes (`{images: [{url}]}`,
    `{video: {url}}`, `{audio: {url}}`). Mutually exclusive with
    `content_store` / `fetch_bytes` / `asset_fetcher`, which
    configure the built-in converter only — passing both raises, rather
    than silently ignoring the ones a custom converter cannot honour.
    Converters do not own `cost_usd`: the executor stamps it from
    the observed run outcome after conversion, overwriting whatever
    the converter set (falaw#26).
  * **content_store** – Injected `lacing.ArtifactStore` that media bytes
    are materialized into. Defaults to
    [`falaw.content.default_content_store()`](falaw.content.html.md#falaw.content.default_content_store) (a directory store
    rooted in the falaw cache). Point this at an S3-backed store to
    share content — and therefore cache hits — across machines.
  * **fetch_bytes** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool)]) – Whether to download each media result so its `asset_id`
    is the SHA-256 of its bytes. Defaults to `DFLT_FETCH_BYTES`
    (true), overridable process-wide via `FETCH_BYTES_ENVVAR`.
    **Opting out forfeits caching for chained calls**: without bytes
    there is no content hash, so downstream calls fall back to keying
    on the upstream URL — which fal mints fresh per upload, so the
    downstream entry can never be reused across runs or machines. It
    also means `asset_id` is *not* a content hash, in violation of
    `lacing.Artifact`’s contract. Use it only when you genuinely
    want URL-only artifacts and no reuse.
  * **asset_fetcher** – Injected byte source (`url -> Iterable[bytes]`) used to
    read media results; defaults to
    [`falaw.content.default_url_fetcher()`](falaw.content.html.md#falaw.content.default_url_fetcher). This is the per-call
    transport seam. A **hermetic test suite** usually wants the
    process-wide one instead — [`falaw.testing.fake_assets()`](falaw.testing.html.md#falaw.testing.fake_assets), built
    on [`falaw.content.using_url_fetcher()`](falaw.content.html.md#falaw.content.using_url_fetcher) — because a suite
    reaching falaw *through* its own public API has no `execute`
    call site to pass this to. Passing it here still wins over any
    installed default. (`$FALAW_FETCH_ARTIFACT_BYTES=0` also silences
    the network, but by turning content addressing off — see
    `FETCH_BYTES_ENVVAR`.)
  * **concurrency** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – How many calls may be in flight at once. `1`
    (`DFLT_CONCURRENCY`) runs the Plan sequentially, on the
    calling thread, exactly as it always has. Above 1, independent calls
    run on a thread pool bounded by this number — a Plan is I/O-bound
    (an HTTP request that fal takes tens of seconds to answer), so
    threads are the right tool and the bound is what keeps a 200-call
    fan-out from becoming 200 simultaneous paid requests. \*\*Chained
    calls are never parallelised with their producers\*\*: a call holding
    a `"<from N>"` placeholder waits for call `N`. Two things to
    weigh before raising it: the vendor’s rate limit, and memory —
    materializing a media result peaks at roughly twice the asset’s size
    (thorwhalen/lacing#25), so `concurrency` multiplies the peak.
* **Return type:**
  [*list*](https://docs.python.org/3/builtins/stdtypes.html#list)

## Failure handling — a paid result is never discarded

Two different things can go wrong when reading a result’s bytes, and they
get two different answers:

- **A fresh call whose bytes cannot be fetched.** fal has already run — and
  billed — the generation. Raising would throw away a result we paid for,
  typically over a transient network failure. So the artifact **degrades**:
  `url` is kept, `bytes_size` stays 0, `asset_id` is a digest of the
  response and is *not* claimed to be a content hash, and a
  [`UserWarning`](https://docs.python.org/3/builtins/exceptions.html#UserWarning) is emitted. Downstream key resolution reads
  > `bytes_size == 0` and falls back to the URL — a guaranteed cache
  > *miss*, never a wrong hit.
- **A cache hit that cannot be materialized** — fal deleted the URL and the
  bytes are not in the content store. The entry is unusable, so it is
  treated as a **miss**: it is invalidated and the call re-executed once.
  A cache must never become a trap whose only escape is re-billing the
  whole plan with `use_cache=False`.

## Placeholder resolution — the wire/key split

`terms_context` checks every call against the terms ledger before any
call runs; see `execute_isolated()`.

Any string argument equal to `"<from N>"` (for an integer `N`) is
rewritten *just before* the call is made — so a multi-step plan (e.g.
generate_image → image_to_video) can reference the upstream output without
the planner needing to know its URL. The rewrite happens after the upstream
call has executed; planning itself is unaffected.

It happens **twice**, into two different argument sets, because the same
value cannot serve both jobs:

- the **wire** arguments get `artifacts[N].url` — what fal needs in order
  to fetch the input;
- the **key** arguments get `sha256:<artifacts[N].asset_id>` — the
  upstream’s content hash, so a byte-identical upstream regeneration
  produces a downstream cache *hit* instead of re-billing the expensive
  call. Keying on the URL instead is the defect this split exists to fix
  (falaw#14): fal mints a unique URL per upload, so a URL-keyed downstream
  entry is unreachable the moment the upstream genuinely re-runs.

An upstream artifact with no materialized bytes has no content hash, so its
key ref falls back to the URL — a guaranteed miss, never a wrong hit.

* **rtype:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)
* **returns:**
  One `lacing.Artifact` per [`CallPlan`](#falaw.CallPlan) in `plan.calls`,
  in the same order.

### falaw.execute_plan_isolated(plan, , on_event=None, dry_run=False, use_cache=True, refresh=False, artifact_converter=None, content_store=None, fetch_bytes=None, asset_fetcher=None, concurrency=1, halt_on_failure=False, terms_context=None)

Execute a Plan with **per-call failure isolation**, returning a report.

The fan-out counterpart of `execute()`. Where `execute` raises on the
first failure — discarding every artifact produced before it, each of which
fal has already billed — this returns an [`ExecutionReport`](#falaw.ExecutionReport)
carrying one [`CallOutcome`](#falaw.CallOutcome) per call: the successes with their
artifacts, the failures with their exceptions, and the calls that never ran
with the reason why.

`len(report.outcomes) == len(plan.calls)` always, so a caller that built
something per call can zip against `report.outcomes` and stay aligned.

* **Parameters:**
  * **halt_on_failure** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – When True, stop *submitting* work as soon as any call
    fails; everything not yet started is reported `blocked` with a
    run-level reason. This is what `execute()` uses, and at
    `concurrency=1` it reproduces the historical sequential
    behaviour exactly. Note that at `concurrency > 1` calls already
    in flight are **not** cancelled — a fal request cannot be recalled
    once made, and pretending otherwise would discard results that were
    billed anyway.
  * **terms_context** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`TermsContext`](falaw.terms.html.md#falaw.terms.TermsContext)]) – Opt in to the terms ledger (falaw#16) at execution
    time: every call’s `(application, backend)` is checked \*\*before
    any call runs\*\*, whatever its backend, and one refusal raises
    [`FalTermsViolation`](#falaw.FalTermsViolation) for the whole plan. Planning
    checks only the calls `plan_*` builds; this also covers plans
    rebuilt from dicts, edited, or given a non-default `backend`.
* **Return type:**
  [`ExecutionReport`](falaw.outcomes.html.md#falaw.outcomes.ExecutionReport)

:param All other arguments are as `execute()`.:

## Three outcome states, not two

`failed` and `blocked` are different questions for the caller. A failed
call can be retried verbatim. A blocked one cannot: its input does not
exist, so it has to be re-planned after its producer succeeds. Any call
holding a `"<from N>"` placeholder whose call `N` did not succeed is
blocked, transitively.

### Examples

```pycon
>>> from falaw import CallPlan, Plan, execute_plan_isolated
>>> plan = Plan(calls=(CallPlan(tool="t", application="m",
...                             arguments={}, output_kind="image"),))
>>> report = execute_plan_isolated(plan, dry_run=True)
>>> report.is_complete, len(report.outcomes)
(True, 1)
```

### falaw.extract_models_from_corpus(path)

Yield ModelRecord-shaped dicts parsed from llms-full.txt.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### falaw.fetch_model_prices(endpoint_ids, , api_key=None, http_get=None, batch_size=50)

`{endpoint_id: {"unit_price", "unit", "currency"}}` from fal’s API.

Batches requests at `batch_size` ids (the endpoint caps at
`MAX_IDS_PER_REQUEST`). Ids the API does not know are simply
absent from the result — the caller decides what absence means. That
takes work: the live endpoint answers a batch containing even one
unknown id with a blanket 404, so a failed batch is bisected down to
the ids that actually price (O(unknown x log batch) extra requests).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### falaw.generate_audio(prompt, , kind='ambient', duration_s=None, model_id=None, extra=None)

Generate ambient/SFX/music from a prompt. Argument shape mirrors
[`falaw.plan_generate_audio()`](#falaw.plan_generate_audio) exactly, so planned and eager calls
with identical inputs collapse to the same cache entry.

* **Return type:**
  [`Result`](falaw.results.html.md#falaw.results.Result)

### falaw.generate_image(prompt, , quality='balanced', image_size='landscape_4_3', model_id=None, extra=None)

Generate an image from a text prompt.

`image_size` is a fal preset (`landscape_16_9` …); models that size by
`aspect_ratio` (`nano-banana-pro`) get the equivalent ratio, with
`extra={"resolution": "2K"}` for the pixel tier. A prompt over the
model’s cap raises [`falaw.FalPromptTooLong`](#falaw.FalPromptTooLong) before any call. Check
[`falaw.model_params()`](#falaw.model_params) for enums whose default may not be what you
want (Recraft `style` defaults to photoreal).

* **Return type:**
  [`Result`](falaw.results.html.md#falaw.results.Result)

### falaw.generate_image_with_refs(prompt, reference_image_urls, , quality='balanced', model_id=None, extra=None)

Generate a new image conditioned on one or more reference images.

The missing twin of [`generate_image()`](#falaw.generate_image): text-to-image models silently
ignore reference images, so callers wanting a recurring subject to stay
consistent (a character’s face across storyboard panels) need a model that
actually ingests references. This routes to the `image_edit` category
(Flux Kontext et al.) and threads the references as `image_url` (first)

+ `image_urls` (all) — the same wire shape image-edit models understand.

Pass `model_id` to override the picked model.

* **Return type:**
  [`Result`](falaw.results.html.md#falaw.results.Result)

### falaw.get_llm_price(provider, model, , prices=None)

The row for `model` (exact id), or `None` when the table does not list it.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`LlmPrice`](falaw.llm_prices.html.md#falaw.llm_prices.LlmPrice)]

### falaw.get_llm_rate(model, , rates=None)

The row for `model`, or `None` when the table does not price it.

`None` is the load-bearing answer: it means *unknown*, and every caller
must propagate it as unknown rather than substituting the router’s flat
price for a model nobody has priced.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`LlmRate`](falaw.llm_rates.html.md#falaw.llm_rates.LlmRate)]

### falaw.image_to_video(image_url, prompt='', , quality='high', duration_s=None, model_id=None, extra=None)

Animate a still image into a video.

* **Return type:**
  [`Result`](falaw.results.html.md#falaw.results.Result)

### falaw.iter_render_scene(scene, , tts_quality='balanced', lipsync_quality='high', shot_quality='balanced', shots_as_video=False, force=False, concurrency=1)

Yield `(kind, result)` pairs as each shot/beat finishes.

`kind` ∈ `{"shot", "beat"}`. With `concurrency=1` results
arrive in submission order (shots before beats). With
`concurrency > 1` they arrive in completion order (use the
`"shot_id"` / `"beat_id"` keys to re-key by identity).

Cache hits are immediate: a fully-cached scene yields all results
in close succession even at `concurrency=1`.

### falaw.lipsync(video_url, audio_url, , quality='high', model_id=None, extra=None)

Re-sync mouth motion in an existing video to a new audio track.

* **Return type:**
  [`Result`](falaw.results.html.md#falaw.results.Result)

### falaw.list_llm_prices(provider=None, , prices=None)

Every row, or the rows of one `provider`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`LlmPrice`](falaw.llm_prices.html.md#falaw.llm_prices.LlmPrice)]

### falaw.list_llm_rates(, rates=None)

Every row in the table, in file order — the catalogue view.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`LlmRate`](falaw.llm_rates.html.md#falaw.llm_rates.LlmRate)]

### falaw.listening(callback)

Deliver every event emitted in this context to `callback`, then stop.

The scoped sibling of [`subscribe()`](#falaw.subscribe): where `subscribe` hears every call in
the process, `listening` hears only the calls made inside the `with` block (and
the contexts copied from it, as [`falaw.plan`](falaw.plan.html.md#module-falaw.plan) does for its worker threads). It
is how a host that runs one unit of work per thread, such as a job worker, gets
that unit’s events without threading `on_event=` through every layer between.
`None` binds nothing, so a caller with no sink needs no `if`.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`None`](https://docs.python.org/3/builtins/constants.html#None)]

### falaw.llm_call_cost_usd(provider, model, usage, , prices=None)

`(USD, known)` for one first-party call from the vendor’s reported `usage`.

- `provider="anthropic"`: `input_tokens` (uncached), `output_tokens`,
  `cache_read_input_tokens`, `cache_creation_input_tokens`.
- `provider="openai"`: Responses (`input_tokens` / `output_tokens` /
  `input_tokens_details.cached_tokens`) or Chat Completions
  (`prompt_tokens` / `completion_tokens` /
  `prompt_tokens_details.cached_tokens`). Input includes the cached part,
  which is billed at the cached rate; reasoning tokens are already in output.

`known` is `False` when the model is not in the table; the cost is then
priced at the provider’s dearest listed rates, which is not a ceiling for a
model pricier than any listed (see the module docstring). `prices=` swaps in the caller’s
own table, e.g. one reconciled against an invoice.

* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – `provider` is not one of `PROVIDERS`.
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]

### falaw.llm_ceiling_usd(model, , input_tokens=None, max_output_tokens=None, count=1, rates=None)

Ceiling cost in USD of `count` calls routing `model`, or `None`.

Two modes, decided by whether the caller passes a token hint at all.

**No hints** — quote fal’s published per-request price for the routed
model. That is a known vendor fact, and for the premium tier it is ten
times what the router’s flat record said:

```pycon
>>> flat = llm_ceiling_usd('anthropic/claude-sonnet-4.5')
>>> flat
0.01
```

**Both hints** — quote the **maximum** of that request price and
`input_tokens` in plus `max_output_tokens` out at the routed model’s
upstream rates. Taking the max is what makes it a ceiling: the flat price
binds a short prompt, the token sum binds a long one, and quoting either
alone under-quotes the other case.

```pycon
>>> long_prompt = llm_ceiling_usd(
...     'anthropic/claude-sonnet-4.5', input_tokens=20_000, max_output_tokens=4_000
... )
>>> round(long_prompt, 4)
0.12
>>> long_prompt > flat        # length raises the quote; the flat rate is a floor
True
```

Monotone in both hints, so a bigger hint never quotes less:

```pycon
>>> a = llm_ceiling_usd('openai/gpt-4o', input_tokens=1_000, max_output_tokens=100)
>>> b = llm_ceiling_usd('openai/gpt-4o', input_tokens=9_000, max_output_tokens=100)
>>> b >= a
True
```

Both hints are upper bounds the *caller* holds at plan time: the prompt is
already written, and `max_tokens` caps the response. Real output length
is unknowable before the call, which is exactly why this quotes the cap and
never a midpoint guess.

A token quote is therefore **all or nothing**. Asking for one that cannot
be bounded yields `None` — unknown, which forces approval — rather than a
number that looks like a ceiling and is not. That covers one hint without
the other (an uncapped response has no bound to quote):

```pycon
>>> llm_ceiling_usd('anthropic/claude-sonnet-4.5', input_tokens=50_000) is None
True
```

and a row with no published upstream token rates (the request price alone
is not a ceiling on a token bill nobody has priced):

```pycon
>>> llm_ceiling_usd(
...     'google/gemini-flash-1.5', input_tokens=50_000, max_output_tokens=1_000
... ) is None
True
```

* **Parameters:**
  * **model** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The `model` argument the call will send to the router.
  * **input_tokens** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Upper bound on prompt tokens. `None` together with
    `max_output_tokens` selects the per-request basis alone.
  * **max_output_tokens** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – The response cap (any-llm’s `max_tokens`).
  * **count** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Number of identical calls.
  * **rates** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`LlmRate`](falaw.llm_rates.html.md#falaw.llm_rates.LlmRate)]]) – Override table, for a caller who has reconciled real rates
    against their own billing.
* **Raises:**
  * [**TypeError**](https://docs.python.org/3/builtins/exceptions.html#TypeError) – a token hint or `count` that is not a plain `int`.
        A `bool` and a `float` both do the arithmetic silently —
        `True` prices one token, `1.5e4` prices a fractional one —
        so a caller who passed the wrong thing would get a number rather
        than a complaint.
  * [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – a negative token hint or `count`, which would make the
        token basis *lower* the ceiling — silently, and in the one
        direction a spend gate must never err.
* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

### falaw.llm_complete(prompt, , system='', model='anthropic/claude-sonnet-4.5', temperature=0.7, extra=None)

Single-shot LLM completion. Returns the assistant text.

Delegates to [`llm_complete_with_receipt()`](#falaw.llm_complete_with_receipt) (one argument-construction
site, so the two spellings share one cache identity) and discards the
receipt. A caller that accounts for spend wants the receipt variant.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### falaw.llm_complete_with_receipt(prompt, , system='', model='anthropic/claude-sonnet-4.5', temperature=0.7, extra=None)

Single-shot LLM completion that also reports what it cost.

Same arguments, same wire call, same cache identity as
[`llm_complete()`](#falaw.llm_complete) — the receipt is a side channel, observed from the
call this function was making anyway (the cache layer’s `cache_hit`
event, the response’s usage block, the registry’s estimate). Library
surface only — deliberately NOT a registered tool: the tool surface
keeps the one string-returning `llm_complete`.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`LlmReceipt`](falaw.operations.llm.html.md#falaw.operations.llm.LlmReceipt)]

### falaw.llm_cost_basis(routed_model, , input_tokens=None, max_output_tokens=None, custom_rates=False)

A [`falaw.CostBasis`](#falaw.CostBasis) for a routed LLM call priced from the rate table.

`custom_rates=True` records that the quote came from a caller-supplied
`rates=` table rather than the committed one: there is no file to digest,
so the version stays empty and the table names itself
[`falaw.llm_rates.CUSTOM_LLM_RATES_TABLE`](falaw.llm_rates.html.md#falaw.llm_rates.CUSTOM_LLM_RATES_TABLE). [`reprice_plan()`](#falaw.reprice_plan) then
**refuses** to re-quote it with the committed table, reporting `unknown`
— a caller’s reconciled $0.50 row re-priced at falaw’s published $0.01 is a
50x under-quote, not a price drop. Re-quote it by passing a
[`Pricer`](#falaw.Pricer) over your table that names that same identity.

* **Return type:**
  [`CostBasis`](falaw.plan.html.md#falaw.plan.CostBasis)

### falaw.llm_prices_table_version()

The table’s version, a digest of its bytes (see [`falaw.base.data_table_version()`](falaw.base.html.md#falaw.base.data_table_version)).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### falaw.llm_token_counts(provider, usage)

The [`LlmTokenCounts`](#falaw.LlmTokenCounts) of a vendor `usage`, in the shapes
[`llm_call_cost_usd()`](#falaw.llm_call_cost_usd) accepts (a mapping or an SDK object).

```pycon
>>> llm_token_counts("openai", {"prompt_tokens": 1000, "completion_tokens": 100,
...     "prompt_tokens_details": {"cached_tokens": 400}})
LlmTokenCounts(fresh_input=600, cache_read=400, cache_write=0, cache_write_1h=0, output=100, reasoning=0)
```

A key that is present but `None` falls through to the next shape’s key
(`{"input_tokens": None, "prompt_tokens": 7}` counts 7).

* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – `provider` is not one of `PROVIDERS`.
* **Return type:**
  [`LlmTokenCounts`](falaw.llm_prices.html.md#falaw.llm_prices.LlmTokenCounts)

### falaw.make_call_plan(, tool, application, arguments, output_kind, backend='fal', estimated_cost_usd=None, expected_duration_s=None, expected_wall_time_s=None, metadata=None, consult_cache=True, cost_basis=None, terms_context=None)

Build a [`CallPlan`](#falaw.CallPlan) and (optionally) check the cache.

When `consult_cache=True` (the default), the cache is peeked using the
same key the eventual call would produce; `cache_status` is set to
`"hit"` if a cached entry exists, `"miss"` otherwise. This makes
`Plan.total_cost_usd` honest: a fully-cached Plan reports $0.

When `consult_cache=False` (e.g. for unit tests or “what would a fresh
run cost?” reporting), `cache_status` is `"unknown"`.

A **chained call** — arguments still holding a `"<from N>"` placeholder,
because the upstream call has not executed yet — is never peeked
(falaw#15, D2): its resolved key is not knowable at plan time, and the
unresolved key is never written by anything (`execute()` always keys
on the resolved form), so peeking it can only ever report a false
`"miss"` — never a real `"hit"`. That silently over-quotes cost and
under-reports the plan’s `cache_hit_savings_usd` on every chained call,
which under prepaid billing (a quote that may be *deducted*) is a billing
bug. `cache_status` is `"unknown"` here instead, exactly the case
`CacheStatus` documents it for.

`cost_basis` records how `estimated_cost_usd` was arrived at so the
quote can be re-run later (falaw#60). It is descriptive only: it never
reaches the cache key or [`plan_hash()`](#falaw.plan_hash), and a plan built without one
is byte-identical to one built before the field existed.

`terms_context` opts this call into the terms ledger (falaw#16): with a
[`falaw.terms.TermsContext`](falaw.terms.html.md#falaw.terms.TermsContext), a `(application, backend)` whose terms
forbid the job — or are unknown — is refused here, before anything is
called. `None` (the default) checks nothing.

* **Raises:**
  * [**FalNonCanonicalArgument**](falaw.errors.html.md#falaw.errors.FalNonCanonicalArgument) – an argument cannot be hashed
        faithfully (non-JSON object, non-finite float, non-string mapping
        key). Raised here — while planning is still free — rather than at
        key-composition time on the way to the network (falaw#17).
  * [**FalTermsViolation**](falaw.errors.html.md#falaw.errors.FalTermsViolation) – `terms_context` was given and the
        ledger does not clear this `(application, backend)`.
* **Return type:**
  [`CallPlan`](falaw.plan.html.md#falaw.plan.CallPlan)

### falaw.materialize_asset(url, , key_hint='', store=None, fetcher=None, refresh=False)

Download a remote asset to the cache and return the local path.

The local filename is content-addressed by the asset’s **bytes**, so two
URLs serving identical bytes resolve to one file. The extension is a
presentational hint for ffmpeg/PIL; the SHA-256 is the address.

Repeat calls are cheap, in three widening circles — this is what makes it
safe to call from a loop over 200 shots:

1. the file is already on disk here (no store lookup, no network) —
   **immutable URLs only**, see below;
2. the bytes are in the content store (no network, or one validating
   round-trip) — so it still works after fal has expired the URL;
3. otherwise, one download.

Circle 1 matters on its own: the content store is prunable, so an asset
can survive as a materialized file after its blob is gone.

**Circle 1 is taken only when the URL cannot change** — that is,
[`falaw.content.is_immutable_url()`](falaw.content.html.md#falaw.content.is_immutable_url) — because reaching it requires
trusting the `url -> hash` index to name the *current* bytes, and for an
arbitrary caller-supplied URL it does not (thorwhalen/falaw#23). A mutable
URL goes to circle 2, where [`falaw.content.content_ref_for_url()`](falaw.content.html.md#falaw.content.content_ref_for_url)
revalidates before reusing anything; when the bytes really are unchanged
that costs one conditional request and still no download, and when they
have changed you get the new file instead of silently getting the old one.

* **Parameters:**
  * **url** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – the remote asset URL. `file://` is supported and is used
    deliberately by downstream packages for locally-rendered media.
  * **key_hint** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – optional human-readable filename prefix.
  * **store** – injected `lacing.ArtifactStore`; defaults to
    [`falaw.content.default_content_store()`](falaw.content.html.md#falaw.content.default_content_store).
  * **fetcher** – injected byte source (`url -> Iterable[bytes]`); defaults to
    the `urllib`-based one. The seam for custom transport (auth
    headers, retries) and for a hermetic test suite.
  * **refresh** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – re-fetch unconditionally, skipping every circle. Rarely needed
    now: a mutable URL revalidates on its own (falaw#23), so this is for
    an origin that lies about its validators.
* **Raises:**
  [**FalAssetFetchError**](falaw.errors.html.md#falaw.errors.FalAssetFetchError) – the bytes could not be retrieved.
      Unlike a generated-media artifact (which degrades to URL-only —
      see [`falaw.plan.execute()`](falaw.plan.html.md#falaw.plan.execute)), there is nothing to degrade to
      here: the caller asked for a local file.
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### falaw.model_constraints(id)

The capability/limit fields for a model — the “static reminder of
limitations” a shot-list builder surfaces. Resolves aliases.

Returns a JSON-able dict; `max_clip_seconds` etc. are `None` / empty
when unknown for that model.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### falaw.model_params(id)

Per-model parameters worth knowing before a call, `{name: spec}`.

Each spec is `{"enum": [...], "default": ...}` (or `{"max_items": n}` for
a list argument such as reference images); resolves aliases. For
`fal-ai/recraft/v3/text-to-image` this shows `style` defaults to
`realistic_image` — a photograph, whatever the prompt describes — and
lists the styles that actually give a woodcut or a linocut. Empty when the
catalogue records none (fal’s OpenAPI schema is the full source).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### falaw.parse_response(raw, , application, arguments)

Best-effort parser over the common fal response shapes.

fal models return a variety of layouts (lists, single objects, bare URLs).
We normalize each into Asset(url, kind, …). Unknown shapes pass through
as `raw` only — callers can read `result.raw` for anything we miss.

* **Return type:**
  [`Result`](falaw.results.html.md#falaw.results.Result)

### falaw.parse_screenplay(text, , title='', style='', model='anthropic/claude-sonnet-4.5')

Convert prose screenplay text into a Scene IR via an LLM call.

* **Return type:**
  [`Scene`](falaw.scene.html.md#falaw.scene.Scene)

### falaw.pick_model(, category, quality_tier='balanced')

Pick a sensible fal model for a (category, quality) request.

First-match semantics: when several models share a tier, the earlier
entry wins. Curated entries are written first in `data/models.json`,
so they take precedence over corpus-merged additions. If no model
has the exact tier, neighboring tiers are tried. KeyError only when
the category is empty.

* **Return type:**
  [`ModelRecord`](falaw.base.html.md#falaw.base.ModelRecord)

### falaw.plan_animate_face(image_url, audio_url, , prompt='', quality='balanced', model_id=None, duration_s=None, extra=None, metadata=None, consult_cache=True, terms_context=None)

Plan a [`falaw.animate_face()`](#falaw.animate_face) call (image + audio → talking video).

#### NOTE
the default avatar model is known to hang. For production-grade
behavior, callers should pass `model_id="fal-ai/bytedance/omnihuman/v1.5"`
or set `quality="high"` (which picks omnihuman).

* **Return type:**
  [`CallPlan`](falaw.plan.html.md#falaw.plan.CallPlan)

### falaw.plan_composite_character_in_environment(character_image_url, environment_image_url, , prompt='', quality='balanced', model_id=None, extra=None, metadata=None, consult_cache=True, terms_context=None)

Plan a [`falaw.composite_character_in_environment()`](#falaw.composite_character_in_environment) call.

The character image anchors identity; the environment image anchors
location, lighting, palette. The default model is Flux Kontext dev.

* **Return type:**
  [`CallPlan`](falaw.plan.html.md#falaw.plan.CallPlan)

### falaw.plan_dependencies(plan)

Per-call set of the call indices it references via `"<from N>"`.

The Plan’s dependency DAG, read straight off the placeholders — one
`frozenset` per call, in plan order, so `deps[3] == {1}` means call 3
consumes call 1’s output. An empty set means the call is **independent** and
may run concurrently with any other independent call, which is what
`execute_isolated()` schedules on.

Also the plan’s structural validator, and it runs \*\*before a cent is
spent\*\*: a malformed reference used to surface only when execution reached
the offending call, i.e. after every call before it had been billed.

* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – a placeholder that is not `"<from N>"` for an integer
      `N`; an `N` outside the plan; or an `N` that does not run
      *before* the referencing call (including a self-reference) — the
      output would not exist yet, so it can only ever be a bug.
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)[[`int`](https://docs.python.org/3/builtins/functions.html#int)], [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

```pycon
>>> a = CallPlan(tool="t", application="m", arguments={}, output_kind="image")
>>> b = CallPlan(tool="t", application="m",
...              arguments={"image_url": "<from 0>"}, output_kind="video")
>>> plan_dependencies(Plan(calls=(a, b)))
(frozenset(), frozenset({0}))
>>> plan_dependencies(Plan(calls=(b,)))
Traceback (most recent call last):
    ...
ValueError: Placeholder '<from 0>' in call 0 references call 0, which does not run before it. ...
```

### falaw.plan_edit_image(image_url, prompt, , quality='balanced', model_id=None, extra=None, metadata=None, consult_cache=True, terms_context=None)

Plan a [`falaw.edit_image()`](#falaw.edit_image) call (Flux Kontext / SeedEdit / OmniGen).

* **Return type:**
  [`CallPlan`](falaw.plan.html.md#falaw.plan.CallPlan)

### falaw.plan_from_dict(d)

Rebuild a [`Plan`](#falaw.Plan) from a [`plan_to_dict()`](#falaw.plan_to_dict) dict.

Raises `ValueError` if `d` carries an unrecognized `schema` tag — a
plan written by an incompatible future version should fail loudly, not
silently lose calls. A missing `schema` is tolerated (treated as v1) so
hand-written plans stay easy.

* **Return type:**
  [`Plan`](falaw.plan.html.md#falaw.plan.Plan)

### falaw.plan_generate_audio(prompt, , kind='ambient', duration_s=None, model_id=None, extra=None, metadata=None, consult_cache=True, terms_context=None)

Plan a [`falaw.generate_audio()`](#falaw.generate_audio) call (prompt → ambient/SFX/music).

The planning primitive behind an ambient bed or music cue (falaw#10):
the user who leaves their editor to hunt a city-night ambience is the
user this generates one for — costed, cached and planned like every
other call. Mirrors the eager [`falaw.generate_audio()`](#falaw.generate_audio) signature so
a planned call and an eager call with identical inputs collapse to the
same cache entry. Pure data; no network at plan time.

`kind` selects the default model (see `GENERATE_AUDIO_DEFAULTS`
for why these are explicit ids). `duration_s` reaches the model as its
duration argument where the model takes one (see
`resolve_generate_audio()`) AND feeds the cost estimate; for models
with no duration argument it is estimator-only.

* **Return type:**
  [`CallPlan`](falaw.plan.html.md#falaw.plan.CallPlan)

### falaw.plan_generate_image(prompt, , quality='balanced', image_size='landscape_4_3', model_id=None, extra=None, metadata=None, consult_cache=True, terms_context=None)

Plan a [`falaw.generate_image()`](#falaw.generate_image) call without executing it.

* **Return type:**
  [`CallPlan`](falaw.plan.html.md#falaw.plan.CallPlan)

### falaw.plan_generate_image_with_refs(prompt, reference_image_urls, , quality='balanced', model_id=None, extra=None, metadata=None, consult_cache=True, terms_context=None)

Plan a [`falaw.generate_image_with_refs()`](#falaw.generate_image_with_refs) call.

The planning sibling of the eager op: text-to-image models ignore
reference images, so a caller wanting a recurring subject to stay
consistent must route to a reference-capable model. This picks the
`image_edit` category (Flux Kontext et al.) and threads the references
as `image_url` (first) + `image_urls` (all), the same wire shape the
eager op uses — so a planned and an eager call with identical inputs
collapse to one cache entry.

* **Return type:**
  [`CallPlan`](falaw.plan.html.md#falaw.plan.CallPlan)

### falaw.plan_hash(plan)

Stable, plan-scoped **structural idempotency key** for a whole [`Plan`](#falaw.Plan).

Answers “does this whole plan match one I already ran?” — the handle a job
manager (its first customer, `nw.jobs`) uses to dedup double-submits and
to replay a resumed render for free. It is computed *before* execution and
with `<from N>` placeholders intact, so it is stable across re-plans of the
same structural request.

The digest canonicalizes each call over `{app, args, tool}`
([`falaw.canonical.plan_identity_payload()`](falaw.canonical.html.md#falaw.canonical.plan_identity_payload)) — matching
`_synthetic_artifact()`’s canonicalization, and deliberately **not** the
per-call content-addressed cache key (`falaw.cache._key()`, which keys on
`{app, args}` with no `tool`). `plan_hash` and the per-call cache key
therefore key on *different* bytes and must not be assumed to agree
call-for-call. Both projections live side by side in [`falaw.canonical`](falaw.canonical.html.md#module-falaw.canonical)
with one shared byte-form ([`falaw.canonical.canonical_blob()`](falaw.canonical.html.md#falaw.canonical.canonical_blob) — sorted
keys, **no** `default=str` fallback, no NaN), so an argument the form
cannot represent faithfully raises
[`falaw.errors.FalNonCanonicalArgument`](falaw.errors.html.md#falaw.errors.FalNonCanonicalArgument) instead of colliding, and a
new identity-bearing field is an explicit decision about both hashes.

Two structurally-identical plans hash equal; changing any call’s `app`,
`args`, or `tool` — or the *order* of calls — changes the hash.

```pycon
>>> a = CallPlan(tool="generate_image", application="fal-ai/flux/dev",
...              arguments={"prompt": "a tiger"}, output_kind="image")
>>> b = CallPlan(tool="image_to_video", application="fal-ai/svd",
...              arguments={"image_url": "<from 0>"}, output_kind="video")
>>> plan_hash(Plan(calls=(a, b))) == plan_hash(Plan(calls=(a, b)))
True
>>> plan_hash(Plan(calls=(a, b))) == plan_hash(Plan(calls=(b, a)))
False
```

`backend` (falaw#15) joins the hashed payload too, so a plan built for
one backend never dedups against the structurally-identical plan for
another — and, since it is included only when non-default, every plan
made of today’s (all-`"fal"`) calls hashes exactly as it did before:

```pycon
>>> comfy = CallPlan(tool="generate_image", application="fal-ai/flux/dev",
...                   arguments={"prompt": "a tiger"}, output_kind="image",
...                   backend="comfyui")
>>> plan_hash(Plan(calls=(a,))) == plan_hash(Plan(calls=(comfy,)))
False
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### falaw.plan_image_to_video(image_url, prompt='', , quality='high', model_id=None, duration_s=None, extra=None, metadata=None, consult_cache=True, terms_context=None)

Plan a [`falaw.image_to_video()`](#falaw.image_to_video) call.

`duration_s` is used for cost estimation (`per_second` and
`per_token` models); it reaches fal only for models whose catalogue
record lists a `duration` parameter (see `_plan_video()`), else only
if the caller puts it in `extra`.

* **Return type:**
  [`CallPlan`](falaw.plan.html.md#falaw.plan.CallPlan)

### falaw.plan_lipsync(video_url, audio_url, , quality='high', model_id=None, duration_s=None, extra=None, metadata=None, consult_cache=True, terms_context=None)

Plan a [`falaw.lipsync()`](#falaw.lipsync) call (existing video + new audio → re-synced video).

* **Return type:**
  [`CallPlan`](falaw.plan.html.md#falaw.plan.CallPlan)

### falaw.plan_llm_complete(prompt, , system='', model=None, temperature=0.7, output_kind='text', input_tokens=None, max_output_tokens=None, llm_rates=None, extra=None, metadata=None, consult_cache=True, terms_context=None)

Plan a [`falaw.llm_complete()`](#falaw.llm_complete) call without executing it.

Routes through `fal-ai/any-llm` with the *exact same* application id and
argument shape as the eager [`falaw.llm_complete()`](#falaw.llm_complete), so a planned call
and an eager call with identical inputs collapse to the same cache entry.

`output_kind` is `"text"` for a free-form completion or `"json"` when
the prompt asks for a strict-JSON response — it tells `falaw.execute()`
what kind of `lacing.Artifact` to materialize. Either way the LLM
response is materialized to a content-addressed cache *file*
(`Artifact.path`), because LLM output is text, not a URL.

**Cost is a ceiling for the routed model**, not the router’s flat price
(falaw#50, option A). `fal-ai/any-llm` is one registry record routing
thirty models at two published request tiers, so the record’s single
`per_call` figure under-quotes every premium model tenfold — including
this function’s own default. [`falaw.llm_ceiling_usd()`](#falaw.llm_ceiling_usd) prices the
`model` argument instead:

- no token hints → fal’s published per-request price for that model;
- `input_tokens` **and** `max_output_tokens` → the greater of that
  price and the upstream per-token cost of a prompt that long capped at
  that many output tokens. Monotone in both hints;
- a model the rate table does not price, or a token quote that cannot be
  bounded → `estimated_cost_usd` is `None`, which lights up
  [`falaw.plan.Plan.has_unknown_costs`](falaw.plan.html.md#falaw.plan.Plan.has_unknown_costs) and forces approval. It is
  > never quietly the router’s flat price.

`input_tokens` is what opts a call into a token quote. Given one,
`max_output_tokens` defaults to whatever the caller already put under
`MAX_OUTPUT_TOKENS_ARGUMENT` in `extra` — the cap is a fact of the
call, not a second thing to remember. Without one, `extra` is left alone:
capping your response is not asking to be quoted by tokens, and reading the
cap as half a token quote would drop a call that has a perfectly good
request price down to forced approval.

Both hints are **estimator-only**: they never enter `arguments`, so adding
one to an existing call site changes the quote without moving the cache key
or the plan hash.

`llm_rates` swaps in a caller’s own rate table — the seam for someone who
has reconciled real numbers against their fal invoice.

* **Return type:**
  [`CallPlan`](falaw.plan.html.md#falaw.plan.CallPlan)

### falaw.plan_reference_to_video(prompt, , image_urls=(), video_urls=(), audio_urls=(), quality='high', model_id=None, duration_s=None, extra=None, metadata=None, consult_cache=True, terms_context=None)

Plan a reference-to-video call (Seedance 2.0): a prompt steered by
reference images, videos and audio.

The counts are checked against the model’s recorded limits
(`model_constraints(id)["max_references"]`) by [`make_call_plan()`](#falaw.make_call_plan), while
planning is free, whatever route (`extra` included) they arrive by. The
quote is the standard rate, a ceiling for the no-video case: fal bills
reference videos differently (falaw#99, unverified), so none is discounted.

* **Return type:**
  [`CallPlan`](falaw.plan.html.md#falaw.plan.CallPlan)

### falaw.plan_text_to_speech(text, , quality='balanced', voice=None, model_id=None, duration_s=None, tokens=None, extra=None, metadata=None, consult_cache=True, terms_context=None)

Plan a [`falaw.text_to_speech()`](#falaw.text_to_speech) call (text → audio Artifact).

Mirrors the eager [`falaw.text_to_speech()`](#falaw.text_to_speech) signature so a planned
call and an eager call with identical inputs collapse to the same
cache entry. `voice` semantics are model-specific.

`duration_s` and `tokens` are *optional* hints used only by the
cost estimator — they never enter `arguments`, so they cannot move
the cache identity. `duration_s` prices `per_second` records (the
produced audio’s actual duration comes back on the materialized
Artifact); `tokens` prices `per_token` records. For
character-billed TTS (ElevenLabs — its registry record says so
explicitly) pass `tokens=len(text)`. Without the matching hint a
quantity-priced record stays `estimated_cost_usd=None` — unknown,
never free, which forces approval downstream.

* **Return type:**
  [`CallPlan`](falaw.plan.html.md#falaw.plan.CallPlan)

### falaw.plan_text_to_video(prompt, , quality='high', model_id=None, duration_s=None, extra=None, metadata=None, consult_cache=True, terms_context=None)

Plan a [`falaw.text_to_video()`](#falaw.text_to_video) call — the sibling of
[`plan_image_to_video()`](#falaw.plan_image_to_video) (same duration and cost rules).

* **Return type:**
  [`CallPlan`](falaw.plan.html.md#falaw.plan.CallPlan)

### falaw.plan_to_dict(plan)

Convert a [`Plan`](#falaw.Plan) to a plain JSON-serializable dict.

The result round-trips through [`plan_from_dict()`](#falaw.plan_from_dict). This is the
substrate primitive a consumer (a persistence layer, an MCP transport, a
plan-diff tool) builds on — falaw owns the wire shape of its own Plan so
every consumer agrees on it. Carries a `schema` tag (`PLAN_DICT_SCHEMA`)
so a future breaking change is detectable.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### falaw.prune_assets(, older_than=None, max_bytes=None, dry_run=True, store=None)

Reclaim materialized asset copies — the cheapest disk in the cache (falaw#22).

`assets/` holds a **copy** of each blob rather than a hard link, which is
deliberate ([`falaw.content.write_blob_to_file()`](falaw.content.html.md#falaw.content.write_blob_to_file) explains why a link
would let a consumer corrupt the content store) but doubles the on-disk cost
of every materialized asset. That makes this the prune to reach for first:
while a blob survives, re-materializing its asset is a local copy and costs
nothing, so `rebillable_entries` counts only the copies whose blob is
*also* gone.

* **Parameters:**
  * **older_than** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`int`](https://docs.python.org/3/builtins/functions.html#int), [`timedelta`](https://docs.python.org/3/library/datetime.html#datetime.timedelta), [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – drop copies last written more than this ago — seconds, or a
    [`timedelta`](https://docs.python.org/3/library/datetime.html#datetime.timedelta).
  * **max_bytes** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – drop oldest-first until the area fits in this budget.
  * **dry_run** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – report without deleting. Default, deliberately.
  * **store** – injected `lacing.ArtifactStore`, used only to ask whether
    each dropped copy still has a blob behind it; defaults to
    [`falaw.content.default_content_store()`](falaw.content.html.md#falaw.content.default_content_store).
* **Returns:**
  with `area="assets"`.
* **Return type:**
  [`PruneReport`](falaw.prune.html.md#falaw.prune.PruneReport)
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – neither bound was given.

### falaw.prune_content(, older_than=None, max_bytes=None, dry_run=True, store=None)

Reclaim content-addressed blobs — the gigabytes (falaw#22).

This is the **expensive** prune. A blob is the last copy of an asset once
fal has expired its URL (“expired files are permanently deleted and cannot
be recovered”), so dropping one can turn a free cache hit into a re-rendered
clip. The report says how many entries that applies to *before* you commit;
read `rebillable_entries`.

* **Parameters:**
  * **older_than** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`int`](https://docs.python.org/3/builtins/functions.html#int), [`timedelta`](https://docs.python.org/3/library/datetime.html#datetime.timedelta), [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – drop blobs last written more than this ago — seconds, or a
    [`timedelta`](https://docs.python.org/3/library/datetime.html#datetime.timedelta).
  * **max_bytes** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – drop oldest-first until the area fits in this budget.
  * **dry_run** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – report without deleting. Default, deliberately.
  * **store** – injected `lacing.ArtifactStore`; defaults to
    [`falaw.content.default_content_store()`](falaw.content.html.md#falaw.content.default_content_store), whose deletes remove
    the file. An injected store keeps its own backend’s delete policy:
    a stock `ArtifactStore.from_directory` store moves each blob to
    the OS trash, which frees no space on that volume even though the
    report counts the bytes as freed.
* **Return type:**
  [*PruneReport*](falaw.prune.html.md#falaw.prune.PruneReport)

Blobs are listed and deleted through lacing’s contained
`iter_blobs`/`delete_blob` (falaw#66): nothing outside the blob root is
listed or removed, and an in-root symlink is unlinked, never its target.

* **Returns:**
  with `area="content"`.
* **Return type:**
  [`PruneReport`](falaw.prune.html.md#falaw.prune.PruneReport)
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – neither bound was given — see `_require_a_bound()`.

Both bounds may be combined; a blob selected by either is dropped.

```pycon
>>> report = prune_content(older_than=timedelta(days=90))
>>> report.dry_run
True
```

### falaw.prune_manifests(, older_than=None, max_bytes=None, dry_run=True)

Reclaim cache entries — the fal responses themselves (falaw#22).

Manifests are kilobytes, so this is rarely where the disk is; it is here
because a stale *entry* is its own problem — it pins a model version and a
price you may no longer want served from cache.

Unlike [`prune_content()`](#falaw.prune_content), the cost is unconditional: every dropped
entry re-bills its call on the next run, so `rebillable_entries` always
equals the candidate count.

* **Parameters:**
  * **older_than** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`int`](https://docs.python.org/3/builtins/functions.html#int), [`timedelta`](https://docs.python.org/3/library/datetime.html#datetime.timedelta), [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – drop entries stored more than this ago — seconds, or a
    [`timedelta`](https://docs.python.org/3/library/datetime.html#datetime.timedelta). Read from the manifest’s own
    `stored_at`, falling back to file mtime.
  * **max_bytes** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – drop oldest-first until the area fits in this budget.
  * **dry_run** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – report without deleting. Default, deliberately.
* **Returns:**
  with `area="manifests"`.
* **Return type:**
  [`PruneReport`](falaw.prune.html.md#falaw.prune.PruneReport)
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – neither bound was given.

Only the manifest is removed; blobs are shared by content hash across
entries and are never dropped from here — the same rule
[`falaw.drop_cache_entry()`](#falaw.drop_cache_entry) follows.

### falaw.prune_uploads(, older_than=None, max_bytes=None, dry_run=True)

Drop upload-index entries (falaw#92): digest -> fal URL hints.

An entry older than `falaw.upload.DEFAULT_UPLOAD_TTL_S` is dead by
definition ([`falaw.upload()`](#falaw.upload) re-uploads past its `ttl_s`), so pass
`older_than=` at least that. Dropping one costs a re-upload, which is
free, so `rebillable_entries` is always 0.

* **Parameters:**
  * **older_than** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`int`](https://docs.python.org/3/builtins/functions.html#int), [`timedelta`](https://docs.python.org/3/library/datetime.html#datetime.timedelta), [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – drop entries written more than this ago — seconds, or a
    [`timedelta`](https://docs.python.org/3/library/datetime.html#datetime.timedelta).
  * **max_bytes** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – drop oldest-first until the area fits in this budget.
  * **dry_run** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – report without deleting. Default, deliberately.
* **Returns:**
  with `area="uploads"`.
* **Return type:**
  [`PruneReport`](falaw.prune.html.md#falaw.prune.PruneReport)
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – neither bound was given.

### falaw.refresh_full_docs(, docs_dir=None, max_workers=16, force=False, journal=True)

Re-crawl per-page docs and rebuild `fal_ai_docs_full.md`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### falaw.refresh_llm_rates(, write=False, http_get_any_llm_doc=None, http_get_openrouter_models=None, rates_path=None, proposed_path=None, diff_path=None, today=None)

Fetch both sources, propose a fresh table, diff it — never overwrite.

`rates_path` (default: the committed `llm_rates.json`) is read only,
never written: this function has no code path that touches the committed
table, by design — a repriced or retiered model is a decision for a human
to promote, not something a refresh job gets to make silently. With
`write=True`, the freshly-derived table is written to `proposed_path`
(default: `llm_rates.proposed.json` next to the committed file) and the
diff report to `diff_path` (default: `llm_rates.diff.txt`).

Returns a summary dict: `{"fetched_at", "committed_models",
"proposed_models", "diff", "write", "proposed_path", "diff_path"}`. The
two path keys are `None` when `write=False`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### falaw.refresh_llms(, docs_dir=None, journal=True)

Refresh `llms.txt` and `llms-full.txt`; return a summary dict.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### falaw.refresh_model_prices(, write=False, api_key=None, http_get=None, models_path=None, today=None)

Refresh `models.json` cost estimates from fal’s pricing API.

Returns a summary dict; `write=False` (default) reports what would
change without touching the file. `models_path` and `today` exist
for tests (the fetch date lands in each estimate’s `notes`).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### falaw.refresh_models_from_corpus(, path=None, write=False)

Merge corpus-discovered models into models.json (additive).

Returns `{added, total, from_corpus, write}` summary. Setting
`write=False` (the default) reports what *would* change without
touching the file.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### falaw.refresh_state()

Return the saved per-source refresh state (etags, last fetch times).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### falaw.register_tool(\*\*spec_kwargs)

Decorator: register the wrapped function as a falaw tool.

```pycon
>>> @register_tool(name='echo', description='echo back', tags=('demo',))
... def _echo(x): return x
>>> get_tool('echo').name
'echo'
```

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)

### falaw.remove_background(image_url, , quality='high', model_id=None, extra=None)

Remove the background from an image.

* **Return type:**
  [`Result`](falaw.results.html.md#falaw.results.Result)

### falaw.render_beat(beat, character, , tts_quality='balanced', lipsync_quality='high', tts_model_id=None, avatar_model_id=None, force=False)

Render one Beat to a lipsynced video. Returns a small manifest dict.

* **Parameters:**
  * **tts_model_id** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Override the TTS model. When provided, takes precedence
    over the character’s voice.model_id and over `tts_quality`-based
    `pick_model`. Use this to force a specific TTS engine for one
    beat (e.g. eleven-v3 for emotional delivery, multilingual-v2 for
    consistency).
  * **avatar_model_id** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Override the avatar/lipsync model (e.g.
    `"fal-ai/bytedance/omnihuman/v1.5"` to bypass the default
    `ai-avatar` which is known to hang).
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### falaw.render_scene(scene, , tts_quality='balanced', lipsync_quality='high', shot_quality='balanced', shots_as_video=False, force=False, concurrency=1)

Render every shot and beat. Returns a manifest dict.

`concurrency` controls how many shots/beats run in parallel
against fal. The work is HTTP-bound, so a thread pool is enough.
Default `1` preserves serial behavior. Use
[`iter_render_scene()`](#falaw.iter_render_scene) instead if you want results yielded as
each unit completes (for live UI updates).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### falaw.render_shot(shot, , environment=None, characters=(), style='', as_video=False, quality='balanced', image_model_id=None, image_to_video_model_id=None, force=False)

Render a Shot as a still (default) or a short clip.

* **Parameters:**
  * **image_model_id** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Override the image-gen model used for the storyboard
    still (defaults to `pick_model(category="image", …)`).
  * **image_to_video_model_id** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Override the image-to-video model used when
    `as_video=True` (e.g. `"fal-ai/minimax/hailuo-02/pro/image-to-video"`).
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### falaw.reprice_plan(plan, \*, pricers={'llm_rates': Pricer(quote=<function \_quote_from_llm_rates>, table='falaw/data/llm_rates.json', version=<functools._lru_cache_wrapper object>), 'model_catalogue': Pricer(quote = <function \_quote_from_catalogue>, table='falaw/data/models.json', version=<functools._lru_cache_wrapper object>)})

Re-quote every call in `plan` against today’s rate tables.

Pure data: no network, no billing API, nothing executed. Returns a new
[`RepricedPlan`](#falaw.RepricedPlan) — the input plan is untouched.

A call carrying a [`falaw.CostBasis`](#falaw.CostBasis) is re-quoted through the pricer
its basis names, with the exact quantity hints that produced the original
figure, and comes back with a basis re-stamped to today’s table version. A
call carrying no basis is reported as `"no_basis"` and its cost is
**cleared to** `None`: the frozen number is a fact about a past moment,
and silently re-presenting it as a current quote is the failure this
function exists to prevent. That clearing lights up
[`falaw.Plan.has_unknown_costs`](#falaw.Plan.has_unknown_costs), which is exactly right — nobody can
say what that call costs today.

A basis is only re-quoted by a pricer reading the **same table** it names.
A mismatch is `"unknown"`, not a re-quote: two tables are two sets of
books, and pricing a caller’s reconciled $0.50 row at falaw’s published
$0.01 would be a 50x under-quote wearing the clothes of a price drop. Pass
a [`Pricer`](#falaw.Pricer) naming that table to re-quote against the same books.

`cache_status` is carried through unchanged. Re-pricing answers “what
would this cost?”, not “is it still cached?”; peeking the cache here would
quietly turn a re-quote into an I/O operation and make a hit look like a
price drop. Re-plan the calls if you want a fresh cache reading.

* **Parameters:**
  * **plan** ([`Plan`](falaw.plan.html.md#falaw.plan.Plan)) – The plan to re-quote, typically just deserialized with
    [`falaw.plan_from_dict()`](#falaw.plan_from_dict).
  * **pricers** ([`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Pricer`](falaw.reprice.html.md#falaw.reprice.Pricer)]) – Pricing rules by [`falaw.CostBasis.pricer`](#falaw.CostBasis.pricer) name. The seam
    for a caller who has reconciled real numbers against their own
    invoice — see [`Pricer`](#falaw.Pricer).
* **Return type:**
  [`RepricedPlan`](falaw.reprice.html.md#falaw.reprice.RepricedPlan)

```pycon
>>> from falaw import Plan, CallPlan, reprice_plan
>>> stale = CallPlan(tool="generate_image", application="fal-ai/flux/dev",
...                  arguments={"prompt": "a tiger"}, output_kind="image",
...                  estimated_cost_usd=0.025)
>>> out = reprice_plan(Plan(calls=(stale,)))
>>> out.calls[0].status
'no_basis'
>>> out.plan.calls[0].estimated_cost_usd is None   # unknown, not $0.025
True
>>> out.plan.has_unknown_costs
True
```

### falaw.scene_from_dict(d)

Inverse of asdict: reconstruct a Scene from a plain dict.

* **Return type:**
  [`Scene`](falaw.scene.html.md#falaw.scene.Scene)

### falaw.storyboard_shot(shot, , environment=None, characters=(), style='', quality='balanced')

Render a storyboard still for a Shot.

* **Return type:**
  [`Result`](falaw.results.html.md#falaw.results.Result)

### falaw.subscribe(callback)

Register `callback` to receive every emitted ProgressEvent.

Returns the callback unchanged so it can be used as a decorator:

```default
@subscribe
def log_to_file(ev: ProgressEvent) -> None:
    ...
```

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`ProgressEvent`](falaw.events.html.md#falaw.events.ProgressEvent)], [`None`](https://docs.python.org/3/builtins/constants.html#None)]

### falaw.talking_avatar_from_text(text, image_url, , voice=None, prompt='', tts_quality='balanced', avatar_quality='balanced')

text + face image → talking video. Two fal calls, one Result.

* **Return type:**
  [`Result`](falaw.results.html.md#falaw.results.Result)

### falaw.text_to_speech(text, , quality='balanced', voice=None, model_id=None, extra=None)

Synthesize speech. `voice` semantics are model-specific.

* **Return type:**
  [`Result`](falaw.results.html.md#falaw.results.Result)

### falaw.text_to_video(prompt, , quality='high', duration_s=None, model_id=None, extra=None)

Generate a video from a text prompt.

* **Return type:**
  [`Result`](falaw.results.html.md#falaw.results.Result)

### falaw.third_party_tenancy_ok(model_id, backend, , ledger=None)

The routing-visible projection: may a router send third-party work to
`(model_id, backend)` without consulting the full ledger? `False` when
unsure — the cheap 80%, so a router can drop an incompatible backend.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### falaw.unsubscribe(callback)

Remove a previously [`subscribe()`](#falaw.subscribe)’d callback. No-op if absent.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### falaw.upload(path, \*, uploader=None, index=None, ttl_s=86400, namespace=None, api_key=None, clock=<built-in function time>)

A fal-fetchable URL for the local file at `path`.

Cached by content: an unchanged file within `ttl_s` of its last upload
returns the remembered URL without any transfer. With the default fal
uploader the object is uploaded with a lifecycle of `ttl_s` and the entry
records when it dies, so a remembered URL is never trusted past that.
`namespace` keeps URLs from different backends apart in a shared index
(default: `"fal"`, or `derive_namespace()` for another uploader).
`api_key` is used by the default uploader only (see
[`falaw.core.fal_client_for()`](falaw.core.html.md#falaw.core.fal_client_for)).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### falaw.upscale_image(image_url, , scale=2.0, model_id=None, extra=None)

Upscale an image.

* **Return type:**
  [`Result`](falaw.results.html.md#falaw.results.Result)

### falaw.using_fal_credentials(key)

Bind `key` as the fal credential for every [`call_fal()`](#falaw.call_fal) in this context.

Intended for server-side bring-your-own-key flows: wrap a unit of work
that will make one or more fal calls, and they all authenticate with
`key` instead of the server’s `FAL_KEY` env var — without any
intermediate function needing a credential parameter.

A falsy `key` is a deliberate no-op (the context is left untouched), so
a caller can pass an optional header value straight through without
special-casing “no BYO key — fall back to the server/env key”.

Thread/async safe: this is `ocracy.kit.using_credentials(fal=key)`, backed
by a [`contextvars.ContextVar`](https://docs.python.org/3/library/contextvars.html#contextvars.ContextVar), so the binding is visible only within
the entering context (and asyncio tasks or copied contexts it spawns),
never to concurrent
requests.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`None`](https://docs.python.org/3/builtins/constants.html#None)]

### falaw.using_terms_context(context)

Scope *context* over every call made inside the block, eager or planned.

The eager verbs (`generate_image`, `render_scene`, …) take no
`terms_context`; this is the one seam that covers all of them, enforced
where every call passes ([`falaw.cache.cached_call_fal()`](falaw.cache.html.md#falaw.cache.cached_call_fal),
[`falaw.core.call_fal()`](falaw.core.html.md#falaw.core.call_fal)). Scoped to the block (and its threads/tasks),
never process-global: the deployment decides, per job.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`None`](https://docs.python.org/3/builtins/constants.html#None)]

### falaw.using_uploader(uploader, , namespace=None)

Make `uploader` the transfer for every [`upload()`](#falaw.upload) (and every local
file in an executed Plan) for the duration: an S3 uploader, or a fake in a
test suite. An explicit `uploader=` argument still wins. `namespace`
keys its URLs in the index (default `derive_namespace()`). Nests and
restores.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### falaw.using_url_fetcher(fetcher)

Make `fetcher` falaw’s default asset transport for the duration.

The **public seam** for replacing falaw’s network transport wholesale —
with an authenticated client, a retrying one, a local mirror, or (the
common case) an in-memory fake in a test suite.

Prefer this to reaching for the module’s private default: it covers every
entry point in one place, it needs no `monkeypatch`, and it cannot be
invalidated by an internal rename. It is also the only mechanism that
reaches a call falaw makes from a thread you did not create — see
`_DEFAULT_FETCHER` for why that matters.

An explicitly passed `fetcher=` / `asset_fetcher=` still wins: this
changes the *default*, never an explicit choice.

Nests and restores, so an inner block cannot leak over an outer one:

```pycon
>>> from lacing import ArtifactStore
>>> store = ArtifactStore.in_memory()
>>> before = default_url_fetcher()
>>> with using_url_fetcher(lambda url: [b"faked"]):
...     content_ref_for_url("https://fal.media/x.png", store=store).bytes_size
5
>>> default_url_fetcher() is before
True
```

For a ready-made fake with pinned bytes and 404s, see [`falaw.testing`](falaw.testing.html.md#module-falaw.testing).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]]]

### falaw.video_model_constraints()

`model_constraints` for every video model in the catalog — the data a
shot-list builder shows as its model-limits reference.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### falaw.voice_clone(reference_audio_url, text, , model_id=None, extra=None)

Generate speech in a cloned voice.

* **Return type:**
  [`Result`](falaw.results.html.md#falaw.results.Result)

### Modules

| [`journal`](falaw.journal.html.md#module-falaw.journal)                     | Agent journal: append-only log of notes, issues and improvements.                                                     |
|---------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|
| [`account`](falaw.account.html.md#module-falaw.account)                     | Account health probe.                                                                                                 |
| [`backends`](falaw.backends.html.md#module-falaw.backends)                   | Execution backend registry — where `CallPlan.backend` dispatches (falaw#15).                                          |
| [`base`](falaw.base.html.md#module-falaw.base)                           | Core types: ToolSpec and ModelRecord.                                                                                 |
| [`bridges`](falaw.bridges.html.md#module-falaw.bridges)                     | Bridges: derive auxiliary surfaces (skill, MCP, HTTP service) from the tool registry.                                 |
| [`cache`](falaw.cache.html.md#module-falaw.cache)                         | Content-addressed cache for fal calls.                                                                                |
| [`canonical`](falaw.canonical.html.md#module-falaw.canonical)                 | One canonical byte-form for everything falaw hashes (falaw#17).                                                       |
| [`comfyui`](falaw.comfyui.html.md#module-falaw.comfyui)                     | The ComfyUI deployment gate, executable (falaw#94, from reelee#241).                                                  |
| [`content`](falaw.content.html.md#module-falaw.content)                     | Content addressing for fal-produced media — identify a file by *what it is*.                                          |
| [`core`](falaw.core.html.md#module-falaw.core)                           | Wrapper over `fal_client.subscribe` with progress events and auto-journaling.                                         |
| [`corpus`](falaw.corpus.html.md#module-falaw.corpus)                       | Extract model records from `misc/docs/llms-full.txt`.                                                                 |
| [`cost`](falaw.cost.html.md#module-falaw.cost)                           | Cost estimation: ModelRecord.cost_estimate + Scene rollups.                                                           |
| [`degrade`](falaw.degrade.html.md#module-falaw.degrade)                     | Where falaw sends "I carried on, but you should know" — one collection point.                                         |
| [`errors`](falaw.errors.html.md#module-falaw.errors)                       | Typed exceptions for falaw operations.                                                                                |
| [`events`](falaw.events.html.md#module-falaw.events)                       | Structured progress events for fal calls.                                                                             |
| [`licences`](falaw.licences.html.md#module-falaw.licences)                   | One licence vocabulary for every falaw ledger (falaw#110).                                                            |
| [`liveness`](falaw.liveness.html.md#module-falaw.liveness)                   | Is a catalogued endpoint still deployed? (falaw#76)                                                                   |
| [`llm_prices`](falaw.llm_prices.html.md#module-falaw.llm_prices)               | One first-party LLM price table: what a direct Anthropic / OpenAI call costs (falaw#81).                              |
| [`llm_rates`](falaw.llm_rates.html.md#module-falaw.llm_rates)                 | Per-routed-model LLM rates: the data behind a *ceiling* quote (falaw#50, option A).                                   |
| [`llm_rates_refresh`](falaw.llm_rates_refresh.html.md#module-falaw.llm_rates_refresh) | Refresh proposals for the LLM rate table, never a silent overwrite (falaw#56).                                        |
| [`local`](falaw.local.html.md#module-falaw.local)                         | Local utilities: ffmpeg + PIL glue for stitching fal outputs.                                                         |
| [`operations`](falaw.operations.html.md#module-falaw.operations)               | Task-level verbs: stable, agent-friendly entry points.                                                                |
| [`outcomes`](falaw.outcomes.html.md#module-falaw.outcomes)                   | Per-call outcomes of running a [`falaw.Plan`](#falaw.Plan) — the partial-result type. |
| [`plan`](falaw.plan.html.md#module-falaw.plan)                           | Plan / Execute primitives — separate planning (data) from execution (effects).                                        |
| [`pricing`](falaw.pricing.html.md#module-falaw.pricing)                     | Read fal's pricing API into `models.json` cost estimates (falaw#18).                                                  |
| [`prune`](falaw.prune.html.md#module-falaw.prune)                         | Capacity management for the falaw cache: see what is on disk, and reclaim it.                                         |
| [`refresh`](falaw.refresh.html.md#module-falaw.refresh)                     | Refresh fal.ai docs locally with conditional GETs.                                                                    |
| [`registry`](falaw.registry.html.md#module-falaw.registry)                   | Tool and model registries.                                                                                            |
| [`reprice`](falaw.reprice.html.md#module-falaw.reprice)                     | Re-quote a persisted [`falaw.Plan`](#falaw.Plan) at today's rates (falaw#60).         |
| [`results`](falaw.results.html.md#module-falaw.results)                     | Result wrapper: parse fal responses into typed assets, lazy download.                                                 |
| [`routing`](falaw.routing.html.md#module-falaw.routing)                     | Which model a router call really goes to (falaw#115).                                                                 |
| [`scene`](falaw.scene.html.md#module-falaw.scene)                         | Scene IR: the editable structure that survives all the way to the pixels.                                             |
| [`schema_export`](falaw.schema_export.html.md#module-falaw.schema_export)         | Export the Python SSOT as committed JSON for the TypeScript twin (`ts/`).                                             |
| [`session`](falaw.session.html.md#module-falaw.session)                     | Session: optional stateful controller over a sequence of falaw operations.                                            |
| [`terms`](falaw.terms.html.md#module-falaw.terms)                         | The terms ledger: may this `(model, backend)` be used for *this* job? (falaw#16)                                      |
| [`testing`](falaw.testing.html.md#module-falaw.testing)                     | Make a suite that uses falaw genuinely offline — the fake asset transport.                                            |
| [`validation`](falaw.validation.html.md#module-falaw.validation)               | Check a call's arguments against the limits its catalogue record states.                                              |
