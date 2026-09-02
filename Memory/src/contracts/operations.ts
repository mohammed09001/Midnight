/**
 * Versioned Memory inter-engine contracts (Task 6).
 *
 * Sibling engines call Memory ONLY through these named operations via the
 * envelope dispatcher (`src/engine/dispatcher.ts`). No caller may read the
 * Memory store directly — the store file is private to this engine and the
 * public module surface (`src/index.ts`) never exposes it.
 *
 * Versioning policy: the envelope carries contractVersion. Callers are
 * accepted while the MAJOR matches; additive changes bump minor, breaking
 * changes bump major and reject old callers with MEMORY_CONTRACT_MISMATCH.
 */
import type { MEMORY_ENGINE_CONTRACT_VERSION } from "./version.ts";

export const MEMORY_OPERATIONS = [
  "memory.search",
  "memory.get",
  "memory.propose",
  "memory.promote",
  "memory.revise",
  "memory.related",
  "memory.history",
  "memory.explain",
  "memory.candidates",
  "memory.contradictions",
  "memory.lifecycle",
  "memory.lexical",
  "memory.current",
  "memory.timeline",
  "memory.ranked",
  "memory.duplicates",
  "memory.fused",
  "memory.relation",
  "memory.entities",
  "memory.embeddings",
  "memory.semantic",
  "memory.graph",
  "memory.hybrid",
  "memory.projections",
  "memory.performance.propose",
  "memory.study.propose",
  "memory.analysis.propose",
  "memory.search.session",
  "memory.context",
  "memory.user.note",
  "memory.excerpts",
  "memory.privacy",
  "memory.trust",
  "memory.backup",
  "memory.health",
] as const;

export type MemoryOperation = (typeof MEMORY_OPERATIONS)[number];

/** Versioned request envelope — the ONLY way in. */
export interface MemoryRequestEnvelope {
  contractVersion: string;
  operation: MemoryOperation;
  request: unknown;
}

export type MemoryResponseEnvelope =
  | {
      ok: true;
      contractVersion: string;
      operation: MemoryOperation;
      result: unknown;
    }
  | {
      ok: false;
      contractVersion: string;
      operation: MemoryOperation | null;
      error: { code: string; message: string };
    };

export function isMemoryOperation(value: unknown): value is MemoryOperation {
  return (
    typeof value === "string" &&
    (MEMORY_OPERATIONS as readonly string[]).includes(value)
  );
}
