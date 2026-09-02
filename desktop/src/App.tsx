import { useEffect, useMemo, useState } from "react";
import { ActivityMap } from "./components/ActivityMap";
import { GranularityControl } from "./components/GranularityControl";
import { activityRangeForEvents, aggregateActivity } from "./activity/aggregate";
import { loadActivity, resolveActivitySource } from "./activity/adapter";
import { formatBucketPeriod, formatPrompts } from "./activity/format";
import { todayKey } from "./activity/localDate";
import type { ActivityBucket, ActivityEvent, ActivityMapData, Granularity } from "./activity/types";

const GRANULARITIES: readonly Granularity[] = ["day", "week", "month"];

function readInitialGranularity(): Granularity {
  const param = new URLSearchParams(window.location.search).get("g");
  return GRANULARITIES.includes(param as Granularity) ? (param as Granularity) : "day";
}

function readInitialSelectionKey(): string | null {
  return new URLSearchParams(window.location.search).get("sel");
}

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

  return (
    <div className="desktop">
      <header className="desktop__header">
        <span className="desktop__brand">Midnight</span>
        <span className="desktop__surface-label">Desktop</span>
      </header>
      <main className="desktop__main">
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
                onPeriodSelect={setSelected}
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
      </main>
    </div>
  );
}
