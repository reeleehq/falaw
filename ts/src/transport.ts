/**
 * The transport seam: how a `CallPlan` becomes a fal request.
 *
 * A `Transport` takes one call and returns fal's raw response. The default,
 * `queueTransport`, speaks fal's queue API with plain `fetch` — no client library —
 * and has two configurations of one shape:
 *
 * - **through a relay** (`proxyUrl`): every request is POSTed/GETed to the relay with
 *   the real fal URL in `X-Fal-Target-Url` and the caller's key, if any, in `X-Fal-Key`.
 *   This is the protocol `reelee/fal_proxy.py` implements (and what `@fal-ai/client`'s
 *   proxy mode speaks), because fal.ai forbids browser-held keys. With no key the relay
 *   may supply a server-held one and meter the call (reelee#146).
 * - **direct** (no `proxyUrl`): for Node or a server, with `Authorization: Key …`.
 *
 * Replacing the transport is one argument to `execute`; a server endpoint that runs
 * `falaw.execute_plan` on the posted plan is the same seam with a different value.
 */

import { FalError } from './errors';
import type { CallPlan } from './generated/call-plan';
import { CONSTANTS } from './generated/constants';

export type Json = Record<string, unknown>;

export interface TransportContext {
  readonly signal?: AbortSignal;
  readonly onEvent?: (event: ProgressEvent) => void;
}

/** Every event kind the Python side emits (`falaw.events.EventKind`); the transport uses a subset. */
export type EventKind = (typeof CONSTANTS.event_kinds)[number];
/** fal's word on where a call is (`falaw.events.ProviderPhase`). */
export type ProviderPhase = (typeof CONSTANTS.provider_phases)[number];

/**
 * One step of a call, in the Python `ProgressEvent` vocabulary (camelCased):
 * `queued` (submitted), `provider_queued` (waiting in fal's line, `queuePosition`
 * ahead, reported on a change only), `progress` (being made), `done` (with fal's run
 * `metrics`, e.g. `inference_time`, when it reported any), `error`. `providerPhase` is
 * set only on what fal reported (`in_queue` / `in_progress`); `status` is fal's raw
 * status string.
 */
export interface ProgressEvent {
  readonly kind: EventKind;
  readonly application: string;
  readonly requestId?: string;
  readonly providerPhase?: ProviderPhase;
  readonly queuePosition?: number;
  readonly status?: string;
  readonly message?: string;
  readonly metrics?: Json;
}

export interface TransportResult {
  readonly raw: Json;
  readonly requestId?: string;
}

export type Transport = (call: CallPlan, ctx: TransportContext) => Promise<TransportResult>;

export interface QueueTransportOptions {
  /** The relay endpoint (e.g. `/api/fal/proxy`). Omit to call fal directly (server/Node only). */
  readonly proxyUrl?: string | null;
  /** The caller's fal key, or a getter read per request (so a rotated key applies at once). */
  readonly key?: string | null | (() => string | null | undefined);
  /** fal's queue host (default `https://queue.fal.run`). */
  readonly queueBaseUrl?: string;
  readonly fetch?: typeof globalThis.fetch;
  /** Status poll cadence (default 1000 ms). */
  readonly pollIntervalMs?: number;
  /** Give up waiting for a result after this long (default 10 minutes). */
  readonly timeoutMs?: number;
}

const DFLT_QUEUE_BASE_URL = 'https://queue.fal.run';
const DFLT_POLL_INTERVAL_MS = 1000;
const DFLT_TIMEOUT_MS = 10 * 60 * 1000;
/** No queue position seen yet: unlike `null`, a value fal's JSON can never carry. */
const NO_POSITION = Symbol('no queue position');

interface QueueSubmission {
  request_id?: string;
  status_url?: string;
  response_url?: string;
  cancel_url?: string;
}

interface QueueStatus {
  status?: string;
  queue_position?: number;
  response_url?: string;
  metrics?: Json;
  error?: string | null;
  error_type?: string | null;
}

