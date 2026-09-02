/**
 * Stable identity generation for the Memory Engine.
 *
 * - Prefixed ULIDs (`mem_`, `cand_`, `evt_`, `ctg_`) are time-sortable,
 *   globally unique, and independent of any filesystem path or client
 *   restart.
 * - Scope ids (`scp_`) are DERIVED deterministically from the caller-chosen
 *   `projectKey` via SHA-256, so the same project key always yields the same
 *   scope id across restarts, machines, and project-path moves.
 *
 * ULID shape follows the ULID specification (github.com/ulid/spec):
 * 26 characters, Crockford base32 alphabet excluding I/L/O/U,
 * 48-bit millisecond timestamp + 80 bits of randomness, with in-process
 * monotonic increment when generated within the same millisecond.
 */
import { createHash, randomBytes } from "node:crypto";

const ENCODING = "0123456789ABCDEFGHJKMNPQRSTVWXYZ" as const;
const TIME_LEN = 10;
const RANDOM_LEN = 16;

export type IdPrefix = "mem" | "cand" | "evt" | "ctg" | "scp" | "ses";

function encodeTime(timeMs: number): string {
  if (timeMs < 0 || !Number.isSafeInteger(timeMs)) {
    throw new Error(`ULID timestamp out of range: ${timeMs}`);
  }
  let out = "";
  for (let i = TIME_LEN - 1; i >= 0; i--) {
    out = ENCODING[timeMs % 32]! + out;
    timeMs = Math.floor(timeMs / 32);
  }
  return out;
}

function encodeRandom(bytes: Uint8Array): string {
  // All 80 bits of randomness -> exactly 16 Crockford-base32 chars,
  // big-endian 5-bit groups (so +1 increments preserve lexicographic order).
  let value = 0n;
  for (const byte of bytes) {
    value = (value << 8n) | BigInt(byte);
  }
  let out = "";
  for (let i = 0; i < RANDOM_LEN; i++) {
    out = ENCODING[Number(value & 31n)]! + out;
    value >>= 5n;
  }
  return out;
}

let lastTime = -1;
let lastRandom = 0n;

/** Monotonic ULID (26 chars). Unique and increasing within this process. */
export function ulid(now: number = Date.now()): string {
  let random: bigint;
  if (now === lastTime) {
    random = lastRandom + 1n;
    if (random >= 1n << 80n) {
      // Randomness overflow: advance to next millisecond.
      now = now + 1;
      random = BigInt("0x" + randomBytes(10).toString("hex"));
    }
  } else {
    random = BigInt("0x" + randomBytes(10).toString("hex"));
  }
  lastTime = now;
  lastRandom = random;
  const bytes = Buffer.alloc(10);
  for (let shift = 72n, i = 0; i < 10; i++, shift -= 8n) {
    bytes[i] = Number((random >> shift) & 0xffn);
  }
  return encodeTime(now) + encodeRandom(bytes);
}

/** Prefixed, time-sortable engine identity, e.g. `mem_01J...`. */
export function newId(prefix: IdPrefix): string {
  return `${prefix}_${ulid()}`;
}

/**
 * Deterministic scope identity: `scp_` + first 128 bits of
 * SHA-256(UTF-8 projectKey), encoded as 26 Crockford-base32 chars.
 * Stable across restarts, machines, and project-path moves; the project
 * key is the caller-owned stable identity contract, never a path.
 */
export function scopeIdFromProjectKey(projectKey: string): string {
  const digest = createHash("sha256").update(projectKey, "utf8").digest();
  let bits = BigInt("0x" + digest.subarray(0, 16).toString("hex"));
  let out = "";
  for (let i = 0; i < 26; i++) {
    out = ENCODING[Number(bits % 32n)]! + out;
    bits /= 32n;
  }
  return `scp_${out}`;
}

const ULID_RE = /^[0-9ABCDEFGHJKMNPQRSTVWXYZ]{26}$/;

export function isUlidShaped(value: string): boolean {
  return ULID_RE.test(value);
}

/** Canonical actor identity string used inside provenance. */
export function actorKey(actor: { kind: string; name: string }): string {
  return `${actor.kind}:${actor.name.trim()}`;
}

export function contentHashOf(normalizedContent: string): string {
  return createHash("sha256").update(normalizedContent, "utf8").digest("hex");
}
