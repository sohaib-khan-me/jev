import { useState } from "react";
import { api } from "../services/api.js";
import { ErrorBox } from "./common.jsx";
import JEVResult from "./JEVResult.jsx";

export default function CampaignTester({ schema }) {
  const [campaign, setCampaign] = useState("");
  const [expected, setExpected] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  async function submit(event) {
    event.preventDefault();
    if (loading) return; // no duplicate submissions
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.evaluate(campaign.trim(), expected));
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="stack">
      <form className="card stack" onSubmit={submit}>
        <label htmlFor="campaign">Campaign</label>
        <textarea
          id="campaign"
          rows={3}
          maxLength={1000}
          value={campaign}
          onChange={(e) => setCampaign(e.target.value)}
          placeholder="Example: Find students with CGPA above 3.5."
        />

        <label htmlFor="expected">
          Expected field <span className="muted">(optional; only used after JEV answers, never sent to JEV)</span>
        </label>
        <select id="expected" value={expected} onChange={(e) => setExpected(e.target.value)} disabled={!schema}>
          <option value="">No expected field (don't score)</option>
          {schema?.tables.map((t) => (
            <optgroup key={t.name} label={t.name}>
              {t.columns.map((c) => (
                <option key={c.name} value={`${t.name}.${c.name}`}>
                  {t.name}.{c.name}
                </option>
              ))}
            </optgroup>
          ))}
        </select>

        <div>
          <button className="primary" type="submit" disabled={loading || !campaign.trim()}>
            {loading ? "Evaluating..." : "Evaluate with JEV"}
          </button>
        </div>
      </form>

      <ErrorBox error={error} />
      {result && <JEVResult result={result} />}
    </div>
  );
}
