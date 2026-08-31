# Midnight 101

- **Project:** Midnight
- **Document:** Midnight 101
- **Version:** 1.0
- **Created:** 28 August 2026
- **Status:** Living Architecture and Product Reference
- **Current interaction priority:** CLI-first
- **Future interaction layer:** Midnight Desktop
- **Architecture generation:** New-Midnight / Post-Midnight-Code
- **Purpose:** Provide one editable reference explaining what Midnight is now, how its products fit together, how the CLI should work, what is authoritative, and which parts are intentionally evolvable.

---

# 1. What Midnight Is Now

Midnight is no longer a coding-agent host, a GraphRAG product, or a control plane that requires developers to run Claude Code, Codex, OpenCode, or another coding agent *through* Midnight.

Midnight is an **intelligence layer around the software lifecycle**.

Its job is to observe different parts of software development and operation, preserve trustworthy evidence, correlate evidence across time and domains, build durable domain memory, and provide intelligence when the user asks for it.

The shortest current definition is:

> **Midnight observes development, runtime, data, and security; preserves evidence and memory for each domain; connects verified outcomes over time; and helps the user understand what happened, why it may have happened, and what should be investigated or improved next.**

The current product family is:

- **Midnight Performance**
  - development-history intelligence;
  - prompt and coding-agent execution observation;
  - actual repository-change evidence;
  - verification and user feedback;
  - development Episodes;
  - historical learning and Performance Memory.

- **Midnight Security**
  - security discovery and scanning;
  - findings and vulnerabilities;
  - attack surface and attack paths;
  - risk and prioritization;
  - remediation tracking;
  - deterministic re-verification;
  - Security Memory.

- **Midnight Watch**
  - umbrella for operational/runtime intelligence.

  - **Midnight Watch Runtime**
    - application-runtime truth;
    - Errors, Issues, Logs, Events, Traces, Metrics;
    - Releases and Deployments;
    - Signals, Alerts, Investigations;
    - Watch Runtime Memory.

  - **Midnight Watch Data**
    - data architecture and data-runtime truth;
    - schemas, relationships, query families, plans, indexes;
    - transactions, locks, connections, storage and database resources;
    - data cost, regressions, recommendations and verification;
    - Watch Data Memory.

Each capability must be useful on its own. Installing one product must not silently require every other product.

---

# 2. What Ended

The following ideas belong to the retired Midnight architecture and are not foundations of the new platform:

- Midnight Code as a user-facing GraphRAG/code-context product.
- A universal Code Graph as the center of Midnight.
- GraphRAG as a mandatory retrieval architecture.
- Midnight launching or hosting Claude Code, Codex, Gemini, or OpenCode for normal development.
- Provider authentication owned by Midnight for the normal coding workflow.
- Git-worktree multi-agent execution as the core Midnight identity.
- A planner that breaks the user's coding goal into agent tasks and runs the agents.
- A merge manager that merges agent work because Midnight hosted the agents.
- One universal Midnight database, memory, or graph owning every domain.

Useful ideas from the old architecture survive only where they remain general engineering principles:

- deterministic state machines;
- capability contracts;
- verification gates;
- provenance;
- evidence ledgers;
- failure isolation;
- bounded retries;
- workflow DAGs where a cross-product workflow genuinely needs them.

---

# 3. The Core Operating Principle

> **Midnight is invisible by default, explicit by choice.**

A developer should be able to:

- open a project;
- run Claude Code, Codex, OpenCode, an IDE, or another coding harness normally;
- write ordinary prompts;
- build, test, run, deploy, and debug normally;
- receive Midnight intelligence without being forced to put Midnight in the middle of the workflow.

Midnight attaches to the project and to approved evidence surfaces.

It does not force the user to work inside Midnight.

---

# 4. Passive Intelligence and Active Intelligence

Midnight should separate passive observation from active interaction.

## Passive Intelligence

Passive mode may:

- capture;
- normalize;
- redact;
- store;
- index;
- correlate;
- detect;
- analyze;
- preserve provenance;
- build domain Memory;
- update derived relationship/vector projections.

Passive mode must not silently:

