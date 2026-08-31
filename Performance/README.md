# Midnight Performance

Midnight Performance is a development-history intelligence core. It records
evidence observed during normal developer and coding-agent work; it does not
host coding agents, modify prompts, or own repository truth.

The package is deliberately stdlib-only and file-backed so its contracts can be
used before a product persistence layer exists. The append-only ledger is the
canonical owner of accepted raw and normalized Performance observations.
Repository/VCS captures and verification observations remain separate evidence
types, while episodes and analysis are rebuildable projections over that ledger.

## Contract boundaries

* Every record has a versioned, typed Performance identity and an explicit
  claim qualification (`observed`, `derived`, `inferred`, `statistical`,
  `predicted`, `recommended`, or `unknown`).
* External systems are represented only by versioned references. The contract
  grants no database access and does not copy sibling-product authority.
* A `ChangeSet` is Performance's durable observation of repository changes; it
  is not a universal source-code graph.
* Episodes correlate prompt runs, agent runs, changes, verifications, feedback,
  and outcomes. Rebuilding the projection is deterministic and does not alter
  raw evidence.
* A provider-neutral observation envelope preserves raw, normalized, and
  derived layers, with narrow OpenTelemetry GenAI import/export mappings.
* Durable writes are project-isolated and policy-gated. Field-level categories
  independently control prompts, model output, source/diff content, commands,
  tools, transcripts, repository metadata, sibling references, PII, secrets,
  and credentials. Unclassified fields fail closed; recognised secrets and PII
  are locally redacted. Export is disabled unless the policy explicitly allows
  it; transcript/debug content should use the `transcript` category.
* Coding-harness adapters are observation declarations, not launchers. The
  Codex adapter only normalizes supplied approved-hook, app-server, or SDK
  event dictionaries; unsupported fields remain explicit evidence gaps.

Run the verification suite with `python -m unittest discover -s tests -v`.
