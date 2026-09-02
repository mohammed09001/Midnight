/**
 * Memory Engine CLI — terminal/tool surface. The engine is fully usable
 * without any game client. Output is machine-readable JSON on stdout;
 * failures print { error: { code, message } } and exit non-zero.
 *
 * Exit codes: 0 success, 1 engine/failure, 2 usage error.
 */
import { realpathSync, readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { MemoryEngine } from "../engine/memoryEngine.ts";
import { dispatch } from "../engine/dispatcher.ts";
import { MEMORY_OPERATIONS, type MemoryOperation } from "../contracts/operations.ts";
import type { ActorInput } from "../engine/records.ts";
import { MemoryEngineError } from "../contracts/errors.ts";
import { localHashProvider } from "../engine/embeddings.ts";
import { runMcpServer } from "../tools/mcpServer.ts";
import { runProductTruthGate } from "../engine/gate.ts";

interface ParsedArgs {
  command: string | null;
  args: string[];
  flags: Map<string, string>;
  /** Repeatable --arg key=value pairs (values parsed as JSON when valid). */
  argPairs: string[];
  /** Repeatable --evidence <engine>:<ref> values. */
  evidencePairs: string[];
  store: string | undefined;
}

function parseArgs(argv: string[]): ParsedArgs {
  const flags = new Map<string, string>();
  const positional: string[] = [];
  const argPairs: string[] = [];
  const evidencePairs: string[] = [];
  let store: string | undefined;
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i]!;
    if (arg === "--store") {
      store = argv[++i];
    } else if (arg === "--arg") {
      const next = argv[++i];
      if (next !== undefined) argPairs.push(next);
    } else if (arg === "--evidence") {
      const next = argv[++i];
      if (next !== undefined) evidencePairs.push(next);
    } else if (arg.startsWith("--")) {
      const key = arg.slice(2);
      const next = argv[i + 1];
      if (next !== undefined && !next.startsWith("--")) {
        flags.set(key, next);
        i++;
      } else {
        flags.set(key, "true");
      }
    } else {
      positional.push(arg);
    }
  }
  return { command: positional[0] ?? null, args: positional.slice(1), flags, argPairs, evidencePairs, store };
}

function fail(payload: { code: string; message: string }, exitCode: number): never {
  process.stdout.write(`${JSON.stringify({ error: payload }, null, 2)}\n`);
  process.exit(exitCode);
}

interface RequiredArgs {
  get(name: string): string;
  opt(name: string): string | undefined;
}

function requireArgs(parsed: ParsedArgs, names: string[], usage: string): RequiredArgs {
  const map = new Map<string, string>();
  for (const name of names) {
    const v = parsed.flags.get(name);
    if (v === undefined || v === "true") {
      process.stderr.write(`usage: memory-engine ${usage}\n`);
      process.exit(2);
    }
    map.set(name, v);
  }
  return {
    get(name: string): string {
      const v = map.get(name);
      if (v === undefined) {
        process.stderr.write(`usage: memory-engine ${usage}\n`);
        process.exit(2);
      }
      return v;
    },
    opt(name: string): string | undefined {
      const v = parsed.flags.get(name);
      return v === "true" ? undefined : v;
    },
  };
}

/** Parse repeatable --evidence <engine>:<ref> values into EvidenceRef objects. */
function collectEvidence(parsed: ParsedArgs): Array<{ engine: never; ref: string; expiresAt?: string }> | undefined {
  const entries: Array<{ engine: never; ref: string; expiresAt?: string }> = [];
  const expiresAt = parsed.flags.get("evidence-expires-at");
  for (const value of parsed.evidencePairs) {
    const colon = value.indexOf(":");
    if (colon > 0) {
      const entry: { engine: never; ref: string; expiresAt?: string } = {
        engine: value.slice(0, colon) as never,
        ref: value.slice(colon + 1),
      };
      if (expiresAt !== undefined && expiresAt !== "true") entry.expiresAt = expiresAt;
      entries.push(entry);
    }
  }
  return entries.length > 0 ? entries : undefined;
}

const ACTOR_KINDS = ["human", "agent", "engine", "tool"] as const;
const PROMOTION_POLICIES = [
  "explicit_user_decision",
  "verified_study_fact",
  "repeated_evidence_backed_lesson",
] as const;

/** Parse "engine:repository_sync" → {kind:"engine", name:"repository_sync"}. */
function parseCallerKey(key: string): ActorInput {
  const colon = key.indexOf(":");
  if (colon <= 0) {
    fail(
      { code: "MEMORY_VALIDATION_FAILED", message: `caller must be a canonical actor key like 'engine:repository_sync' (got '${key}')` },
      2,
    );
  }
  const kind = key.slice(0, colon);
  if (!ACTOR_KINDS.includes(kind as (typeof ACTOR_KINDS)[number])) {
    fail(
      { code: "MEMORY_VALIDATION_FAILED", message: `caller kind must be one of ${ACTOR_KINDS.join(", ")}` },
      2,
    );
  }
  return { kind: kind as ActorInput["kind"], name: key.slice(colon + 1) };
}

/** Collect repeatable --allow actor keys for scope intake policies. */
function collectAllow(parsed: ParsedArgs): string[] {
  const allow: string[] = [];
  for (const pair of parsed.argPairs) {
    if (pair.startsWith("allow=")) {
      allow.push(pair.slice("allow=".length));
    }
  }
  // Also honor legacy --allow <value> single flags.
  const single = parsed.flags.get("allow");
  if (single !== undefined && single !== "true" && !allow.includes(single)) {
    allow.push(single);
  }
  return allow;
}

/** Collect repeatable --arg record=<id> values for contradiction registration. */
function collectRecordIds(parsed: ParsedArgs): string[] {
  const recordIds: string[] = [];
  for (const pair of parsed.argPairs) {
    if (pair.startsWith("record=")) {
      recordIds.push(pair.slice("record=".length));
    }
  }
  const single = parsed.flags.get("record");
  if (single !== undefined && single !== "true" && !recordIds.includes(single)) {
    recordIds.push(single);
  }
  return recordIds;
}

function actorFromFlags(parsed: ParsedArgs): ActorInput {
  const kind = parsed.flags.get("actor-kind") ?? "agent";
  if (!ACTOR_KINDS.includes(kind as (typeof ACTOR_KINDS)[number])) {
    fail(
      { code: "MEMORY_VALIDATION_FAILED", message: `--actor-kind must be one of ${ACTOR_KINDS.join(", ")}` },
      2,
    );
  }
  const actor: ActorInput = {
    kind: kind as ActorInput["kind"],
    name: parsed.flags.get("actor-name") ?? "memory-cli",
  };
  const agentType = parsed.flags.get("agent-type");
  if (agentType !== undefined && agentType !== "true") actor.agentType = agentType;
  return actor;
}

