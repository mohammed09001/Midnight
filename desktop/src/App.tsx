import { useEffect, useMemo, useState } from "react";
import { ActivityMap } from "./components/ActivityMap";
import { GranularityControl } from "./components/GranularityControl";
import { PromptRunSelector } from "./components/PromptRunSelector";
import { PerformanceGraph } from "./components/PerformanceGraph";
import { activityRangeForEvents, aggregateActivity, eventsInBucket } from "./activity/aggregate";
import { loadActivity, resolveActivitySource } from "./activity/adapter";
import { formatBucketPeriod, formatPrompts } from "./activity/format";
import { todayKey } from "./activity/localDate";
import type { ActivityBucket, ActivityEvent, ActivityMapData, Granularity } from "./activity/types";
import { fetchPromptRunGraph } from "./graph/graphSource";
import { PerformanceHostError } from "./activity/performanceSource";
import type { PromptRunGraphDocument } from "./graph/types";
import { fetchTerminalCard, recordInsightFeedback } from "./insights/insightSource";
import { InsightCard } from "./components/InsightCard";
import type { InsightOutcome, TerminalCardDocument } from "./insights/types";

const GRANULARITIES: readonly Granularity[] = ["day", "week", "month"];

/**
 * Execution 10, Section A: the default Prompt-scoped slice never sends a
 * full project graph — a bounded hop count from the root keeps the initial
 * view legible as history grows, with `onExpandNode` (below) revealing more
 * around a specific node on demand rather than widening this default.
 */
const DEFAULT_GRAPH_MAX_DEPTH = 3;

function readInitialGranularity(): Granularity {
  const param = new URLSearchParams(window.location.search).get("g");
  return GRANULARITIES.includes(param as Granularity) ? (param as Granularity) : "day";
}

function readInitialSelectionKey(): string | null {
  return new URLSearchParams(window.location.search).get("sel");
}

function readInitialRunId(): string | null {
  return new URLSearchParams(window.location.search).get("run");
}

/**
 * Execution 08: a dev-only escape hatch for Visible Verification. The real
 * Desktop Host deliberately never accepts caller-supplied structural
 * evidence over HTTP (see `graph_bridge.py`'s `resolved_entities` — Python-
 * function-only, no CLI flag, no Host/IPC change; Desktop must never become
 * a second evidence owner) — so there is no live-flow path to render a
 * document produced with `resolved_entities` (real repository/file/symbol
 * depth). `?fixtureUrl=` lets a real, offline-generated, schema-validated
 * document (e.g. from `generate_repository_entity_fixture.py`) be rendered
 * directly by the real `<PerformanceGraph>` component for a real screenshot.
 * `import.meta.env.DEV`-gated — stripped from production builds entirely.
 */
function readDevFixtureUrl(): string | null {
  if (!import.meta.env.DEV) return null;
  return new URLSearchParams(window.location.search).get("fixtureUrl");
}

/**
 * Execution 07: which of the three activity → run-select → graph steps is
 * showing. Purely additive alongside `ActivityState`/`selected` below —
 * neither's own phases or rendering change, so the Activity Map keeps
 * behaving exactly as it did before this execution.
 */
type View =
  | { kind: "activity" }
  | { kind: "run-select"; bucket: ActivityBucket }
  | { kind: "graph"; promptRunId: string }
  | { kind: "insights" };

type GraphState =
  | { phase: "loading" }
  | { phase: "ready"; document: PromptRunGraphDocument }
  | { phase: "not-found" }
  | { phase: "unavailable"; reason: string };

/**
 * Execution 12: Repo Intelligent's single terminal insight card for the
 * current project. `decide_terminal_card` is deliberately single-candidate
 * — there is no "list" ready state, only one document (which may itself
 * carry `card: null` for an honest "nothing to show" state) or unavailable.
 */
type InsightState =
  | { phase: "loading" }
  | { phase: "ready"; document: TerminalCardDocument }
  | { phase: "unavailable"; reason: string };

/**
 * Truthful Activity Map data states: loading, real evidence, empty real
 * history, unavailable source, or explicit development fixture mode.
 * Fixture data is never presented as Performance history.
 */
type ActivityState =
  | { phase: "loading" }
  | {
      phase: "ready";
      kind: "fixture" | "performance";
      events: readonly ActivityEvent[];
      partialHistory: boolean;
      warnings: readonly string[];
    }
  | { phase: "unavailable"; reason: string };

