# JEV Audience Field Evaluator

A standalone proof-of-concept that answers one question:

> **Given a real relational database schema and a natural-language campaign, can JEV pick the database field the campaign's audience condition is about?**

Example: *"Find students with CGPA above 3.5."* → JEV should pick `students.cgpa`.

The app reads the schema of a local MySQL database (`fast_jev_test`), builds a shortlist of candidate fields, asks JEV a typed **choice** question, shows JEV's answer with its confidence and probabilities, and compares the answer against an expected field you provide. A test suite runs 24 prepared campaigns and reports **POC field-selection accuracy**. That number describes this small dataset only, not JEV in general.

> The data in `fast_jev_test` is fictional FAST-NUCES-style test data. It is not real student information.

**New to JEV?** Start with the [JEV tutorial](docs/JEV_TUTORIAL.md). It explains everything end to end with real examples and exercises.

---

## 1. What JEV is

JEV is TypeSafe's structured-evaluation model. This app can reach it through **OpenRouter's Decisions API** (verified, the current default) or **Cloudflare Workers AI** (implemented from the docs, not yet tested live). You send it a **state** (context) and typed **questions** (`noul`, `choice` or `score`). For a `choice` question it returns:

- `choice`: the option it picked
- `confidence`: JEV's confidence in that answer (0–1)
- `probabilities`: JEV's probability for every option

This project uses a single `choice` question whose options are candidate database fields like `students.cgpa`. See [docs/JEV_INTEGRATION.md](docs/JEV_INTEGRATION.md).

## 2. Architecture

```
React (Vite) ──HTTP──▶ FastAPI backend ──▶ MySQL fast_jev_test   (read-only, jev_reader)
                               │
                               ├──▶ OpenRouter /api/alpha/decisions  or  Cloudflare Workers AI ──▶ JEV
                               └──▶ SQLite backend/data/history.sqlite3 (evaluation history)
```

The frontend only talks to our backend. Only the backend holds credentials and talks to the JEV provider. Details are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

### Project structure

```
jev-audience-evaluator/
├── backend/                     FastAPI app (Python)
│   ├── app/
│   │   ├── main.py              app setup: CORS, middleware, routers
│   │   ├── config.py            settings from backend/.env
│   │   ├── dependencies.py      wires services together
│   │   ├── database/            read-only MySQL access + schema discovery
│   │   ├── models/schemas.py    Pydantic request/response models
│   │   ├── services/            candidates, JEV client, evaluation, test suite, history
│   │   ├── routes/              HTTP endpoints (/api/...)
│   │   └── utils/               errors + structured logging
│   ├── tests/                   pytest suite (JEV is mocked) + fixtures
│   ├── scripts/                 manual real-JEV connection test
│   ├── requirements.txt
│   └── .env.example             copy to .env and fill in
├── frontend/                    React + Vite dashboard
│   ├── src/components/          Dashboard, Schema, Campaign Tester, History, ...
│   ├── src/services/api.js      the only file that calls the backend
│   └── .env.example
├── evaluation/test_cases.json   POC test set (24 campaigns)
└── docs/                        tutorial, architecture, JEV integration, methodology
```

### How one evaluation flows

```
campaign text
  → schema discovery      (information_schema: tables, columns, PKs, FKs, row counts)
  → candidate generation  (deterministic shortlist of table.column fields, ≤ 25)
  → JEV choice question   (state = campaign + tables + relationships; options = candidates)
  → parse JEV's answer    (choice, confidence, probabilities, usage, raw response)
  → local evaluation      (correct = selected_field == expected_field)
  → saved to SQLite history
```

The **expected field is never sent to JEV**. It is only compared after JEV answers.

## 3. The MySQL database

The live schema (discovered, not hardcoded):

| Table | Rows | Notable columns | Foreign keys |
|---|---|---|---|
| universities | 1 | university_name, country, established_year | — |
| campuses | 5 | campus_name, **city**, province, campus_type | university_id → universities |
| departments | 7 | department_name, department_code, degree_type | campus_id → campuses |
| students | 12 | gender, age, **city**, semester, **admission_year**, cgpa, scholarship_status, student_status | department_id → departments |
| courses | 10 | course_code, course_name, credit_hours, course_level | department_id → departments |
| enrollments | 35 | semester_name, **enrollment_year**, marks, grade, enrollment_status | student_id → students, course_id → courses |

Intentional ambiguities: `students.city` vs `campuses.city` (detected automatically), and `students.admission_year` vs `enrollments.enrollment_year` (a difference in meaning, noted in the test cases).

### Database safety

The app is **read-only** against MySQL, enforced at three levels:

1. The `jev_reader` account has only `SELECT, SHOW VIEW` on `fast_jev_test.*`.
2. Every connection runs `SET SESSION TRANSACTION READ ONLY` (checked by a test).
3. The code only issues `SELECT` queries on `information_schema`, plus `COUNT(*)` and `SELECT DISTINCT`.