export function main(argv: string[]): void {
  const parsed = parseArgs(argv);
  let engine: MemoryEngine | null = null;
  try {
    if (parsed.command === null || parsed.flags.get("help") === "true") {
      usageAndExit();
    }
    engine = new MemoryEngine({ storePath: parsed.store });

    switch (parsed.command) {
      case "doctor": {
        engine.open();
        const report = engine.doctor();
        process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
        process.exit(report.healthy ? 0 : 1);
        break;
      }
      case "events": {
        engine.open();
        const limitFlag = parsed.flags.get("limit");
        const limit = limitFlag !== undefined ? Number(limitFlag) : 50;
        process.stdout.write(`${JSON.stringify(engine.listEvents(limit), null, 2)}\n`);
        process.exit(0);
        break;
      }
      case "scope": {
        const sub = parsed.args[0];
        if (sub === "create") {
          const req = requireArgs(
            parsed,
            ["key", "name"],
            "scope create --key <projectKey> --name <displayName>",
          );
          engine.open();
          const scope = engine.createScope(req.get("key"), req.get("name"));
          emit(scope, 0);
        }
        if (sub === "get") {
          const req = requireArgs(parsed, ["key"], "scope get --key <projectKey|scopeId>");
          engine.open();
          const scope = engine.getScope(req.get("key"));
          emit(scope, 0);
        }
        if (sub === "policy") {
          const req = requireArgs(
            parsed,
            ["key", "mode"],
            "scope policy --key <projectKey> --mode open|allowlist [--allow engine:repository_sync --allow user:kim]",
          );
          const mode = req.get("mode");
          if (mode !== "open" && mode !== "allowlist") {
            fail({ code: "MEMORY_VALIDATION_FAILED", message: "--mode must be open or allowlist" }, 2);
          }
          engine.open();
          emit(engine.setScopeIntakePolicy(req.get("key"), { mode, allow: collectAllow(parsed) }), 0);
        }
        if (sub === "mutation-policy") {
          const req = requireArgs(
            parsed,
            ["key", "mode"],
            "scope mutation-policy --key <projectKey> --mode open|restricted [--allow agent:worker-a --allow human:kim]",
          );
          const mode = req.get("mode");
          if (mode !== "open" && mode !== "restricted") {
            fail({ code: "MEMORY_VALIDATION_FAILED", message: "--mode must be open or restricted" }, 2);
          }
          engine.open();
          emit(engine.setScopeMutationPolicy(req.get("key"), { mode, allow: collectAllow(parsed) }), 0);
        }
        if (sub === "delete") {
          const req = requireArgs(
            parsed,
            ["key", "reason"],
            "scope delete --key <projectKey> --reason <why> [--purge]",
          );
          engine.open();
          emit(
            engine.deleteScope(req.get("key"), {
              actor: actorFromFlags(parsed),
              reason: req.get("reason"),
              mode: parsed.flags.get("purge") === "true" ? "purge" : "tombstone",
              origin: "cli",
            }),
            0,
          );
        }
        usageAndExit();
        break;
      }
      case "record": {
        const sub = parsed.args[0];
        engine.open();
        if (sub === "user-note") {
          const req = requireArgs(
            parsed,
            ["scope", "subject", "content"],
            "record user-note --scope <key> --subject <subject> --content <text> [--kind note|decision] [--actor-kind human --actor-name NAME] [--tags a,b] [--confidence 0.85]",
          );
          const tags = req.opt("tags");
          const kind = req.opt("kind");
          const record = engine.addUserNote({
            scope: req.get("scope"),
            subject: req.get("subject"),
            content: req.get("content"),
            kind: kind === "decision" ? "decision" : kind === "note" ? "note" : undefined,
            actor: actorFromFlags(parsed),
            tags: tags !== undefined ? tags.split(",").map((t) => t.trim()).filter(Boolean) : undefined,
            confidence: req.opt("confidence") !== undefined ? Number(req.opt("confidence")) : undefined,
          });
          emit(record, 0);
        }
        if (sub === "add") {
          const req = requireArgs(
            parsed,
            ["scope", "subject", "content"],
            "record add --scope <key|scopeId> --subject <subject> --content <text> [--kind fact] [--confidence 0.8] [--epistemic observed] [--privacy internal] [--tags a,b] [--valid-until <iso>] [--source-kind study_finding] [--observed-at <iso>] [--derived-from-engine E --derived-from-ref R]",
          );
          const tags = req.opt("tags");
          const confidence = req.opt("confidence");
          const validUntil = req.opt("valid-until");
          const derivedEngine = req.opt("derived-from-engine");
          const derivedRef = req.opt("derived-from-ref");
          const record = engine.addRecord({
            scope: req.get("scope"),
            subject: req.get("subject"),
            content: req.get("content"),
            kind: recordKindFlag(parsed.flags.get("kind"), "fact"),
            actor: actorFromFlags(parsed),
            method: req.opt("method") ?? "cli-add",
            epistemicClass: epistemicFlag(parsed.flags.get("epistemic"), "observed"),
            confidence: confidence !== undefined ? Number(confidence) : 0.8,
            privacyClass: privacyFlag(req.opt("privacy")),
            evidenceRefs: collectEvidence(parsed),
            tags:
              tags !== undefined
                ? tags.split(",").map((t) => t.trim()).filter(Boolean)
                : undefined,
            validUntil,
            observedAt: req.opt("observed-at"),
            sourceKind: sourceKindFlag(req.opt("source-kind")),
            idempotencyKey: req.opt("idempotency-key"),
            derivedFrom:
              derivedEngine !== undefined && derivedRef !== undefined
                ? { engine: derivedEngine as never, ref: derivedRef }
                : undefined,
          });
          emit(record, 0);
        }
        if (sub === "get") {
          const req = requireArgs(parsed, ["id"], "record get --id <recordId>");
          emit(engine.getRecord(req.get("id")), 0);
        }
        if (sub === "revise") {
          const req = requireArgs(
            parsed,
            ["id", "content", "reason"],
            "record revise --id <recordId> --content <new text> --reason <why>",
          );
          const record = engine.reviseRecord(req.get("id"), {
            content: req.get("content"),
            actor: actorFromFlags(parsed),
            method: req.opt("method") ?? "cli-revise",
            reason: req.get("reason"),
            origin: "cli",
          });
          emit(record, 0);
        }
        if (sub === "supersede") {
          const req = requireArgs(
            parsed,
            ["id", "content", "reason"],
            "record supersede --id <recordId> --content <replacement text> --reason <why>",
          );
          const record = engine.supersedeRecord(req.get("id"), {
            content: req.get("content"),
            actor: actorFromFlags(parsed),
            method: req.opt("method") ?? "cli-supersede",
            reason: req.get("reason"),
            origin: "cli",
          });
          emit(record, 0);
        }
        if (sub === "contradictions") {
          const scope = parsed.flags.get("scope");
          if (scope === undefined || scope === "true") {
            process.stderr.write("usage: memory-engine record contradictions --scope <key>\n");
            process.exit(2);
          }
          emit({ pairs: engine.detectContradictions(scope), openGroups: engine.listOpenContradictions(scope) }, 0);
        }
        if (sub === "archive") {
          const req = requireArgs(parsed, ["id", "reason"], "record archive --id <recordId> --reason <why>");
          emit(engine.archiveRecord(req.get("id"), { actor: actorFromFlags(parsed), reason: req.get("reason"), origin: "cli" }), 0);
        }
        if (sub === "restore") {
          const req = requireArgs(parsed, ["id", "reason"], "record restore --id <recordId> --reason <why>");
          emit(engine.restoreRecord(req.get("id"), { actor: actorFromFlags(parsed), reason: req.get("reason"), origin: "cli" }), 0);
        }
        if (sub === "delete") {
          const req = requireArgs(parsed, ["id", "reason"], "record delete --id <recordId> --reason <why> [--purge]");
          if (parsed.flags.get("purge") === "true") {
            emit(engine.purgeRecord(req.get("id"), { actor: actorFromFlags(parsed), reason: req.get("reason"), origin: "cli" }), 0);
          }
          emit(engine.deleteRecord(req.get("id"), { actor: actorFromFlags(parsed), reason: req.get("reason"), origin: "cli" }), 0);
        }
        if (sub === "purge-privacy") {
          const req = requireArgs(
            parsed,
            ["reason"],
            "record purge-privacy --reason <why> --classes sensitive [--scope key] [--actor-kind human]",
          );
          const classes = (req.opt("classes") ?? "sensitive")
            .split(",")
            .map((c) => c.trim())
            .filter((c) => ["public", "internal", "sensitive"].includes(c)) as Array<"public" | "internal" | "sensitive">;
          emit(
            engine.purgeByPrivacy({
              actor: actorFromFlags(parsed),
              reason: req.get("reason"),
              privacyClasses: classes,
              scope: parsed.flags.get("scope"),
              origin: "cli",
            }),
            0,
          );
        }
        if (sub === "retract") {
          const req = requireArgs(
            parsed,
            ["id", "reason"],
            "record retract --id <recordId> --reason <why>",
          );
          const record = engine.retractRecord(req.get("id"), {
            actor: actorFromFlags(parsed),
            reason: req.get("reason"),
            origin: "cli",
          });
          emit(record, 0);
        }
        if (sub === "search") {
          const limitFlag = parsed.flags.get("limit");
          const asOf = parsed.flags.get("as-of");
          if (asOf !== undefined && asOf !== "true") {
            const results = engine.queryRecordsAsOfTraced({
              scope: parsed.flags.get("scope"),
              asOf,
              includeRetracted: parsed.flags.get("include-retracted") !== "false",
              limit: limitFlag !== undefined ? Number(limitFlag) : undefined,
            });
            emit(results, 0);
          }
          const q = parsed.flags.get("q");
          if (q !== undefined && q !== "true") {
            const results = engine.lexicalSearch(q, {
              scope: parsed.flags.get("scope"),
              status: parsed.flags.get("status") === "all" ? "all" : undefined,
              limit: limitFlag !== undefined ? Number(limitFlag) : undefined,
            });
            emit(results, 0);
          }
          const results = engine.searchRecordsTraced({
            scope: parsed.flags.get("scope"),
            exactSubject: parsed.flags.get("subject-exact"),
            subjectContains: parsed.flags.get("subject"),
            contentContains: parsed.flags.get("contains"),
            tag: parsed.flags.get("tag"),
            sourceEngine: parsed.flags.get("source-engine"),
            actor: parsed.flags.get("actor"),
            confidenceMin: parsed.flags.get("confidence-min") !== undefined ? Number(parsed.flags.get("confidence-min")) : undefined,
            confidenceMax: parsed.flags.get("confidence-max") !== undefined ? Number(parsed.flags.get("confidence-max")) : undefined,
            validAt: parsed.flags.get("valid-at"),
            createdAfter: parsed.flags.get("created-after"),
            createdBefore: parsed.flags.get("created-before"),
            observedAfter: parsed.flags.get("observed-after"),
            observedBefore: parsed.flags.get("observed-before"),
            status: statusFlag(parsed.flags.get("status"), "all"),
            limit: limitFlag !== undefined ? Number(limitFlag) : undefined,
          });
          emit(results, 0);
        }
        if (sub === "current") {
          const scope = parsed.flags.get("scope");
          if (scope === undefined || scope === "true") {
            process.stderr.write("usage: memory-engine record current --scope <key> [--subject S]\n");
            process.exit(2);
          }
          emit(engine.currentRecordsTraced({ scope, subject: parsed.flags.get("subject") }), 0);
        }
        if (sub === "explain") {
          const req = requireArgs(parsed, ["id"], "record explain --id <recordId> [--at <iso>]");
          emit(engine.explainRecord(req.get("id"), parsed.flags.get("at")), 0);
        }
        if (sub === "ranked") {
          const q = parsed.flags.get("q");
          if (q === undefined || q === "true") {
            process.stderr.write("usage: memory-engine record ranked --q <query> [--scope K] [--limit N] [--at <iso>]\n");
            process.exit(2);
          }
          const limitFlag = parsed.flags.get("limit");
          emit(
            engine.rankedSearch(q, {
              scope: parsed.flags.get("scope"),
              limit: limitFlag !== undefined ? Number(limitFlag) : undefined,
              at: parsed.flags.get("at"),
            }),
            0,
          );
        }
        if (sub === "fused") {
          const q = parsed.flags.get("q");
          if (q === undefined || q === "true") {
            process.stderr.write("usage: memory-engine record fused --q <query> [--scope K] [--tag T] [--subject-exact S] [--limit N] [--at <iso>]\n");
            process.exit(2);
          }
          const limitFlag = parsed.flags.get("limit");
          emit(
            engine.fusedSearch(q, {
              scope: parsed.flags.get("scope"),
              exactSubject: parsed.flags.get("subject-exact"),
              tag: parsed.flags.get("tag"),
              limit: limitFlag !== undefined ? Number(limitFlag) : undefined,
              at: parsed.flags.get("at"),
            }),
            0,
          );
        }
        if (sub === "hybrid") {
          const q = parsed.flags.get("q");
          if (q === undefined || q === "true") {
            process.stderr.write("usage: memory-engine record hybrid --q <query> [--scope K] [--limit N] [--at <iso>]\n");
            process.exit(2);
          }
          engine.setEmbeddingProvider(localHashProvider);
          const limitFlag = parsed.flags.get("limit");
          emit(
            engine.hybridSearch(q, {
              scope: parsed.flags.get("scope"),
              limit: limitFlag !== undefined ? Number(limitFlag) : undefined,
              at: parsed.flags.get("at"),
            }),
            0,
          );
        }
        if (sub === "timeline") {
          const scope = parsed.flags.get("scope");
          const subject = parsed.flags.get("subject");
          if (scope === undefined || scope === "true" || subject === undefined || subject === "true") {
            process.stderr.write("usage: memory-engine record timeline --scope <key> --subject <S>\n");
            process.exit(2);
          }
          emit(engine.decisionTimeline(scope, subject), 0);
        }
        if (sub === "history") {
          const req = requireArgs(parsed, ["id"], "record history --id <recordId>");
          emit(engine.getRecordHistory(req.get("id")), 0);
        }
        if (sub === "related") {
          const req = requireArgs(parsed, ["id"], "record related --id <recordId> [--direction out|in|both]");
          const direction = parsed.flags.get("direction");
          emit(
            engine.related(
              req.get("id"),
              direction === "out" ? "out" : direction === "in" ? "in" : "both",
            ),
            0,
          );
        }
        usageAndExit();
        break;
      }
      case "contract": {
        if (parsed.args[0] !== "call") usageAndExit();
        const op = parsed.flags.get("operation");
        const requestFlag = parsed.flags.get("request");
        if (op === undefined || op === "true") {
          process.stderr.write(
            `usage: memory-engine contract call --operation <${MEMORY_OPERATIONS.join("|")}> --request '<json>'\n`,
          );
          process.exit(2);
        }
        engine.open();
        let request: unknown = {};
        if (requestFlag !== undefined && requestFlag !== "true") {
          try {
            request = JSON.parse(requestFlag) as unknown;
          } catch {
            fail({ code: "MEMORY_VALIDATION_FAILED", message: "--request must be valid JSON" }, 2);
          }
        } else if (parsed.argPairs.length > 0) {
          const obj: Record<string, unknown> = {};
          for (const pair of parsed.argPairs) {
            const eq = pair.indexOf("=");
            if (eq <= 0) {
              fail({ code: "MEMORY_VALIDATION_FAILED", message: `--arg must be key=value, got '${pair}'` }, 2);
            }
            const key = pair.slice(0, eq);
            const raw = pair.slice(eq + 1);
            try {
              obj[key] = JSON.parse(raw) as unknown;
            } catch {
              obj[key] = raw;
            }
          }
          request = obj;
        }
        const envelope = dispatch(engine, {
          contractVersion: parsed.flags.get("version") ?? engine.contractVersion,
          operation: op as MemoryOperation,
          request,
        });
        emit(envelope, envelope.ok ? 0 : 1);
      }
      case "contradiction": {
        const sub = parsed.args[0];
        if (sub === "register") {
          const req = requireArgs(
            parsed,
            ["scope", "subject"],
            "contradiction register --scope <key> --subject <s> --arg record=<id> --arg record=<id2> [...]",
          );
          const recordIds = collectRecordIds(parsed);
          engine.open();
          const group = engine.registerContradiction(req.get("scope"), req.get("subject"), recordIds);
          emit(group, 0);
        }
        if (sub === "resolve") {
          const req = requireArgs(
            parsed,
            ["id", "action", "winner", "reason"],
            "contradiction resolve --id <groupId> --action supersede|retract --winner <recordId> --reason <why> [--actor-kind human]",
          );
          const action = req.get("action");
          if (action !== "supersede" && action !== "retract") {
            fail({ code: "MEMORY_VALIDATION_FAILED", message: "--action must be supersede or retract" }, 2);
          }
          engine.open();
          const group = engine.resolveContradiction(req.get("id"), {
            action,
            winnerRecordId: req.get("winner"),
            actor: actorFromFlags(parsed),
            reason: req.get("reason"),
            origin: "cli",
          });
          emit(group, 0);
        }
        usageAndExit();
        break;
      }
      case "candidate": {
        const sub = parsed.args[0];
        engine.open();
        if (sub === "add") {
          const req = requireArgs(
            parsed,
            ["scope", "subject", "content", "reason"],
            "candidate add --scope <key> --subject <subject> --content <text> --reason <why> [--kind fact] [--confidence 0.5] [--epistemic inferred] [--source-kind agent_inference] [--actor-kind agent] [--caller engine:name]",
          );
          const tags = req.opt("tags");
          const confidence = req.opt("confidence");
          const caller = req.opt("caller");
          const candidate = engine.addCandidate({
            scope: req.get("scope"),
            subject: req.get("subject"),
            content: req.get("content"),
            kind: recordKindFlag(parsed.flags.get("kind"), "fact"),
            actor: actorFromFlags(parsed),
            method: req.opt("method") ?? "cli-candidate",
            epistemicClass: epistemicFlag(parsed.flags.get("epistemic"), "inferred"),
            confidence: confidence !== undefined ? Number(confidence) : 0.5,
            tags:
              tags !== undefined
                ? tags.split(",").map((t) => t.trim()).filter(Boolean)
                : undefined,
            reason: req.get("reason"),
            sourceKind: sourceKindFlag(req.opt("source-kind")),
            evidenceRefs: collectEvidence(parsed),
            caller: caller !== undefined ? parseCallerKey(caller) : undefined,
            idempotencyKey: req.opt("idempotency-key"),
          });
          emit(candidate, 0);
        }
        if (sub === "list") {
          const statusFlag = parsed.flags.get("status");
          const results = engine.listCandidates({
            scope: parsed.flags.get("scope"),
            status:
              statusFlag !== undefined && ["open", "promoted", "rejected", "all"].includes(statusFlag)
                ? (statusFlag as "open" | "promoted" | "rejected" | "all")
                : "open",
            limit: parsed.flags.get("limit") !== undefined ? Number(parsed.flags.get("limit")) : undefined,
          });
          emit(results, 0);
        }
        if (sub === "evaluate") {
          const req = requireArgs(parsed, ["id"], "candidate evaluate --id <candidateId>");
          emit(engine.evaluatePromotion(req.get("id")), 0);
        }
        if (sub === "promote") {
          const req = requireArgs(
            parsed,
            ["id"],
            "candidate promote --id <candidateId> [--policy explicit_user_decision|verified_study_fact|repeated_evidence_backed_lesson] [--actor-kind human] [--actor-name kim]",
          );
          const policyFlag = req.opt("policy");
          if (policyFlag !== undefined && !PROMOTION_POLICIES.includes(policyFlag as never)) {
            fail(
              { code: "MEMORY_VALIDATION_FAILED", message: `--policy must be one of ${PROMOTION_POLICIES.join(", ")}` },
              2,
            );
          }
          const record = engine.promoteCandidate(req.get("id"), {
            actor: actorFromFlags(parsed),
            policy: policyFlag as never,
            origin: "cli",
          });
          emit(record, 0);
        }
        if (sub === "reject") {
          const req = requireArgs(
            parsed,
            ["id", "reason"],
            "candidate reject --id <candidateId> --reason <why>",
          );
          const candidate = engine.rejectCandidate(req.get("id"), {
            actor: actorFromFlags(parsed),
            reason: req.get("reason"),
            origin: "cli",
          });
          emit(candidate, 0);
        }
        usageAndExit();
        break;
      }
      case "dedup": {
        const sub = parsed.args[0];
        engine.open();
        if (sub === "analyze") {
          const req = requireArgs(
            parsed,
            ["scope", "subject", "content"],
            "dedup analyze --scope <key> --subject <subject> --content <text> [--evidence engine:ref ...]",
          );
          const evidenceRefs = collectEvidence(parsed);
          emit(
            engine.analyzeDuplicates(req.get("scope"), {
              subject: req.get("subject"),
              content: req.get("content"),
              evidenceRefs,
            }),
            0,
          );
        }
        if (sub === "candidates") {
          const req = requireArgs(parsed, ["scope"], "dedup candidates --scope <key> [--status open|promoted|rejected|all] [--limit N]");
          const status = parsed.flags.get("status");
          emit(
            engine.findCandidateDuplicates(req.get("scope"), {
              status:
                status !== undefined && ["open", "promoted", "rejected", "all"].includes(status)
                  ? (status as "open" | "promoted" | "rejected" | "all")
                  : "open",
              limit: parsed.flags.get("limit") !== undefined ? Number(parsed.flags.get("limit")) : undefined,
            }),
            0,
          );
        }
        usageAndExit();
        break;
      }
      case "relation": {
        const sub = parsed.args[0];
        engine.open();
        if (sub === "add") {
          const req = requireArgs(
            parsed,
            ["id", "type", "target", "method"],
            "relation add --id <recordId> --type <related|depends_on|supports|contradicts|derived_from|applies_to|learned_from> --target <recordId|engine:name:ref|entity:kind:name> --method <how> [--note N] [--actor-kind human] [--actor-name NAME]",
          );
          emit(
            engine.addRelation(req.get("id"), {
              type: req.get("type") as never,
              target: req.get("target"),
              note: req.opt("note"),
              actor: actorFromFlags(parsed),
              method: req.get("method"),
            }),
            0,
          );
        }
        if (sub === "remove") {
          const req = requireArgs(
            parsed,
            ["id", "type", "target"],
            "relation remove --id <recordId> --type <type> --target <target>",
          );
          emit(
            engine.removeRelation(req.get("id"), {
              type: req.get("type") as never,
              target: req.get("target"),
            }),
            0,
          );
        }
        usageAndExit();
        break;
      }
      case "entities": {
        const req = requireArgs(parsed, ["scope"], "entities --scope <key> [--rebuild]");
        engine.open();
        if (parsed.flags.get("rebuild") === "true") {
          emit(engine.rebuildEntityProjection(req.get("scope")), 0);
        }
        emit(engine.entityProjection(req.get("scope")), 0);
        break;
      }
      case "embeddings": {
        // Terminal surface defaults to the deterministic local provider so the
        // optional semantic projection works self-hosted; programmatic callers
        // inject any provider-neutral EmbeddingProvider.
        engine.setEmbeddingProvider(localHashProvider);
        const sub = parsed.args[0];
        const req = requireArgs(
          parsed,
          ["scope"],
          "embeddings status|build|rebuild --scope <key> [--include-sensitive]",
        );
        engine.open();
        if (sub === "build") {
          emit(engine.buildEmbeddingProjection(req.get("scope"), { includeSensitive: parsed.flags.get("include-sensitive") === "true" }), 0);
        }
        if (sub === "rebuild") {
          emit(engine.rebuildEmbeddingProjection(req.get("scope"), { includeSensitive: parsed.flags.get("include-sensitive") === "true" }), 0);
        }
        emit(engine.embeddingProjectionStatus(req.get("scope")), 0);
        break;
      }
      case "semantic": {
        engine.setEmbeddingProvider(localHashProvider);
        const sub = parsed.args[0];
        if (sub !== "search") usageAndExit();
        const req = requireArgs(parsed, ["q"], "semantic search --q <query> [--scope K] [--limit N]");
        engine.open();
        const limitFlag = parsed.flags.get("limit");
        emit(
          engine.semanticSearch(req.get("q"), {
            scope: parsed.flags.get("scope"),
            limit: limitFlag !== undefined ? Number(limitFlag) : undefined,
          }),
          0,
        );
        break;
      }
      case "graph": {
        engine.open();
        const sub = parsed.args[0];
        if (sub === "traverse") {
          const req = requireArgs(
            parsed,
            ["scope", "start"],
            "graph traverse --scope <key> --start <nodeId> [--direction out|in|both] [--types a,b] [--max-depth N]",
          );
          const types = parsed.flags.get("types");
          const maxDepth = parsed.flags.get("max-depth");
          emit(
            engine.traverseGraph(req.get("scope"), req.get("start"), {
              direction: parsed.flags.get("direction") as never,
              relationTypes: types !== undefined ? types.split(",").map((t) => t.trim()).filter(Boolean) : undefined,
              maxDepth: maxDepth !== undefined ? Number(maxDepth) : undefined,
            }),
            0,
          );
        }
        const req = requireArgs(parsed, ["scope"], "graph --scope <key> [--rebuild]");
        if (parsed.flags.get("rebuild") === "true") {
          emit(engine.rebuildGraphProjection(req.get("scope")), 0);
        }
        emit(engine.graphProjection(req.get("scope")), 0);
        break;
      }
      case "projections": {
        engine.open();
        const sub = parsed.args[0];
        const scope = parsed.flags.get("scope");
        const includeSensitive = parsed.flags.get("include-sensitive") === "true";
        if (sub === "rebuild") {
          emit(engine.rebuildAllProjections({ scope, includeSensitive }), 0);
        }
        if (sub === "repair") {
          emit(engine.repairProjections({ scope, includeSensitive }), 0);
        }
        emit(engine.checkProjectionIntegrity(scope), 0);
        break;
      }
      case "performance": {
        const sub = parsed.args[0];
        engine.open();
        if (sub === "propose") {
          const req = requireArgs(
            parsed,
            ["scope", "subject", "content"],
            "performance propose --scope <key> --subject <lesson> --content <text> --evidence perf:<recordId> [--evidence perf:<id2> ...] [--caller engine:performance] [--idempotency-key K]",
          );
          const evidenceRefs = parsed.evidencePairs.map((pair) => {
            const colon = pair.indexOf(":");
            return colon > 0 ? pair.slice(colon + 1) : pair;
          });
          if (evidenceRefs.length === 0) {
            fail({ code: "MEMORY_VALIDATION_FAILED", message: "--evidence perf:<recordId> is required (Performance lessons are evidence-backed)" }, 2);
          }
          const caller = req.opt("caller");
          const result = engine.proposePerformanceLessons(
            req.get("scope"),
            [{
              subject: req.get("subject"),
              content: req.get("content"),
              evidenceRefs,
              kind: "observation",
              epistemicClass: "derived",
              confidence: 0.8,
              tags: req.opt("tags") !== undefined ? req.opt("tags")!.split(",").map((t) => t.trim()).filter(Boolean) : undefined,
              actor: actorFromFlags(parsed),
              idempotencyKey: req.opt("idempotency-key"),
            }],
            caller !== undefined ? { caller: parseCallerKey(caller) } : {},
          );
          emit(result, 0);
        }
        usageAndExit();
        break;
      }
      case "study": {
        const sub = parsed.args[0];
        engine.open();
        if (sub === "propose") {
          const req = requireArgs(
            parsed,
            ["scope", "kind", "study", "version", "source-revision", "subject", "content"],
            "study propose --scope <key> --kind finding|annotation --study <studyId> --version <v> --source-revision <rev> --subject <S> --content <T> [--note N] [--caller engine:study_document]",
          );
          const type = req.get("kind");
          if (type !== "finding" && type !== "annotation") {
            fail({ code: "MEMORY_VALIDATION_FAILED", message: "--kind must be finding or annotation" }, 2);
          }
          const caller = req.opt("caller");
          const result = engine.proposeStudy(
            req.get("scope"),
            [{
              type,
              subject: req.get("subject"),
              content: req.get("content"),
              studyId: req.get("study"),
              version: req.get("version"),
              sourceRevision: req.get("source-revision"),
              note: req.opt("note"),
              actor: actorFromFlags(parsed),
            }],
            caller !== undefined ? { caller: parseCallerKey(caller) } : {},
          );
          emit(result, 0);
        }
        usageAndExit();
        break;
      }
      case "analysis": {
        const sub = parsed.args[0];
        engine.open();
        if (sub === "propose") {
          const req = requireArgs(
            parsed,
            ["scope", "subject", "content"],
            "analysis propose --scope <key> --subject <finding> --content <text> --evidence analysis:<recordId> [--evidence analysis:<id2> ...] [--caller engine:analysis]",
          );
          const evidenceRefs = parsed.evidencePairs.map((pair) => {
            const colon = pair.indexOf(":");
            return colon > 0 ? pair.slice(colon + 1) : pair;
          });
          if (evidenceRefs.length === 0) {
            fail({ code: "MEMORY_VALIDATION_FAILED", message: "--evidence analysis:<recordId> is required (Analysis findings are evidence-linked)" }, 2);
          }
          const caller = req.opt("caller");
          const result = engine.proposeAnalysis(
            req.get("scope"),
            [{
              subject: req.get("subject"),
              content: req.get("content"),
              evidenceRefs,
              kind: "note",
              epistemicClass: "derived",
              confidence: 0.7,
              tags: req.opt("tags") !== undefined ? req.opt("tags")!.split(",").map((t) => t.trim()).filter(Boolean) : undefined,
              actor: actorFromFlags(parsed),
            }],
            caller !== undefined ? { caller: parseCallerKey(caller) } : {},
          );
          emit(result, 0);
        }
        usageAndExit();
        break;
      }
      case "search-session": {
        engine.open();
        const sub = parsed.args[0];
        if (sub === "record") {
          const req = requireArgs(
            parsed,
            ["scope", "intent"],
            "search-session record --scope <key> --intent <query> [--observed-at <iso>] [--evidence engine:ref ...] [--arg candidate=engine:ref ...] [--note N] [--actor-kind human] [--actor-name NAME]",
          );
          const resultRefs = collectEvidence(parsed);
          const candidatePairs = parsed.argPairs.filter((p) => p.startsWith("candidate="));
          const candidateRefs = candidatePairs.map((p) => {
            const raw = p.slice("candidate=".length);
            const colon = raw.indexOf(":");
            return colon > 0 ? { engine: raw.slice(0, colon), ref: raw.slice(colon + 1) } : { engine: "external", ref: raw };
          });
          const session = engine.recordSearchSession({
            scope: req.get("scope"),
            intent: req.get("intent"),
            actor: actorFromFlags(parsed),
            observedAt: req.opt("observed-at"),
            resultRefs,
            candidateRefs: candidateRefs.length > 0 ? (candidateRefs as never) : undefined,
            note: req.opt("note"),
          });
          emit(session, 0);
        }
        if (sub === "list") {
          const limitFlag = parsed.flags.get("limit");
          emit(
            engine.listSearchSessions({
              scope: parsed.flags.get("scope"),
              limit: limitFlag !== undefined ? Number(limitFlag) : undefined,
            }),
            0,
          );
        }
        usageAndExit();
        break;
      }
      case "context": {
        const sub = parsed.args[0];
        engine.open();
        if (sub === "query") {
          const req = requireArgs(
            parsed,
            ["scope"],
            "context query --scope <key> [--size N] [--at <iso>] [--time-from <iso>] [--time-until <iso>] [--kind fact,decision] [--source-kind study_finding] [--min-authority verified_source] [--min-confidence 0.8] [--include-retracted]",
          );
          const kinds = req.opt("kind");
          const sourceKinds = req.opt("source-kind");
          const result = engine.contextQuery({
            scope: req.get("scope"),
            query: req.opt("q"),
            size: parsed.flags.get("size") !== undefined ? Number(parsed.flags.get("size")) : undefined,
            at: req.opt("at"),
            time:
              parsed.flags.get("time-from") !== undefined || parsed.flags.get("time-until") !== undefined
                ? {
                    from: parsed.flags.get("time-from") !== "true" ? parsed.flags.get("time-from") : undefined,
                    until: parsed.flags.get("time-until") !== "true" ? parsed.flags.get("time-until") : undefined,
                  }
                : undefined,
            kinds: kinds !== undefined ? kinds.split(",").map((k) => k.trim()).filter(Boolean) as never : undefined,
            sourceKinds: sourceKinds !== undefined ? sourceKinds.split(",").map((k) => k.trim()).filter(Boolean) as never : undefined,
            minAuthority: req.opt("min-authority") as never,
            minConfidence: parsed.flags.get("min-confidence") !== undefined ? Number(parsed.flags.get("min-confidence")) : undefined,
            includeRetracted: parsed.flags.get("include-retracted") === "true",
          });
          emit(result, 0);
        }
        usageAndExit();
        break;
      }
      case "excerpts": {
        engine.open();
        const sub = parsed.args[0];
        if (sub === "record") {
          const req = requireArgs(parsed, ["id"], "excerpts record --id <recordId> [--max-content-chars N] [--include-sensitive]");
          emit(
            engine.memoryExcerpt(req.get("id"), {
              maxContentChars: parsed.flags.get("max-content-chars") !== undefined ? Number(parsed.flags.get("max-content-chars")) : undefined,
              includeSensitive: parsed.flags.get("include-sensitive") === "true",
            }),
            0,
          );
        }
        const req = requireArgs(parsed, ["scope"], "excerpts --scope <key> [--max-excerpts N] [--max-content-chars N] [--include-sensitive] [--min-authority tier] [--min-confidence 0.8]");
        emit(
          engine.contextExcerpts({
            scope: req.get("scope"),
            maxExcerpts: parsed.flags.get("max-excerpts") !== undefined ? Number(parsed.flags.get("max-excerpts")) : undefined,
            maxContentChars: parsed.flags.get("max-content-chars") !== undefined ? Number(parsed.flags.get("max-content-chars")) : undefined,
            includeSensitive: parsed.flags.get("include-sensitive") === "true",
            minAuthority: req.opt("min-authority") as never,
            minConfidence: parsed.flags.get("min-confidence") !== undefined ? Number(parsed.flags.get("min-confidence")) : undefined,
          }),
          0,
        );
        break;
      }
      case "mcp": {
        // MCP stdio server: read-only tools by default; mutations only with
        // --allow-mutations (separately permissioned; each mutation logs
        // origin "mcp" and flows through the scope mutation policy).
        engine.open();
        runMcpServer(engine, { allowMutations: parsed.flags.get("allow-mutations") === "true" });
        break;
      }
      case "privacy": {
        engine.open();
        const sub = parsed.args[0];
        if (sub === "isolation") {
          const mode = parsed.flags.get("mode");
          if (mode !== "strict" && mode !== "open") {
            fail({ code: "MEMORY_VALIDATION_FAILED", message: "--mode must be strict or open" }, 2);
          }
          engine.setProjectIsolation(mode);
          emit(engine.policyStatus(), 0);
        }
        if (sub === "content-policy") {
          const req = requireArgs(parsed, ["scope"], "privacy content-policy --scope <key> [--forbid-sensitive] [--exportable public,internal]");
          engine.setScopePrivacyPolicy(req.get("scope"), {
            content: {
              exportable: (req.opt("exportable") ?? "public,internal").split(",").map((c) => c.trim()).filter((c) => c === "public" || c === "internal") as never,
              forbidSensitive: parsed.flags.get("forbid-sensitive") === "true",
            },
          });
          emit(engine.policyStatus(), 0);
        }
        emit(engine.policyStatus(), 0);
        break;
      }
      case "trust": {
        engine.open();
        emit(engine.contentBoundaryStatus(), 0);
        break;
      }
      case "backup": {
        engine.open();
        const sub = parsed.args[0];
        if (sub === "create") {
          const path = parsed.flags.get("path");
          if (path !== undefined && path !== "true") {
            emit(engine.backupToFile(path), 0);
          }
          emit(engine.backup(), 0);
        }
        if (sub === "restore") {
          const path = parsed.flags.get("path");
          if (path === undefined || path === "true") {
            fail({ code: "MEMORY_VALIDATION_FAILED", message: "backup restore --path <file> is required" }, 2);
          }
          const raw = readFileSync(path, "utf8");
          emit(engine.restoreBundle(JSON.parse(raw)), 0);
        }
        if (sub === "verify") {
          const path = parsed.flags.get("path");
          if (path === undefined || path === "true") {
            fail({ code: "MEMORY_VALIDATION_FAILED", message: "backup verify --path <file> is required" }, 2);
          }
          const raw = readFileSync(path, "utf8");
          emit(engine.verifyBackup(JSON.parse(raw)), 0);
        }
        emit(engine.verifyStoreReferences(), 0);
        break;
      }
      case "health": {
        engine.open();
        emit(engine.memoryHealth(), 0);
        break;
      }
      case "corpus": {
        engine.open();
        const sub = parsed.args[0];
        const includeEmbeddings = parsed.flags.get("no-embeddings") !== "true";
        if (sub === "build") {
          const result = engine.buildQualificationCorpus({ includeEmbeddings });
          const path = parsed.flags.get("path");
          if (path !== undefined && path !== "true") {
            writeFileSync(path, JSON.stringify(result, null, 2), "utf8");
          }
          emit(result, 0);
        }
        if (sub === "verify") {
          const report = engine.verifyQualificationCorpus({ includeEmbeddings });
          const path = parsed.flags.get("path");
          if (path !== undefined && path !== "true") {
            writeFileSync(path, JSON.stringify(report, null, 2), "utf8");
          }
          emit(report, report.passed ? 0 : 1);
        }
        fail(
          {
            code: "MEMORY_VALIDATION_FAILED",
            message: "corpus requires a subcommand: corpus build|verify [--no-embeddings] [--path <file>]",
          },
          2,
        );
        break;
      }
      case "evaluate": {
        engine.open();
        const sub = parsed.args[0];
        if (sub === "retrieval") {
          const includeSemantic = parsed.flags.get("no-semantic") !== "true";
          const report = engine.evaluateRetrieval({ includeSemantic });
          const path = parsed.flags.get("path");
          if (path !== undefined && path !== "true") {
            writeFileSync(path, JSON.stringify(report, null, 2), "utf8");
          }
          emit(report, report.passed ? 0 : 1);
        }
        fail(
          { code: "MEMORY_VALIDATION_FAILED", message: "evaluate requires: evaluate retrieval [--no-semantic] [--path <file>]" },
          2,
        );
        break;
      }
      case "gate": {
        const report = runProductTruthGate();
        const path = parsed.flags.get("path");
        if (path !== undefined && path !== "true") {
          writeFileSync(path, JSON.stringify(report, null, 2), "utf8");
        }
        emit(report, report.passed ? 0 : 1);
        break;
      }
      case "qualify": {
        engine.open();
        const sub = parsed.args[0];
        if (sub === "lineage") {
          const report = engine.qualifyContradictionSupersession();
          const path = parsed.flags.get("path");
          if (path !== undefined && path !== "true") {
            writeFileSync(path, JSON.stringify(report, null, 2), "utf8");
          }
          emit(report, report.passed ? 0 : 1);
        }
        if (sub === "recovery") {
          const report = engine.qualifyRecovery();
          const path = parsed.flags.get("path");
          if (path !== undefined && path !== "true") {
            writeFileSync(path, JSON.stringify(report, null, 2), "utf8");
          }
          emit(report, report.passed ? 0 : 1);
        }
        fail(
          { code: "MEMORY_VALIDATION_FAILED", message: "qualify requires: qualify lineage|recovery [--path <file>]" },
          2,
        );
        break;
      }
      default:
        usageAndExit();
    }
  } catch (err) {
    if (err instanceof MemoryEngineError) {
      fail({ code: err.code, message: err.message }, 1);
    }
    fail(
      {
        code: "MEMORY_ENGINE_UNEXPECTED",
        message: err instanceof Error ? err.message : String(err),
      },
      1,
    );
  } finally {
    engine?.close();
  }
}

