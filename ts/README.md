# falaw-client (npm)

Plan and execute fal.ai media generation **from the browser**. The TypeScript twin of the Python [`falaw`](https://github.com/thorwhalen/falaw) package (PyPI `falaw`; the registry refused that name on npm as too similar to existing packages, hence `falaw-client`): the same model catalogue with its prices, the same cost rules, the same `CallPlan` wire shape and the same `plan_hash`, so a plan built in a browser is one a server running Python `falaw.execute_plan` accepts unchanged.

```bash
npm install falaw-client
```

```ts
import { planGenerateImage, planImageToVideo, makePlan, totalCostUsd, hasUnknownCosts, execute, queueTransport } from 'falaw-client';

// Plans are pure data: no network, cost-honest.
const plan = makePlan([
  planGenerateImage({ prompt: 'a tiger eye, macro, 35mm', quality: 'fast' }),
  planImageToVideo({ imageUrl: '<from 0>', prompt: 'slow push in', durationS: 6 }),
]);
if (hasUnknownCosts(plan)) askFirst();      // null means unknown, never free
console.log(totalCostUsd(plan));            // e.g. 0.483

// fal.ai forbids browser-held keys, so execution goes through a relay.
const done = await execute(plan, {
  transport: queueTransport({ proxyUrl: '/api/fal/proxy', key: () => userKey }),
  onEvent: (e) => console.log(e.kind, e.providerPhase, e.queuePosition),  // the Python event vocabulary
});
done[1].result.assets[0].url;               // the clip
done[1].requestId;                          // fal's id — provenance
```

## The transport seam

`queueTransport` speaks fal's queue API with plain `fetch` and has two configurations of one shape:

- **through a relay** (`proxyUrl`): each request goes to the relay with the fal URL in `X-Fal-Target-Url` and the caller's key, if any, in `X-Fal-Key`. That is the protocol `reelee/fal_proxy.py` implements. With no key, the relay may supply a server-held one and meter the call (reelee#146).
- **direct** (no `proxyUrl`): for Node or a server, `Authorization: Key …`.

A `Transport` is one function `(call, ctx) => Promise<{ raw, requestId? }>`, so a server endpoint that runs Python `execute_plan` on a posted plan is the same seam with a different value.

## What a plan carries

`CallPlan` is `falaw.call_plan_to_dict`'s shape: `tool`, `application`, `backend`, `arguments`, `output_kind`, `estimated_cost_usd` (`null` when unknown), `cache_status` (always `"unknown"` in a browser: there is no cache to peek), `expected_duration_s`, `metadata`, `key_extra`, and `cost_basis` (which record, which quantities, which catalogue version priced it, so it can be re-quoted later). `planHash` is SHA-256 over the same canonical bytes Python uses.

Known divergences, all in how a *number* is spelled: an integral-valued float (`1.0` in Python, `1` here), floats below 1e-4 or in [1e16, 1e21) (different exponent thresholds), and integers beyond 2^53. A prompt cannot trigger any of them; only `extra` or `durationS` can, and a plan still hashes consistently across the wire because the browser hashes what it sends and a server recomputes from the JSON it receives.

## How it stays in step with Python

`schema/` at the repo root is written by `python -m falaw export-schema`: JSON Schemas for `CallPlan`, `Result` and `ModelRecord`, the catalogue byte for byte (its digest is `MODELS_TABLE_VERSION`), constants, and **parity fixtures** (planner inputs → the plan Python builds and its hash; raw responses → parsed results; model picks; cost cases; canonical blobs with their SHA-256). `npm run codegen` generates `src/generated/`; `npm test` replays every fixture. A change on either side that forgets the other fails CI.
