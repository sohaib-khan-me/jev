import { Fragment, useEffect, useState } from "react";
import { api, formatPercent } from "../services/api.js";
import { Empty, ErrorBox, Loading, VerdictBadge } from "./common.jsx";
import JEVResult from "./JEVResult.jsx";
import Metrics from "./Metrics.jsx";

// Tests run one at a time (one request per test, grouped by run_id) so we can show
// progress. The backend computes the metrics for the whole run at the end.
export default function TestSuite() {
  const [cases, setCases] = useState(null);
  const [run, setRun] = useState(null);
  const [progress, setProgress] = useState(null);
  const [expanded, setExpanded] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.testCases().then(setCases).catch(setError);
    api.latestTestRun().then(setRun).catch(setError);
  }, []);

  async function runAll() {
    const runId = crypto.randomUUID();
    setError(null);
    setRun(null);
    setExpanded(null);
    try {
      for (let i = 0; i < cases.length; i++) {
        setProgress({ current: i + 1, total: cases.length, id: cases[i].id });
        await api.runTests([cases[i].id], runId);
      }
    } catch (e) {
      setError(e); // e.g. JEV not configured or auth failure: stop instead of failing every test
    } finally {
      setProgress(null);
    }
    try {
      setRun(await api.testRun(runId));
    } catch {
      /* nothing was recorded for this run */
    }
  }

  const byId = Object.fromEntries((run?.results || []).map((r) => [r.test_case_id, r]));

  return (
    <div className="stack">
      <div className="row between">
        <p className="muted">{cases ? `${cases.length} test cases in evaluation/test_cases.json` : ""}</p>
        <button className="primary" onClick={runAll} disabled={!cases || progress !== null}>
          {progress ? `Running test ${progress.current} / ${progress.total} (${progress.id})...` : "Run All Tests"}
        </button>
      </div>
      <ErrorBox error={error} />

      {run && <Metrics metrics={run.metrics} />}

      <section className="card">
        <h2>{run ? "Results" : "Test cases"}</h2>
        {!cases ? (
          <Loading />
        ) : cases.length === 0 ? (
          <Empty>No test cases.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Category</th>
                  <th>Campaign</th>
                  <th>Expected</th>
                  <th>Selected</th>
                  <th>JEV confidence</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {cases.map((c) => {
                  const r = byId[c.id];
                  const clickable = Boolean(r);
                  return (
                    <Fragment key={c.id}>
                      <tr
                        className={clickable ? "clickable" : ""}
                        onClick={() => clickable && setExpanded(expanded === c.id ? null : c.id)}
                        title={c.notes || ""}
                      >
                        <td>{c.id}</td>
                        <td>{c.category}</td>
                        <td>{c.campaign}</td>
                        <td>
                          <code>{c.expected_field || c.expected_fields.join(" + ")}</code>
                          {c.ambiguous_with.length > 0 && <div className="muted small">alt: {c.ambiguous_with.join(", ")}</div>}
                        </td>
                        <td>
                          <code>{r?.selected_field ?? "—"}</code>
                        </td>
                        <td>{formatPercent(r?.confidence)}</td>
                        <td>
                          {!r ? (
                            <span className="muted">not run</span>
                          ) : r.status === "error" ? (
                            <span className="badge bad">Error</span>
                          ) : c.category === "multi_field" ? (
                            <span className="badge neutral">multi-field</span>
                          ) : (
                            <VerdictBadge correct={r.correct} />
                          )}
                        </td>
                      </tr>
                      {expanded === c.id && r && (
                        <tr>
                          <td colSpan={7}>
                            <JEVResult result={r} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
