/**
 * Bijective mapping between Performance's canonical identity string
 * (`mp:v<version>:<kind>:<uuid>`) and Memory's projectKey shape
 * (`[\w][\w.-]*`, docs/IDENTITIES.md). A projectKey cannot contain a colon;
 * it can contain a dot. Since neither a Performance EntityKind value nor a
 * UUID's canonical hex-with-hyphens form ever contains a literal dot, the
 * only dots in the mapped string are exactly the three substituted colons —
 * so colon-to-dot substitution is lossless and its inverse is unambiguous.
 *
 * Scoped to PROJECT and WORKSPACE identities only: Memory scopes correspond
 * to Performance projects/workspaces, never to evidence-record identities
 * (Performance's own Observation.identity is restricted to a disjoint
 * whitelist of evidence kinds that excludes PROJECT/WORKSPACE). Ambiguity
 * stays explicit — every other kind, and every malformed input, is a typed
 * rejection, never a guess.
 *
 * No new Memory persistence is introduced: the mapped string IS the
 * projectKey `createScope` already persists verbatim, and the original
 * Performance identity is always recoverable via the inverse mapping.
 */
import { ValidationError } from "../contracts/errors.ts";

export const PERFORMANCE_IDENTITY_KINDS = ["project", "workspace"] as const;
export type PerformanceIdentityKind = (typeof PERFORMANCE_IDENTITY_KINDS)[number];

export interface ParsedPerformanceIdentity {
  kind: PerformanceIdentityKind;
  version: number;
  uuid: string;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function parseSegments(segments: string[], separatorName: string): ParsedPerformanceIdentity {
  if (segments.length !== 4) {
    throw new ValidationError(
      `Performance identity must have exactly 4 ${separatorName}-separated segments (mp, v<N>, <kind>, <uuid>), got ${segments.length}`,
    );
  }
  const [prefix, versionRaw, kind, uuid] = segments as [string, string, string, string];
  if (prefix !== "mp") {
    throw new ValidationError(`Performance identity must start with 'mp', got '${prefix}'`);
  }
  if (!/^v\d+$/.test(versionRaw)) {
    throw new ValidationError(`Performance identity version segment must match 'v<N>', got '${versionRaw}'`);
  }
  const version = Number(versionRaw.slice(1));
  if (!Number.isInteger(version) || version < 1) {
    throw new ValidationError(`Performance identity version must be a positive integer, got '${versionRaw}'`);
  }
  if (!(PERFORMANCE_IDENTITY_KINDS as readonly string[]).includes(kind)) {
    throw new ValidationError(
      `Performance identity kind '${kind}' cannot map to a Memory scope; only ${PERFORMANCE_IDENTITY_KINDS.join(", ")} are supported`,
    );
  }
  if (!UUID_RE.test(uuid)) {
    throw new ValidationError(`Performance identity value must be a canonical UUID, got '${uuid}'`);
  }
  return { kind: kind as PerformanceIdentityKind, version, uuid: uuid.toLowerCase() };
}

/** Structural parse (kind/version/uuid) without producing a projectKey. */
export function parsePerformanceIdentity(canonical: string): ParsedPerformanceIdentity {
  return parseSegments(canonical.split(":"), "colon");
}

/** `mp:v1:project:<uuid>` -> `mp.v1.project.<uuid>` (a valid Memory projectKey). */
export function projectKeyFromPerformanceIdentity(canonical: string): string {
  const parsed = parsePerformanceIdentity(canonical);
  const projectKey = canonical.replace(/:/g, ".");
  // Self-check: the transform must always land inside Memory's own projectKey
  // shape. Should be unreachable given the validation above, but guards
  // against silently producing an unusable key if that validation ever drifts.
  if (!/^[\w][\w.-]*$/.test(projectKey)) {
    throw new ValidationError(`mapped projectKey '${projectKey}' is not a valid Memory projectKey`);
  }
  void parsed;
  return projectKey;
}

/** Inverse of {@link projectKeyFromPerformanceIdentity} — recovers the exact original canonical string. */
export function performanceIdentityFromProjectKey(projectKey: string): string {
  const parsed = parseSegments(projectKey.split("."), "dot");
  return `mp:v${parsed.version}:${parsed.kind}:${parsed.uuid}`;
}
