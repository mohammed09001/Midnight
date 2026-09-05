import type { InsightOutcome, ProjectInsight, TerminalCardDocument } from "../insights/types";

interface InsightCardProps {
  readonly document: TerminalCardDocument;
  readonly onFeedback: (exposureId: string, outcome: InsightOutcome) => void;
  readonly feedbackPending?: boolean;
  readonly feedbackError?: string | null;
}

/**
 * Renders Repo Intelligent's single "terminal card" for the current project
 * — never a list. `decide_terminal_card` (Python) is deliberately
 * single-candidate: at most one current insight competes for attention at a
 * time (the "Attention Budget" principle — optimize attention, not insight
 * count), matching the progressive-disclosure visual language already
 * established by `GraphHoverPanel`/`GraphInspector`. When there is nothing
 * to show, this renders the honest `reason` rather than an empty list or a
 * fabricated placeholder.
 */
export function InsightCard({ document, onFeedback, feedbackPending, feedbackError }: InsightCardProps) {
  if (document.card === null || document.insight === null) {
    return (
      <div className="insight-card insight-card--empty" role="status">
        <p className="insight-card__empty-reason">{document.reason}</p>
      </div>
    );
  }

  const insight: ProjectInsight = document.insight;

  return (
    <div className="insight-card" role="region" aria-label="Current insight">
      <p className="insight-card__statement">{insight.statement}</p>
      <dl className="insight-card__facts">
        <dt>Why now</dt>
        <dd>{insight.whyNow}</dd>
        <dt>Project connection</dt>
        <dd>{insight.projectConnection}</dd>
        <dt>Next learning action</dt>
        <dd>{insight.nextLearningAction}</dd>
        <dt>Claim</dt>
        <dd>
          {insight.claimKind}
          {insight.confidence !== null ? ` · confidence ${insight.confidence}` : ""} · {insight.uncertainty}
        </dd>
        {insight.externalConnection && (
          <>
            <dt>External connection</dt>
            <dd>{insight.externalConnection}</dd>
          </>
        )}
      </dl>
      <div className="insight-card__actions">
        <button
          type="button"
          className="insight-card__action"
          disabled={feedbackPending}
          onClick={() => onFeedback(insight.exposureId, "opened")}
        >
          Open
        </button>
        <button
          type="button"
          className="insight-card__action insight-card__action--accept"
          disabled={feedbackPending}
          onClick={() => onFeedback(insight.exposureId, "saved")}
        >
          Accept
        </button>
        <button
          type="button"
          className="insight-card__action insight-card__action--dismiss"
          disabled={feedbackPending}
          onClick={() => onFeedback(insight.exposureId, "dismissed")}
        >
          Dismiss
        </button>
      </div>
      {feedbackError && (
        <p className="panel__status" role="alert">
          {feedbackError}
        </p>
      )}
    </div>
  );
}
