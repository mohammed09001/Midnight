/**
 * Contract dispatcher (Task 6) — the single owner of the versioned
 * inter-engine call envelope. Every external caller (sibling engine, agent,
 * CLI) enters through `dispatch`; nobody touches the Memory store directly.
 */
import { isMemoryOperation, type MemoryOperation, type MemoryRequestEnvelope, type MemoryResponseEnvelope } from "../contracts/operations.ts";
import { ContractMismatchError, MemoryEngineError, ValidationError } from "../contracts/errors.ts";
import { MEMORY_ENGINE_CONTRACT_VERSION } from "../contracts/version.ts";
import type { ActorInput, RecordInput } from "./records.ts";
import type { MemoryEngine } from "./memoryEngine.ts";
import { relatedImpl } from "./relations.ts";

function majorOf(version: string): string {
  return version.split(".")[0] ?? version;
}

function requireObject(request: unknown): Record<string, unknown> {
  if (request === null || typeof request !== "object" || Array.isArray(request)) {
    throw new ValidationError("request must be a JSON object");
  }
  return request as Record<string, unknown>;
}

function requireString(request: Record<string, unknown>, field: string): string {
  const value = request[field];
  if (typeof value !== "string" || value.length === 0) {
    throw new ValidationError(`request.${field} must be a non-empty string`);
  }
  return value;
}

/**
 * Dispatch a versioned contract call. Never throws: failures are returned
 * as typed error envelopes so remote/engine callers can inspect codes.
 */
export function dispatch(
  engine: MemoryEngine,
  envelope: MemoryRequestEnvelope,
): MemoryResponseEnvelope {
  try {
    if (!isMemoryOperation(envelope.operation)) {
      return {
        ok: false,
        contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
        operation: null,
        error: {
          code: "MEMORY_VALIDATION_FAILED",
          message: `unknown operation '${String(envelope.operation)}'; supported: memory.search, memory.get, memory.propose, memory.promote, memory.revise, memory.related, memory.history, memory.explain`,
        },
      };
    }
    if (majorOf(envelope.contractVersion) !== majorOf(MEMORY_ENGINE_CONTRACT_VERSION)) {
      throw new ContractMismatchError(
        `caller contractVersion '${envelope.contractVersion}' is incompatible with engine contract '${MEMORY_ENGINE_CONTRACT_VERSION}' (major must match)`,
      );
    }
    const request = requireObject(envelope.request);
    const result = route(engine, envelope.operation, request);
    return {
      ok: true,
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: envelope.operation,
      result,
    };
  } catch (err) {
    const code = err instanceof MemoryEngineError ? err.code : "MEMORY_ENGINE_UNEXPECTED";
    return {
      ok: false,
      contractVersion: MEMORY_ENGINE_CONTRACT_VERSION,
      operation: isMemoryOperation(envelope.operation) ? envelope.operation : null,
      error: {
        code,
        message: err instanceof Error ? err.message : String(err),
      },
    };
  }
}

