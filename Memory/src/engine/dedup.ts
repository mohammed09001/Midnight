/**
 * Deduplication and near-duplicate handling (Task 18).
 *
 * Detect exact and normalized duplicate proposals, preserve idempotency, and
 * distinguish duplicate content from independently corroborating evidence.
 *
 * - Exact duplicate: identical normalized content (same content hash) in the
 *   same scope.
 * - Normalized / near-duplicate: same normalized subject with high token-set
 *   overlap in content (deterministic Jaccard on the unicode token set).
 * - Corroborating evidence: same subject but genuinely DISTINCT content whose
 *   evidence references differ from the existing record — independent
 *   corroboration, NOT a duplicate to collapse.
 *
 * Idempotency is preserved by the existing replay-safe machinery
 * (idempotencyKey + content hash, docs/PERSISTENCE.md); this module ADDS
 * explicit duplicate detection and duplicate-vs-corroboration classification.
 *
 * Provider-free: near-duplicate similarity is token-based and deterministic.
 * Research: mem0's embedding-based dedup ADAPTED in intent but the embedding
 * provider dependency is REJECTED here — a small Library-owned token/Jaccard
 * matcher is clearer and self-hosted (main @ 2026-08-30).
 */
import type { EvidenceRef, MemoryCandidate } from "../contracts/types.ts";
import { ValidationError } from "../contracts/errors.ts";
import { normalizeText } from "./normalize.ts";
import { contentHashOf } from "./ids.ts";
import { getScopeImpl } from "./scopes.ts";
import { rowToCandidate, rowToRecord } from "./records.ts";
import type { MemoryStore } from "./store.ts";

/** Token Jaccard similarity at/above which content is a near-duplicate. */
export const NEAR_DUPLICATE_THRESHOLD = 0.85;
export type DuplicateKind = "exact" | "normalized" | "near" | "corroborating" | "independent";

export interface DuplicateMatch {
  recordId: string;
  kind: DuplicateKind;
  /** Always true for subject-scoped matches (subject is the join key). */
  sameSubject: boolean;
  /** Content token Jaccard similarity in [0,1]. */
  similarity: number;
  /** Shared evidence refs between the two sources. */
  sharedEvidenceRefs: string[];
  /** Distinct (non-shared) evidence refs on the existing record. */
  distinctEvidenceRefs: string[];
}

export interface DuplicateAnalysis {
  /** Scope analyzed (scope id). */
  scopeId: string;
  /** The normalized subject that was matched against. */
  subject: string;
  /** Content hash of the proposed/normalized content (for exact detection). */
  contentHash: string;
  /** Every record in the scope that matched by subject, classified. */
  matches: DuplicateMatch[];
  /** True when an exact or near duplicate exists — the proposal is redundant. */
  isDuplicate: boolean;
  /** Records that independently corroborate the claim (distinct evidence). */
  corroborating: string[];
  /** Human-readable summary of the classification. */
  summary: string;
}

/** Split normalized text into a deterministic unicode token set (lowercased). */
export function tokenSet(text: string): Set<string> {
  const normalized = normalizeText(text);
  const tokens = normalized
    .toLowerCase()
    .split(/[^\p{L}\p{N}_]+/u)
    .map((t) => t.trim())
    .filter((t) => t.length > 0);
  return new Set(tokens);
}

/** Deterministic Jaccard similarity between two texts' token sets, in [0,1]. */
export function jaccardSimilarity(a: string, b: string): number {
  const setA = tokenSet(a);
  const setB = tokenSet(b);
  if (setA.size === 0 || setB.size === 0) return 0;
  let intersection = 0;
  for (const token of setA) {
    if (setB.has(token)) intersection++;
  }
  const union = setA.size + setB.size - intersection;
  return union === 0 ? 0 : intersection / union;
}

function evidenceKey(ref: EvidenceRef): string {
  return `${ref.engine}:${ref.ref}`;
}

