/**
 * Cost rules — the TS twin of `falaw.cost.estimate_call_cost` and the catalogue cost basis.
 *
 * `null` means **unknown**, never free: a `per_second` call with no duration is unpriceable,
 * and returning `0` would let a budget gate wave through the most expensive thing fal bills
 * for. `per_megapixel` alone has a house default (`CONSTANTS.default_megapixels`).
 */

import { CONSTANTS } from './generated/constants';
import type { CallPlan } from './generated/call-plan';
import type { ModelRecord } from './generated/model-record';
import { MODELS_TABLE_VERSION } from './generated/models';

export type CostBasis = NonNullable<CallPlan['cost_basis']>;

export interface CostHints {
  readonly count?: number;
  readonly seconds?: number | null;
  readonly megapixels?: number | null;
  readonly tokens?: number | null;
}

export function estimateCallCost(record: Pick<ModelRecord, 'cost_estimate'>, hints: CostHints = {}): number | null {
  const ce = record.cost_estimate;
  if (!ce) return null;
  const count = hints.count ?? 1;
  switch (ce.kind) {
    case 'per_call':
    case 'per_image':
      return ce.amount * count;
    case 'per_second':
      if (hints.seconds == null) return null; // unknown duration → unpriceable, NOT free
      return ce.amount * hints.seconds * count;
    case 'per_megapixel': {
      const mp = hints.megapixels ?? CONSTANTS.default_megapixels;
      return ce.amount * mp * count;
    }
    case 'per_token':
      if (hints.tokens == null) return null;
      return ce.amount * hints.tokens * count;
    default:
      return null;
  }
}

/** The basis for a call priced from the catalogue: which record, which quantities,
 *  which table and which version of it — enough to re-quote later. `null` hints are
 *  dropped, as on the Python side (absent is what the estimator saw). */
export function catalogueCostBasis(modelId: string, quantities: Omit<CostHints, 'count'> = {}): CostBasis {
  const supplied: Record<string, number> = {};
  for (const [k, v] of Object.entries(quantities)) if (v != null) supplied[k] = v;
  return {
    pricer: CONSTANTS.catalogue_pricer,
    priced: modelId,
    quantities: supplied,
    table: CONSTANTS.model_catalogue_table,
    table_version: MODELS_TABLE_VERSION,
  };
}

/** Python's `round()` — halves go to the even neighbour (JS `Math.round` rounds them up). */
export function roundHalfEven(x: number): number {
  const floor = Math.floor(x);
  const diff = x - floor;
  if (diff < 0.5) return floor;
  if (diff > 0.5) return floor + 1;
  return floor % 2 === 0 ? floor : floor + 1;
}

/** `durationS` as the string fal's duration enum wants (`falaw.cost.video_duration_arg`):
 *  whole seconds (halves to even), within the record's numeric `duration` enum. Throws otherwise. */
export function videoDurationArg(record: Pick<ModelRecord, 'id' | 'param_specs'>, durationS: number): string {
  if (!Number.isFinite(durationS)) throw new Error(`${record.id}: duration must be finite, got ${durationS}`);
  const seconds = roundHalfEven(durationS);
  const enumValues = (record.param_specs.duration?.enum as unknown[] | undefined) ?? [];
  const allowed = enumValues.filter((v) => /^\d+$/.test(String(v))).map(Number).sort((x, y) => x - y);
  if (allowed.length && !allowed.includes(seconds)) {
    throw new Error(`${record.id} accepts durations of ${allowed[0]} to ${allowed[allowed.length - 1]} s; got ${durationS}`);
  }
  return String(seconds);
}

/** A duration argument as seconds; `null` for absent, `"auto"`, empty or junk (unknown, never free). */
export function numericSeconds(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value !== 'string' || value.trim() === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** Pixels per frame of a named resolution at a "W:H" aspect (`falaw.cost.frame_pixels`). */
export function framePixels(resolution: string, aspectRatio?: string | null): number {
  const short = (CONSTANTS.video_resolution_short_side as Record<string, number>)[resolution]!;
  const ratio = !aspectRatio || aspectRatio === 'auto' ? CONSTANTS.default_video_aspect : aspectRatio;
  const parts = String(ratio).split(':');
  const [w, h] = parts.map((p) => (/^\d+$/.test(p.trim()) ? Number(p) : 0));
  if (parts.length !== 2 || !w || !h) throw new Error(`aspect_ratio must look like '16:9' or 'auto', got ${JSON.stringify(ratio)}`);
  return (short * short * Math.max(w, h)) / Math.min(w, h);
}

/** The quantity hints that price one video call (`falaw.cost.video_price_quantities`):
 *  `{tokens}` for a per-video-token model, `{seconds}` otherwise, `{}` when the duration
 *  is unknown (unpriceable, never free). */
export function videoPriceQuantities(
  record: Pick<ModelRecord, 'id' | 'tokens_per_pixel_second' | 'param_specs'>,
  seconds: number | null | undefined,
  resolution?: string | null,
  aspectRatio?: string | null,
): Omit<CostHints, 'count'> {
  if (seconds == null) return {};
  const factor = record.tokens_per_pixel_second;
  if (factor == null) return { seconds };
  const spec = record.param_specs.resolution;
  const res = resolution || (spec?.default as string | undefined) || CONSTANTS.default_video_resolution;
  const shortSides = CONSTANTS.video_resolution_short_side as Record<string, number>;
  const allowed = (spec?.enum as string[] | undefined) ?? Object.keys(shortSides).sort();
  if (!allowed.includes(res) || shortSides[res] === undefined) {
    throw new Error(`${record.id} does not offer resolution '${res}'; expected one of ${JSON.stringify(allowed)}`);
  }
  return { tokens: roundHalfEven(framePixels(res, aspectRatio) * seconds * factor) };
}
