# Midnight Memory

Canonical owner of durable Midnight knowledge: validated MemoryRecords with
provenance, scope, epistemic class, confidence, temporal validity, privacy
class, contradiction groups, and supersession chains.

- **Boundary:** docs/BOUNDARY.md (frozen, contract v1.27.0)
- **Identities:** docs/IDENTITIES.md
- **Canonical schema:** docs/SCHEMA.md
- **Authority:** docs/AUTHORITY.md · **Temporal:** docs/TEMPORAL.md · **Contracts:** docs/CONTRACTS.md
- **Persistence:** docs/PERSISTENCE.md · **Intake:** docs/INTAKE.md · **Promotion:** docs/PROMOTION.md
- **Contradictions:** docs/CONTRADICTIONS.md · **Supersession:** docs/SUPERSESSION.md · **Revisions:** docs/REVISIONS.md
- **Retention:** docs/RETENTION.md · **Retrieval:** docs/RETRIEVAL.md · **Projections:** docs/PROJECTIONS.md
- **Relations:** docs/RELATIONS.md · **Entities:** docs/ENTITIES.md · **Embeddings:** docs/EMBEDDINGS.md · **Graph:** docs/GRAPH.md
- **Performance:** docs/PERFORMANCE.md · **Study:** docs/STUDY.md · **Analysis:** docs/ANALYSIS.md · **Search History:** docs/SEARCH_HISTORY.md · **Context:** docs/CONTEXT.md · **User Notes:** docs/USER_NOTES.md · **Evidence References:** docs/EVIDENCE_REFERENCES.md
- **Excerpts:** docs/EXCERPTS.md · **Privacy:** docs/PRIVACY.md · **Trust:** docs/TRUST.md · **Backup:** docs/BACKUP.md · **Health:** docs/HEALTH.md · **Tools:** docs/TOOLS.md · **Permissions:** docs/PERMISSIONS.md
- **Corpora:** docs/CORPORA.md · **Evaluation:** docs/EVALUATION.md · **Lineage Qualification:** docs/LINEAGE_QUALIFICATION.md · **Recovery Qualification:** docs/RECOVERY_QUALIFICATION.md · **V1 Gate:** docs/PRODUCT_TRUTH_GATE.md
- **Cross-Engine Lineage:** docs/CROSS_ENGINE_LINEAGE.md · **Compatibility Gate:** docs/COMPATIBILITY_GATE.md · **Troubleshooting:** docs/TROUBLESHOOTING.md

Backend/terminal-first, agent-neutral, game-independent. Zero runtime
dependencies (Node.js ≥ 22.13 built-in `node:sqlite`).

## Commands

```powershell
npm run typecheck                                   # tsc --noEmit (strict)
npm test                                            # node --test (297 tests)
npm run cli -- doctor --store data/memory-engine.db # store health
npm run cli -- record search --scope library101 --q "rate limit"          # BM25 lexical
npm run cli -- record current --scope library101 --subject "Rate limit"   # current view
npm run cli -- record timeline --scope library101 --subject "Rate limit"  # evolution
npm run cli -- record ranked --scope library101 --q "rate limit"          # provenance-aware ranking
npm run cli -- record fused --scope library101 --q "rate limit"           # explainable multi-signal fusion
npm run cli -- record hybrid --scope library101 --q "rate limit"          # hybrid lexical+semantic+relation
npm run cli -- dedup analyze --scope library101 --subject "Rate limit" --content "…"  # dup vs corroboration
npm run cli -- record explain --id <recordId> [--at <iso>]                # validity/contradiction/evidence gaps
npm run cli -- record user-note --scope K --subject S --content T --kind decision  # explicit user note/decision (stronger subjective authority)
npm run cli -- relation add --id <recordId> --type applies_to --target entity:component:api-gateway --method classified   # attributed relation
npm run cli -- entities --scope library101                               # derived entity projection
npm run cli -- embeddings build --scope library101 [--include-sensitive] # optional semantic projection (privacy-gated)
npm run cli -- semantic search --q "rate" --scope library101             # cosine-ranked semantic search
npm run cli -- graph --scope library101                                  # derived relationship-graph projection
npm run cli -- graph traverse --scope library101 --start <nodeId> --types supersedes --max-depth 3  # bounded traversal/history
npm run cli -- projections check|rebuild|repair [--scope K]              # index integrity + corruption recovery
npm run cli -- performance propose --scope K --subject S --content T --evidence perf:ID  # Performance lesson → proposal
npm run cli -- study propose --scope K --kind finding --study ID --version V --source-revision R --subject S --content T  # Study finding → proposal
npm run cli -- analysis propose --scope K --subject S --content T --evidence analysis:ID  # Analysis architectural finding → proposal
npm run cli -- search-session record --scope K --intent Q [--evidence engine:ref …]  # search intent history (retrieval context)
npm run cli -- context query --scope K [--size N] [--min-authority verified_source]  # bounded context-oriented retrieval
npm run cli -- record related --id <recordId>       # outgoing/incoming relations + supersession
npm run cli -- scope mutation-policy --key K --mode restricted --allow agent:worker-a  # explicit mutation authorization
npm run cli -- mcp [--allow-mutations]              # MCP stdio server (read tools; mutations separately permissioned)
npm run cli -- excerpts --scope K [--max-excerpts N]  # bounded context-safe excerpts (sensitive excluded/redacted)
npm run cli -- privacy status|isolation --mode strict|open|content-policy --scope K   # privacy posture
npm run cli -- trust status                          # content-trust boundary (content is data)
npm run cli -- backup create --path backup.json      # canonical backup (checksum)
npm run cli -- backup verify --path backup.json      # backup integrity
npm run cli -- health                                # operational health + retrieval quality
npm run cli -- corpus build --store data/memory-engine.db  # materialize the frozen qualification corpus
npm run cli -- corpus verify --store data/memory-engine.db # verify frozen expectations (exit 1 on failure)
npm run cli -- evaluate retrieval --store data/memory-engine.db # precision/recall retrieval evaluation (exit 1 on failure)
npm run cli -- qualify lineage --store data/memory-engine.db  # contradiction/supersession qualification (exit 1 on failure)
npm run cli -- qualify recovery --store data/memory-engine.db # crash/corruption/restore/deletion qualification on scratch stores
npm run cli -- gate run                             # the V1 product-truth gate (exit 1 on any failed clause)
npm run cli -- record search --scope library101 --source-engine study_document --confidence-min 0.9
npm run cli -- contract call --operation memory.lexical --request '{"query":"rate","scope":"library101"}'
npm run cli -- events --limit 10
```

Store location: `data/memory-engine.db` (gitignored) or `MIDNIGHT_MEMORY_STORE`
env var (legacy `LIBRARY_MEMORY_STORE` still honored, deprecated) / `--store` flag.

Note: `node:sqlite` prints an experimental warning on Node 22 — expected.
