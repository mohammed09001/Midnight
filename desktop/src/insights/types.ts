/**
 * Wire types for `insights.getTerminalCard`'s response — mirrors
 * `Performance/midnight_performance/schemas/project-insight-response.schema.json`
 * field-for-field. `repo_intelligence_bridge.py`'s `decide_terminal_card`
 * output is deliberately single-candidate: at most one current insight is
 * ever surfaced for a project at a time (Repo Intelligent's "Attention
 * Budget" principle — optimize attention, not insight count), never a list.
 * `card`/`insight` are null together exactly as often as they carry a real
 * single insight; there is no third state.
 */

export type InsightOutcome = "opened" | "saved" | "dismissed";

export interface ProjectInsight {
  readonly identity: string;
  readonly exposureId: string;
  readonly statement: string;
  readonly claimKind: string;
  readonly confidence: number | null;
  readonly uncertainty: string;
  readonly whyNow: string;
  readonly projectConnection: string;
  readonly nextLearningAction: string;
  readonly externalConnection: string | null;
  readonly evidenceBundle: string;
  readonly lineageReceipt: string | null;
  readonly channel: string;
  readonly outcome: string;
}

export interface TerminalCardDocument {
  readonly version: 1;
  readonly project: string;
  readonly generatedAt: string;
  readonly card: string | null;
  readonly reason: string;
  readonly insight: ProjectInsight | null;
}

export interface InsightFeedbackResult {
  readonly version: 1;
  readonly project: string;
  readonly recorded: true;
  readonly outcome: string;
}