- rewrite user prompts;
- submit prompts;
- run coding agents;
- apply code changes;
- accept Security risk;
- change production databases;
- close findings without verification;
- claim causation from temporal correlation.

## Active Intelligence

Active mode begins when the user explicitly asks Midnight to do something.

Examples include:

- inspect development history;
- compare two Prompt Runs;
- explain why a change caused rework;
- investigate a runtime regression;
- query Watch Data about a slow query;
- run a Security scan;
- review a finding;
- generate a remediation prompt;
- compare before/after evidence;
- retrieve durable Memory.

---

# 5. Evidence Before Intelligence

Every Midnight product follows the same epistemic rule:

> **Evidence is not the same thing as interpretation.**

Examples:

- an agent saying “I changed auth.ts” is not stronger than the repository's actual final state;
- a code change is not a Verified Change;
- a scanner saying “fixed” does not close a vulnerability;
- a recommendation is a hypothesis until verification;
- a vector-neighbor is not proof of equivalence;
- a graph path is not automatic causation;
- absence of telemetry is not proof that nothing happened;
- user feedback is important but subjective;
- model output is not authoritative product truth.

Midnight should preserve:

- raw/accepted evidence;
- normalized evidence;
- derived analysis;
- method/version;
- provenance;
- confidence;
- unknown and degraded states.

---

# 6. Product Ownership

Midnight uses strong domain ownership.

## Performance owns development-history truth

Performance owns the history it captures around:

- Prompt;
- Prompt Run;
- Agent Run;
- tool/command observations;
- repository baselines and Change Sets;
- verification;
- user feedback;
- Episode;
- Performance analysis and Memory.

The repository/VCS/filesystem remains the underlying source of actual repository state.

## Watch Runtime owns application-runtime truth

Watch Runtime owns:

- Errors and Error Occurrences;
- Issues;
- Logs;
- Events;
- Traces and Spans;
- application/runtime Metrics;
- Releases and Deployments;
- Signals and Alerts;
- Investigations;
- Runtime Memory.

## Watch Data owns data-domain truth

Watch Data owns:

- database/schema structure;
- relationships;
- query fingerprints and families;
- query runtime;
- query plans;
- indexes;
- transactions;
- locks and waits;
- connections;
- database resource behavior;
- storage and growth;
- data cost;
- data regressions;
- optimization hypotheses and verification;
- Data Memory.

## Security owns security truth

Security owns:

- Security Scans;
- scanner/rule evidence;
- Findings;
- Vulnerabilities;
- Attack Surface and Attack Paths;
- risk and accepted-risk state;
- remediation;
- deterministic verification;
- Security Memory.

The common boundary is:

> **Reference does not equal ownership.**

A product may link to another product's evidence through a stable reference or API contract. It must not silently become owner of that sibling's truth.

---

# 7. Memory Architecture

Midnight does not need one giant Memory.

Each product owns logical Memory domains relevant to its job.

Performance may maintain:

- Prompt Memory;
- Agent Execution Memory;
- Change Memory;
- Verification Memory;
- Outcome Memory;
- Episode Memory;
- Performance Knowledge Memory.

Security may maintain:

- Finding History;
- Remediation Memory;
- Verification Memory;
- Security Knowledge Memory.

Watch Runtime may maintain:

- Issue and Investigation history;
- operational patterns;
- Runtime Knowledge Memory.

Watch Data may maintain:

- schema/change history;
- query/workload history;
- optimization/verification history;
- Data Knowledge Memory.

A logical Memory domain does **not** imply a separate physical database.

---

# 8. Relational, Vector, and Graph Roles

The preferred new Midnight retrieval architecture is multi-view.

- **Relational / SQL storage**
  - exact identities;
  - timestamps;
  - structured entities;
  - status;
  - metrics;
  - provenance;
  - deterministic joins inside one product boundary.

- **Vector indexes**
  - semantic similarity;
  - similar prompts;
  - similar development Episodes;
  - similar findings or evidence when a domain supports it.

