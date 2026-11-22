/**
 * Plans — pure data describing what *would* be called and what it would cost.
 * The TS twin of `falaw.plan` + `falaw.operations._plan`, in the same wire shape
 * `call_plan_to_dict` / `plan_to_dict` produce, so a plan built here can be sent
 * to a server that runs `falaw.execute_plan` unchanged (metered billing, reelee#146).
 *
 * `cache_status` is always `"unknown"`: a browser has no falaw cache to peek.
 */

import { canonicalBlob, ensureCanonical, planIdentityPayload, sha256Hex } from './canonical';
import { FalError, FalPromptTooLong } from './errors';
import { catalogueCostBasis, estimateCallCost, numericSeconds, videoDurationArg, videoPriceQuantities, type CostBasis } from './cost';
import { CONSTANTS } from './generated/constants';
import type { CallPlan } from './generated/call-plan';
import type { ModelRecord } from './generated/model-record';
import { getModel, pickModel } from './registry';
import { checkCallArguments } from './validation';

export type { CallPlan };
export type OutputKind = CallPlan['output_kind'];

/** The wire form of a whole plan (`falaw.plan_to_dict`). */
export interface Plan {
  readonly schema: string;
  readonly calls: readonly CallPlan[];
}

export interface MakeCallPlanOptions {
  readonly tool: string;
  readonly application: string;
  readonly arguments: Readonly<Record<string, unknown>>;
  readonly outputKind: OutputKind;
  readonly backend?: string;
  readonly estimatedCostUsd?: number | null;
  readonly expectedDurationS?: readonly [number, number] | null;
  /** Measured wall-clock range of the call (`ModelRecord.typical_wall_time_s`), not the clip length. */
  readonly expectedWallTimeS?: readonly [number, number] | null;
  readonly metadata?: Readonly<Record<string, unknown>> | null;
  readonly costBasis?: CostBasis | null;
  /** Identity beyond the wire arguments (nw's Transform `impl_version`): joins the cache
   *  key and `plan_hash` only when non-empty, exactly as on the Python side. */
  readonly keyExtra?: Readonly<Record<string, unknown>> | null;
}

/** Build a `CallPlan`, refusing non-canonical arguments while planning is still free. */
export function makeCallPlan(opts: MakeCallPlanOptions): CallPlan {
  ensureCanonical({ ...opts.arguments }, 'arguments');
  if (opts.keyExtra) ensureCanonical({ ...opts.keyExtra }, 'key_extra');
  const cost = opts.estimatedCostUsd ?? null;
  // Python's CallPlan.__post_init__ refuses these; a NaN here would read as a *known* cost.
  if (cost !== null && !(Number.isFinite(cost) && cost >= 0)) {
    throw new FalError(`estimated_cost_usd must be a finite number >= 0 or null, got ${String(cost)}`);
  }
  const plan: CallPlan = {
    tool: opts.tool,
    application: opts.application,
    backend: opts.backend ?? CONSTANTS.dflt_backend,
    arguments: { ...opts.arguments },
    output_kind: opts.outputKind,
    estimated_cost_usd: cost,
    cache_status: 'unknown',
    expected_duration_s: opts.expectedDurationS ? [...opts.expectedDurationS] : null,
    expected_wall_time_s: opts.expectedWallTimeS ? [...opts.expectedWallTimeS] : null,
    metadata: { ...(opts.metadata ?? {}) },
    key_extra: { ...(opts.keyExtra ?? {}) },
    // Python omits the key when unset; `null` here parses identically on that side
    // (`call_plan_from_dict`) and keeps the TS type one shape. Never hashed either way.
    local_files: [],
    cost_basis: opts.costBasis ?? null,
  };
  return plan;
}

function resolveModel(modelId: string | undefined, category: string, qualityTier: string): ModelRecord {
  return modelId ? getModel(modelId) : pickModel({ category, qualityTier });
}