function emit(value: unknown, exitCode: number): never {
  process.stdout.write(`${JSON.stringify(value, null, 2)}\n`);
  process.exit(exitCode);
}

const RECORD_KINDS = ["fact", "decision", "preference", "observation", "note"] as const;
const EPISTEMIC_CLASSES = ["observed", "derived", "inferred", "recommendation", "unknown"] as const;
const PRIVACY_CLASSES = ["public", "internal", "sensitive"] as const;
const STATUSES = ["active", "superseded", "retracted", "expired", "archived", "deleted", "all"] as const;

function recordKindFlag(value: string | undefined, fallback: (typeof RECORD_KINDS)[number]) {
  const v = value ?? fallback;
  if (!RECORD_KINDS.includes(v as (typeof RECORD_KINDS)[number])) {
    fail({ code: "MEMORY_VALIDATION_FAILED", message: `--kind must be one of ${RECORD_KINDS.join(", ")}` }, 2);
  }
  return v as (typeof RECORD_KINDS)[number];
}

function epistemicFlag(value: string | undefined, fallback: (typeof EPISTEMIC_CLASSES)[number]) {
  const v = value ?? fallback;
  if (!EPISTEMIC_CLASSES.includes(v as (typeof EPISTEMIC_CLASSES)[number])) {
    fail({ code: "MEMORY_VALIDATION_FAILED", message: `--epistemic must be one of ${EPISTEMIC_CLASSES.join(", ")}` }, 2);
  }
  return v as (typeof EPISTEMIC_CLASSES)[number];
}