function route(
  engine: MemoryEngine,
  operation: MemoryOperation,
  request: Record<string, unknown>,
): unknown {
  switch (operation) {
    case "memory.search": {
      const asOf = request["asOf"];
      if (asOf !== undefined && asOf !== null) {
        return engine.queryRecordsAsOfTraced({
          scope: request["scope"] as string | undefined,
          asOf: asOf as string,
          includeRetracted: request["includeRetracted"] as boolean | undefined,
          limit: request["limit"] as number | undefined,
        });
      }
      return engine.searchRecordsTraced({
        scope: request["scope"] as string | undefined,
        kind: request["kind"] as RecordInput["kind"] | undefined,
        status: request["status"] as never,
        subjectContains: request["subjectContains"] as string | undefined,
        contentContains: request["contentContains"] as string | undefined,
        tag: request["tag"] as string | undefined,
        limit: request["limit"] as number | undefined,
        // Task 14: structured-filter retrieval.
        exactSubject: request["exactSubject"] as string | undefined,
        sourceEngine: request["sourceEngine"] as string | undefined,
        actor: request["actor"] as string | undefined,
        confidenceMin: request["confidenceMin"] as number | undefined,
        confidenceMax: request["confidenceMax"] as number | undefined,
        validAt: request["validAt"] as string | undefined,
        createdAfter: request["createdAfter"] as string | undefined,
        createdBefore: request["createdBefore"] as string | undefined,
        observedAfter: request["observedAfter"] as string | undefined,
        observedBefore: request["observedBefore"] as string | undefined,
      });
    }
    case "memory.lexical": {
      return engine.lexicalSearch(requireString(request, "query"), {
        scope: request["scope"] as string | undefined,
        status: request["status"] as never,
        limit: request["limit"] as number | undefined,
      });
    }
    case "memory.current": {
      return engine.currentRecordsTraced({
        scope: requireString(request, "scope"),
        subject: request["subject"] as string | undefined,
        at: request["at"] as string | undefined,
        limit: request["limit"] as number | undefined,
      });
    }
    case "memory.timeline": {
      return {
        timeline: engine.decisionTimeline(
          requireString(request, "scope"),
          requireString(request, "subject"),
        ),
      };
    }
    case "memory.ranked": {
      return engine.rankedSearch(requireString(request, "query"), {
        scope: request["scope"] as string | undefined,
        limit: request["limit"] as number | undefined,
        at: request["at"] as string | undefined,
      });
    }
    case "memory.duplicates": {
      return {
        analysis: engine.analyzeDuplicates(
          requireString(request, "scope"),
          {
            subject: requireString(request, "subject"),
            content: requireString(request, "content"),
            evidenceRefs: request["evidenceRefs"] as never,
          },
        ),
      };
    }
    case "memory.fused": {
      return engine.fusedSearch(requireString(request, "query"), {
        scope: request["scope"] as string | undefined,
        exactSubject: request["exactSubject"] as string | undefined,
        tag: request["tag"] as string | undefined,
        kind: request["kind"] as never,
        limit: request["limit"] as number | undefined,
        at: request["at"] as string | undefined,
        weights: request["weights"] as never,
      });
    }
    case "memory.get":
      return { record: engine.getRecord(requireString(request, "recordId")) };
    case "memory.propose": {
      const candidate = engine.addCandidate({
        scope: requireString(request, "scope"),
        kind: request["kind"] as RecordInput["kind"],
        subject: requireString(request, "subject"),
        content: requireString(request, "content"),
        actor: request["actor"] as ActorInput,
        method: requireString(request, "method"),
        epistemicClass: request["epistemicClass"] as RecordInput["epistemicClass"],
        confidence: request["confidence"] as number,
        evidenceRefs: request["evidenceRefs"] as RecordInput["evidenceRefs"],
        tags: request["tags"] as string[] | undefined,
        sourceKind: request["sourceKind"] as RecordInput["sourceKind"],
        derivedFrom: request["derivedFrom"] as RecordInput["derivedFrom"],
        // Task 8 intake pipeline fields.
        reason: requireString(request, "reason"),
        caller: request["caller"] as ActorInput | undefined,
        idempotencyKey: request["idempotencyKey"] as string | undefined,
      });
      return { candidate };
    }
    case "memory.promote": {
      const actor = request["actor"] as ActorInput;
      if (actor === null || typeof actor !== "object") {
        throw new ValidationError(
          "request.actor is required: promotions are attributed decisions (agents cannot promote)",
        );
      }
      const record = engine.promoteCandidate(requireString(request, "candidateId"), {
        actor,
        policy: request["policy"] as never,
        origin: (request["origin"] as string | undefined) ?? "contract",
      });
      return { record };
    }
    case "memory.candidates": {
      const status = request["status"] as never;
      return {
        candidates: engine.listCandidates({
          scope: request["scope"] as string | undefined,
          status,
          limit: request["limit"] as number | undefined,
        }),
      };
    }
    case "memory.contradictions": {
      const scope = request["scope"] as string | undefined;
      if (scope === undefined) {
        throw new ValidationError("request.scope is required for memory.contradictions");
      }
      return {
        pairs: engine.detectContradictions(scope),
        openGroups: engine.listOpenContradictions(scope),
      };
    }
    case "memory.lifecycle": {
      const action = requireString(request, "action");
      const actor = request["actor"] as ActorInput;
      if (actor === null || typeof actor !== "object") {
        throw new ValidationError("request.actor is required: lifecycle decisions are attributed");
      }
      const reason = requireString(request, "reason");
      const origin = (request["origin"] as string | undefined) ?? "contract";
      switch (action) {
        case "archive":
          return { record: engine.archiveRecord(requireString(request, "recordId"), { actor, reason, origin }) };
        case "restore":
          return { record: engine.restoreRecord(requireString(request, "recordId"), { actor, reason, origin }) };
        case "delete":
          return { record: engine.deleteRecord(requireString(request, "recordId"), { actor, reason, origin }) };
        case "purge":
          return engine.purgeRecord(requireString(request, "recordId"), { actor, reason, origin });
        case "purgeByPrivacy":
          return engine.purgeByPrivacy({
            actor,
            reason,
            privacyClasses: request["privacyClasses"] as never,
            scope: request["scope"] as string | undefined,
            origin,
          });
        case "deleteScope":
          return {
            scope: engine.deleteScope(requireString(request, "scope"), {
              actor,
              reason,
              mode: request["mode"] as never,
              origin,
            }),
          };
        default:
          throw new ValidationError(
            "action must be one of archive, restore, delete, purge, purgeByPrivacy, deleteScope",
          );
      }
    }
    case "memory.revise": {
      const actor = request["actor"] as ActorInput;
      if (actor === null || typeof actor !== "object") {
        throw new ValidationError(
          "request.actor is required: corrections are attributed revisions",
        );
      }
      const record = engine.reviseRecord(requireString(request, "recordId"), {
        content: requireString(request, "content"),
        actor,
        method: requireString(request, "method"),
        reason: requireString(request, "reason"),
        origin: (request["origin"] as string | undefined) ?? "contract",
      });
      return { record };
    }
    case "memory.related":
      return relatedImpl(
        engine.store,
        requireString(request, "recordId"),
        (request["direction"] as "out" | "in" | "both" | undefined) ?? "both",
      );
    case "memory.history":
      return engine.getRecordHistory(requireString(request, "recordId"));
    case "memory.relation": {
      const action = requireString(request, "action");
      const recordId = requireString(request, "recordId");
      if (action === "add") {
        const actor = request["actor"] as ActorInput;
        if (actor === null || typeof actor !== "object") {
          throw new ValidationError("request.actor is required: relations are attributed");
        }
        return {
          related: engine.addRelation(recordId, {
            type: requireString(request, "type") as never,
            target: requireString(request, "target"),
            ...(request["note"] !== undefined ? { note: String(request["note"]) } : {}),
            actor,
            method: requireString(request, "method"),
          }),
        };
      }
      if (action === "remove") {
        return {
          related: engine.removeRelation(recordId, {
            type: requireString(request, "type") as never,
            target: requireString(request, "target"),
          }),
        };
      }
      throw new ValidationError("action must be 'add' or 'remove'");
    }
    case "memory.entities": {
      const scope = requireString(request, "scope");
      if (request["rebuild"] === true) {
        return { projection: engine.rebuildEntityProjection(scope) };
      }
      return { projection: engine.entityProjection(scope) };
    }
    case "memory.embeddings": {
      const scope = requireString(request, "scope");
      const action = request["action"] === undefined ? "status" : String(request["action"]);
      const includeSensitive = request["includeSensitive"] === true;
      switch (action) {
        case "status":
          return { status: engine.embeddingProjectionStatus(scope) };
        case "build":
          return { projection: engine.buildEmbeddingProjection(scope, { includeSensitive }) };
        case "rebuild":
          return { projection: engine.rebuildEmbeddingProjection(scope, { includeSensitive }) };
        default:
          throw new ValidationError("action must be 'status', 'build', or 'rebuild'");
      }
    }
    case "memory.semantic": {
      return engine.semanticSearch(requireString(request, "query"), {
        scope: request["scope"] as string | undefined,
        limit: request["limit"] as number | undefined,
      });
    }
    case "memory.graph": {
      const scope = requireString(request, "scope");
      const action = request["action"] === undefined ? "get" : String(request["action"]);
      if (action === "get") {
        return { projection: engine.graphProjection(scope) };
      }
      if (action === "rebuild") {
        return { projection: engine.rebuildGraphProjection(scope) };
      }
      if (action === "traverse") {
        const typesRaw = request["relationTypes"];
        const relationTypes = Array.isArray(typesRaw)
          ? typesRaw.map(String)
          : typesRaw !== undefined
            ? [String(typesRaw)]
            : undefined;
        return {
          traversal: engine.traverseGraph(scope, requireString(request, "start"), {
            direction: request["direction"] as "out" | "in" | "both" | undefined,
            relationTypes,
            maxDepth: request["maxDepth"] as number | undefined,
          }),
        };
      }
      throw new ValidationError("action must be 'get', 'rebuild', or 'traverse'");
    }
    case "memory.hybrid": {
      return engine.hybridSearch(requireString(request, "query"), {
        scope: request["scope"] as string | undefined,
        exactSubject: request["exactSubject"] as string | undefined,
        tag: request["tag"] as string | undefined,
        kind: request["kind"] as never,
        limit: request["limit"] as number | undefined,
        at: request["at"] as string | undefined,
        weights: request["weights"] as never,
      });
    }
    case "memory.projections": {
      const action = request["action"] === undefined ? "check" : String(request["action"]);
      const scope = request["scope"] as string | undefined;
      const includeSensitive = request["includeSensitive"] === true;
      switch (action) {
        case "check":
          return { report: engine.checkProjectionIntegrity(scope) };
        case "rebuild":
          return engine.rebuildAllProjections({ scope, includeSensitive });
        case "repair":
          return engine.repairProjections({ scope, includeSensitive });
        default:
          throw new ValidationError("action must be 'check', 'rebuild', or 'repair'");
      }
    }
    case "memory.performance.propose": {
      const scope = requireString(request, "scope");
      const lessons = request["lessons"];
      if (!Array.isArray(lessons)) {
        throw new ValidationError("request.lessons must be an array of Performance lessons");
      }
      const caller = request["caller"] as ActorInput | undefined;
      return engine.proposePerformanceLessons(scope, lessons as never, caller !== undefined ? { caller } : {});
    }
    case "memory.study.propose": {
      const scope = requireString(request, "scope");
      const proposals = request["proposals"];
      if (!Array.isArray(proposals)) {
        throw new ValidationError("request.proposals must be an array of Study proposals");
      }
      const caller = request["caller"] as ActorInput | undefined;
      return engine.proposeStudy(scope, proposals as never, caller !== undefined ? { caller } : {});
    }
    case "memory.analysis.propose": {
      const scope = requireString(request, "scope");
      const findings = request["findings"];
      if (!Array.isArray(findings)) {
        throw new ValidationError("request.findings must be an array of Analysis findings");
      }
      const caller = request["caller"] as ActorInput | undefined;
      return engine.proposeAnalysis(scope, findings as never, caller !== undefined ? { caller } : {});
    }
    case "memory.search.session": {
      const action = request["action"] === undefined ? "record" : String(request["action"]);
      if (action === "record") {
        const session = engine.recordSearchSession({
          scope: requireString(request, "scope"),
          intent: requireString(request, "intent"),
          actor: request["actor"] as ActorInput | undefined,
          observedAt: request["observedAt"] as string | undefined,
          resultRefs: request["resultRefs"] as never,
          candidateRefs: request["candidateRefs"] as never,
          note: request["note"] as string | undefined,
        });
        return { session };
      }
      if (action === "list") {
        return {
          sessions: engine.listSearchSessions({
            scope: request["scope"] as string | undefined,
            limit: request["limit"] as number | undefined,
          }),
        };
      }
      if (action === "get") {
        return { session: engine.getSearchSession(requireString(request, "searchSessionId")) };
      }
      throw new ValidationError("action must be 'record', 'list', or 'get'");
    }
    case "memory.context": {
      return {
        result: engine.contextQuery({
          scope: requireString(request, "scope"),
          query: request["query"] as string | undefined,
          size: request["size"] as number | undefined,
          at: request["at"] as string | undefined,
          time: request["time"] as never,
          kinds: request["kinds"] as never,
          sourceKinds: request["sourceKinds"] as never,
          minAuthority: request["minAuthority"] as never,
          minConfidence: request["minConfidence"] as number | undefined,
          includeRetracted: request["includeRetracted"] as boolean | undefined,
        }),
      };
    }
    case "memory.user.note": {
      const actor = request["actor"] as ActorInput;
      if (actor === null || typeof actor !== "object") {
        throw new ValidationError("request.actor is required: user notes are explicitly user-authored");
      }
      const record = engine.addUserNote({
        scope: requireString(request, "scope"),
        kind: request["kind"] as never,
        subject: requireString(request, "subject"),
        content: requireString(request, "content"),
        actor,
        method: request["method"] as string | undefined,
        epistemicClass: request["epistemicClass"] as never,
        confidence: request["confidence"] as number | undefined,
        tags: request["tags"] as string[] | undefined,
        relationHints: request["relationHints"] as never,
        evidenceRefs: request["evidenceRefs"] as never,
        privacyClass: request["privacyClass"] as never,
        validFrom: request["validFrom"] as string | undefined,
        validUntil: request["validUntil"] as string | undefined,
        observedAt: request["observedAt"] as string | undefined,
        idempotencyKey: request["idempotencyKey"] as string | undefined,
      });
      return { record };
    }
    case "memory.excerpts": {
      const action = request["action"] === undefined ? "pack" : String(request["action"]);
      if (action === "record") {
        return {
          excerpt: engine.memoryExcerpt(requireString(request, "recordId"), {
            at: request["at"] as string | undefined,
            maxContentChars: request["maxContentChars"] as number | undefined,
            includeSensitive: request["includeSensitive"] === true,
          }),
        };
      }
      return {
        pack: engine.contextExcerpts({
          scope: requireString(request, "scope"),
          at: request["at"] as string | undefined,
          maxExcerpts: request["maxExcerpts"] as number | undefined,
          maxContentChars: request["maxContentChars"] as number | undefined,
          includeSensitive: request["includeSensitive"] === true,
          sourceKinds: request["sourceKinds"] as never,
          kinds: request["kinds"] as never,
          minConfidence: request["minConfidence"] as number | undefined,
          minAuthority: request["minAuthority"] as never,
        }),
      };
    }
    case "memory.privacy": {
      const action = request["action"] === undefined ? "status" : String(request["action"]);
      if (action === "status") {
        return { status: engine.policyStatus() };
      }
      if (action === "setProjectIsolation") {
        const mode = String(request["mode"]);
        if (mode !== "strict" && mode !== "open") {
          throw new ValidationError("mode must be 'strict' or 'open'");
        }
        engine.setProjectIsolation(mode);
        return { status: engine.policyStatus() };
      }
      if (action === "setScopeContentPolicy") {
        engine.setScopePrivacyPolicy(requireString(request, "scope"), request["policy"] as never);
        return { status: engine.policyStatus() };
      }
      throw new ValidationError("action must be 'status', 'setProjectIsolation', or 'setScopeContentPolicy'");
    }
    case "memory.trust": {
      return { status: engine.contentBoundaryStatus() };
    }
    case "memory.backup": {
      const action = request["action"] === undefined ? "create" : String(request["action"]);
      if (action === "create") {
        return { bundle: engine.backup() };
      }
      if (action === "verify") {
        return { verified: engine.verifyBackup(request["bundle"]) };
      }
      if (action === "verifyReferences") {
        return { report: engine.verifyStoreReferences() };
      }
      throw new ValidationError("action must be 'create', 'verify', or 'verifyReferences'");
    }
    case "memory.health": {
      return { metrics: engine.memoryHealth() };
    }
    case "memory.explain": {
      const recordId = requireString(request, "recordId");
      return engine.explainRecord(recordId, request["at"] as string | undefined);
    }
  }
}
