// Parity with the Python side, replayed from schema/fixtures (what `python -m falaw
// export-schema` wrote). Python computed every expectation; the TS port must match it —
// plan for plan, hash for hash.

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { cacheKeyPayload, canonicalBlob, ensureCanonical, planIdentityPayload, sha256Hex } from './canonical';
import { estimateCallCost } from './cost';
import { FalNonCanonicalArgument } from './errors';
import { MODELS, MODELS_TABLE_VERSION } from './generated/models';
import { CONSTANTS } from './generated/constants';
import { hasUnknownCosts, makePlan, planGenerateImage, planHash, planImageToVideo, planReferenceToVideo, planTextToVideo, totalCostUsd } from './plan';
import { pickModel } from './registry';
import { parseResponse } from './results';

const FIXTURES = resolve(__dirname, '../../schema/fixtures');
const load = <T>(name: string): T => JSON.parse(readFileSync(resolve(FIXTURES, name), 'utf8')) as T;

interface PlanCase {
  tool: string;
  input: Record<string, unknown>;
  expected: Record<string, unknown>;
  plan_hash: string;
}
interface Plans {
  calls: PlanCase[];
  errors: { tool: string; input: Record<string, unknown>; message: string }[];
  plans: { calls: number[]; expected: Record<string, unknown>; plan_hash: string; total_cost_usd: number; has_unknown_costs: boolean }[];
}

/** Python planner kwargs → the TS input object. */
function plan(tool: string, input: Record<string, unknown>) {
  const camel: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(input)) camel[k.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase())] = v;
  if (tool === 'generate_image') return planGenerateImage(camel as unknown as Parameters<typeof planGenerateImage>[0]);
  if (tool === 'image_to_video') return planImageToVideo(camel as unknown as Parameters<typeof planImageToVideo>[0]);
  if (tool === 'text_to_video') return planTextToVideo(camel as unknown as Parameters<typeof planTextToVideo>[0]);
  if (tool === 'reference_to_video') return planReferenceToVideo(camel as unknown as Parameters<typeof planReferenceToVideo>[0]);
  throw new Error(`no planner for ${tool}`);
}

/** Python omits `local_files` when empty and `expected_wall_time_s` when unmeasured; absent reads as empty / null. */
function withTolerated(call: Record<string, unknown>): Record<string, unknown> {
  return { local_files: [], expected_wall_time_s: null, ...call };
}

describe('plans', () => {
  const fixture = load<Plans>('plans.json');

  it.each(fixture.calls.map((c, i) => [i, c] as const))('call %i builds the same CallPlan and hash', async (_, c) => {
    const built = plan(c.tool, c.input);
    expect(built).toEqual(withTolerated(c.expected));
    expect(await planHash(makePlan([built]))).toBe(c.plan_hash);
  });

  it.each(fixture.plans.map((p, i) => [i, p] as const))('plan %i (calls %s)', async (_, p) => {
    const built = makePlan(p.calls.map((i) => plan(fixture.calls[i]!.tool, fixture.calls[i]!.input)));
    expect(built).toEqual({ ...p.expected, calls: (p.expected.calls as Record<string, unknown>[]).map(withTolerated) });
    expect(await planHash(built)).toBe(p.plan_hash);
    expect(totalCostUsd(built)).toBeCloseTo(p.total_cost_usd, 12);
    expect(hasUnknownCosts(built)).toBe(p.has_unknown_costs);
  });

  it.each(fixture.errors.map((e, i) => [i, e] as const))('error case %i raises like Python', (_, e) => {
    expect(() => plan(e.tool, e.input)).toThrow(e.message);
  });

  it('every plan fixture prices from this catalogue version', () => {
    for (const c of fixture.calls) {
      expect((c.expected.cost_basis as { table_version: string }).table_version).toBe(MODELS_TABLE_VERSION);
    }
    expect(CONSTANTS.models_table_version).toBe(MODELS_TABLE_VERSION);
  });
});

describe('responses', () => {
  const cases = load<{ application: string; arguments: Record<string, unknown>; raw: unknown; expected: unknown }[]>('responses.json');
  it.each(cases.map((c, i) => [i, c] as const))('parses response %i like Python', (_, c) => {
    expect(parseResponse(c.raw, { application: c.application, arguments: c.arguments })).toEqual(c.expected);
  });
});

describe('pickModel', () => {
  const cases = load<{ category: string; quality_tier: string; expected: string | null; error: string | null }[]>('pick_model.json');
  it.each(cases)('$category / $quality_tier', (c) => {
    if (c.expected === null) {
      expect(() => pickModel({ category: c.category, qualityTier: c.quality_tier })).toThrow();
    } else {
      expect(pickModel({ category: c.category, qualityTier: c.quality_tier }).id).toBe(c.expected);
    }
  });
});

describe('estimateCallCost', () => {
  type Case = { cost_estimate: { kind: string; amount: number } | null; count: number; seconds?: number; megapixels?: number; tokens?: number; expected: number | null };
  it.each(load<Case[]>('cost.json'))('%o', (c) => {
    const record = { cost_estimate: c.cost_estimate ? { ...c.cost_estimate, currency: 'USD', notes: '', source: 'approximate' } : null };
    const got = estimateCallCost(record as Parameters<typeof estimateCallCost>[0], {
      count: c.count,
      seconds: c.seconds ?? null,
      megapixels: c.megapixels ?? null,
      tokens: c.tokens ?? null,
    });
    if (c.expected === null) expect(got).toBeNull();
    else expect(got).toBeCloseTo(c.expected, 12);
  });
});

describe('canonical byte-form', () => {
  const fixture = load<{
    blobs: { payload: unknown; blob: string; sha256: string }[];
    identities: { application: string; arguments: Record<string, unknown>; tool: string | null; backend?: string; key_extra?: Record<string, unknown>; cache_key_payload: unknown; plan_identity_payload: unknown }[];
  }>('canonical.json');

  it.each(fixture.blobs.map((b, i) => [i, b] as const))('blob %i matches Python byte for byte', async (_, b) => {
    const blob = canonicalBlob(b.payload);
    expect(blob).toBe(b.blob);
    expect(await sha256Hex(blob)).toBe(b.sha256);
  });

  it.each(fixture.identities.map((c, i) => [i, c] as const))('identity projections %i', (_, c) => {
    const opts = { backend: c.backend, keyExtra: c.key_extra ?? null };
    expect(cacheKeyPayload(c.application, c.arguments, opts)).toEqual(c.cache_key_payload);
    expect(planIdentityPayload(c.application, c.arguments, { ...opts, tool: c.tool })).toEqual(c.plan_identity_payload);
  });

  it('refuses what JSON cannot carry, naming the path', () => {
    expect(() => ensureCanonical({ a: { b: [1, Number.NaN] } })).toThrow(FalNonCanonicalArgument);
    expect(() => ensureCanonical({ a: { ref: undefined } })).toThrow(/arguments\.a\.ref/);
    expect(() => ensureCanonical({ when: new Date(0) })).toThrow(/Date/);
  });
});

describe('catalogue', () => {
  it('is the committed models.json, with a matching table version', () => {
    const rows = JSON.parse(readFileSync(resolve(__dirname, '../../schema/models.json'), 'utf8')) as Record<string, unknown>[];
    expect(MODELS.map((m) => m.id)).toEqual(rows.map((r) => r.id));
    rows.forEach((row, i) => expect(MODELS[i]).toMatchObject(row)); // defaults added, nothing changed
    expect(MODELS_TABLE_VERSION).toHaveLength(12);
  });
});