function privacyFlag(value: string | undefined) {
  if (value === undefined) return undefined;
  if (!PRIVACY_CLASSES.includes(value as (typeof PRIVACY_CLASSES)[number])) {
    fail({ code: "MEMORY_VALIDATION_FAILED", message: `--privacy must be one of ${PRIVACY_CLASSES.join(", ")} ('secret' is never storable)` }, 2);
  }
  return value as (typeof PRIVACY_CLASSES)[number];
}

function statusFlag(value: string | undefined, fallback: (typeof STATUSES)[number]) {
  const v = value ?? fallback;
  if (!STATUSES.includes(v as (typeof STATUSES)[number])) {
    fail({ code: "MEMORY_VALIDATION_FAILED", message: `--status must be one of ${STATUSES.join(", ")}` }, 2);
  }
  return v as (typeof STATUSES)[number];
}

const SOURCE_KINDS = [
  "user_note",
  "study_finding",
  "performance_evidence",
  "analysis_evidence",
  "search_session",
  "repository_evidence",
  "external_document",
  "agent_summary",
  "agent_inference",
  "unknown",
] as const;

function sourceKindFlag(value: string | undefined) {
  if (value === undefined) return undefined;
  if (!SOURCE_KINDS.includes(value as (typeof SOURCE_KINDS)[number])) {
    fail({ code: "MEMORY_VALIDATION_FAILED", message: `--source-kind must be one of ${SOURCE_KINDS.join(", ")}` }, 2);
  }
  return value as (typeof SOURCE_KINDS)[number];
}

