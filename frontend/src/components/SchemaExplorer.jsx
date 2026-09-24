import { useState } from "react";
import { ErrorBox, Loading } from "./common.jsx";

export default function SchemaExplorer({ schema, onRefresh }) {
  const [open, setOpen] = useState({});
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);

  async function refresh() {
    setRefreshing(true);
    setError(null);
    try {
      await onRefresh();
    } catch (e) {
      setError(e);
    } finally {
      setRefreshing(false);
    }
  }

  if (!schema) return <Loading text="Loading schema..." />;
  const allOpen = schema.tables.every((t) => open[t.name]);

  return (
    <div className="stack">
      <div className="row between">
        <p className="muted">
          <strong>{schema.database}</strong>: {schema.tables.length} tables, discovered{" "}
          {new Date(schema.discovered_at).toLocaleString()}
        </p>
        <div className="row">
          <button onClick={() => setOpen(Object.fromEntries(schema.tables.map((t) => [t.name, !allOpen])))}>
            {allOpen ? "Collapse all" : "Expand all"}
          </button>
          <button className="primary" onClick={refresh} disabled={refreshing}>
            {refreshing ? "Refreshing..." : "Refresh Schema"}
          </button>
        </div>
      </div>
      <ErrorBox error={error} />

      <section className="card">
        <h2>Relationships</h2>
        {schema.relationships.length === 0 ? (
          <p className="muted">No foreign keys found.</p>
        ) : (
          <ul className="plain">
            {schema.relationships.map((r) => (
              <li key={`${r.from_table}.${r.from_column}`}>
                <code>
                  {r.from_table}.{r.from_column}
                </code>{" "}
                →{" "}
                <code>
                  {r.to_table}.{r.to_column}
                </code>
              </li>
            ))}
          </ul>
        )}
        {schema.ambiguous_columns.length > 0 && (
          <>
            <h3>Same-named columns (possible ambiguity)</h3>
            <ul className="plain">
              {schema.ambiguous_columns.map((g) => (
                <li key={g.column_name}>
                  {g.fields.map((f) => (
                    <code key={f} className="spaced">
                      {f}
                    </code>
                  ))}
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      {schema.tables.map((table) => (
        <section className="card" key={table.name}>
          <button className="table-toggle" onClick={() => setOpen({ ...open, [table.name]: !open[table.name] })}>
            <span>{open[table.name] ? "▾" : "▸"}</span>
            <strong>{table.name}</strong>
            <span className="muted">
              {table.columns.length} columns · {table.row_count ?? "?"} rows
            </span>
          </button>
          {open[table.name] && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Column</th>
                    <th>Type</th>
                    <th>Keys</th>
                    <th>Nullable</th>
                    <th>References</th>
                  </tr>
                </thead>
                <tbody>
                  {table.columns.map((c) => (
                    <tr key={c.name}>
                      <td>
                        <code>{c.name}</code>
                      </td>
                      <td>{c.column_type.toUpperCase()}</td>
                      <td>
                        {c.primary_key && <span className="badge key">PK</span>}
                        {c.foreign_key && <span className="badge fk">FK</span>}
                        {c.unique && <span className="badge neutral">UNIQUE</span>}
                      </td>
                      <td>{c.nullable ? "yes" : "no"}</td>
                      <td>
                        {c.foreign_key && (
                          <code>
                            → {c.foreign_key.references_table}.{c.foreign_key.references_column}
                          </code>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ))}
    </div>
  );
}
