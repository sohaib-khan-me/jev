import { useState } from "react";
import { formatPercent } from "../services/api.js";

const TOP_N = 10;

// Bars show JEV's per-candidate probabilities exactly as returned. Nothing is rescaled.
export default function ProbabilityChart({ probabilities, selected, expected, note }) {
  const [showAll, setShowAll] = useState(false);
  const entries = Object.entries(probabilities || {}).sort((a, b) => b[1] - a[1]);

  if (entries.length === 0) {
    return <p className="muted">No probabilities available{note ? `: ${note}` : "."}</p>;
  }

  const visible = showAll ? entries : entries.slice(0, TOP_N);
  return (
    <div>
      <p className="muted small">JEV probability per candidate field (sorted, as returned by JEV)</p>
      <div className="prob-chart">
        {visible.map(([field, p]) => (
          <div className="prob-row" key={field}>
            <code className="prob-label" title={field}>
              {field}
              {field === selected && <span className="tag sel">selected</span>}
              {field === expected && <span className="tag exp">expected</span>}
            </code>
            <div className="prob-track">
              <div className={`prob-bar ${field === selected ? "is-selected" : ""}`} style={{ width: `${p * 100}%` }} />
            </div>
            <span className="prob-value">{formatPercent(p, p > 0 && p < 0.01 ? 2 : 0)}</span>
          </div>
        ))}
      </div>
      {entries.length > TOP_N && (
        <button className="link" onClick={() => setShowAll(!showAll)}>
          {showAll ? `Show top ${TOP_N}` : `Show all ${entries.length}`}
        </button>
      )}
    </div>
  );
}
