# Evaluation methodology

## Question being measured

> On **this** schema and **this** hand-written set of campaigns, how often does JEV pick the field we expected?

The headline number is **POC field-selection accuracy**. It is not "JEV accuracy". Twenty-two scored cases on a 6-table, 43-column schema can't support general claims about the model. Report results as *"Results on our POC evaluation dataset."*

## Test categories

| Category | Count | What it tests |
|---|---|---|
| easy | 6 | the campaign names the column or one of its values ("CGPA", "female", "semester 8") |
| medium | 5 | a paraphrase or value-level wording ("high-performing", "merit scholarships", "currently active") |
| hard | 5 | indirect intent ("strong academic performance", "final year", "recently enrolled", "need financial support") |
| relational | 6 | the condition lives in another table, reached through foreign keys (course name, marks, grade, department, campus) |
| multi_field | 2 | two conditions at once, reported but **not scored** |

## Definitions

- **Single-field case**: one `expected_field`, fixed before any JEV results were seen and never changed afterwards.
- **Correct**: `selected_field == expected_field`, exact string equality. Confidence plays no part.
- **Ambiguous alternative** (`ambiguous_with`): a field a reasonable person could defend, for example `campuses.city` for "students from Peshawar". Picking one is still **incorrect**, but it's counted separately in `matched_alternative`, so readers can tell a defensible miss from a wrong one.
- **Multi-field case**: `expected_fields` holds 2+ fields. A single `choice` question can only return one, so these cases are excluded from accuracy. We only report whether JEV's pick was one of the expected fields.
- **Error**: JEV didn't answer (timeout, API error, malformed response). Errors are excluded from the accuracy denominator and reported as their own count, never as incorrect or correct.

## Metrics

| Metric | Formula |
|---|---|
| POC field-selection accuracy | correct / scored (single-field cases with a JEV answer) |
| Per-category accuracy | same, within a category |
| matched_alternative | incorrect answers that picked a documented alternative |
| expected_in_candidates_rate | cases where candidate generation kept the expected field / cases with an expectation |
| Average JEV confidence | mean of JEV's reported `confidence` over answered cases (missing values skipped) |
| low_confidence_count | answers with confidence below `JEV_LOW_CONFIDENCE_THRESHOLD` (0.5) |
| Latency avg / min / max | JEV call time in milliseconds, including retries |

Any metric with no data is shown as `—` or `null`, never as 0.

## Confidence vs probability

- `probabilities` is JEV's distribution over the candidate fields.
- `confidence` is JEV's own separate confidence value. Cloudflare's documentation shows confidence 0.8 next to a top probability of 0.87, so the two are not interchangeable. The UI labels them separately.
- Neither one tells us whether the answer is right. Only the comparison with the expected field does.

## Two sources of failure

A wrong answer can come from:

1. **Candidate generation** dropping the right field: check `expected_in_candidates`. In the development check against the live schema, all 24 cases kept their expected field.
2. **JEV** choosing a different field among the candidates.

Keeping them apart stops the heuristic filter's mistakes from being blamed on JEV.

## Known biases and limitations

- **Author bias**: one person wrote the campaigns and the expected answers, and knew the schema. The wording may lean toward column names.
- **Small sample**: one flipped answer moves accuracy by about 4.5 points.
- **Labelling choices are arguable.** TC014 ("recently enrolled" → `enrollments.enrollment_year`) could just as well mean `students.admission_year`; it's kept as specified and marked ambiguous.
- **Value leakage**: candidate generation uses stored values. That helps recall but makes some cases easier than a schema-only setup would. Sample values are **not** sent to JEV by default.
- **Single run**: the suite runs each case once. JEV may not be deterministic, so repeat runs give a better picture of stability.
- **Order effects** aren't measured. Candidates are sent in schema order; shuffling them would test position sensitivity.
