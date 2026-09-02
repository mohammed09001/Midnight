/**
 * Contradiction/supersession qualification over the frozen corpus (Task 44,
 * Phase VIII).
 *
 * Proves the lineage invariants that make non-destructive Memory trustworthy:
 *
 * - HISTORICAL FACTS REMAIN QUERYABLE: superseded records are retrievable
 *   as-of their own capture time, through the immutable revision chain, the
 *   decision timeline, and lexical search (status-filtered) — retirement
 *   never means disappearance.
 * - CURRENT TRUTH RESOLVES CORRECTLY: the current view exposes exactly the
 *   winning versions; a resolved contradiction group leaves the winner
 *   active, the losers retired, and no open groups behind.
 * - NO DESTRUCTIVE OVERWRITE: every superseded/retired record keeps its
 *   original content with a matching canonical content hash, and its
 *   retirement reason is recorded on the record itself — verified across
 *   the WHOLE corpus by recomputing every record's hash.
 *
 * The checks run over the frozen qualification corpus (docs/CORPORA.md) and
 * are deterministic: subject-keyed, pinned or store-derived instants, no
 * volatile fields in the report.
 */
import type { MemoryEngine } from "./memoryEngine.ts";
import { QUALIFICATION_CORPUS_SCOPE_KEY, QUALIFICATION_CORPUS_VERSION, type QualificationCheck } from "./corpora.ts";
import { contentHashOf } from "./ids.ts";
import type { MemoryRecord } from "../contracts/types.ts";

const AUTH_V1 = "Auth provider is Auth0 with RS256";
const AUTH_V2 = "Auth provider is Clerk with RS256";
const SESSIONS_LOSER = "Maximum 100 concurrent sessions per project";
const SESSIONS_WINNER = "Maximum 250 concurrent sessions per project";
const RESOLUTION_REASON = "corpus: 250 is the ratified limit";
const SUPERSESSION_REASON = "migrated auth providers";

function check(name: string, pass: boolean, detail: string): QualificationCheck {
  return { name, pass, detail };
}

export interface LineageQualificationReport {
  corpusVersion: typeof QUALIFICATION_CORPUS_VERSION;
  contractVersion: string;
  scopeKey: typeof QUALIFICATION_CORPUS_SCOPE_KEY;
  checks: QualificationCheck[];
  passed: boolean;
}

function sortedContents(records: Array<{ content: string }>): string[] {
  return records.map((r) => r.content).sort();
}

/**
 * Qualify contradiction/supersession behavior over the frozen corpus.
 * Builds the corpus first when missing (replay-safe). Read-only afterwards.
 */
