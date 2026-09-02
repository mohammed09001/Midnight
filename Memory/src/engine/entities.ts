/**
 * Entity linking as a derived, rebuildable projection (Task 22).
 *
 * Stable project entities (components, repositories, technologies, decisions)
 * are expressed as attributed `applies_to` relations targeting
 * `entity:<kind>:<name>` on canonical records (Task 21). This module builds
 * a VERSIONED entity index FROM those canonical records — a derived,
 * rebuildable projection that is NEVER canonical truth (docs/BOUNDARY.md).
 *
 * The projection:
 * - extracts every entity referenced by an `applies_to` hint in the scope,
 * - auto-links records whose subject exactly matches an entity's canonical
 *   name (deterministic corpus extraction, no LLM/embedding),
 * - groups linked records per entity with the link kind (explicit applies_to,
 *   subject auto-link, or both),
 * - reports first/last-seen instants and a version stamp so callers can
 *   detect when the projection was built.
 *
 * Rebuildable: recomputed on demand; `rebuildEntityProjection` forces a fresh
 * build and emits `memory.entities.projection.rebuilt`. Versioned: the
 * projection carries `schemaVersion` + `version` (contract version @ build
 * time) and `builtAt`.
 *
 * Research: mem0 entity-linking and getzep/graphiti's entity extraction are
 * ADAPTED in intent (stable entity identity, incremental graph links) but the
 * LLM/embedding-driven extraction is REJECTED — Memory's extraction is a
 * deterministic, self-hosted projection over canonical relations.
 */
import { MEMORY_ENGINE_CONTRACT_VERSION } from "../contracts/version.ts";
import type { EntityKind, RelationHint } from "../contracts/types.ts";
import { getScopeImpl } from "./scopes.ts";
import type { MemoryStore } from "./store.ts";

/** Known entity kinds in the bounded taxonomy (others classify as "other"). */
export const ENTITY_KINDS: readonly EntityKind[] = [
  "component",
  "repository",
  "technology",
  "decision",
];

export const ENTITY_TARGET_PREFIX = "entity:";

export interface EntityProjectionRecord {
  recordId: string;
  subject: string;
  /** How the record was linked: explicit applies_to hint, subject auto-match, or both. */
  linkKind: "applies_to" | "subject" | "both";
}

export interface EntityProjectionEntry {
  /** Canonical entity key, e.g. "component:api-gateway". */
  entity: string;
  kind: EntityKind;
  name: string;
  records: EntityProjectionRecord[];
  /** Records linked via an explicit `applies_to` hint. */
  explicitCount: number;
  /** Records linked only by subject auto-match. */
  autoCount: number;
  /** Earliest / latest valid time among the linked records. */
  firstSeenAt: string;
  lastSeenAt: string;
}

export interface EntityProjection {
  scopeId: string;
  /** Contract version @ build time — a fresh stamp per rebuild. */
  version: string;
  /** Shape version of the projection (bump on breaking shape changes). */
  schemaVersion: "1";
  builtAt: string;
  entityCount: number;
  entities: EntityProjectionEntry[];
}

/**
 * Parse a relation target into an entity reference, or null when the target
 * is not an entity reference. Accepts `entity:<kind>:<name>` (kind in the
 * bounded taxonomy) and `entity:<name>` (classified "other").
 */
export function parseEntityTarget(target: string): { kind: EntityKind; name: string } | null {
  if (typeof target !== "string" || !target.startsWith(ENTITY_TARGET_PREFIX)) return null;
  const rest = target.slice(ENTITY_TARGET_PREFIX.length);
  const parts = rest.split(":");
  let kind: EntityKind = "other";
  let name: string;
  if (parts.length >= 2 && parts[0]!.length > 0) {
    kind = (ENTITY_KINDS as readonly string[]).includes(parts[0]!)
      ? (parts[0] as EntityKind)
      : "other";
    name = parts.slice(1).join(":");
  } else {
    name = parts[0] ?? "";
  }
  if (name.length === 0) return null;
  return { kind, name };
}

interface InternalEntry {
  kind: EntityKind;
  name: string;
  records: Map<string, { recordId: string; subject: string; linkKind: "applies_to" | "subject" | "both"; observedAt: string }>;
}

function entityKey(kind: EntityKind, name: string): string {
  return `${kind}:${name}`;
}

