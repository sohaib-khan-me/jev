# JEV integration

All provider-specific code is in `backend/app/services/jev_service.py`. The rest of the app uses the `JEVClient` protocol:

```python
result = client.choose(campaign, candidates, schema, column_values)  # -> JEVChoiceResult
```

| Client | When | Behaviour |
|---|---|---|
| `HttpJEVClient` | provider credentials set, mock off | real HTTP call to the configured provider |
| `UnconfiguredJEVClient` | credentials missing, mock off | raises `jev_not_configured` |
| `MockJEVClient` | `JEV_MOCK_MODE=true` | obviously fake answer, `source: "mock"` |

## Providers

`JEV_PROVIDER` picks the transport. Both accept the same TypeSafe `{model, state, questions}` body.

| Provider | Endpoint | Auth | Model |
|---|---|---|---|
| `openrouter` (verified) | `POST https://openrouter.ai/api/alpha/decisions` | `Bearer OPENROUTER_API_KEY` | `~typesafe/jev-latest` (resolved to `typesafe/jev-1.13-20260917`) |
| `cloudflare` (docs only) | `POST https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run` | `Bearer CLOUDFLARE_API_TOKEN` | `typesafe/jev` |

OpenRouter's Decisions endpoint is under `/api/alpha/` and may move.

## Request

```json
{
  "model": "typesafe/jev",
  "state": {
    "campaign": "Find students with CGPA above 3.5.",
    "task": "Audience targeting: decide which database field the campaign's audience condition filters on.",
    "database": "fast_jev_test",
    "tables": {
      "students": ["student_id (int, PK)", "department_id (int, FK)", "cgpa (decimal(3,2))", "..."]
    },
    "relationships": ["students.department_id → departments.department_id", "..."]
  },
  "questions": {
    "audience_field": {
      "type": "choice",
      "instructions": "Identify the single database field that most directly represents the audience condition described by the campaign.",
      "criteria": {
        "students.cgpa": "Column 'cgpa' of table 'students', type decimal(3,2).",
        "students.department_id": "Column 'department_id' of table 'students', type int; foreign key to departments.department_id.",
        "...": "..."
      }
    }
  }
}
```

- The criteria keys are the field identifiers, so JEV's `choice` is a field ID directly.
- The **expected field, candidate scores and ranking reasons are never sent.** A test checks this.
- With `JEV_INCLUDE_SAMPLE_VALUES=true`, descriptions also list up to 10 stored values (for example `Male, Female`). It's off by default so the baseline is a schema-only experiment.

## Response (as documented by Cloudflare)

Source: [Cloudflare model page for typesafe/jev](https://developers.cloudflare.com/ai/models/typesafe/jev/).

```json
{
  "model": "jev-1.13.0",
  "answers": {
    "audience_field": {
      "type": "choice",
      "choice": "students.cgpa",
      "confidence": 0.8,
      "probabilities": {"students.cgpa": 0.87, "students.age": 0.13}
    }
  },
  "usage": {"input_tokens": 426, "output_tokens": 73}
}
```

## Parsing rules (`parse_choice_response`)

- Accepts the documented unwrapped body **and** Cloudflare's usual `{"result": {...}, "success": true}` envelope. `success: false` becomes an error carrying Cloudflare's `errors[].message`.
- `answers.audience_field` must exist, be of type `choice`, and have a `choice` string that is **one of the candidates**. Otherwise the error is `jev_malformed_response`.
- `confidence`: copied if it's a finite number in [0, 1], otherwise `null`. It's never derived from probabilities.
- `probabilities`: numeric values in [0, 1] are kept and sorted in descending order. If they're missing or invalid, the result is `{}` plus a `probabilities_note` explaining why.
- `usage` and `model`: copied if present.
- `raw_response`: always stored unmodified, and viewable in the UI.
- `latency_ms`: wall-clock time of the whole call, including retries. `attempts` records how many tries it took.

## Retry policy

| Condition | Retry? |
|---|---|
| Timeout, network error, HTTP 429/500/502/503/504 | yes, up to **2** retries, 0.5 s then 1.0 s backoff |
| HTTP 401/403 | no (`jev_auth_failed`) |
| Other 4xx | no (`jev_request_rejected`) |
| 200 with non-JSON or malformed body | no |

## Verified against a real response (OpenRouter, 2026-09-24)

Captured in `backend/tests/fixtures/openrouter_real_response.json`:

```json
{
  "model": "typesafe/jev-1.13-20260917",
  "answers": {
    "audience_field": {
      "type": "choice",
      "choice": "students.cgpa",
      "probabilities": {"students.cgpa": 1, "students.semester": 0, "students.age": 0},
      "confidence": 1
    }
  },
  "usage": {"input_tokens": 373, "output_tokens": 48, "cost": 1.5666e-05},
  "id": "gen-dec-…",
  "provider": "TypeSafe"
}
```

What that settled:

1. **No envelope.** The body is returned directly, as documented. The `{"result": …}` handling stays for Cloudflare, which hasn't been tested live.
2. **Dotted criteria keys are accepted.** `students.cgpa` comes back verbatim as the `choice`.
3. **Probabilities and confidence can be JSON integers** (`1`, `0`). The parser accepts ints and rejects booleans.
4. **Extras:** `usage.cost` (USD), `id`, `provider`. All are kept in `raw_response` and `usage`.
5. **Confidence differs from the top probability on real data** (for example 0.89 vs 0.91), so the two stay separate.

A full request with 25 candidates uses about 1,600 input tokens, costs about $0.00007, and takes 0.4–2.5 s.

Re-check any time with:

```bash
cd backend && source .venv/bin/activate
python -m scripts.test_jev_connection "Find students taking Machine Learning."
```

The script saves the request and response to `backend/data/jev_last_raw_response.json`.