export function qualifyContradictionSupersessionImpl(engine: MemoryEngine): LineageQualificationReport {
  const scopeKey = QUALIFICATION_CORPUS_SCOPE_KEY;
  const checks: QualificationCheck[] = [];

  let marker: MemoryRecord | undefined;
  try {
    marker = engine
      .searchRecords({ scope: scopeKey, exactSubject: "Qualification corpus marker" })
      .find((r) => r.status !== "deleted");
  } catch {
    marker = undefined;
  }
  if (marker === undefined) {
    engine.buildQualificationCorpus();
  }

  const allRecords = () => engine.searchRecords({ scope: scopeKey, status: "all" });

  // ---- supersession chain integrity ----
  const authAll = allRecords().filter((r) => r.subject === "Auth provider");
  const authV1 = authAll.find((r) => r.status === "superseded");
  const authV2 = authAll.find((r) => r.status === "active");
  {
    let ok = authV1 !== undefined && authV2 !== undefined;
    let detail = "chain incomplete";
    if (ok) {
      const history = engine.getRecordHistory(authV2!.recordId);
      ok =
        history.chain.length === 2 &&
        history.chain[0]!.content === AUTH_V1 &&
        history.chain[1]!.content === AUTH_V2 &&
        history.chain[0]!.supersededReason === SUPERSESSION_REASON;
      detail = `chain length ${history.chain.length}`;
    }
    checks.push(check("chain-integrity", ok, detail));
  }

  // ---- predecessor immutability (content, canonical hash, retirement reason) ----
  {
    let ok = false;
    let detail = "predecessor missing";
    if (authV1 !== undefined) {
      const recomputed = contentHashOf(authV1.content);
      ok =
        authV1.content === AUTH_V1 &&
        authV1.contentHash === recomputed &&
        authV1.supersededReason === SUPERSESSION_REASON &&
        authV1.supersededById === authV2?.recordId;
      detail = ok
        ? "v1 content/hash intact; retirement reason and successor recorded"
        : "predecessor was destructively altered";
    }
    checks.push(check("predecessor-immutability", ok, detail));
  }

  // ---- resolution non-destructiveness ----
  {
    const sessionsAll = allRecords().filter((r) => r.subject === "Max concurrent sessions");
    const loser = sessionsAll.find((r) => r.content === SESSIONS_LOSER);
    const winner = sessionsAll.find((r) => r.content === SESSIONS_WINNER);
    let ok = loser !== undefined && winner !== undefined;
    let detail = "resolution records missing";
    if (ok && loser !== undefined && winner !== undefined) {
      const resolvedEvent = engine
        .listEvents(500)
        .find((e) => e.type === "memory.contradiction.resolved");
      const resolution = (resolvedEvent?.payload ?? {}) as {
        winnerRecordId?: string;
        reason?: string;
        action?: string;
      };
      ok =
        loser.status === "superseded" &&
        loser.contentHash === contentHashOf(loser.content) &&
        loser.supersededById === winner.recordId &&
        winner.status === "active" &&
        resolution.winnerRecordId === winner.recordId &&
        resolution.reason === RESOLUTION_REASON &&
        resolution.action === "supersede";
      detail = ok
        ? "loser retired intact with reason; winner active; resolution attributed"
        : "resolution altered record history";
    }
    checks.push(check("resolution-non-destructive", ok, detail));
  }

  // ---- historical facts remain queryable ----
  {
    let ok = false;
    let detail = "chain incomplete";
    if (authV1 !== undefined && authV2 !== undefined) {
      const asOfV1 = engine
        .queryRecordsAsOf({ scope: scopeKey, asOf: authV1.createdAt })
        .filter((r) => r.subject === "Auth provider");
      const lexicalHistorical = engine
        .lexicalSearch("Auth0", { scope: scopeKey, status: "all" })
        .hits.map((h) => h.record);
      const timeline = engine.decisionTimeline(scopeKey, "Auth provider");
      ok =
        asOfV1.length === 1 &&
        asOfV1[0]!.content === AUTH_V1 &&
        lexicalHistorical.some((r) => r.content === AUTH_V1) &&
        timeline.length === 2 &&
        JSON.stringify(sortedContents(timeline)) === JSON.stringify([AUTH_V1, AUTH_V2]);
      detail = ok
        ? "as-of, lexical (status-filtered), and timeline all expose history"
        : "a historical surface lost the superseded fact";
    }
    checks.push(check("historical-queryable", ok, detail));
  }

  // ---- current truth resolves correctly ----
  {
    let ok = false;
    let detail = "records missing";
    if (authV2 !== undefined) {
      const currentAuth = engine.currentRecords({
        scope: scopeKey,
        at: "2026-07-01T00:00:00.000Z",
        subject: "Auth provider",
      });
      const currentSessions = engine.currentRecords({
        scope: scopeKey,
        at: "2026-07-01T00:00:00.000Z",
        subject: "Max concurrent sessions",
      });
      const openGroups = engine.listOpenContradictions(scopeKey);
      ok =
        currentAuth.length === 1 &&
        currentAuth[0]!.content === AUTH_V2 &&
        currentSessions.length === 1 &&
        currentSessions[0]!.content === SESSIONS_WINNER &&
        openGroups.length === 0;
      detail = ok
        ? "current view exposes exactly the winning versions; no open groups"
        : "current truth diverges from the resolved winners";
    }
    checks.push(check("current-truth-resolves", ok, detail));
  }

  // ---- no destructive overwrite anywhere in the corpus ----
  {
    const records = allRecords();
    const hashMismatches = records.filter((r) => r.contentHash !== contentHashOf(r.content));
    const frozenRetired = records.filter(
      (r) =>
        (r.subject === "Auth provider" && r.status === "superseded") ||
        (r.subject === "Max concurrent sessions" && r.status === "superseded"),
    );
    const retiredIntact = frozenRetired.every(
      (r) => r.content === AUTH_V1 || r.content === SESSIONS_LOSER,
    );
    const ok = hashMismatches.length === 0 && retiredIntact;
    checks.push(
      check(
        "no-destructive-overwrite",
        ok,
        `${records.length} record(s) hash-verified, ${hashMismatches.length} mismatch(es), retired-retained ${retiredIntact}`,
      ),
    );
  }

  return {
    corpusVersion: QUALIFICATION_CORPUS_VERSION,
    contractVersion: engine.contractVersion,
    scopeKey,
    checks,
    passed: checks.every((c) => c.pass),
  };
}