export interface GenerateImageInput {
  readonly prompt: string;
  /** `fast` | `balanced` | `high` | `ultra` (default `balanced`). */
  readonly quality?: string;
  /** fal's image_size vocabulary (default `landscape_4_3`). */
  readonly imageSize?: string;
  /** A catalogue id or alias; overrides the quality pick. */
  readonly modelId?: string;
  /** Model-specific arguments merged over the standard ones (seed, guidance_scale, …). */
  readonly extra?: Readonly<Record<string, unknown>>;
  /** Sent only to a model whose record has `accepts_negative_prompt`; otherwise dropped and
   *  named in `metadata.dropped_inputs`, never folded into `prompt` (`falaw#158`). */
  readonly negativePrompt?: string | null;
  readonly metadata?: Readonly<Record<string, unknown>>;
}

/**
 * The prompt and size arguments for one text-to-image call
 * (`falaw.operations._image_args.image_arguments`): a model whose `size_param` is
 * `aspect_ratio` gets the ratio a named preset denotes (or a `W:H` given as is);
 * a prompt over the model's `max_prompt_chars` is refused before any call.
 */
function imageSizeArgs(
  record: ModelRecord,
  prompt: string,
  imageSize: string,
  extra: Readonly<Record<string, unknown>> | undefined,
): Record<string, unknown> {
  const limit = record.max_prompt_chars;
  const length = [...prompt].length; // code points, as Python's len()
  if (limit != null && length > limit) {
    throw new FalPromptTooLong(
      `${record.id} accepts prompts of at most ${limit} characters; this one is ${length} (${length - limit} over). ` +
        'Shorten it (a long reusable style suffix is the usual culprit) or pick a model with a larger limit.',
      record.id,
      limit,
      length,
    );
  }
  const sizeParam = record.size_param ?? 'image_size';
  if (sizeParam === 'image_size') return { prompt, image_size: imageSize };
  if (extra && 'image_size' in extra) {
    throw new FalError(
      `${record.id} sizes images by ${sizeParam}, not image_size: pass the size as image_size='W:H' or a named preset, or ${sizeParam} in extra.`,
    );
  }
  const ratios = CONSTANTS.image_size_aspect_ratios as Record<string, string>;
  const ratio = ratios[imageSize] ?? (imageSize.includes(':') ? imageSize : undefined);
  if (ratio === undefined) {
    const presets = Object.keys(ratios).sort().map((k) => `'${k}'`).join(', ');
    throw new FalError(
      `${record.id} sizes images by ${sizeParam}, and '${imageSize}' is neither a named preset ([${presets}]) nor a 'W:H' ratio.`,
    );
  }
  return { prompt, [sizeParam]: ratio };
}

/** Plan a text-to-image call (`falaw.plan_generate_image`). */
export function planGenerateImage(input: GenerateImageInput): CallPlan {
  const record = resolveModel(input.modelId, 'image', input.quality ?? 'balanced');
  const negative = (input.negativePrompt ?? '').trim();
  const accepted = negative && record.accepts_negative_prompt ? { negative_prompt: negative } : {};
  const args = { ...imageSizeArgs(record, input.prompt, input.imageSize ?? 'landscape_4_3', input.extra), ...accepted, ...(input.extra ?? {}) };
  checkCallArguments(record, args);
  // A constraint that never reached the picture is named, outside the plan hash.
  const dropped = negative && !('negative_prompt' in args) ? ['negative_prompt'] : [];
  return makeCallPlan({
    tool: 'generate_image',
    application: record.id,
    arguments: args,
    outputKind: 'image',
    estimatedCostUsd: estimateCallCost(record),
    metadata: dropped.length ? { ...(input.metadata ?? {}), dropped_inputs: dropped } : input.metadata,
    costBasis: catalogueCostBasis(record.id),
  });
}

interface VideoInput {
  readonly quality?: string;
  readonly modelId?: string;
  /** Prices the call; sent to fal only for a model whose record lists a `duration` parameter
   *  (Seedance spells it as a string enum), else only if you put it in `extra`. */
  readonly durationS?: number | null;
  readonly extra?: Readonly<Record<string, unknown>>;
  readonly metadata?: Readonly<Record<string, unknown>>;
}

