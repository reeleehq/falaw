/**
 * falaw-client — plan and execute fal.ai media generation from the browser.
 *
 * The TypeScript twin of the Python `falaw` package. The plan and result shapes,
 * the model catalogue with its prices, the cost rules and the canonical hashing
 * form are generated from and pinned to the Python side (`schema/` at the repo
 * root); execution goes through a server relay because fal.ai forbids browser-held
 * keys.
 *
 * ```ts
 * import { planGenerateImage, makePlan, totalCostUsd, execute, queueTransport } from 'falaw-client';
 *
 * const plan = makePlan([planGenerateImage({ prompt: 'a tiger eye, macro', quality: 'fast' })]);
 * console.log(totalCostUsd(plan));            // cost-honest, before any network
 * const [{ result }] = await execute(plan, {
 *   transport: queueTransport({ proxyUrl: '/api/fal/proxy', key: () => userKey }),
 * });
 * result.assets[0].url;
 * ```
 */

export {
  makeCallPlan,
  planGenerateImage,
  planImageToVideo,
  planTextToVideo,
  makePlan,
  totalCostUsd,
  billableCostUsd,
  hasUnknownCosts,
  planHash,
} from './plan';
export type { Plan, CallPlan, OutputKind, GenerateImageInput, ImageToVideoInput, TextToVideoInput, MakeCallPlanOptions } from './plan';
export { execute, hasPlaceholder } from './execute';
export type { ExecutedCall, ExecuteOptions } from './execute';
export { queueTransport } from './transport';
export type { Transport, TransportContext, TransportResult, ProgressEvent, QueueTransportOptions } from './transport';
export { parseResponse } from './results';
export type { Result, Asset } from './results';
export { listModels, getModel, pickModel, TIER_ORDER } from './registry';
export { estimateCallCost, catalogueCostBasis } from './cost';
export type { CostBasis, CostHints } from './cost';
export {
  canonicalBlob,
  ensureCanonical,
  sha256Hex,
  cacheKeyPayload,
  planIdentityPayload,
  DFLT_BACKEND,
} from './canonical';
export { FalError, FalNonCanonicalArgument, UnknownModelError } from './errors';
export { callPlanSchema, type CallPlanInput } from './generated/call-plan';
export { resultSchema } from './generated/result';
export { modelRecordSchema, type ModelRecord } from './generated/model-record';
export { MODELS, MODELS_TABLE_VERSION } from './generated/models';
export { CONSTANTS } from './generated/constants';