- **Relationship graphs**
  - lineage;
  - causally relevant chains;
  - multi-hop relationships;
  - attack paths;
  - data relationships;
  - Prompt → Agent Run → Change → Verification → Outcome relationships.

Graph and Vector systems are derived indexes/projections over evidence.

> **GraphRAG is not a required Midnight foundation.**

GraphRAG may be evaluated later only if benchmarks show that it improves real Midnight questions beyond direct graph traversal + vector + relational/lexical retrieval.

---

# 9. Current CLI-First Product Strategy

The current engineering focus is **Midnight CLI**.

Midnight Desktop is a future interaction client, not a separate intelligence architecture.

The CLI should own:

- installation/bootstrap;
- project initialization;
- capability enable/disable;
- configuration;
- connector/adapter setup;
- health and diagnostics;
- explicit queries and scans;
- evidence inspection;
- status;
- export;
- local/self-host operations.

The CLI should **not** become:

- a wrapper required to launch Claude/Codex;
- an agent terminal multiplexer;
- a provider credential owner;
- a mandatory orchestration shell.

The future Desktop should consume the same capability contracts, APIs, evidence stores, and policies as the CLI.

---

# 10. Target CLI UX — Evolvable Contract

The commands below describe the **target interaction model**. They are intentionally evolvable and must be reconciled with the real repository before implementation. A command shown here is not proof that it already exists.

## Project initialization

```bash
midnight init
```

The intended result is:

- identify the current project/workspace;
- create or reconcile Midnight project configuration;
- establish stable project identity;
- show available capabilities;
- default to no hidden destructive behavior.

## Capability discovery

```bash
midnight capabilities
midnight status
midnight doctor
```

These should explain:

- which Midnight products are enabled;
- which adapters/connectors are available;
- which permissions are missing;
- which evidence paths are healthy/degraded/unavailable;
- which provider/harness integrations require approval;
- whether storage, collectors, SDKs, or scanners are healthy.

## Enable Performance

Illustrative target:

```bash
midnight enable performance
midnight performance attach claude
midnight performance attach codex
midnight performance attach opencode
```

The desired behavior is to register or configure supported native hooks/plugins/events.

After attachment the user continues to run:

```bash
claude
codex
opencode
```

normally.

Performance observes only approved evidence and never requires:

```bash
midnight run claude
```

as the normal product workflow.

## Enable Watch Runtime

Illustrative target:

```bash
midnight enable watch-runtime
midnight watch runtime configure
midnight watch runtime status
```

Watch Runtime may then receive evidence from:

- Midnight SDKs;
- OpenTelemetry;
- log/event sources;
- release/deployment integrations;
- supported runtime collectors.

The monitored application must remain independent of Watch availability.

## Enable Watch Data

Illustrative target:

```bash
midnight enable watch-data
midnight watch data connect postgres
midnight watch data inspect-access
midnight watch data status
```

Before continuous collection, Watch Data should make permission and collection behavior visible.

Default posture:

- read-only;
- metadata first;
- aggregate runtime evidence;
- parameter/literal redaction;
- no raw-row access;
- no mutation authority.

## Enable Security

Illustrative target:

```bash
midnight enable security
midnight security discover
midnight security scan
midnight security status
```

Security discovers the project surface, chooses relevant scanner capabilities, executes within policy/resource/sandbox boundaries, normalizes evidence, and produces findings.

A later command may verify a remediation:

```bash
midnight security verify
```

but closure is based on deterministic evidence rather than a coding agent claiming the fix is complete.

## Query Midnight

Illustrative active interactions:

```bash
midnight performance history
midnight performance explain <episode-or-change>
midnight watch issues
midnight watch investigate <issue>
midnight watch data queries
midnight watch data explain <query-family>
midnight security findings
midnight security explain <finding>
midnight security verify <finding>
```

A future unified query surface may exist:

```bash
midnight ask "Why did authentication change so much this week?"
```

The implementation may choose a different syntax. The important contract is the capability/ownership model, not the exact command spelling.

---

# 11. Installation Model

The exact package-distribution mechanism remains evolvable until the repository's packaging strategy is frozen.

Midnight should support a predictable install experience through one or more of:

