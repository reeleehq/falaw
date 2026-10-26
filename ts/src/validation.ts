/**
 * Request-shape limits a catalogue record states (`falaw.validation.check_call_arguments`):
 * `max_items` on a list argument and `min_pixels` / `max_pixels` on an explicit
 * `{width, height}` size. Throws where Python raises `ValueError`.
 */

import type { ModelRecord } from './generated/model-record';

const isInt = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v);

export function checkCallArguments(
  record: Pick<ModelRecord, 'id' | 'param_specs'>,
  args: Readonly<Record<string, unknown>>,
): void {
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