/**
 * Desktop shell for Execution 02: product identity, the Activity Map over
 * real Midnight Performance Prompt Run evidence, and the Day / Week / Month
 * granularity control — nothing else by design.
 */
export default function App() {
  const [granularity, setGranularity] = useState<Granularity>(readInitialGranularity);
  const [selected, setSelected] = useState<ActivityBucket | null>(null);
  const [state, setState] = useState<ActivityState>({ phase: "loading" });
  const [pendingSelectionKey] = useState<string | null>(readInitialSelectionKey);
  const [view, setView] = useState<View>({ kind: "activity" });
  const [graphState, setGraphState] = useState<GraphState>({ phase: "loading" });
  // Execution 10, Section A (neighborhood expansion): which node, if any,
  // the user asked to see more around. Reset whenever `view` itself changes
  // (a fresh Prompt Run selection should never inherit a previous run's
  // expansion target).
  const [focusNode, setFocusNode] = useState<string | null>(null);
  const [pendingRunId] = useState<string | null>(readInitialRunId);
  const [insightState, setInsightState] = useState<InsightState>({ phase: "loading" });
  const [feedbackPending, setFeedbackPending] = useState(false);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);
  const [devFixtureUrl] = useState<string | null>(readDevFixtureUrl);
  const [devFixtureState, setDevFixtureState] = useState<
    { phase: "loading" } | { phase: "ready"; document: PromptRunGraphDocument } | { phase: "error"; reason: string }
  >({ phase: "loading" });

  useEffect(() => {
    if (!devFixtureUrl) return;
    let alive = true;
    fetch(devFixtureUrl)
      .then((response) => {
        if (!response.ok) throw new Error(`fixture fetch failed: HTTP ${response.status}`);
        return response.json();
      })
      .then((document: PromptRunGraphDocument) => {
        if (alive) setDevFixtureState({ phase: "ready", document });
      })
      .catch((cause: unknown) => {
        if (alive) setDevFixtureState({ phase: "error", reason: cause instanceof Error ? cause.message : String(cause) });
      });
    return () => {
      alive = false;
    };
  }, [devFixtureUrl]);

  useEffect(() => {
    let alive = true;
    const source = resolveActivitySource(window.location.search);
    loadActivity(source)
      .then((result) => {
        if (!alive) return;
        setState({
          phase: "ready",
          kind: result.kind,
          events: result.events,
          partialHistory: result.coverage !== null && !result.coverage.complete,
          warnings: result.warnings,
        });
        if (import.meta.env.DEV) {
          // Development-only proof of real data: identities + timestamps only,
          // never prompt content. Fixture mode is always labelled as such.
          console.info(
            `[midnight-desktop] activity source: ${result.kind}` +
              (result.kind === "performance"
                ? `; prompt runs loaded: ${result.events.length}` +
                  (result.coverage ? ` of ${result.coverage.totalMatching} matching` : "") +
                  (result.warnings.length ? `; warnings: ${result.warnings.join(" | ")}` : "")
                : "; deterministic development fixture"),
            result.kind === "performance"
              ? result.events.map((event) => `${event.promptRunId} @ ${event.occurredAt}`)
              : undefined,
          );
        }
      })
      .catch((cause: unknown) => {
        if (!alive) return;
        setState({
          phase: "unavailable",
          reason: cause instanceof Error ? cause.message : String(cause),
        });
      });
    return () => {
      alive = false;
    };
  }, []);

  const data = useMemo<ActivityMapData | null>(() => {
    if (state.phase !== "ready") return null;
    // The visible end is the current local calendar day; recorded evidence
    // decides how far back the real map reaches. Fixture mode follows the
    // same runtime clock so no fixture date can leak into range behavior.
    const range = activityRangeForEvents(state.events, todayKey());
    return {
      granularity,
      rangeStart: range.rangeStart,
      rangeEnd: range.rangeEnd,
      buckets: aggregateActivity(state.events, granularity, range.rangeStart, range.rangeEnd),
    };
  }, [state, granularity]);

  useEffect(() => {
    if (!data || !pendingSelectionKey || selected) return;
    const match = data.buckets.find((bucket) => bucket.key === pendingSelectionKey);
    if (match) setSelected(match);
  }, [data, pendingSelectionKey, selected]);

  // Execution 07: `?run=` restoration — jump straight to a shared Prompt
  // Run's graph once its owning bucket is known, without disturbing the
  // `?sel=` restoration above (a separate, untouched effect).
  useEffect(() => {
    if (!data || !pendingRunId || view.kind !== "activity" || state.phase !== "ready") return;
    for (const bucket of data.buckets) {
      if (bucket.promptCount === 0) continue;
      const inBucket = eventsInBucket(state.events, bucket);
      if (inBucket.some((event) => event.promptRunId === pendingRunId)) {
        setSelected(bucket);
        setView({ kind: "graph", promptRunId: pendingRunId });
        break;
      }
    }
  }, [data, pendingRunId, view, state]);

  useEffect(() => {
    setFocusNode(null);
  }, [view]);

  useEffect(() => {
    if (view.kind !== "graph") return;
    let alive = true;
    setGraphState({ phase: "loading" });
    fetchPromptRunGraph(view.promptRunId, { maxDepth: DEFAULT_GRAPH_MAX_DEPTH, focusNode: focusNode ?? undefined })
      .then((document) => {
        if (alive) setGraphState({ phase: "ready", document });
      })
      .catch((cause: unknown) => {
        if (!alive) return;
        if (cause instanceof PerformanceHostError && cause.code === "NOT_FOUND") {
          setGraphState({ phase: "not-found" });
        } else {
          setGraphState({ phase: "unavailable", reason: cause instanceof Error ? cause.message : String(cause) });
        }
      });
    return () => {
      alive = false;
    };
  }, [view, focusNode]);

  // Execution 12: fetch the single terminal insight card on entry to the
  // Insights view — `--user-pull` semantics (Section 5): this is a
  // deliberate user pull, never a background poll.
  useEffect(() => {
    if (view.kind !== "insights") return;
    let alive = true;
    setInsightState({ phase: "loading" });
    setFeedbackError(null);
    fetchTerminalCard()
      .then((document) => {
        if (alive) setInsightState({ phase: "ready", document });
      })
      .catch((cause: unknown) => {
        if (!alive) return;
        setInsightState({ phase: "unavailable", reason: cause instanceof Error ? cause.message : String(cause) });
      });
    return () => {
      alive = false;
    };
  }, [view]);

  const handleInsightFeedback = (exposureId: string, outcome: InsightOutcome) => {
    setFeedbackPending(true);
    setFeedbackError(null);
    recordInsightFeedback(exposureId, outcome)
      .then(() => fetchTerminalCard())
      .then((document) => {
        // A recorded outcome (especially "dismissed") may change which
        // insight, if any, is terminal on the next decision — re-fetch
        // rather than assuming the same card remains current.
        setInsightState({ phase: "ready", document });
      })
      .catch((cause: unknown) => {
        setFeedbackError(cause instanceof Error ? cause.message : String(cause));
      })
      .finally(() => {
        setFeedbackPending(false);
      });
  };

  const handlePeriodSelect = (bucket: ActivityBucket | null) => {
    setSelected(bucket);
    if (bucket) setView({ kind: "run-select", bucket });
  };

  if (devFixtureUrl) {
    return (
      <div className="desktop">
        <header className="desktop__header">
          <span className="desktop__brand">Midnight</span>
          <span className="desktop__surface-label">Desktop — dev fixture preview</span>
        </header>
        <main className="desktop__main">
          <section className="panel" aria-label="Dev Fixture Preview">
            {devFixtureState.phase === "loading" && <p className="panel__status">Loading fixture…</p>}
            {devFixtureState.phase === "error" && (
              <p className="panel__status" role="status">
                Failed to load fixture: {devFixtureState.reason}
              </p>
            )}
            {devFixtureState.phase === "ready" && <PerformanceGraph document={devFixtureState.document} />}
          </section>
        </main>
      </div>
    );
  }

  return (
    <div className="desktop">
      <header className="desktop__header">
        <span className="desktop__brand">Midnight</span>
        <span className="desktop__surface-label">Desktop</span>
        <nav className="desktop__nav" aria-label="Views">
          <button
            type="button"
            className="desktop__nav-button"
            aria-current={view.kind !== "insights"}
            onClick={() => setView({ kind: "activity" })}
          >
            Activity
          </button>
          <button
            type="button"
            className="desktop__nav-button"
            aria-current={view.kind === "insights"}
            onClick={() => setView({ kind: "insights" })}
          >
            Insights
          </button>
        </nav>
      </header>
      <main className="desktop__main">
        {view.kind === "activity" && (
        <section className="panel" aria-label="Activity Map">
          <div className="panel__header">
            <div className="panel__heading">
              <h1 className="panel__title">Activity Map</h1>
              {state.phase === "ready" && (
                <span className="panel__source" data-kind={state.kind}>
                  {state.kind === "performance" ? "Performance" : "Development fixture"}
                </span>
              )}
            </div>
            <GranularityControl
              value={granularity}
              onChange={(next) => {
                setGranularity(next);
                setSelected(null);
              }}
            />
          </div>
          {state.phase === "loading" && <p className="panel__status">Loading activity…</p>}
          {state.phase === "unavailable" && (
            <p className="panel__status" role="status">
              Performance source unavailable — activity history cannot be read right now.
            </p>
          )}
          {state.phase === "ready" && state.kind === "performance" && state.events.length === 0 && (
            <p className="panel__status" role="status">
              No Prompt Runs recorded yet.
            </p>
          )}
          {data && state.phase === "ready" && (
            <>
              <ActivityMap
                data={data}
                selectedKey={selected?.key ?? null}
                onPeriodSelect={handlePeriodSelect}
              />
              <div className="panel__footer">
                <div className="activity-legend">
                  <span className="activity-legend__hint">Less</span>
                  {[0, 1, 2, 3, 4].map((level) => (
                    <span key={level} className="activity-legend__swatch" data-level={level} />
                  ))}
                  <span className="activity-legend__hint">More</span>
                </div>
                {state.partialHistory && (
                  <span className="panel__source-note">bounded history</span>
                )}
                {selected && (
                  <p className="panel__selection" aria-live="polite">
                    Selected · {formatBucketPeriod(selected)} ·{" "}
                    <span className="panel__selection-count">{formatPrompts(selected.promptCount)}</span>
                  </p>
                )}
              </div>
            </>
          )}
        </section>
        )}

        {view.kind === "run-select" && (
          <section className="panel" aria-label="Select Prompt Run">
            <div className="panel__header">
              <div className="panel__heading">
                <h1 className="panel__title">{formatBucketPeriod(view.bucket)}</h1>
              </div>
            </div>
            <PromptRunSelector
              events={state.phase === "ready" ? eventsInBucket(state.events, view.bucket) : []}
              onSelect={(event) => setView({ kind: "graph", promptRunId: event.promptRunId })}
              onBack={() => setView({ kind: "activity" })}
            />
          </section>
        )}

        {view.kind === "graph" && (
          <section className="panel" aria-label="Prompt Run Graph">
            <div className="panel__header">
              <div className="panel__heading">
                <h1 className="panel__title">Prompt Run Graph</h1>
              </div>
              <button
                type="button"
                className="prompt-run-selector__back"
                onClick={() => setView(selected ? { kind: "run-select", bucket: selected } : { kind: "activity" })}
              >
                ← Back
              </button>
            </div>
            {graphState.phase === "loading" && <p className="panel__status">Loading graph…</p>}
            {graphState.phase === "not-found" && (
              <p className="panel__status" role="status">
                This Prompt Run's graph could not be found.
              </p>
            )}
            {graphState.phase === "unavailable" && (
              <p className="panel__status" role="status">
                Performance graph source unavailable right now.
              </p>
            )}
            {graphState.phase === "ready" && <PerformanceGraph document={graphState.document} onExpandNode={setFocusNode} />}
          </section>
        )}

        {view.kind === "insights" && (
          <section className="panel" aria-label="Insights">
            <div className="panel__header">
              <div className="panel__heading">
                <h1 className="panel__title">Insights</h1>
              </div>
            </div>
            {insightState.phase === "loading" && <p className="panel__status">Loading insight…</p>}
            {insightState.phase === "unavailable" && (
              <p className="panel__status" role="status">
                Insights source unavailable right now.
              </p>
            )}
            {insightState.phase === "ready" && (
              <InsightCard
                document={insightState.document}
                onFeedback={handleInsightFeedback}
                feedbackPending={feedbackPending}
                feedbackError={feedbackError}
              />
            )}
          </section>
        )}
      </main>
    </div>
  );
}
