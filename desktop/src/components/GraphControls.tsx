interface GraphControlsProps {
  layers: readonly string[];
  /** null means "all layers visible" — the default, unfiltered state. */
  activeLayers: ReadonlySet<string> | null;
  onChange: (activeLayers: Set<string> | null) => void;
  onResetView: () => void;
  /** Execution 10, Section E: the on-demand priority tier (Session/Turn,
   * Tool, Command, Symbols, Analysis, Memory, similarity/history) is hidden
   * by default — a display policy only, never a loss of evidence (the
   * document still carries every node/edge; this control only changes what
   * is rendered). */
  showOnDemand: boolean;
  onToggleOnDemand: () => void;
}

/**
 * Layer filter (checkbox group — layers are independent toggles, not
 * mutually exclusive like `GranularityControl`'s radiogroup) plus the
 * on-demand-tier toggle and a reset/fit-view button (Section F).
 */
export function GraphControls({ layers, activeLayers, onChange, onResetView, showOnDemand, onToggleOnDemand }: GraphControlsProps) {
  const isActive = (layer: string) => activeLayers === null || activeLayers.has(layer);

  const toggle = (layer: string) => {
    const next = new Set(activeLayers ?? layers);
    if (next.has(layer)) next.delete(layer);
    else next.add(layer);
    onChange(next.size === layers.length ? null : next);
  };

  return (
    <div className="graph-controls">
      <div className="graph-controls__layers" role="group" aria-label="Filter by layer">
        {layers.map((layer) => (
          <label key={layer} className="graph-controls__layer">
            <input type="checkbox" checked={isActive(layer)} onChange={() => toggle(layer)} />
            {layer}
          </label>
        ))}
      </div>
      <label className="graph-controls__on-demand">
        <input type="checkbox" checked={showOnDemand} onChange={onToggleOnDemand} />
        Show on-demand evidence (Session/Turn, Tool, Command, Symbols, Analysis, Memory, similarity/history)
      </label>
      <button type="button" className="graph-controls__reset" onClick={onResetView}>
        Reset view
      </button>
    </div>
  );
}