- package-manager installation;
- standalone signed binary;
- platform-specific installer;
- development/source installation.

Installation should not automatically:

- connect external AI providers;
- scan private repositories remotely;
- read databases;
- enable DAST;
- modify production;
- register coding-agent hooks without transparent user approval where the provider requires it.

Installation and project enablement are separate concepts.

A useful target lifecycle is:

```text
Install Midnight CLI
→ midnight init
→ inspect capabilities
→ enable only desired products
→ grant narrow permissions
→ attach/collect/scan
→ query when desired
```

---

# 12. CLI Configuration

Configuration should be layered and inspectable.

Potential layers:

- global user configuration;
- project configuration;
- capability-specific configuration;
- environment-specific configuration;
- secret references stored outside normal config;
- local overrides excluded from Git when sensitive.

Users should be able to inspect:

- what is enabled;
- what data is collected;
- what leaves the machine/environment;
- what external AI receives;
- what database permissions exist;
- what scanners can execute;
- what alert policies can interrupt them.

Configuration changes should be versionable where they affect evidence interpretation.

---

# 13. Performance Workflow

A normal Performance flow should look like:

```text
Developer opens project
→ Performance is attached
→ Developer runs Claude/Codex/OpenCode normally
→ user submits normal prompt
→ native hook/plugin events are captured when available
→ repository baseline exists
→ tools/commands/file events are observed
→ terminal repository state is reconciled
→ verification is recorded
→ final response is stored as agent evidence
→ user feedback may be captured
→ later Watch/Data/Security outcomes may link to the Episode
→ Memory promotion occurs only when evidence rules permit it
```

Performance can later answer:

- what prompts caused repeated rework;
- which Prompt Runs deleted or changed files;
- which agents worked best for a task class;
- which verification strategies correlate with better outcomes;
- what happened after a particular development change;
- which prior Episodes resemble the current task.

---

# 14. Watch Runtime Workflow

A normal Watch Runtime flow should look like:

```text
Application/SDK/OTel
→ bounded collection
→ privacy/redaction
→ ingestion
→ evidence ledger
→ domain processing
→ Errors / Logs / Events / Traces / Metrics
→ Issues / Signals / Alerts / Investigations
→ verified Runtime Memory
```

Watch should answer:

- what happened to the running application;
- which release/deployment preceded a regression;
- which errors belong to the same Issue;
- which trace/span became slow;
- what runtime evidence supports an investigation.

---

# 15. Watch Data Workflow

A normal Watch Data flow should look like:

```text
Restricted database identity
→ metadata/capability discovery
→ local collection
→ redaction/normalization
→ schema/query/runtime evidence
→ relationship/workload/change intelligence
→ optimization hypothesis
→ user/external change
→ before/after verification
→ Data Memory
```

Watch Data should answer:

- how the data system is structured;
- how entities relate;
- which query families dominate workload;
- why database latency or cost changed;
- whether an index/query/schema recommendation is justified;
- whether an implemented optimization actually improved the data layer.

---

# 16. Security Workflow

A normal Security flow should look like:

```text
Project discovery
→ relevant scanner selection
→ safe execution plan
→ scanner evidence
→ normalization
→ finding/vulnerability correlation
→ exploitability/reachability/risk
→ remediation
→ deterministic re-scan
→ verification
→ Security Memory
```

Security should answer:

- what was actually scanned;
- what could not be scanned;
- which findings are duplicated/corroborated across scanners;
- which vulnerabilities are reachable or actively exploited;
- what remediation was attempted;
- whether the fix was verified;
- whether the vulnerability later reappeared.

---

# 17. Cross-Product Feedback Loops

The strongest Midnight behavior appears when independent products exchange **bounded references**.

Example:

```text
Performance Change Set
→ Watch Runtime regression
→ Watch Data slow query
→ Security finding
→ remediation prompt/context
→ external coding agent changes repository
→ Performance captures new Episode
→ Watch/Data/Security verify outcome
→ each product updates its own Memory
```

No product becomes the master database.

---

# 18. Midnight Intelligence Orchestration

A future internal orchestration layer may coordinate cross-product workflows.

