import { useState } from "react";

export function ErrorBox({ error }) {
  if (!error) return null;
  return (
    <div className="error-box" role="alert">
      <strong>{error.code ? `${error.code}: ` : "Error: "}</strong>
      {error.message || String(error)}
    </div>
  );
}

export function Loading({ text = "Loading..." }) {
  return <p className="muted">{text}</p>;
}

export function Empty({ children }) {
  return <p className="empty">{children}</p>;
}

export function SourceBadge({ source }) {
  if (!source) return null;
  return source === "mock" ? (
    <span className="badge mock">MOCK (not JEV)</span>
  ) : (
    <span className="badge real">Real JEV · {source}</span>
  );
}

export function VerdictBadge({ correct }) {
  if (correct === true) return <span className="badge ok">✓ Correct</span>;
  if (correct === false) return <span className="badge bad">✗ Incorrect</span>;
  return <span className="badge neutral">Not scored</span>;
}

export function JsonView({ data, label = "Raw JSON" }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="json-view">
      <button className="link" onClick={() => setOpen(!open)}>
        {open ? "▾" : "▸"} {label}
      </button>
      {open && <pre>{JSON.stringify(data, null, 2)}</pre>}
    </div>
  );
}

export function Stat({ label, value, hint }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}
