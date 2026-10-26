/**
 * Turn a plan into results — the browser-side counterpart of `falaw.execute_plan`.
 *
 * Calls run in order. A `"<from N>"` placeholder in a call's arguments is replaced by
 * the URL of call N's first asset, so an image→video chain is one plan. There is no
 * cache and no content addressing here (the relay's server side owns both); what comes
 * back is the parsed `Result` plus the plan that produced it and fal's request id —
 * the provenance breadcrumb a picture carries into the application.
 */

import { CONSTANTS } from './generated/constants';
import type { CallPlan } from './generated/call-plan';
import type { Result } from './generated/result';
import type { Plan } from './plan';
import { parseResponse } from './results';
import type { Transport, TransportContext } from './transport';

export interface ExecutedCall {
  readonly call: CallPlan;
  /** The call as sent: placeholders resolved. */
  readonly sent: CallPlan;
  readonly result: Result;
  readonly requestId?: string;
}

export interface ExecuteOptions extends TransportContext {
  readonly transport: Transport;
}

export async function execute(plan: Plan | readonly CallPlan[], opts: ExecuteOptions): Promise<ExecutedCall[]> {
  const calls = Array.isArray(plan) ? (plan as readonly CallPlan[]) : (plan as Plan).calls;
  const done: ExecutedCall[] = [];
  for (const call of calls) {
    if (call.local_files?.length) {
      throw new Error(
        `Call ${call.application} names local files (${CONSTANTS.file_prefix}...>); only falaw (Python) can upload them. Send the plan to a falaw executor.`,
      );
    }
    const sent: CallPlan = { ...call, arguments: resolvePlaceholders(call.arguments, done) as Record<string, unknown> };
    const { raw, requestId } = await opts.transport(sent, { signal: opts.signal, onEvent: opts.onEvent });
    const result = parseResponse(raw, { application: sent.application, arguments: sent.arguments });
    done.push({ call, sent, result, requestId });
  }
  return done;
}

const PLACEHOLDER_PREFIX: string = CONSTANTS.placeholder_prefix;

export function hasPlaceholder(value: unknown): boolean {
  if (typeof value === 'string') return value.startsWith(PLACEHOLDER_PREFIX);
  if (Array.isArray(value)) return value.some(hasPlaceholder);
  if (typeof value === 'object' && value !== null) return Object.values(value).some(hasPlaceholder);
  return false;
}

function resolvePlaceholders(value: unknown, done: readonly ExecutedCall[]): unknown {
  if (typeof value === 'string' && value.startsWith(PLACEHOLDER_PREFIX)) return lookup(value, done);
  if (Array.isArray(value)) return value.map((v) => resolvePlaceholders(v, done));
  if (typeof value === 'object' && value !== null) {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, resolvePlaceholders(v, done)]));
  }
  return value;
}

function lookup(placeholder: string, done: readonly ExecutedCall[]): string {
  const m = /^<from (\d+)>$/.exec(placeholder);
  if (!m) throw new Error(`Malformed placeholder ${JSON.stringify(placeholder)}; expected "<from N>".`);
  const idx = Number(m[1]);
  const upstream = done[idx];
  if (!upstream) throw new Error(`Placeholder ${placeholder} references call ${idx}, which has not run before it.`);
  const url = upstream.result.assets[0]?.url;
  if (!url) throw new Error(`Placeholder ${placeholder}: call ${idx} produced no asset with a URL.`);
  return url;
}
