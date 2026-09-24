# JEV Audience Field Evaluator

A proof-of-concept for evaluating whether [JEV](https://openrouter.ai/blog/insights/what-is-jev/) (TypeSafe's decision model) can identify the database field a natural-language campaign targets.

```
"Find students with CGPA above 3.5."  →  students.cgpa
```

The application reads a MySQL schema, builds a shortlist of candidate fields, asks JEV a typed `choice` question, and compares the answer against an expected field.

## Results

On a 24-case test set against a 6-table schema (22 single-field cases scored):

| Category   | Correct |
|------------|---------|
| Easy       | 6 / 6   |
| Medium     | 4 / 5   |
| Hard       | 4 / 5   |
| Relational | 5 / 6   |
| **Total**  | **19 / 22 (86%)** |

Average latency was about 0.6 s and cost about $0.00007 per request. All three misses were ambiguous cases, and JEV returned noticeably lower confidence for each of them. These figures describe this small test set only; see [docs/EVALUATION_METHODOLOGY.md](docs/EVALUATION_METHODOLOGY.md).

## How it works

1. **Schema discovery**: reads tables, columns and foreign keys from `information_schema` (read-only).
2. **Candidate generation**: a deterministic scorer shortlists up to 25 `table.column` fields.
3. **JEV request**: sends the campaign, the relevant schema and the candidates as a `choice` question.
4. **Evaluation**: compares JEV's selection with the expected field, if one is given, and stores the result in SQLite.

The expected field is never sent to JEV.

## Tech stack

- **Backend:** Python, FastAPI, SQLAlchemy, httpx, pytest
- **Frontend:** React, Vite
- **Data:** MySQL (source, read-only), SQLite (evaluation history)
- **Model:** JEV via the OpenRouter Decisions API (Cloudflare Workers AI also supported)

## Getting started

### Prerequisites

- Python 3.12+
- Node.js 18+
- MySQL 8 with the `fast_jev_test` database
- An OpenRouter API key

### 1. Create a read-only MySQL user

```sql
CREATE USER 'jev_reader'@'localhost' IDENTIFIED BY '<password>';
GRANT SELECT, SHOW VIEW ON fast_jev_test.* TO 'jev_reader'@'localhost';
```

### 2. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then fill in MySQL and OpenRouter credentials
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. If the backend runs on a different port, set `VITE_API_BASE_URL` in `frontend/.env.local`.

## Configuration

Key settings in `backend/.env` (see [`.env.example`](backend/.env.example) for the full list):

| Variable | Description |
|----------|-------------|
| `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE` | Read-only database connection |
| `JEV_PROVIDER` | `openrouter` or `cloudflare` |
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `JEV_MOCK_MODE` | Returns placeholder answers for UI development (default `false`) |
| `FRONTEND_URL` | Allowed CORS origin |

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET`  | `/api/health` | Service, database and JEV status |
| `GET`  | `/api/schema` | Discovered database schema |
| `POST` | `/api/evaluate` | Evaluate a campaign |
| `GET`  | `/api/evaluations` | Evaluation history |
| `POST` | `/api/tests/run` | Run the test set |

Example:

```bash
curl -X POST http://localhost:8000/api/evaluate \
  -H "Content-Type: application/json" \
  -d '{"campaign": "Find students with CGPA above 3.5.", "expected_field": "students.cgpa"}'
```

## Testing

```bash
cd backend
pytest
```

JEV is mocked in the test suite, so no API key is required. To send one real request:

```bash
python -m scripts.test_jev_connection "Find students taking Machine Learning."
```

## Project structure

```
backend/
  app/
    database/      Read-only MySQL access and schema discovery
    services/      Candidate generation, JEV client, evaluation, history
    routes/        API endpoints
  tests/           pytest suite
frontend/
  src/components/  Dashboard, schema explorer, campaign tester, history
evaluation/        Test cases
docs/              Architecture, JEV integration, methodology, tutorial
```

## Documentation

- [JEV tutorial](docs/JEV_TUTORIAL.md): JEV explained end to end, with examples and exercises
- [Architecture](docs/ARCHITECTURE.md)
- [JEV integration](docs/JEV_INTEGRATION.md)
- [Evaluation methodology](docs/EVALUATION_METHODOLOGY.md)

## Limitations

- The test set is small and hand-written; results are not a general measure of JEV.
- Each request selects a single field. Campaigns with multiple conditions are not yet supported.
- SQL generation from the selected field is out of scope for this version.

## Note

The `fast_jev_test` database contains fictional data for testing purposes only.
