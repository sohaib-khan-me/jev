# Architecture

## Components

```
┌──────────────────┐   HTTP (JSON)   ┌──────────────────────────────────────────┐
│ React + Vite     │ ──────────────▶ │ FastAPI backend                          │
│ (no credentials) │                 │                                          │
└──────────────────┘                 │ routes/     thin HTTP layer              │
                                     │ services/   business logic               │
                                     │ database/   read-only MySQL access       │
                                     └───┬──────────────┬────────────────┬──────┘
                                         │              │                │
                                         ▼              ▼                ▼
                               MySQL fast_jev_test   Cloudflare     SQLite history
                               (jev_reader, R/O)     Workers AI     backend/data/
                                                     typesafe/jev
```

## Backend layout

| Path | Responsibility |
|---|---|
| `app/main.py` | `create_app()`: CORS, request-ID middleware, error handlers, routers |
| `app/config.py` | `Settings` from env/`.env`; secrets are `SecretStr` |
| `app/dependencies.py` | builds the service `Container` once per app, stored on `app.state` |
| `app/database/connection.py` | engine with timeouts; sets every session `READ ONLY`; maps MySQL error codes to friendly errors |
| `app/database/schema_inspector.py` | `information_schema` queries plus a pure `build_schema()` |
| `app/services/mysql_schema_service.py` | discovers and caches the schema; `refresh()` |
| `app/services/candidate_service.py` | deterministic candidate shortlist |
| `app/services/jev_service.py` | **the only Cloudflare-aware module**: payload builder, parser, clients |
| `app/services/evaluation_service.py` | one campaign end to end, plus local scoring |
| `app/services/suite_service.py` | test-case loading, sequential runs, metrics |
| `app/services/history_service.py` | SQLite persistence |
| `app/routes/*` | HTTP endpoints; no logic beyond calling services |
| `app/utils/errors.py` | typed `AppError`s → `{"error": {code, message, request_id}}` |
| `app/utils/logging.py` | JSON-lines logs with a request ID |

The design keeps pure functions (`build_schema`, `generate_candidates`, `build_jev_payload`, `parse_choice_response`, `compute_metrics`) apart from I/O, which is why most tests need neither MySQL nor Cloudflare.

## Schema discovery

Queries (all `SELECT`):

- `information_schema.COLUMNS` joined to `TABLES` (base tables only): name, ordinal position, data type, full column type, nullability, key, extra
- `information_schema.KEY_COLUMN_USAGE WHERE REFERENCED_TABLE_NAME IS NOT NULL`: foreign keys
- `SELECT COUNT(*)` per table. `TABLES.TABLE_ROWS` is only an InnoDB estimate; it reported 0 for the 1-row `universities` table.
- `SELECT DISTINCT col … LIMIT 101` for non-key, non-unique text columns in tables up to 100k rows. These values are used **only on the backend** for candidate matching, and are not returned by `/api/schema`.

Nothing is hardcoded, so a new table or column appears after **Refresh Schema**.

Same-named non-key columns in different tables (for example `city`) are reported as `ambiguous_columns`.

## Candidate generation

Recall comes first. Its job is to remove obviously irrelevant fields, never to decide the answer.

| Signal | Weight | Example |
|---|---|---|
| Specific column-name word matches a campaign word | +5, direct | "CGPA" → `students.cgpa` |
| Generic column-name word (year, status, type, name, code…) | +2 | "final **year**" → `*.…_year` |
| Campaign contains a stored value | +6, direct | "Peshawar" → `students.city`, `campuses.city` |
| Campaign word appears inside a stored value | +3, direct | "merit" → `Merit Scholarship` |
| Campaign names the table | +3 | "students" → all `students.*` |
| 1 / 2 foreign-key hops from a named table | +2 / +1 | `enrollments`, `courses` |
| Primary/foreign key column | −2 | `enrollments.course_id` |

Words are lowercased, stop-words are removed, and a small suffix stripper joins forms like "enrolled"/"enrollments". A column name's words exclude the table name it repeats (`student_status` → "status"), and for foreign keys the referenced table too.

Selection: every field with a **direct** match is kept. The remaining slots up to `CANDIDATE_MAX_FIELDS` (25) go to the highest scores. The final list goes to JEV **in schema order**, so option position can't leak the heuristic ranking. With 43 columns in this database, about 18 get dropped per campaign.

Join keys usually fall below the cap. That's deliberate: they're not audience conditions, and JEV still sees the full join path in `state.relationships`.

Every result records `expected_in_candidates`, so a candidate-generation miss is distinguishable from a JEV mistake.

## Error handling

| Situation | HTTP | code |
|---|---|---|
| MySQL down / bad credentials / unknown database | 503 | `mysql_unavailable` / `mysql_auth_failed` / `mysql_database_not_found` |
| No tables visible | 503 | `empty_schema` |
| Blank campaign, bad body | 422 | `validation_error` |
| Expected field not in schema | 422 | `invalid_expected_field` |
| No candidates | 422 | `no_candidate_fields` |
| Credentials missing | 503 | `jev_not_configured` (not saved to history, since no call was made) |
| 401/403 from Cloudflare | 502 | `jev_auth_failed` (not retried) |
| Other 4xx | 502 | `jev_request_rejected` (not retried) |
| Timeout after retries | 504 | `jev_timeout` |
| Network error / 429 / 5xx after retries | 502 | `jev_upstream_error` |
| Response missing answer, or choice not a candidate | 502 | `jev_malformed_response` |
| Anything else | 500 | `internal_error` (details only if `DEBUG_ERRORS=true`) |

JEV failures during an evaluation are saved to history with `status: "error"`; they are never turned into fake successes.

## Security

- Secrets only live in `backend/.env` (git-ignored, `chmod 600`), loaded as `SecretStr`.
- The token is sent only in the `Authorization` header to Cloudflare. It isn't logged or returned, and the tests check that it never shows up in error messages.
- CORS allows exactly `FRONTEND_URL`, with methods GET/POST only.
- Pydantic validates every request body; the campaign is capped at 1,000 characters.
- MySQL connect timeout is 5 s and read timeout 15 s. The JEV timeout is 20 s, with at most 2 retries (0.5 s then 1 s backoff).

## Future: relational query planning (not implemented)

```
campaign → relevant field(s) → owning table(s) → join path over FK graph → SQL (SELECT only)
```

The pieces already exist: `fk_hop_distances()` walks the foreign-key graph, and relationships are part of the schema model. A later phase could ask JEV to choose the field and, separately, validate the join path, then generate parameterised read-only SQL.
