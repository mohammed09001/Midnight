# Midnight 101 — CLI-First Execution Pack

- **Created:** 28 August 2026
- **Reference version:** Midnight 101 v1.0
- **Execution pack:** O1 Execution Pack / New-Midnight Architecture
- **Total roadmap tasks covered:** 412
- **Total execution prompts:** 165

## Contents

- `Midnight 101.md`
  - Living reference for the new Midnight architecture, CLI-first operating model, product ownership, installation/use target, Memory, Graph/Vector roles, orchestration boundaries, privacy, and future Desktop.

- `Midnight Performance/`
  - Self-contained Execution prompts compiled from the current Performance roadmap.

- `Midnight Security/`
  - Self-contained Execution prompts compiled from the current Security roadmap.

- `Midnight Watch/Midnight Watch Runtime/`
  - Self-contained Execution prompts compiled from the current Watch Runtime roadmap.

- `Midnight Watch/Midnight Watch Data/`
  - Self-contained Execution prompts compiled from the current Watch Data roadmap.

## Execution Prompt Rules

Every generated prompt:

- embeds the source Task requirements directly;
- does not require the coding agent to access the roadmap;
- uses Parent Loop + Child Loop execution;
- requires Ground Truth → Deep Questions → Plan → Execute → Verify → Review → Repair → Final Goal Gate;
- is portable across Claude Code CLI, Codex CLI, OpenCode CLI, and similar repository-capable agents;
- is repository-first and preserves unrelated user work;
- prevents fake completion;
- explicitly guards against dead/duplicate/superseded code;
- preserves the current New-Midnight product boundaries.

## Grouping

Tasks are grouped only within the same roadmap phase.

An Execution may contain:

- one heavy or boundary-sensitive Task;
- two tightly coupled Tasks;
- three related Tasks;
- occasionally four lightweight sequential Tasks.

No fixed task count was imposed.
