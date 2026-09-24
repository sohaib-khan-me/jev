import { formatMs, formatPercent } from "../services/api.js";
import { Stat } from "./common.jsx";

export default function Metrics({ metrics }) {
  const m = metrics;
  return (
    <section className="card">
      <div className="row between">
        <h2>POC field-selection results</h2>
        {m.source === "mock" && <span className="badge mock">MOCK (not JEV)</span>}
      </div>
      <p className="muted small">
        Results on our small, hand-written POC dataset. This is not a general measure of JEV accuracy.
      </p>
      <div className="stats">
        <Stat label="Total tests" value={m.total_tests} />
        <Stat label="Scored (single-field)" value={m.scored} />
        <Stat label="Correct" value={m.correct} />
        <Stat label="Incorrect" value={m.incorrect} hint={m.matched_alternative ? `${m.matched_alternative} picked an ambiguous alternative` : null} />
        <Stat label="Errors" value={m.errors} />
        <Stat label="POC accuracy" value={formatPercent(m.accuracy, 1)} />
        <Stat label="Avg JEV confidence" value={formatPercent(m.average_confidence, 1)} hint={m.low_confidence_count ? `${m.low_confidence_count} low-confidence` : null} />
        <Stat label="Latency avg / min / max" value={formatMs(m.average_latency_ms)} hint={`${formatMs(m.min_latency_ms)} / ${formatMs(m.max_latency_ms)}`} />
        <Stat label="Expected in candidates" value={formatPercent(m.expected_in_candidates_rate)} hint="candidate-generation recall" />
        <Stat label="Multi-field (not scored)" value={m.multi_field_total} hint={`${m.multi_field_selected_in_expected_set} picked one expected field`} />
      </div>

      <h3>By category</h3>
      <table className="compact">
        <thead>
          <tr>
            <th>Category</th>
            <th>Total</th>
            <th>Correct</th>
            <th>Incorrect</th>
            <th>Errors</th>
            <th>Accuracy</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(m.by_category).map(([cat, c]) => (
            <tr key={cat}>
              <td>{cat}</td>
              <td>{c.total}</td>
              <td>{c.correct}</td>
              <td>{c.incorrect}</td>
              <td>{c.errors}</td>
              <td>{formatPercent(c.accuracy)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
