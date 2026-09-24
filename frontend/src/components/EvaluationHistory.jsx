import { Fragment, useEffect, useState } from "react";
import { api, formatMs, formatPercent } from "../services/api.js";
import { Empty, ErrorBox, Loading, SourceBadge, VerdictBadge } from "./common.jsx";
import JEVResult from "./JEVResult.jsx";

const PAGE_SIZE = 25;

export default function EvaluationHistory() {
  const [page, setPage] = useState(0);
  const [data, setData] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setData(null);
    api.evaluations(PAGE_SIZE, page * PAGE_SIZE).then(setData).catch(setError);
  }, [page]);

  async function toggle(id) {
    if (detail?.id === id) return setDetail(null);
    try {
      setDetail(await api.evaluation(id));
    } catch (e) {
      setError(e);
    }
  }

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  if (data.total === 0) return <Empty>No evaluations recorded yet.</Empty>;

  const pages = Math.ceil(data.total / PAGE_SIZE);
  return (
    <section className="card">
      <div className="row between">
        <h2>Evaluation history</h2>
        <span className="muted">{data.total} total · stored in local SQLite, not MySQL</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>When</th>
              <th>Campaign</th>
              <th>Expected</th>
              <th>Selected</th>
              <th>JEV confidence</th>
              <th>Latency</th>
              <th>Result</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((e) => (
              <Fragment key={e.id}>
                <tr className="clickable" onClick={() => toggle(e.id)}>
                  <td className="small">{new Date(e.created_at).toLocaleString()}</td>
                  <td>
                    {e.campaign}
                    {e.test_case_id && <div className="muted small">{e.test_case_id} (test run)</div>}
                  </td>
                  <td>
                    <code>{e.expected_field ?? "—"}</code>
                  </td>
                  <td>
                    <code>{e.selected_field ?? "—"}</code>
                  </td>
                  <td>{formatPercent(e.confidence)}</td>
                  <td>{formatMs(e.latency_ms)}</td>
                  <td>{e.status === "error" ? <span className="badge bad">Error</span> : <VerdictBadge correct={e.correct} />}</td>
                  <td>
                    <SourceBadge source={e.source} />
                  </td>
                </tr>
                {detail?.id === e.id && (
                  <tr>
                    <td colSpan={8}>
                      <JEVResult result={detail} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <div className="row">
          <button disabled={page === 0} onClick={() => setPage(page - 1)}>
            Previous
          </button>
          <span className="muted">
            Page {page + 1} of {pages}
          </span>
          <button disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>
            Next
          </button>
        </div>
      )}
    </section>
  );
}