/**
 * Monotonic in-process projection build counter. Each computation of the
 * projection gets a distinct version stamp, even within the same millisecond
 * (builtAt alone is only ms-precise). Survives restart via the builtAt stamp.
 */
let projectionBuildCounter = 0;

/**
 * Build the derived entity projection for a scope. Pure function over the
 * canonical store — never writes canonical state; the result is rebuildable.
 */
export function entityProjectionImpl(
  store: MemoryStore,
  scopeOrProjectKey: string,
): EntityProjection {
  const scope = getScopeImpl(store, scopeOrProjectKey);
  const db = store.ensureOpen();
  const rows = db
    .prepare(
      `SELECT record_id, subject, relation_hints_json, observed_at
       FROM memory_records WHERE scope_id = ? AND status != 'deleted'`,
    )
    .all(scope.scopeId) as Array<Record<string, unknown>>;
  const builtAt = new Date().toISOString();

  const map = new Map<string, InternalEntry>();
  const byName = new Map<string, string>();

  // Pass 1: explicit entity references from `applies_to` hints.
  for (const row of rows) {
    const recordId = String(row["record_id"]);
    const subject = String(row["subject"]);
    const observedAt = String(row["observed_at"] ?? "");
    const hints = JSON.parse(String(row["relation_hints_json"])) as RelationHint[];
    for (const hint of hints) {
      if (hint.type !== "applies_to") continue;
      const parsed = parseEntityTarget(hint.target);
      if (parsed === null) continue;
      const key = entityKey(parsed.kind, parsed.name);
      let entry = map.get(key);
      if (entry === undefined) {
        entry = { kind: parsed.kind, name: parsed.name, records: new Map() };
        map.set(key, entry);
      }
      const existing = entry.records.get(recordId);
      entry.records.set(recordId, {
        recordId,
        subject,
        linkKind: existing?.linkKind === "subject" ? "both" : "applies_to",
        observedAt,
      });
      byName.set(parsed.name, key);
    }
  }

  // Pass 2: auto-link records whose subject exactly matches an entity name.
  for (const row of rows) {
    const recordId = String(row["record_id"]);
    const subject = String(row["subject"]);
    const observedAt = String(row["observed_at"] ?? "");
    const key = byName.get(subject);
    if (key === undefined) continue;
    const entry = map.get(key)!;
    const existing = entry.records.get(recordId);
    entry.records.set(recordId, {
      recordId,
      subject,
      linkKind: existing !== undefined ? "both" : "subject",
      observedAt,
    });
  }

  const entities: EntityProjectionEntry[] = [...map.entries()]
    .sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
    .map(([entity, entry]) => {
      const records = [...entry.records.values()].sort((a, b) =>
        a.recordId < b.recordId ? -1 : a.recordId > b.recordId ? 1 : 0,
      );
      const instants = records.map((r) => r.observedAt).filter((t) => t.length > 0);
      const sorted = [...instants].sort();
      let explicitCount = 0;
      let autoCount = 0;
      for (const r of records) {
        if (r.linkKind !== "subject") explicitCount++;
        if (r.linkKind !== "applies_to") autoCount++;
      }
      return {
        entity,
        kind: entry.kind,
        name: entry.name,
        records: records.map(({ recordId, subject, linkKind }) => ({ recordId, subject, linkKind })),
        explicitCount,
        autoCount,
        firstSeenAt: sorted[0] ?? builtAt,
        lastSeenAt: sorted[sorted.length - 1] ?? builtAt,
      };
    });

  return {
    scopeId: scope.scopeId,
    version: `${MEMORY_ENGINE_CONTRACT_VERSION}.p${++projectionBuildCounter}@${builtAt}`,
    schemaVersion: "1",
    builtAt,
    entityCount: entities.length,
    entities,
  };
}

/**
 * Force a fresh build of the entity projection (the recovery/observability
 * path — the projection is always computed from canonical truth, so a rebuild
 * simply re-derives it and records the event).
 */
export function rebuildEntityProjectionImpl(
  store: MemoryStore,
  scopeOrProjectKey: string,
): EntityProjection {
  const projection = entityProjectionImpl(store, scopeOrProjectKey);
  store.appendEvent("memory.entities.projection.rebuilt", {
    scopeId: projection.scopeId,
    version: projection.version,
  });
  return projection;
}