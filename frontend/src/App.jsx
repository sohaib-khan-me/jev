import { useCallback, useEffect, useState } from "react";
import { api } from "./services/api.js";
import Dashboard from "./components/Dashboard.jsx";
import SchemaExplorer from "./components/SchemaExplorer.jsx";
import CampaignTester from "./components/CampaignTester.jsx";
import EvaluationHistory from "./components/EvaluationHistory.jsx";
import { ErrorBox } from "./components/common.jsx";

const PAGES = [
  ["dashboard", "Dashboard"],
  ["schema", "Schema"],
  ["tester", "Campaign Tester"],
  ["history", "History"],
];

export default function App() {
  const [page, setPage] = useState("dashboard");
  const [health, setHealth] = useState(null);
  const [schema, setSchema] = useState(null);
  const [error, setError] = useState(null);

  const loadSchema = useCallback(async (refresh = false) => {
    const data = refresh ? await api.refreshSchema() : await api.schema();
    setSchema(data);
    return data;
  }, []);

  useEffect(() => {
    api.health().then(setHealth).catch(setError);
    loadSchema().catch(setError);
  }, [loadSchema]);

  return (
    <div className="app">
      <header className="topbar">
        <h1>JEV Audience Field Evaluator</h1>
        <nav>
          {PAGES.map(([key, label]) => (
            <button key={key} className={page === key ? "tab active" : "tab"} onClick={() => setPage(key)}>
              {label}
            </button>
          ))}
        </nav>
      </header>

      <ModeBanner health={health} />
      {error && <ErrorBox error={error} />}

      <main>
        {page === "dashboard" && <Dashboard health={health} schema={schema} />}
        {page === "schema" && <SchemaExplorer schema={schema} onRefresh={() => loadSchema(true)} />}
        {page === "tester" && <CampaignTester schema={schema} />}
        {page === "history" && <EvaluationHistory />}
      </main>

      <footer>
        Fictional FAST-NUCES-style test data. Results describe this POC dataset only, not JEV in general.
      </footer>
    </div>
  );
}

function ModeBanner({ health }) {
  if (!health) return null;
  if (health.jev_mock_mode) {
    return (
      <div className="banner mock">
        MOCK MODE: answers are synthetic placeholders, not JEV results. Set JEV_MOCK_MODE=false for real evaluations.
      </div>
    );
  }
  if (!health.jev_configured) {
    return (
      <div className="banner warn">
        JEV is not configured for provider "{health.jev_provider}". Add its credentials to backend/.env and restart
        the backend.
      </div>
    );
  }
  return null;
}
