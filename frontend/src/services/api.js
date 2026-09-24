// The only place the frontend talks to the network. It calls our FastAPI backend,
// never Cloudflare, and holds no credentials.

const BASE_URL = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(message, { status, code, details } = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function request(path, { method = "GET", body } = {}) {
  let response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(`Cannot reach the backend at ${BASE_URL}. Is it running?`, { code: "backend_unreachable" });
  }

  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const err = data?.error;
    const fieldErrors = err?.details?.errors?.map((e) => `${e.field}: ${e.message}`).join("; ");
    throw new ApiError(fieldErrors || err?.message || `Request failed (HTTP ${response.status})`, {
      status: response.status,
      code: err?.code,
      details: err?.details,
    });
  }
  return data;
}

export const api = {
  baseUrl: BASE_URL,
  health: () => request("/api/health"),
  schema: () => request("/api/schema"),
  refreshSchema: () => request("/api/schema/refresh", { method: "POST" }),
  evaluate: (campaign, expectedField) =>
    request("/api/evaluate", { method: "POST", body: { campaign, expected_field: expectedField || null } }),
  evaluations: (limit = 50, offset = 0) => request(`/api/evaluations?limit=${limit}&offset=${offset}`),
  evaluation: (id) => request(`/api/evaluations/${encodeURIComponent(id)}`),
  testCases: () => request("/api/tests"),
  runTests: (testIds, runId) => request("/api/tests/run", { method: "POST", body: { test_ids: testIds, run_id: runId } }),
  testRun: (runId) => request(`/api/tests/runs/${encodeURIComponent(runId)}`),
  latestTestRun: () => request("/api/tests/runs/latest"),
};

export function formatPercent(value, digits = 0) {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(digits)}%`;
}

export function formatMs(value) {
  return value === null || value === undefined ? "—" : `${Math.round(value)} ms`;
}