Evaluation history goes to a separate local SQLite file. **Never run `/home/hp/fast_university_test.sql` again**: it starts with `DROP TABLE`.

## 4. Candidate generation (short version)

Every column becomes a `table.column` identifier. A deterministic scorer ranks them using column-name matches, matches against stored values (for example "Peshawar" appears in `students.city` and `campuses.city`), tables named in the campaign, foreign-key distance, and a penalty for key columns. Any field with a direct match is always kept, and the rest fill up to 25 slots. The shortlist goes to JEV **in schema order, not ranked order**, so the ranking can't nudge JEV. There are no embeddings and no LLM. Full rules are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#candidate-generation).

## 5. Selection, confidence and correctness are kept separate

| Concept | Field | Comes from |
|---|---|---|
| What JEV chose | `selected_field` | JEV `choice` |
| How sure JEV was | `confidence`, `probabilities` | JEV, copied unchanged |
| Whether it matched our answer | `correct` | computed locally: `selected_field == expected_field` |

High confidence does not mean correct. JEV's `confidence` is also **not** the same as its highest probability; the docs example shows 0.8 vs 0.87. Missing values are shown as `—` or `null` and are never filled in.

## 6. Test suite and metrics

[evaluation/test_cases.json](evaluation/test_cases.json) has 24 cases: easy (6), medium (5), hard (5), relational (6), multi-field (2). The metrics:

- **POC field-selection accuracy** = correct / scored, over single-field cases only
- correct, incorrect, errors, per-category breakdown
- how many incorrect answers picked a documented ambiguous alternative
- expected-in-candidates rate (whether candidate generation kept the right answer)
- average JEV confidence, low-confidence count, and average/min/max latency
- multi-field cases, reported separately and not scored

See [docs/EVALUATION_METHODOLOGY.md](docs/EVALUATION_METHODOLOGY.md).

## 7. Frontend

Five pages: **Dashboard** (database, JEV status, latest evaluation, latest POC accuracy), **Schema** (expandable tables, PK/FK badges, relationships, same-named columns, Refresh Schema), **Campaign Tester**, **Test Suite** (Run All Tests with progress, metrics, click a row for full detail), and **History**.

A purple **MOCK** badge and banner appear whenever results are synthetic. A yellow banner appears when JEV isn't configured.

---

## 8. Setup

### Prerequisites

Python 3.12, Node 18+ (tested with 22), and MySQL 8 with `fast_jev_test` loaded.

### MySQL read-only user (one-time)

On Ubuntu, MySQL `root` uses `auth_socket`, so it only works through `sudo mysql`. Create an app account:

```bash
sudo mysql -e "CREATE USER 'jev_reader'@'localhost' IDENTIFIED BY 'CHOOSE_A_PASSWORD';
GRANT SELECT, SHOW VIEW ON fast_jev_test.* TO 'jev_reader'@'localhost';"
```

### Environment variables: `backend/.env`

```bash
cp backend/.env.example backend/.env
chmod 600 backend/.env
# then edit it
```

| Variable | Purpose | Default |
|---|---|---|
| `MYSQL_HOST` / `MYSQL_PORT` | MySQL server | `localhost` / `3306` |
| `MYSQL_USER` / `MYSQL_PASSWORD` | read-only account | `jev_reader` / — |
| `MYSQL_DATABASE` | source database | `fast_jev_test` |
| `JEV_PROVIDER` | `openrouter` or `cloudflare` | `cloudflare` (the shipped `.env` uses `openrouter`) |
| `OPENROUTER_API_KEY` / `OPENROUTER_JEV_MODEL` | OpenRouter access (backend only) | — / `~typesafe/jev-latest` |
| `CLOUDFLARE_ACCOUNT_ID` / `CLOUDFLARE_API_TOKEN` | Cloudflare access (backend only) | empty = not configured |
| `JEV_MODEL` | Workers AI model | `typesafe/jev` |
| `JEV_MOCK_MODE` | synthetic answers for UI development | `false` |
| `JEV_TIMEOUT_SECONDS` / `JEV_MAX_RETRIES` | HTTP timeout / retries (max 2) | `20` / `2` |
| `JEV_LOW_CONFIDENCE_THRESHOLD` | flag answers below this confidence | `0.5` |
| `JEV_INCLUDE_SAMPLE_VALUES` | experiment: show JEV example column values | `false` |
| `CANDIDATE_MAX_FIELDS` | candidate shortlist size | `25` |
| `FRONTEND_URL` | the only origin CORS allows | `http://localhost:5173` |
| `LOG_CAMPAIGN_TEXT` | log campaign text (set `false` to log a hash instead) | `true` |

Frontend: `frontend/.env.local` sets `VITE_API_BASE_URL`, the backend URL (default `http://localhost:8000`). It contains no secrets.

### Install

```bash
# Backend
cd backend
python3 -m venv .venv          # needs: sudo apt install python3.12-venv
#   no sudo? use:  uv venv .venv --seed
source .venv/bin/activate
pip install -r requirements.txt

# Frontend
cd ../frontend
npm install
```

