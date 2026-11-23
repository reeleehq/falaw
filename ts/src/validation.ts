/**
 * Request-shape limits a catalogue record states (`falaw.validation.check_call_arguments`):
 * `max_items` on a list argument and `min_pixels` / `max_pixels` on an explicit
 * `{width, height}` size. Throws where Python raises `ValueError`.
 */

import { FalPromptTooLong } from './errors';
import type { ModelRecord } from './generated/model-record';

/** Refuse a prompt over the model's `max_prompt_chars` (`falaw.validation.check_prompt_length`),
 *  for every operation, not only text-to-image (falaw#170). */
export function checkPromptLength(
  record: Pick<ModelRecord, 'id' | 'max_prompt_chars'>,
  prompt: string,
): void {
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
}

const isInt = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v);

export function checkCallArguments(
  record: Pick<ModelRecord, 'id' | 'param_specs'> & Partial<Pick<ModelRecord, 'max_prompt_chars'>>,
  args: Readonly<Record<string, unknown>>,
): void {
  if (typeof args.prompt === 'string') {
    checkPromptLength({ id: record.id, max_prompt_chars: record.max_prompt_chars ?? null }, args.prompt);
  }
  for (const [name, spec] of Object.entries(record.param_specs)) {
    if (!(name in args)) continue;
    const value = args[name];
    const limit = spec.max_items as number | undefined;
    if (limit !== undefined) {
      if (!Array.isArray(value)) throw new Error(`${record.id}: ${name} must be a list, got ${JSON.stringify(value)}`);
      if (value.length > limit) throw new Error(`${record.id} takes at most ${limit} ${name}, got ${value.length}`);
    }
    const low = spec.min_pixels as number | undefined;
    const high = spec.max_pixels as number | undefined;
    if ((low || high) && typeof value === 'object' && value !== null && !Array.isArray(value)) {
      const { width, height } = value as { width?: unknown; height?: unknown };
      if (!isInt(width) || !isInt(height)) {
        throw new Error(`${record.id}: ${name} needs integer width and height, got ${JSON.stringify(value)}`);
      }
      const pixels = width * height;
      if ((low && pixels < low) || (high && pixels > high)) {
        throw new Error(
          `${record.id} needs an explicit ${name} of ${low ?? 0} to ${high ?? 'unlimited'} total pixels; ${width}x${height} is ${pixels}.`,
        );
      }
    }
  }
}
