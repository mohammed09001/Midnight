import { useEffect, useMemo, useState } from "react";
import { ActivityMap } from "./components/ActivityMap";
import { GranularityControl } from "./components/GranularityControl";
import { aggregateActivity, defaultActivityRange } from "./activity/aggregate";
import { loadActivityEvents } from "./activity/adapter";
import { fixtureRangeEnd } from "./activity/fixture";
import { formatBucketPeriod, formatPrompts } from "./activity/format";
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
 * Desktop shell for Execution 01: product identity, the Activity Map, and
 * the Day / Week / Month granularity control — nothing else by design.
 */
export default function App() {
  const [granularity, setGranularity] = useState<Granularity>(readInitialGranularity);
  const [selected, setSelected] = useState<ActivityBucket | null>(null);
  const [events, setEvents] = useState<readonly ActivityEvent[] | null>(null);
  const [pendingSelectionKey] = useState<string | null>(readInitialSelectionKey);

  useEffect(() => {
    let alive = true;
    loadActivityEvents().then((loaded) => {
      if (alive) setEvents(loaded);
    });
    return () => {
      alive = false;
    };
  }, []);

  const data = useMemo<ActivityMapData | null>(() => {
    if (!events) return null;
    const { rangeStart, rangeEnd } = defaultActivityRange(fixtureRangeEnd());
    return {
      granularity,
      rangeStart,
      rangeEnd,
      buckets: aggregateActivity(events, granularity, rangeStart, rangeEnd),
    };
  }, [events, granularity]);

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
            <h1 className="panel__title">Activity Map</h1>
            <GranularityControl
              value={granularity}
              onChange={(next) => {
                setGranularity(next);
                setSelected(null);
              }}
            />
          </div>
          {data ? (
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
                {selected && (
                  <p className="panel__selection" aria-live="polite">
                    Selected · {formatBucketPeriod(selected)} ·{" "}
                    <span className="panel__selection-count">{formatPrompts(selected.promptCount)}</span>
                  </p>
                )}
              </div>
            </>
          ) : (
            <p className="panel__loading">Loading activity…</p>
          )}
        </section>
      </main>
    </div>
  );
}