function planVideo(tool: string, args: Record<string, unknown>, input: VideoInput): CallPlan {
  const record = resolveModel(input.modelId, tool, input.quality ?? 'high');
  const merged: Record<string, unknown> = { ...args, ...(input.extra ?? {}) };
  let seconds = input.durationS ?? null;
  if ('duration' in record.param_specs) {
    if (input.durationS != null && !('duration' in merged)) merged.duration = videoDurationArg(record, input.durationS);
    // Nothing sent: fal bills the record's declared default, so price at it.
    seconds = numericSeconds('duration' in merged ? merged.duration : record.param_specs.duration?.default);
  }
  checkCallArguments(record, merged);
  const quantities = videoPriceQuantities(
    record,
    seconds,
    merged.resolution as string | undefined,
    merged.aspect_ratio as string | undefined,
  );
  return makeCallPlan({
    tool,
    application: record.id,
    arguments: merged,
    outputKind: 'video',
    estimatedCostUsd: estimateCallCost(record, quantities),
    expectedWallTimeS: record.typical_wall_time_s as [number, number] | null,
    metadata: input.metadata,
    costBasis: catalogueCostBasis(record.id, quantities),
  });
}

export interface ImageToVideoInput extends VideoInput {
  /** The still to animate — a URL, or `"<from N>"` to chain onto call N of the same plan. */
  readonly imageUrl: string;
  readonly prompt?: string;
}

/** Plan an image-to-video call (`falaw.plan_image_to_video`). */
export function planImageToVideo(input: ImageToVideoInput): CallPlan {
  const args: Record<string, unknown> = { image_url: input.imageUrl };
  if (input.prompt) args.prompt = input.prompt;
  return planVideo('image_to_video', args, input);
}

export interface TextToVideoInput extends VideoInput {
  readonly prompt: string;
}

/** Plan a text-to-video call (`falaw.plan_text_to_video`). */
export function planTextToVideo(input: TextToVideoInput): CallPlan {
  return planVideo('text_to_video', { prompt: input.prompt }, input);
}

export interface ReferenceToVideoInput extends VideoInput {
  readonly prompt: string;
  readonly imageUrls?: readonly string[];
  readonly videoUrls?: readonly string[];
  readonly audioUrls?: readonly string[];
}

/** Plan a reference-to-video call (`falaw.plan_reference_to_video`): a prompt steered by
 *  reference images, videos and audio. Counts are checked against the model's limits. */
export function planReferenceToVideo(input: ReferenceToVideoInput): CallPlan {
  const refs = { image_urls: input.imageUrls, video_urls: input.videoUrls, audio_urls: input.audioUrls };
  const args: Record<string, unknown> = { prompt: input.prompt };
  for (const [name, urls] of Object.entries(refs)) {
    if (typeof urls === 'string') throw new TypeError(`${name} must be a list of URLs, not one string`);
    if (urls && urls.length) args[name] = [...urls];
  }
  return planVideo('reference_to_video', args, input);
}

export function makePlan(calls: readonly CallPlan[]): Plan {
  return { schema: CONSTANTS.plan_dict_schema, calls: [...calls] };
}

/** What a call will bill: nothing on a cache hit, its estimate otherwise, `0` when
 *  unknown — so read `hasUnknownCosts` before trusting a total as a ceiling. */
export function billableCostUsd(call: CallPlan): number {
  return call.cache_status === 'hit' ? 0 : (call.estimated_cost_usd ?? 0);
}

/** Sum of `billableCostUsd` over the plan (Python's `Plan.total_cost_usd`). */
export function totalCostUsd(plan: Plan): number {
  return plan.calls.reduce((sum, c) => sum + billableCostUsd(c), 0);
}

export function hasUnknownCosts(plan: Plan): boolean {
  return plan.calls.some((c) => c.estimated_cost_usd == null && c.cache_status !== 'hit');
}

/** Structural idempotency key for a whole plan, byte-compatible with Python's `plan_hash`. */
export async function planHash(plan: Plan): Promise<string> {
  const blob = canonicalBlob(
    plan.calls.map((c) =>
      planIdentityPayload(c.application, c.arguments, {
        tool: c.tool,
        backend: c.backend,
        keyExtra: c.key_extra && Object.keys(c.key_extra).length ? c.key_extra : null,
      }),
    ),
  );
  return sha256Hex(blob);
}
