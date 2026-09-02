/**
 * Prompt-injection and untrusted-content boundaries (Task 38).
 *
 * Stored external text (record content, subjects, tags, candidate content) is
 * treated as DATA — never as instructions. Retrieved memories cannot redefine
 * system policy, tool permissions, or promotion rules: every policy surface
 * (promotion, mutation authorization, intake authorization, content-class
 * export rules) reads only STRUCTURAL fields (sourceKind, epistemicClass,
 * evidenceRefs, actor, privacyClass, subject/content hash for repeat counting)
 * and never interprets content text.
 *
 * This module makes that boundary EXPLICIT:
 * - `asUntrustedData` labels any content handed to a host (agent/context pack)
 *   as `untrusted-data`, so the receiver treats it as data, not policy.
 * - `contentBoundaryStatus` reports the invariant and the surfaces that honor
 *   it (content-surfacing surfaces vs. policy surfaces that never read
 *   content).
 */
import type { MemoryStore } from "./store.ts";

export const CONTENT_TRUST = "untrusted-data" as const;

/** Label content as untrusted data before it leaves the engine. */
export function asUntrustedData<T>(value: T): { trust: typeof CONTENT_TRUST; data: T } {
  return { trust: CONTENT_TRUST, data: value };
}

/** Content-surfacing surfaces: they RETURN content as data (never execute it). */
export const CONTENT_SURFACES = [
  "memory.search",
  "memory.lexical",
  "memory.current",
  "memory.timeline",
  "memory.context",
  "memory.excerpts",
  "memory.fused",
  "memory.hybrid",
  "memory.ranked",
  "memory.semantic",
] as const;

/** Policy surfaces: they read STRUCTURAL fields only, never content text. */
export const POLICY_SURFACES = [
  "memory.promote (structural eligibility)",
  "memory.revise/lifecycle (attributed, non-content)",
  "memory.propose (intake authorization by caller)",
  "mutation authorization (actor keys)",
  "content-class export policy (privacyClass)",
  "promotion policies (sourceKind/epistemicClass/evidenceRefs)",
] as const;

export interface ContentBoundaryStatus {
  /** The engine's content-trust invariant. */
  trust: typeof CONTENT_TRUST;
  /** Surfaces that return content as data. */
  contentSurfaces: readonly string[];
  /** Policy surfaces that never read content text. */
  policySurfaces: readonly string[];
}

/** Report the content-trust boundary (data vs. policy). */
export function contentBoundaryStatusImpl(_store: MemoryStore): ContentBoundaryStatus {
  return {
    trust: CONTENT_TRUST,
    contentSurfaces: [...CONTENT_SURFACES],
    policySurfaces: [...POLICY_SURFACES],
  };
}