/**
 * The model catalogue as data — the TS twin of `falaw.registry`'s model half.
 *
 * `MODELS` is generated from the committed `models.json` (curated entries first, so
 * first-match picking prefers them), and `MODELS_TABLE_VERSION` is the digest of those
 * bytes, the same identity a Python `CostBasis` records.
 */

import { UnknownModelError } from './errors';
import { CONSTANTS } from './generated/constants';
import type { ModelRecord } from './generated/model-record';
import { MODELS } from './generated/models';

export const TIER_ORDER: readonly string[] = CONSTANTS.tier_order;

export interface ListModelsOptions {
  readonly category?: string | null;
  readonly qualityTier?: string | null;
}

export function listModels(opts: ListModelsOptions = {}): ModelRecord[] {
  return MODELS.filter(
    (m) =>
      (opts.category == null || m.category === opts.category) &&
      (opts.qualityTier == null || m.quality_tier === opts.qualityTier),
  );
}

/** The record for an id or one of its aliases. */
export function getModel(id: string): ModelRecord {
  const exact = MODELS.find((m) => m.id === id);
  if (exact) return exact;
  const byAlias = MODELS.find((m) => m.aliases.includes(id));
  if (byAlias) return byAlias;
  throw new UnknownModelError(`Unknown model ${JSON.stringify(id)}; see listModels().`);
}

/** A sensible model for a (category, quality) request: exact tier first, then the
 *  nearest tiers outward, then the category's first entry. Throws only when the
 *  category is empty. */
export function pickModel(opts: { readonly category: string; readonly qualityTier?: string }): ModelRecord {
  const tier = opts.qualityTier ?? 'balanced';
  const everything = listModels({ category: opts.category });
  // A record opted out of default picks never wins; a category made only of them still answers.
  const eligible = everything.filter((m) => m.default_pick !== false);
  const candidates = eligible.length ? eligible : everything;
  const firstWithTier = (t: string) => candidates.find((m) => m.quality_tier === t) ?? null;
  const exact = firstWithTier(tier);
  if (exact) return exact;
  const i = TIER_ORDER.indexOf(tier);
  if (i >= 0) {
    for (let offset = 1; offset < TIER_ORDER.length; offset++) {
      for (const j of [i - offset, i + offset]) {
        if (j >= 0 && j < TIER_ORDER.length) {
          const near = firstWithTier(TIER_ORDER[j]!);
          if (near) return near;
        }
      }
    }
  }
  if (!candidates.length) {
    throw new UnknownModelError(`No models known for category=${JSON.stringify(opts.category)}. Try listModels().`);
  }
  return candidates[0]!;
}