function usageAndExit(): never {
  process.stderr.write(
    [
      "usage: memory-engine <command> [options]",
      "",
      "commands:",
      "  doctor                                        store health + migrations",
      "  events [--limit N]                            recent engine events",
      "  scope create --key K --name N                 create/reuse a project scope",
      "  scope get --key K                             fetch scope by projectKey/scopeId",
      "  scope mutation-policy --key K --mode open|restricted [--allow A ...]   explicit mutation authorization",
      "  record add --scope K --subject S --content T  add a memory record",
      "  record user-note --scope K --subject S --content T [--kind note|decision]  explicit user-authored note/decision (stronger subjective authority)",
      "  record get --id ID                            fetch a record",
      "  record revise --id ID --content T             revise an active record",
      "  record supersede --id ID --content T          supersede with a new record",
      "  record retract --id ID --reason R             retract a record",
      "  record search [--scope K] [--subject S] [--q T] [--tag T] [--status ST]",
      "  record search --as-of <iso> [--scope K]       historical belief at T",
      "  record current --scope K [--subject S]        validity-aware current view, with trace",
      "  record ranked --q T [--scope K]                provenance-aware ranked search",
      "  record fused --q T [--scope K] [--tag T]       explainable multi-signal fusion",
      "  dedup analyze --scope K --subject S --content T  duplicate vs corroboration",
      "  dedup candidates --scope K                     scan intake stream for duplicates",
      "  record history --id ID                        revisions + supersession chain",
      "  record related --id ID [--direction out|in|both]   outgoing/incoming relations + supersession",
      "  relation add --id ID --type T --target TGT --method M   attributed typed relation",
      "  relation remove --id ID --type T --target TGT           remove a typed relation",
      "  entities --scope K [--rebuild]                          derived entity projection",
      "  embeddings status|build|rebuild --scope K [--include-sensitive]   optional semantic projection",
      "  semantic search --q T [--scope K] [--limit N]     cosine-ranked semantic search",
      "  graph --scope K [--rebuild]                     derived relationship-graph projection",
      "  graph traverse --scope K --start NODE [--types a,b] [--max-depth N]   bounded graph traversal",
      "  record hybrid --q T [--scope K]                 hybrid lexical+semantic+relation retrieval",
      "  projections check|rebuild|repair [--scope K]   index integrity + rebuild/corruption recovery",
      "  performance propose --scope K --subject S --content T --evidence perf:ID   Performance lesson → proposal",
      "  study propose --scope K --kind finding|annotation --study ID --version V --source-revision R --subject S --content T   Study finding/annotation → proposal",
      "  analysis propose --scope K --subject S --content T --evidence analysis:ID   Analysis architectural finding → proposal",
      "  search-session record|list [--scope K] --intent Q    store/list search intent history (retrieval context)",
      "  context query --scope K [--size N] [--at <iso>]      bounded context-oriented retrieval (provenance-rich)",
      "  excerpts --scope K [--max-excerpts N] [--max-content-chars N] [--include-sensitive]   bounded context-safe excerpts",
      "  mcp [--allow-mutations]                            MCP stdio server (read tools; mutations separately permissioned)",
      "  privacy status|isolation --mode strict|open|content-policy --scope K [--forbid-sensitive]   privacy posture",
      "  trust status                                     content-trust boundary (content is data, never policy)",
      "  backup create [--path F] | restore --path F | verify --path F | verify-references   backup/restore/integrity",
      "  health                                           operational health + retrieval quality",
      "  record explain --id ID [--at <iso>]           provenance/authority/validity/",
      "                                                 contradiction/evidence-gap explanation",
      "  contract call --operation <op> [--request '<json>' | --arg k=v ...] [--version X.Y.Z]",
      "  candidate add --scope K --subject S --content T",
      "  candidate promote --id ID",
      "  contradiction register --scope K --subject S --arg record=ID --arg record=ID2 [...]   group ≥2 records as a contradiction",
      "  contradiction resolve --id GROUPID --action supersede|retract --winner ID --reason R",
      "",
      "global: --store <path>   store location (default: data/memory-engine.db,",
      "                        override via MIDNIGHT_MEMORY_STORE; legacy",
      "                        LIBRARY_MEMORY_STORE still honored, deprecated)",
      "actor:  --actor-kind human|agent|engine|tool --actor-name NAME --agent-type TYPE",
    ].join("\n") + "\n",
  );
  process.exit(2);
}

function isMainModule(): boolean {
  try {
    return realpathSync(process.argv[1] ?? "") === fileURLToPath(import.meta.url);
  } catch {
    return false;
  }
}

if (isMainModule()) {
  main(process.argv.slice(2));
}
