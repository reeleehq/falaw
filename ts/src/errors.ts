/**
 * The error tree, mirroring the part of `falaw.errors` the browser side needs.
 * Key values never appear in a message.
 */

export class FalError extends Error {
  constructor(
    message: string,
    readonly status: number | null = null,
  ) {
    super(status !== null ? `${message} (HTTP ${status})` : message);
    this.name = new.target.name;
  }
}

/** An argument cannot be canonicalised into falaw's hashed JSON form.
 *  Deliberately loud: a hashing function that guesses is one that collides. */
export class FalNonCanonicalArgument extends FalError {
  constructor(
    message: string,
    readonly path: string,
  ) {
    super(message);
  }
}

/** The prompt exceeds the model's hard length cap (`falaw.errors.FalPromptTooLong`):
 *  refused before any call is queued. `limit` and `length` are in characters. */
export class FalPromptTooLong extends FalError {
  constructor(
    message: string,
    readonly model: string,
    readonly limit: number,
    readonly length: number,
  ) {
    super(message);
  }
}

/** A model id (or alias) the catalogue does not know. */
export class UnknownModelError extends FalError {}
