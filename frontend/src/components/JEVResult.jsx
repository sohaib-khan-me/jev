import { formatMs, formatPercent } from "../services/api.js";
import { JsonView, SourceBadge, VerdictBadge } from "./common.jsx";
import ProbabilityChart from "./ProbabilityChart.jsx";

export default function JEVResult({ result }) {
  const isError = result.status === "error";
  const expected = result.expected_field || (result.expected_fields?.length ? result.expected_fields.join(" + ") : null);

  return (
    <section className={`card result ${result.source === "mock" ? "is-mock" : ""}`}>
      <div className="row between">
        <h2>JEV result</h2>
        <SourceBadge source={result.source} />
      </div>
      {result.source === "mock" && <p className="banner mock">Synthetic mock output. This is not a JEV decision.</p>}

      {!isError && result.selected_field && (
        <div className={`decision ${result.correct === true ? "is-correct" : result.correct === false ? "is-wrong" : ""}`}>
          <div className="decision-main">
            <div className="decision-label">JEV selected</div>
            <div className="decision-field">{result.selected_field}</div>
            <div className="decision-campaign">“{result.campaign}”</div>
          </div>
          <div className="decision-side">
            <div className="decision-label">Confidence</div>
            <div className="decision-conf">{formatPercent(result.confidence)}</div>
            <div className="decision-meter">
              <span style={{ width: `${(result.confidence ?? 0) * 100}%` }} />
            </div>
            <div className="decision-meta">
              {formatMs(result.latency_ms)}
              {result.correct === true && <span className="verdict ok">✓ Correct</span>}
              {result.correct === false && <span className="verdict bad">✗ Incorrect</span>}
            </div>
          </div>
        </div>
      )}

      <div className="kv">
        <div>Campaign</div>
        <div>{result.campaign}</div>
        {result.test_case_id && (
          <>
            <div>Test case</div>
            <div>
              {result.test_case_id} · {result.category}
            </div>
          </>
        )}
        <div>Expected</div>
        <div>{expected ? <code>{expected}</code> : <span className="muted">none given</span>}</div>
        <div>JEV selected</div>
        <div>{result.selected_field ? <code className="strong">{result.selected_field}</code> : "—"}</div>
        <div>Result</div>
        <div>
          {isError ? (
            <span className="badge bad">JEV error</span>
          ) : result.expected_fields?.length ? (
            <span className="badge neutral">
              Multi-field case, not scored ({result.selected_in_expected_set ? "selected one of the expected fields" : "selected none of them"})
            </span>
          ) : (
            <VerdictBadge correct={result.correct} />
          )}
          {result.matched_alternative && <span className="badge warn">picked a documented ambiguous alternative</span>}
        </div>
        <div>JEV confidence</div>
        <div>
          {formatPercent(result.confidence)}
          {result.low_confidence && <span className="badge warn">low confidence</span>}
        </div>
        <div>Latency</div>
        <div>
          {formatMs(result.latency_ms)}
          {result.attempts > 1 && <span className="muted"> ({result.attempts} attempts)</span>}
        </div>
        <div>Model</div>
        <div>{result.model ?? "—"}</div>
        <div>Usage</div>
        <div>{result.usage ? <code>{JSON.stringify(result.usage)}</code> : <span className="muted">not reported</span>}</div>
      </div>

      {isError && result.error && (
        <div className="error-box">
          <strong>{result.error.code}:</strong> {result.error.message}
        </div>
      )}

      {result.ambiguity_notes?.length > 0 && (
        <div className="notes">
          {result.ambiguity_notes.map((n) => (
            <p key={n}>⚠ {n}</p>
          ))}
        </div>
      )}

      {!isError && (
        <>
          <h3>Probabilities</h3>
          <ProbabilityChart
            probabilities={result.probabilities}
            selected={result.selected_field}
            expected={result.expected_field}
            note={result.probabilities_note}
          />
        </>
      )}

      {result.candidates?.length > 0 && (
        <details>
          <summary>{result.candidates.length} candidate fields sent to JEV (with local ranking reasons)</summary>
          <table className="compact">
            <tbody>
              {[...result.candidates]
                .sort((a, b) => b.score - a.score)
                .map((c) => (
                  <tr key={c.field}>
                    <td>
                      <code>{c.field}</code>
                    </td>
                    <td className="muted">{c.column_type}</td>
                    <td className="muted small">{c.reasons.join("; ") || "no direct signal"}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </details>
      )}

      {result.raw_response && <JsonView data={result.raw_response} label="Raw JEV response" />}
    </section>
  );
}