export function queueTransport(opts: QueueTransportOptions = {}): Transport {
  const doFetch = opts.fetch ?? globalThis.fetch;
  const base = (opts.queueBaseUrl ?? DFLT_QUEUE_BASE_URL).replace(/\/$/, '');
  const pollInterval = opts.pollIntervalMs ?? DFLT_POLL_INTERVAL_MS;
  const timeout = opts.timeoutMs ?? DFLT_TIMEOUT_MS;
  const readKey = () => (typeof opts.key === 'function' ? opts.key() : opts.key) ?? null;

  async function request(method: 'GET' | 'POST' | 'PUT', target: string, body: unknown, signal?: AbortSignal): Promise<Json> {
    const key = readKey();
    const headers = new Headers({ Accept: 'application/json' });
    if (body !== undefined) headers.set('Content-Type', 'application/json');
    let url = target;
    if (opts.proxyUrl) {
      url = opts.proxyUrl;
      headers.set('X-Fal-Target-Url', target);
      if (key) headers.set('X-Fal-Key', key);
    } else {
      if (!key) throw new FalError('fal needs a key: pass `key`, or route through a relay with `proxyUrl`.');
      headers.set('Authorization', `Key ${key}`);
    }
    let response: Response;
    try {
      response = await doFetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal });
    } catch (e) {
      if (signal?.aborted || (e as Error).name === 'AbortError') throw abortError(signal);
      throw new FalError(`fal request failed: ${(e as Error).message ?? String(e)}`);
    }
    if (!response.ok) throw new FalError(`fal ${method} ${target}: ${await shortBody(response)}`, response.status);
    let decoded: unknown;
    try {
      decoded = await response.json();
    } catch {
      // The classic misroute: a wrong `proxyUrl` answered by an SPA's index.html with 200.
      throw new FalError(`fal ${method} ${target}: the reply was not JSON — is \`proxyUrl\` (${opts.proxyUrl ?? 'direct'}) the relay?`, response.status);
    }
    if (typeof decoded !== 'object' || decoded === null || Array.isArray(decoded)) {
      throw new FalError(`fal ${method} ${target}: unexpected reply type ${Array.isArray(decoded) ? 'array' : typeof decoded}`, response.status);
    }
    return decoded as Json;
  }

  /** Best-effort: tell fal to stop a job we will no longer collect, so it stops billing. */
  async function cancel(submitted: QueueSubmission, signal?: AbortSignal): Promise<void> {
    if (!submitted.cancel_url) return;
    try {
      await request('PUT', submitted.cancel_url, undefined, signal);
    } catch {
      // the caller is already on an error path; a failed cancel adds nothing actionable
    }
  }

  return async (call, ctx) => {
    const { signal } = ctx;
    const { application } = call;
    const fail = (error: FalError, extra: Partial<ProgressEvent> = {}): never => {
      ctx.onEvent?.({ kind: 'error', application, message: error.message, ...extra });
      throw error;
    };
    let submitted: QueueSubmission;
    try {
      submitted = (await request('POST', `${base}/${application}`, call.arguments, signal)) as QueueSubmission;
    } catch (e) {
      return fail(e instanceof FalError ? e : new FalError(String(e)));
    }
    const requestId = submitted.request_id;
    if (!submitted.status_url || !submitted.response_url) {
      // The queue host never answers synchronously; a 2xx JSON without the queue
      // fields is a relay speaking for itself ({"detail": "quota exceeded"} with 200).
      return fail(
        new FalError(`fal queue did not accept the request: ${JSON.stringify(submitted).slice(0, 300)}`),
      );
    }
    ctx.onEvent?.({ kind: 'queued', application, requestId });
    const deadline = Date.now() + timeout;
    let lastPosition: unknown = NO_POSITION; // fal re-reports the line: say it on a change only
    let metrics: Json | undefined;
    try {
      for (;;) {
        const status = (await request('GET', submitted.status_url, undefined, signal)) as QueueStatus;
        if (status.status === 'COMPLETED') {
          // A failed run reports its metrics too: read them first, for the error event.
          metrics = isRecord(status.metrics) && Object.keys(status.metrics).length ? status.metrics : undefined;
          if (status.error) {
            // No result is fetched, so the run fails (the Python side keeps a result in hand).
            throw new FalError(`fal request ${requestId ?? ''} failed: ${status.error_type || 'error'}: ${status.error}`);
          }
          break;
        }
        if (status.status === 'IN_QUEUE') {
          if (status.queue_position !== lastPosition) {
            lastPosition = status.queue_position;
            ctx.onEvent?.({ kind: 'provider_queued', application, requestId, status: status.status, providerPhase: 'in_queue', queuePosition: status.queue_position });
          }
        } else if (status.status === 'IN_PROGRESS') {
          lastPosition = NO_POSITION; // a runner failure sends the call back to IN_QUEUE: report that wait again
          ctx.onEvent?.({ kind: 'progress', application, requestId, status: status.status, providerPhase: 'in_progress' });
        } else if (status.status) {
          throw new FalError(`fal request ${requestId ?? ''} ended with status ${status.status}`);
        }
        if (Date.now() > deadline) {
          await cancel(submitted);
          throw new FalError(`fal request ${requestId ?? ''} timed out after ${timeout} ms (cancel requested)`);
        }
        await sleep(pollInterval, signal);
      }
      const raw = await request('GET', submitted.response_url, undefined, signal);
      ctx.onEvent?.({ kind: 'done', application, requestId, ...(metrics ? { metrics } : {}) });
      return { raw, requestId };
    } catch (e) {
      const error = e instanceof FalError ? e : new FalError(String(e));
      if (signal?.aborted) await cancel(submitted); // stop billing for a job nobody will collect
      return fail(error, metrics ? { metrics } : {});
    }
  };
}

function isRecord(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(abortError(signal));
    const t = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    function onAbort() {
      clearTimeout(t);
      reject(abortError(signal));
    }
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

/** One error for one user action, whether the abort landed during a fetch or a sleep. */
function abortError(signal?: AbortSignal): FalError {
  const reason = signal?.reason;
  return new FalError(`fal request aborted${reason instanceof Error ? `: ${reason.message}` : reason ? `: ${String(reason)}` : ''}`);
}

async function shortBody(response: Response): Promise<string> {
  try {
    const text = (await response.text()).trim();
    return text.length > 300 ? `${text.slice(0, 300)}…` : text || `HTTP ${response.status}`;
  } catch {
    return `HTTP ${response.status}`;
  }
}