function analyze(
  store: MemoryStore,
  scopeOrProjectKey: string,
  subject: string,
  content: string,
  proposedEvidence: EvidenceRef[] = [],
): DuplicateAnalysis {
  if (typeof subject !== "string" || subject.trim().length === 0) {
    throw new ValidationError("subject is required for duplicate analysis");
  }
  if (typeof content !== "string" || content.trim().length === 0) {
    throw new ValidationError("content is required for duplicate analysis");
  }
  const scope = getScopeImpl(store, scopeOrProjectKey);
  const db = store.ensureOpen();
  const normalizedSubject = normalizeText(subject);
  const normalizedContent = normalizeText(content);
  const hash = contentHashOf(normalizedContent);

  const rows = db
    .prepare(
      "SELECT * FROM memory_records WHERE scope_id = ? AND subject = ? AND status != 'deleted'",
    )
    .all(scope.scopeId, normalizedSubject) as Array<Record<string, unknown>>;

  const proposedKeys = new Set(proposedEvidence.map(evidenceKey));
  const matches: DuplicateMatch[] = rows.map((row) => {
    const record = rowToRecord(row);
    const similarity = jaccardSimilarity(record.content, normalizedContent);
    const existingKeys = record.evidenceRefs.map(evidenceKey);
    const shared = existingKeys.filter((k) => proposedKeys.has(k));
    const distinct = existingKeys.filter((k) => !proposedKeys.has(k));

    let kind: DuplicateKind;
    if (record.contentHash === hash) {
      kind = "exact";
    } else if (similarity >= NEAR_DUPLICATE_THRESHOLD) {
      kind = "normalized";
    } else if (similarity >= 0.6) {
      kind = "near";
    } else if (similarity > 0 && distinct.length > 0) {
      // Independently corroborating requires the existing record to carry its
      // own (distinct) evidence basis — otherwise there is nothing to
      // corroborate against.
      kind = "corroborating";
    } else {
      kind = "independent";
    }
    return {
      recordId: record.recordId,
      kind,
      sameSubject: true,
      similarity,
      sharedEvidenceRefs: shared,
      distinctEvidenceRefs: distinct,
    };
  });

  const isDuplicate = matches.some((m) => m.kind === "exact" || m.kind === "normalized" || m.kind === "near");
  const corroborating = matches
    .filter((m) => m.kind === "corroborating")
    .map((m) => m.recordId);

  let summary: string;
  if (isDuplicate) {
    summary = `duplicate: ${matches.filter((m) => m.kind === "exact" || m.kind === "normalized" || m.kind === "near").length} existing record(s) carry the same or near-identical content`;
  } else if (corroborating.length > 0) {
    summary = `corroborating: ${corroborating.length} record(s) independently corroborate this subject with distinct evidence`;
  } else {
    summary = "independent: no duplicate or corroborating record found for this subject";
  }

  return {
    scopeId: scope.scopeId,
    subject: normalizedSubject,
    contentHash: hash,
    matches,
    isDuplicate,
    corroborating,
    summary,
  };
}

/** Analyze a proposed (subject, content, evidence) against the existing corpus. */
export function analyzeProposalImpl(
  store: MemoryStore,
  scopeOrProjectKey: string,
  proposal: { subject: string; content: string; evidenceRefs?: EvidenceRef[] },
): DuplicateAnalysis {
  return analyze(store, scopeOrProjectKey, proposal.subject, proposal.content, proposal.evidenceRefs ?? []);
}

/**
 * Scan a scope's open candidate stream for exact/near duplicates against
 * BOTH other open candidates and promoted records. Used to surface duplicate
 * proposals before they are promoted (append-oriented: nothing is deleted;
 * duplicates are reported, not silently dropped).
 */
export function findCandidateDuplicatesImpl(
  store: MemoryStore,
  scopeOrProjectKey: string,
  filter: { status?: MemoryCandidate["status"] | "all"; limit?: number } = {},
): Array<{ candidate: MemoryCandidate; analysis: DuplicateAnalysis }> {
  const scope = getScopeImpl(store, scopeOrProjectKey);
  const db = store.ensureOpen();
  const status = filter.status === undefined ? "open" : filter.status;
  const rows = db
    .prepare(
      "SELECT * FROM memory_candidates WHERE scope_id = ? AND (? = 'all' OR status = ?) ORDER BY created_at ASC, candidate_id ASC LIMIT ?",
    )
    .all(
      scope.scopeId,
      status,
      status,
      Math.min(Math.max(filter.limit ?? 100, 1), 1000),
    ) as Array<Record<string, unknown>>;
  return rows.map((row) => {
    const candidate = rowToCandidate(row);
    return {
      candidate,
      analysis: analyze(store, scope.scopeId, candidate.subject, candidate.content, candidate.evidenceRefs),
    };
  });
}