## 9. Run

**Port note for this machine:** port 8000 is already used by the WoEngage agent, so run this backend on **8001**. `frontend/.env.local` already points there. If you use another port, change `VITE_API_BASE_URL` to match.

```bash
# Terminal 1: backend
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8001     # use 8000 if it is free

# Terminal 2: frontend
cd frontend
npm run dev                                   # http://localhost:5173
```

- Swagger UI: http://localhost:8001/docs
- Health check: `curl http://localhost:8001/api/health`
- One evaluation:

```bash
curl -X POST http://localhost:8001/api/evaluate \
  -H 'Content-Type: application/json' \
  -d '{"campaign": "Find students with CGPA above 3.5.", "expected_field": "students.cgpa"}'
```

### API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | MySQL + JEV status (no secrets) |
| GET | `/api/schema` | discovered schema (cached) |
| POST | `/api/schema/refresh` | re-discover the schema |
| POST | `/api/evaluate` | `{campaign, expected_field?}` → JEV result + evaluation |
| GET | `/api/evaluations?limit&offset` | history, newest first |
| GET | `/api/evaluations/{id}` | one evaluation, including the raw JEV response |
| GET | `/api/tests` | test cases |
| POST | `/api/tests/run` | `{test_ids?, run_id?}` runs tests sequentially and returns metrics |
| GET | `/api/tests/runs/latest` / `/api/tests/runs/{run_id}` | stored run and metrics |

Errors always look like `{"error": {"code", "message", "request_id"}}`, with no stack traces.

## 10. Tests

```bash
cd backend && source .venv/bin/activate
pytest                 # all tests; JEV is mocked, no Cloudflare credentials needed
pytest -m mysql        # only the read-only live-MySQL checks (skipped if MySQL is unreachable)
```

## 11. Real JEV connection test

With provider credentials in `backend/.env`:

```bash
cd backend && source .venv/bin/activate
python -m scripts.test_jev_connection "Find students with CGPA above 3.5."
```

It prints the HTTP status, model, selected field, confidence, probabilities and usage, and saves the full request and response to `backend/data/jev_last_raw_response.json`. The parser has been checked against a real OpenRouter response (see [docs/JEV_INTEGRATION.md](docs/JEV_INTEGRATION.md)). The key is never printed.

## 12. Mock mode

`JEV_MOCK_MODE=true` makes the backend return an obviously fake answer: always the first candidate, with an identical probability for every option, model `MOCK-not-jev`, and `source: "mock"`. It exists only so the UI can be developed without credentials. Every mock result carries a MOCK badge, and mock accuracy means nothing. Automated tests use their own fake client, not mock mode.

## 13. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `mysql_auth_failed` | wrong `MYSQL_USER`/`MYSQL_PASSWORD`; `root` won't work (auth_socket) |
| `mysql_unavailable` | MySQL not running: `systemctl status mysql` |
| `mysql_database_not_found` | `MYSQL_DATABASE` wrong or not granted to `jev_reader` |
| Banner "JEV is not configured" | set the credentials for your `JEV_PROVIDER`, then restart the backend |
| `jev_auth_failed` | the key or token is wrong, revoked, or lacks permission |
| `jev_request_rejected` | Cloudflare rejected the payload; run the connection script and read the saved response |
| `jev_timeout` / `jev_upstream_error` | slow or failing API after 2 retries; try again later |
| "Cannot reach the backend" in the UI | backend not running, or `VITE_API_BASE_URL` points to the wrong port |
| CORS error in the browser console | `FRONTEND_URL` must exactly match the frontend origin |
| `address already in use` on 8000 | another service is using the port; use `--port 8001` |
| `python3 -m venv` fails with ensurepip | `sudo apt install python3.12-venv`, or `uv venv .venv --seed` |

## 14. Limitations

- **Small dataset.** 22 scored cases can't support general claims about JEV. Expected answers were written by one person and can be argued with; ambiguous cases are marked, not resolved.
- **Single-field only.** A single `choice` question returns one field. Multi-field campaigns are reported but not scored.
- **Heuristic candidate generation.** Its stemming and matching are basic. It reports whether the expected field survived (`expected_in_candidates`), so a candidate-generation miss isn't blamed on JEV.
- **Cloudflare path untested live.** OpenRouter is verified against a real response; the Cloudflare transport follows its docs.
- **Tiny schema.** 43 columns; results may not carry over to wide schemas.
- **No SQL generation.** The next phase would be relevant field → tables → joins → SQL (see ARCHITECTURE.md).

## 15. Next steps

1. Run the suite several times to measure how stable JEV's answers are (single runs can vary).
2. Read the full suite results and read the per-case probabilities, especially the ambiguous and relational cases.
3. Experiment: `JEV_INCLUDE_SAMPLE_VALUES=true` vs `false`, and different `CANDIDATE_MAX_FIELDS`.
4. Multi-field evaluation (for example one `noul` question per candidate).
5. Relational query planning: field → join path → SQL.
