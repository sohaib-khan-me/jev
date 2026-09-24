# Evaluation dataset

`test_cases.json` holds the POC test cases used by **Test Suite → Run All Tests** and `POST /api/tests/run`.

```json
{
  "id": "TC001",
  "category": "easy | medium | hard | relational | multi_field",
  "campaign": "Find students from Peshawar.",
  "expected_field": "students.city",
  "ambiguous_with": ["campuses.city"],
  "notes": "Why the case is tricky."
}
```

Multi-field cases use `"expected_fields": [...]` instead of `expected_field`.

Rules:

- Expected fields are written **before** looking at JEV results and never changed because of them.
- Every field must exist in the live schema. The backend rejects a test file that doesn't validate, and `pytest` checks every field against the schema.
- `ambiguous_with` records defensible alternatives. Picking one is still scored as incorrect but reported separately.
- The expected answer is never sent to JEV.

To add a case, append an object with a new unique `id`. No code changes are needed. See [../docs/EVALUATION_METHODOLOGY.md](../docs/EVALUATION_METHODOLOGY.md).
