import { useEffect, useState } from "react";
import { api, formatMs, formatPercent } from "../services/api.js";
import { Empty, ErrorBox, Loading, SourceBadge, Stat, VerdictBadge } from "./common.jsx";

export default function Dashboard({ health, schema }) {
  const [latest, setLatest] = useState(undefined);
  const [latestRun, setLatestRun] = useState(undefined);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.evaluations(1).then((d) => setLatest(d.items[0] || null)).catch(setError);
    api.latestTestRun().then(setLatestRun).catch(setError);
  }, []);

  return (
    <div className="stack">
      <section className="card">
        <h2>Database</h2>
        {!schema ? (
          <Loading />
        ) : (
          <div className="stats">
            <Stat label="Database" value={schema.database} />
            <Stat label="MySQL" value={health?.mysql ?? "—"} />
            <Stat label="Tables" value={schema.tables.length} />
            {schema.tables.map((t) => (
              <Stat key={t.name} label={t.name} value={t.row_count ?? "—"} hint="rows" />
            ))}
          </div>
        )}
      </section>

      <section className="card">
        <h2>JEV</h2>
        <div className="stats">
          <Stat label="Provider" value={health?.jev_provider ?? "—"} />
          <Stat label="Model" value={health?.jev_model ?? "—"} />
          <Stat label="Configured" value={health ? (health.jev_configured ? "Yes" : "No") : "—"} />
          <Stat label="Mode" value={health ? (health.jev_mock_mode ? "MOCK" : "Real API") : "—"} />
        </div>
      </section>

      <ErrorBox error={error} />

      <section className="card">
        <h2>Latest evaluation</h2>
        {latest === undefined ? (
          <Loading />
        ) : latest === null ? (
          <Empty>No evaluations yet. Try the Campaign Tester.</Empty>
        ) : (
          <div className="kv">
            <div>Campaign</div>
            <div>{latest.campaign}</div>
            <div>Selected</div>
            <div>
              <code>{latest.selected_field ?? "—"}</code> <SourceBadge source={latest.source} />
            </div>
            <div>Expected</div>
            <div>
              <code>{latest.expected_field ?? "—"}</code>
            </div>
            <div>Result</div>
            <div>
              {latest.status === "error" ? <span className="badge bad">Error</span> : <VerdictBadge correct={latest.correct} />}
            </div>
            <div>JEV confidence</div>
            <div>{formatPercent(latest.confidence)}</div>
          </div>
        )}
      </section>

      <section className="card">
        <h2>POC field-selection accuracy (latest test run)</h2>
        {latestRun === undefined ? (
          <Loading />
        ) : latestRun === null ? (
          <Empty>No test runs yet. Run the suite with: curl -X POST http://localhost:8001/api/tests/run</Empty>
        ) : (
          <div className="stats">
            <Stat label="Accuracy" value={formatPercent(latestRun.metrics.accuracy)} hint={`${latestRun.metrics.correct} / ${latestRun.metrics.scored} single-field`} />
            <Stat label="Avg JEV confidence" value={formatPercent(latestRun.metrics.average_confidence)} />
            <Stat label="Avg latency" value={formatMs(latestRun.metrics.average_latency_ms)} />
            <Stat label="Source" value={latestRun.metrics.source === "mock" ? "MOCK" : latestRun.metrics.source ?? "—"} />
          </div>
        )}
      </section>
    </div>
  );
}