It may own:

- workflow definition;
- triggers;
- step state;
- capability routing;
- retries;
- waiting for external action;
- verification gates;
- workflow ledger.

It does not own:

- Performance history;
- Watch runtime evidence;
- Watch Data truth;
- Security findings;
- coding-agent provider sessions.

The key state that distinguishes the new orchestration model is:

`WAITING_EXTERNAL_ACTION`

Midnight may generate or surface a remediation prompt, but the user may execute it in Claude Code/Codex normally. The workflow resumes when new Performance/Watch/Data/Security evidence appears.

---

# 19. Storage Philosophy

Start with the simplest storage architecture that satisfies correctness, privacy, and local/self-host requirements.

Specialized stores should appear only when measured workload justifies them.

Possible roles:

- relational database for canonical entities and structured evidence;
- object/blob storage for large artifacts;
- vector index for semantic similarity;
- relationship graph/index for traversal;
- analytical storage only when high-cardinality workload benchmarks justify it.

No storage technology should become Midnight's product identity.

---

# 20. Privacy and Trust

Midnight should minimize the amount of trust the user must grant.

Shared principles:

- least privilege;
- local processing where practical;
- redaction before export;
- explicit capability escalation;
- auditable access;
- revocable integrations;
- self-host/BYOC support;
- external AI optional;
- secrets excluded from ordinary logs/evidence;
- project/tenant isolation.

For Watch Data in particular:

> **The product should remain useful without raw customer data.**

For Performance:

> **Prompts, source, diffs, transcripts, and tool content are sensitive by default.**

For Security:

> **Scanning an untrusted repository must not silently execute it.**

---

# 21. Midnight Desktop

Midnight Desktop is a future client layer.

It should not fork the architecture.

Desktop may eventually provide:

- product/capability setup;
- Performance timelines and Episode maps;
- Watch Issue/Trace/Release views;
- Watch Data schema/query/plan lenses;
- Security findings and attack paths;
- Memory navigation;
- cross-product investigation;
- workflow progress;
- permissions/privacy controls.

The CLI and Desktop should consume the same stable product contracts.

A user should be able to start CLI-first today and move to Desktop later without migrating to a different intelligence model.

---

# 22. What Is Intentionally Evolvable

This document freezes principles more strongly than syntax.

The following remain intentionally editable:

- exact CLI command spelling;
- packaging/distribution channel;
- local storage engine;
- managed-cloud topology;
- event transport;
- graph/vector implementation;
- Desktop UI architecture;
- optional orchestration runtime implementation;
- supported coding harnesses;
- supported database engines after PostgreSQL;
- scanner portfolio;
- external AI providers;
- model-training/fine-tuning/RL export.

The following should change only through an explicit architectural decision:

- product ownership boundaries;
- evidence before interpretation;
- no direct sibling-database ownership coupling;
- invisible-by-default interaction;
- coding agents remain externally operated in the normal workflow;
- verification over agent/scanner prose;
- GraphRAG is not a required foundation;
- Memory is evidence-backed and domain-owned;
- privacy/least-privilege/self-host/BYOC principles.

---

# 23. Current Roadmap Set

The current implementation references are:

- **Midnight Performance Roadmap O2**
  - 152 tasks.
- **Midnight Security Roadmap O1**
  - 106 tasks.
- **Midnight Watch Runtime Roadmap O2**
  - 86 tasks.
- **Midnight Watch Data Roadmap O1**
  - 68 tasks.

The Execution Pack generated beside this document converts these roadmaps into self-contained prompts grouped by dependency, complexity, and implementation coherence.

---

# 24. Final Definition

Midnight should ultimately feel less like another tool the developer must operate and more like a persistent intelligence layer attached to the project.

> **The developer builds normally. Midnight observes the evidence, remembers verified history, connects development to runtime/data/security outcomes, and becomes visible when the user wants understanding or when an explicitly configured policy requires attention.**

This document is intentionally a living reference. Future changes should update:

- **Version**
- **Created / Updated date**
- **Architecture generation**
- **Change summary**

so the project never confuses an older Midnight model with the current one.
