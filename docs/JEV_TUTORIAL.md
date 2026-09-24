# JEV: A Complete Tutorial, End to End

This tutorial teaches you JEV from zero to the level where you can design, build and evaluate your own JEV-powered features. It uses easy English and real examples. **Every response and number in it comes from real JEV calls** made while building this project (September 2026), unless it says otherwise.

How to study it:
- Read Parts 1–4 first. They cover the core ideas and are enough to use JEV.
- Parts 5–8 show how this project uses JEV in a real system.
- Parts 9–11 cover scaling, production use and evaluation.
- Part 12 has hands-on exercises. Do them; they matter most.

---

## Table of contents

1. [What JEV is](#part-1-what-jev-is)
2. [The core idea: state + questions → typed answers](#part-2-the-core-idea)
3. [The three question types in detail](#part-3-the-three-question-types)
4. [Your first real call](#part-4-your-first-real-call)
5. [Probability vs confidence: reading answers correctly](#part-5-probability-vs-confidence)
6. [Designing good questions](#part-6-designing-good-questions)
7. [How this project uses JEV (the full pipeline)](#part-7-how-this-project-uses-jev)
8. [Walking through the code](#part-8-walking-through-the-code)
9. [Limits, tokens, cost and scaling](#part-9-limits-tokens-cost-and-scaling)
10. [Production concerns: errors, retries, security](#part-10-production-concerns)
11. [Evaluating JEV properly](#part-11-evaluating-jev-properly)
12. [Hands-on exercises](#part-12-hands-on-exercises)
13. [Cheat sheet](#part-13-cheat-sheet)
14. [Glossary](#part-14-glossary)
15. [What is verified and what is not](#part-15-what-is-verified-and-what-is-not)

---

## Part 1: What JEV is

### 1.1 In one sentence

**JEV is a decision model: you give it some information and ask it narrow, typed questions, and it returns structured answers with probabilities instead of free text.**

JEV is made by **TypeSafe**. You can reach it through:
- **OpenRouter**, the Decisions API (what this project uses; verified)
- **Cloudflare Workers AI** (built into this project from the docs; not tested live)
- TypeSafe's own API

### 1.2 How JEV differs from a chat model (like GPT or Claude)

| | Chat model | JEV |
|---|---|---|
| You send | a prompt (free text) | a **state** plus **typed questions** |
| It returns | free text you must parse | **structured JSON**: a choice, a score or a yes/no probability |
| Uncertainty | usually hidden | **explicit probabilities** for every option |
| Answer format | can drift ("Sure! The answer is…") | fixed, e.g. always one of your option keys |
| Speed / cost | slower, pricier | fast (about 0.5–1.5 s) and cheap (about $0.00002–0.0001 per call here) |
| Best for | writing, reasoning, conversation | **classification, routing, scoring, yes/no checks** |

The key idea is that **your code owns the workflow and JEV only makes small decisions inside it.** For example, your code asks "Which team should handle this ticket?" and then routes the ticket itself.

### 1.3 When to use JEV

Good fits:
- Route a support ticket to a team (choice)
- Decide whether a message is urgent (yes/no)
- Rate how angry a customer is (score)
- Pick which database field a campaign targets (choice), which is this project

Poor fits:
- Writing an email (use a chat model)
- Multi-step reasoning that needs explanations
- Anything that needs a free-text answer

---

## Part 2: The core idea

Every JEV request has the same three parts:

```
model      → which JEV version to use
state      → the information JEV should read (the "situation")
questions  → one or more typed questions about that state
```

Every response has the same shape:

```
answers    → one answer per question, under the same name you gave it
model      → the exact model version that answered
usage      → tokens and cost
```

### 2.1 `state`: the situation

The state is **everything JEV needs to know** to answer. It can be:
- **a string**: `"Help! My payouts have been failing for 3 days."`
- **a JSON object**: `{"campaign": "...", "tables": {...}, "relationships": [...]}`

JEV reads only the state. It has no access to your database, files or the internet.

### 2.2 `questions`: what you want to know

`questions` is an object. Each key is **your name for the question**, and you get the answer back under the same key.

Each question has three fields:

| Field | What it is | Example |
|---|---|---|
| `type` | the kind of answer: `noul`, `choice` or `score` | `"choice"` |
| `instructions` | the question in plain words | `"Which team should handle this?"` |
| `criteria` | the possible answers and what each one means | `{"billing": "Payments, refunds", ...}` |

### 2.3 A full request (real)

```json
{
  "model": "~typesafe/jev-latest",
  "state": "Help! My payouts have been failing for 3 days.",
  "questions": {
    "is_urgent": {
      "type": "noul",
      "instructions": "Does this message convey urgency?",
      "criteria": { "true": "Explicitly time-sensitive", "false": "No urgency expressed" }
    },
    "department": {
      "type": "choice",
      "instructions": "Which team should handle this?",
      "criteria": {
        "billing": "Payments, invoicing, refunds",
        "technical": "Bugs, outages, integrations",
        "sales": "Pricing, upgrades, new accounts"
      }
    },
    "frustration": {
      "type": "score",
      "instructions": "How frustrated is the customer?",
      "criteria": ["Calm", "Frustrated", "Very angry"]
    }
  }
}
```

### 2.4 The full response (real, 427 input tokens, about 2.9 s)

```json
{
  "model": "typesafe/jev-1.13-20260917",
  "answers": {
    "is_urgent":   { "type": "noul", "noul": 0.95 },
    "department":  {
      "type": "choice",
      "choice": "billing",
      "probabilities": { "billing": 0.88, "technical": 0.12, "sales": 0 },
      "confidence": 0.81
    },
    "frustration": {
      "type": "score",
      "score": 1.05,
      "legend": { "0": "Calm", "1": "Frustrated", "2": "Very angry" },
      "probabilities": { "0": 0, "1": 0.95, "2": 0.05 },
      "confidence": 0.93
    }
  },
  "usage": { "input_tokens": 427, "output_tokens": 73, "cost": 0.0000179 },
  "id": "gen-dec-1790226415-uOSp9dVMPP0O1ABcVHZR",
  "provider": "TypeSafe"
}
```

**All three questions were answered in one call.** That is cheaper and faster than three separate calls.

---

## Part 3: The three question types

### 3.1 `noul`: yes/no as a probability

Use it for yes/no questions.

**Request**
```json
"is_urgent": {
  "type": "noul",
  "instructions": "Does this message convey urgency?",
  "criteria": { "true": "Explicitly time-sensitive", "false": "No urgency expressed" }
}
```
- `criteria` always has exactly two keys: `"true"` and `"false"`.
- Each value describes what "yes" and "no" mean. Clear descriptions give better answers.

**Answer**
```json
{ "type": "noul", "noul": 0.95 }
```
- `noul` is the **probability that the answer is "true"**, from 0 to 1.
- 0.95 means "very likely yes"; 0.10 means "very likely no"; 0.50 means "JEV can't tell".
- There is no separate `confidence` field. How far the value is from 0.5 tells you how sure JEV is.

**Typical code**
```python
if answers["is_urgent"]["noul"] > 0.8:
    escalate()
```

### 3.2 `choice`: pick one option from a list

Use it for "which one?" questions. **This project is built on the `choice` type.**

**Request**
```json
"department": {
  "type": "choice",
  "instructions": "Which team should handle this?",
  "criteria": {
    "billing": "Payments, invoicing, refunds",
    "technical": "Bugs, outages, integrations",
    "sales": "Pricing, upgrades, new accounts"
  }
}
```
- Each **key** is an option ID. JEV returns this exact key, so make keys your code can use directly (`"billing"`, `"students.cgpa"`).
- Each **value** is a description that helps JEV understand the option.
- **Limit: at most 255 options** (tested: 750 options returned `HTTP 400 "Too many choices. Must have at most 255 choices."`).
- Keys with dots work: `"students.cgpa"` was returned exactly.

**Answer**
```json
{
  "type": "choice",
  "choice": "billing",
  "probabilities": { "billing": 0.88, "technical": 0.12, "sales": 0 },
  "confidence": 0.81
}
```
- `choice`: the selected option key (always one of your keys).
- `probabilities`: a probability for **every** option. They add up to about 1.
- `confidence`: JEV's confidence in its choice (0–1). It is a **separate number**, not the top probability; here it's 0.81 while the top probability is 0.88. See Part 5.
- The order of keys in `probabilities` is random. Sort them yourself.
- Values can be JSON integers (`1`, `0`), not only decimals.

### 3.3 `score`: rate on an ordered scale

Use it for "how much?" questions.

**Request**
```json
"frustration": {
  "type": "score",
  "instructions": "How frustrated is the customer?",
  "criteria": ["Calm", "Frustrated", "Very angry"]
}
```
- `criteria` is a **list** (not an object), ordered from lowest to highest.
- The positions become levels: `0 = Calm`, `1 = Frustrated`, `2 = Very angry`.

**Answer**
```json
{
  "type": "score",
  "score": 1.05,
  "legend": { "0": "Calm", "1": "Frustrated", "2": "Very angry" },
  "probabilities": { "0": 0, "1": 0.95, "2": 0.05 },
  "confidence": 0.93
}
```
- `probabilities`: the chance of each level.
- `score`: the **weighted average (expected value)** of the levels. Check it yourself: 0×0 + 1×0.95 + 2×0.05 = **1.05**. The documentation example matches too (0×0 + 1×0.96 + 2×0.04 = 1.04). So `score` is a smooth number between levels, not a rounded level.
- `legend`: maps level numbers back to your labels.
- `confidence`: as for `choice`.

**Tip:** use `score` for thresholds ("escalate if score > 1.5"), and the top `probabilities` entry when you need one label.

### 3.4 Choosing the right type

| Your question | Type |
|---|---|
| "Is it X?" | `noul` |
| "Which one of these?" (no natural order) | `choice` |
| "How much / how strong?" (ordered levels) | `score` |

---

## Part 4: Your first real call

### 4.1 The endpoint (OpenRouter)

```
POST https://openrouter.ai/api/alpha/decisions
Authorization: Bearer <OPENROUTER_API_KEY>
Content-Type: application/json
```

- Model: `~typesafe/jev-latest`. The `~` means "latest version"; it resolved to `typesafe/jev-1.13-20260917`.
- The path contains `/alpha/`, so it may change in future.

Cloudflare Workers AI alternative (from docs, not tested live):
```
POST https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai/run
Authorization: Bearer <CLOUDFLARE_API_TOKEN>
body model: "typesafe/jev"
```

### 4.2 With curl

```bash
curl https://openrouter.ai/api/alpha/decisions \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "~typesafe/jev-latest",
    "state": "I was charged twice for my subscription this month.",
    "questions": {
      "department": {
        "type": "choice",
        "instructions": "Which team should handle this?",
        "criteria": {
          "billing": "Payments, invoicing, refunds",
          "technical": "Bugs, outages, integrations",
          "sales": "Pricing, upgrades, new accounts"
        }
      }
    }
  }'
```

### 4.3 With Python (plain `httpx`)

```python
import os, httpx

response = httpx.post(
    "https://openrouter.ai/api/alpha/decisions",
    headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
    json={
        "model": "~typesafe/jev-latest",
        "state": "I was charged twice for my subscription this month.",
        "questions": {
            "department": {
                "type": "choice",
                "instructions": "Which team should handle this?",
                "criteria": {
                    "billing": "Payments, invoicing, refunds",
                    "technical": "Bugs, outages, integrations",
                    "sales": "Pricing, upgrades, new accounts",
                },
            }
        },
    },
    timeout=20,
)
response.raise_for_status()
answer = response.json()["answers"]["department"]
print(answer["choice"], answer["confidence"], answer["probabilities"])
```

### 4.4 With the OpenRouter TypeScript SDK

```ts
import { OpenRouter } from "@openrouter/sdk";
const openrouter = new OpenRouter({ apiKey: process.env.OPENROUTER_API_KEY });

const decision = await openrouter.alpha.decisions.create({
  decisionsRequest: {
    model: "~typesafe/jev-latest",
    state: "I was charged twice for my subscription this month.",
    questions: { /* same as above */ },
  },
});
console.log(decision.answers.department);
```

### 4.5 With this project's script

```bash
cd backend && source .venv/bin/activate
python -m scripts.test_jev_connection "Find students taking Machine Learning."
```
It prints the answer and saves the full request and response to `backend/data/jev_last_raw_response.json`.

---

## Part 5: Probability vs confidence

This is the most important idea for using JEV well.

### 5.1 Three different things

| Concept | Where | Meaning |
|---|---|---|
| **Selection** | `choice` | What JEV picked |
| **Probabilities** | `probabilities` | How JEV spreads its belief over **all** options |
| **Confidence** | `confidence` | JEV's own trust in its answer |

And in an evaluation system, a fourth one:

| **Correctness** | computed by *you* | Did JEV's pick match the right answer? |

**Never mix these up.** High confidence does **not** mean correct. Correctness can only be checked against a known answer.

### 5.2 Confidence is not the top probability

Real examples:

| Case | Top probability | Confidence |
|---|---|---|
| Ticket routing (billing) | 0.88 | 0.81 |
| "Students taking Machine Learning" | 0.91 | 0.89 |
| "Target currently active students" | 0.92 | 0.91 |

They are close but not equal, so **show both and never compute one from the other.**

### 5.3 Reading probabilities

`"students.semester": 0.66, "students.student_status": 0.33`: JEV is torn between two fields. That tells you more than the choice alone: **the campaign is ambiguous.**

`"students.cgpa": 1.0, everything else 0`: an easy, clear case.

### 5.4 Confidence as a warning signal (real data)

In our 22 scored test cases:
- 19 correct answers: confidence mostly **0.9–1.0** (lowest 0.78)
- 3 wrong answers: confidence **0.61, 0.62, 0.81**

So low confidence was a good sign of a possible mistake. A common design uses it like this:

```python
if answer["confidence"] >= 0.85:
    use_automatically(answer["choice"])
else:
    ask_a_human_to_confirm(answer["choice"], answer["probabilities"])
```

⚠ This comes from only 22 cases. Measure it on your own data before relying on a threshold.

### 5.5 Is JEV deterministic?

We sent the exact same ambiguous request three times:

| Run | Choice | Confidence | Top 2 probabilities |
|---|---|---|---|
| 1 | students.semester | 0.64 | 0.66 / 0.33 |
| 2 | students.semester | 0.63 | 0.66 / 0.33 |
| 3 | students.semester | 0.67 | 0.69 / 0.29 |

The **choice was stable**, while the **numbers moved slightly** (about ±0.03). So:
- don't compare two runs digit by digit;
- for serious evaluation, run several times and average.

---

## Part 6: Designing good questions

Most of the quality comes from **how you ask**. These are the rules learned in this project.

### 6.1 Write clear, specific instructions

❌ `"What field?"`
✅ `"Identify the single database field that most directly represents the audience condition described by the campaign."`

Say exactly what you want, including "single" when you want one answer.

### 6.2 Give options useful descriptions

❌ `"students.cgpa": "cgpa"`
✅ `"students.cgpa": "Column 'cgpa' of table 'students', type decimal(3,2)."`

Descriptions are JEV's only information about each option. More meaning gives better choices.

### 6.3 Make option keys code-friendly

JEV returns the key as-is, so use keys your code can use directly (`"billing"`, `"students.cgpa"`). No mapping step is needed.

### 6.4 Put only what's needed in `state`

The state should include:
- the input to judge (campaign, message…)
- the context JEV needs (tables, relationships…)

It must **never** include:
- the answer you expect (that's cheating, and it ruins evaluation)
- your own scores or rankings (they bias JEV)
- secrets or unnecessary personal data

### 6.5 Avoid bias from option order

This project sends options **in schema order, not ranked order**. If you put your favourite option first every time, you can't tell whether JEV agreed with it or just followed the position.

### 6.6 Watch out for overlapping options

If two options mean almost the same thing (`customer_level` vs `reward_level`), JEV splits its probability between them and confidence drops. Either:
- make the descriptions clearly different, or
- accept that the case is genuinely ambiguous, and report it that way.

### 6.7 Keep the number of options small

In a real test on the same campaign, confidence went from **0.78 with 25 options** down to **0.41 with 250**. Fewer, better options give clearer answers (see Part 9).

### 6.8 One question = one decision

A `choice` question returns **one** answer. For "female students from Peshawar" (two conditions), JEV split 0.60 / 0.40 between gender and city. For multi-condition inputs, ask one `noul` per option ("Does the campaign filter on gender?", "...on city?") instead of one `choice`.

---

## Part 7: How this project uses JEV

### 7.1 The problem

> Given a campaign like *"Find students with CGPA above 3.5"* and a real database, which field does the campaign target?

### 7.2 The pipeline

```
 ┌─────────────┐
 │  Campaign   │  "Find students taking Machine Learning."
 └──────┬──────┘
        ▼
 ┌─────────────────────┐   read-only SQL on information_schema
 │ 1. Schema discovery │   → tables, columns, types, PKs, FKs, row counts
 └──────┬──────────────┘
        ▼
 ┌──────────────────────┐   simple scoring, no AI
 │ 2. Candidate         │   → top 25 fields like "courses.course_name"
 │    generation        │
 └──────┬───────────────┘
        ▼
 ┌──────────────────────┐   state = campaign + tables + relationships
 │ 3. Build JEV request │   question = choice among the 25 fields
 └──────┬───────────────┘
        ▼
 ┌──────────────────────┐   POST /api/alpha/decisions
 │ 4. Call JEV          │   timeout 20 s, max 2 retries
 └──────┬───────────────┘
        ▼
 ┌──────────────────────┐   choice, confidence, probabilities, usage
 │ 5. Parse the answer  │   (never invent missing values)
 └──────┬───────────────┘
        ▼
 ┌──────────────────────┐   correct = (choice == expected field)
 │ 6. Evaluate locally  │   only if an expected field was given
 └──────┬───────────────┘
        ▼
 ┌──────────────────────┐
 │ 7. Save to history   │   SQLite, never MySQL
 └──────────────────────┘
```

### 7.3 Step 1: schema discovery

The app asks MySQL about its own structure:
- `information_schema.COLUMNS` → every column, its type, and whether it can be empty
- `information_schema.KEY_COLUMN_USAGE` → foreign keys (how tables connect)
- `SELECT COUNT(*)` per table → row counts

Nothing is hardcoded, so if you add a table, it appears after **Refresh Schema**.

### 7.4 Step 2: candidate generation (the shortlist)

JEV allows at most 255 options, and fewer options give clearer answers, so we **shortlist before asking JEV**.

Each column gets points:

| Signal | Points | Example |
|---|---|---|
| Column name matches a campaign word | +5 | "CGPA" → `students.cgpa` |
| Campaign contains a value stored in the column | +6 | "Peshawar" → `students.city`, `campuses.city` |
| A campaign word is inside a stored value | +3 | "merit" → "Merit Scholarship" |
| Campaign names the table | +3 | "students" → all `students.*` |
| Table is 1 or 2 foreign-key steps away | +2 / +1 | `enrollments`, `courses` |
| Column is a key (ID) | −2 | `student_id` |

Columns with a direct match are always kept, and the rest fill up to 25. Stored values are used **only in our code** and are not sent to JEV by default.

In our tests, the right field was in the shortlist **24 of 24 times**. That matters because if the shortlist drops the right answer, JEV can't possibly get it right.

### 7.5 Step 3: the request we build (real, shortened)

```json
{
  "model": "~typesafe/jev-latest",
  "state": {
    "campaign": "Find students taking Machine Learning.",
    "task": "Audience targeting: decide which database field the campaign's audience condition filters on.",
    "database": "fast_jev_test",
    "tables": {
      "courses":     ["course_id (int, PK)", "department_id (int, FK)", "course_code (varchar(20))", "course_name (varchar(150))", "..."],
      "enrollments": ["enrollment_id (int, PK)", "student_id (int, FK)", "course_id (int, FK)", "marks (decimal(5,2))", "..."],
      "students":    ["student_id (int, PK)", "gender (varchar(20))", "cgpa (decimal(3,2))", "..."]
    },
    "relationships": [
      "enrollments.student_id → students.student_id",
      "enrollments.course_id → courses.course_id"
    ]
  },
  "questions": {
    "audience_field": {
      "type": "choice",
      "instructions": "Identify the single database field that most directly represents the audience condition described by the campaign.",
      "criteria": {
        "courses.course_name": "Column 'course_name' of table 'courses', type varchar(150).",
        "courses.course_code": "Column 'course_code' of table 'courses', type varchar(20).",
        "enrollments.marks":   "Column 'marks' of table 'enrollments', type decimal(5,2).",
        "...": "22 more"
      }
    }
  }
}
```

Note that JEV never sees the word "Machine Learning" in the data. It worked out from the **names alone** that a course title belongs in `courses.course_name`, and that students connect to courses through `enrollments`.

### 7.6 Step 4–5: the answer (real)

```json
{
  "model": "typesafe/jev-1.13-20260917",
  "answers": {
    "audience_field": {
      "type": "choice",
      "choice": "courses.course_name",
      "probabilities": {
        "courses.course_name": 0.91,
        "enrollments.enrollment_status": 0.06,
        "courses.course_code": 0.03,
        "...22 others": 0
      },
      "confidence": 0.89
    }
  },
  "usage": { "input_tokens": 1639, "output_tokens": 274, "cost": 0.0000688 }
}
```

### 7.7 Step 6: evaluation

If you gave an expected field (e.g. `courses.course_name`):
```
correct = (JEV choice == expected field)   → true
```
The expected field is **optional**. Without it, JEV still answers and the result is just "Not scored".

---

## Part 8: Walking through the code

Read the files in this order:

| # | File | What to learn |
|---|---|---|
| 1 | [backend/app/config.py](../backend/app/config.py) | Settings from `.env`, `SecretStr` for secrets, provider switch |
| 2 | [backend/app/database/schema_inspector.py](../backend/app/database/schema_inspector.py) | `information_schema` queries, and the pure `build_schema()` |
| 3 | [backend/app/services/candidate_service.py](../backend/app/services/candidate_service.py) | Shortlist scoring rules |
| 4 | [backend/app/services/jev_service.py](../backend/app/services/jev_service.py) | **The heart of it:** `build_jev_payload()`, `parse_choice_response()`, `HttpJEVClient` |
| 5 | [backend/app/services/evaluation_service.py](../backend/app/services/evaluation_service.py) | The full pipeline for one campaign |
| 6 | [backend/app/services/suite_service.py](../backend/app/services/suite_service.py) | Running many test cases, computing metrics |
| 7 | [backend/tests/test_jev_parser.py](../backend/tests/test_jev_parser.py) | How each JEV edge case is tested without calling JEV |

### 8.1 Key function 1: building the request

In `jev_service.py`:

```python
def build_jev_payload(campaign, candidates, schema, model, column_values=None):
    criteria = {c.field: describe_candidate(c, schema, ...) for c in candidates}
    return {
        "model": model,
        "state": build_state(campaign, candidates, schema),
        "questions": {QUESTION_NAME: {"type": "choice",
                                      "instructions": INSTRUCTIONS,
                                      "criteria": criteria}},
    }
```

It is a **pure function**: data in, JSON out, no network. That makes it easy to test.

### 8.2 Key function 2: parsing the answer safely

`parse_choice_response()` follows strict rules:
- The answer **must** exist and be of type `choice`, or it raises "malformed response".
- `choice` **must** be one of the options we sent, or it raises an error. We never accept an answer we didn't offer.
- `confidence` is copied if it's a valid number between 0 and 1, **otherwise `null`**. It is never made up.
- `probabilities` keeps only valid numbers. If there are none, it returns `{}` plus a note explaining why.
- It also accepts Cloudflare's `{"result": {...}}` wrapper.

**Rule: never fake a value.** Missing data shows as `—`, not as 0 or a guess.

### 8.3 Key function 3: the HTTP client with retries

`HttpJEVClient._post_with_retries()`:

| Situation | What happens |
|---|---|
| Success (200) | parse and return |
| Timeout / network error / HTTP 429 / 5xx | retry, **at most 2 times**, waiting 0.5 s then 1 s |
| HTTP 401/403 (bad key) | stop immediately, no retry |
| Other 4xx (bad request) | stop immediately, no retry |

Why not retry everything? Retrying a bad key or a bad request just wastes time and money, because it will fail again.

### 8.4 The provider abstraction

The rest of the app only calls:
```python
result = jev_client.choose(campaign, candidates, schema)
```
It doesn't know whether JEV is reached through OpenRouter, Cloudflare or a mock. Changing provider is one line in `.env`:
```
JEV_PROVIDER=openrouter      # or cloudflare
```

---

## Part 9: Limits, tokens, cost and scaling

### 9.1 Limits

| Limit | Value | Source |
|---|---|---|
| Context (max input size) | 32,000 tokens | Cloudflare model docs |
| Options per `choice` question | **255** | real API error message |
| Largest request we sent successfully | 18,417 tokens | real test |

### 9.2 What a token is

A token is a piece of text, roughly ¾ of an English word. `students.cgpa` is several tokens, not one. A column description like `"Column 'cgpa' of table 'students', type decimal(3,2)."` is about 15–20 tokens.

### 9.3 Real costs

| Request | Input tokens | Output tokens | Cost | Time |
|---|---|---|---|---|
| Ticket routing, 3 questions | 427 | 73 | $0.000018 | 2.9 s |
| Our 6-table DB, 25 options (average of 32 calls) | 1,645 | 275 | $0.000069 | 0.6 s avg |
| Synthetic 50×15 DB, 25 options | 2,338 | 262 | $0.000098 | 1.0 s |
| Synthetic 50×15 DB, 250 options | 18,417 | 2,587 | $0.00077 | 1.3 s |
| Synthetic 50×15 DB, 750 options | rejected | — | — | — |

**Output tokens grow with the number of options**, because JEV returns a probability for each one (about 10 tokens per option).

### 9.4 The scaling lesson

For a big database (e.g. 50 tables × 15 columns = 750 columns):

1. **You cannot send every column as an option** (the limit is 255).
2. **Even below the limit, more options make answers worse**: confidence fell from 0.78 to 0.41.
3. **So shortlist first, then ask JEV.** With a 25-option shortlist, even the 50-table database cost about $0.0001 and 1 second per campaign.

This two-step pattern (cheap filtering, then JEV deciding) is the standard way to use JEV at scale.

---

## Part 10: Production concerns

### 10.1 Secrets
- Keep API keys **only on the backend**, in `.env` (never in code, never in git).
- The browser talks to your backend; only the backend talks to JEV.
- Never log the key. This project stores it as `SecretStr` so it can't be printed by accident.

### 10.2 Timeouts and retries
- Always set a timeout (this project uses 20 s).
- Retry only temporary errors, with a maximum of 2 and increasing waits.

### 10.3 Error handling
Every failure becomes a clear error code, never a fake success:

| Code | Meaning |
|---|---|
| `jev_not_configured` | no API key set |
| `jev_auth_failed` | wrong or expired key |
| `jev_request_rejected` | JEV said the request is invalid (e.g. more than 255 options) |
| `jev_timeout` | no answer in time, even after retries |
| `jev_upstream_error` | provider problem (429 / 5xx) after retries |
| `jev_malformed_response` | the answer is missing or picks an option we didn't send |

### 10.4 Mock mode
`JEV_MOCK_MODE=true` returns obviously fake answers for UI work: always the first option, with equal probabilities. The UI marks them clearly as **MOCK**. Never present mock results as real.

### 10.5 Privacy
- JEV only sees what you put in `state` and `criteria`.
- This project sends **only the schema** (names and types), not student data.
- If you enable `JEV_INCLUDE_SAMPLE_VALUES`, real values are sent too. Think about privacy before doing that with real data.

---

## Part 11: Evaluating JEV properly

### 11.1 Build a test set
Each test case has:
- a campaign
- the expected field, written **before** you see JEV's answer
- a category (easy / medium / hard / relational / multi-field)
- known alternatives if the case is ambiguous

See [evaluation/test_cases.json](../evaluation/test_cases.json).

### 11.2 Metrics
- **Accuracy** = correct ÷ scored (single-field cases only)
- Accuracy **per category**, since easy cases can hide weakness on hard ones
- **Errors**, counted separately, never as wrong or right
- **Shortlist recall**: was the right answer among the options at all?
- Average confidence, and how confident JEV was when it was wrong
- Latency and cost

### 11.3 Our real results

| Category | Correct |
|---|---|
| Easy | 6 / 6 |
| Medium | 4 / 5 |
| Hard | 4 / 5 |
| Relational (answer in another table) | 5 / 6 |
| **Total** | **19 / 22 = 86.4%** |

The 3 misses:

| Campaign | Expected | JEV picked | Why |
|---|---|---|---|
| "about to graduate" | student_status | semester (0.64) | both are reasonable |
| "recently enrolled" | enrollment_year | admission_year (0.64) | "enrolled" has two meanings |
| "Karachi campus" | campus_name | campuses.city (0.81) | both identify the campus |

**Lesson:** the misses were mostly **ambiguous questions**, not JEV being careless, and JEV's lower confidence showed it.

### 11.4 Being honest about results
- 22 cases is a **small sample**: one answer changes accuracy by about 4.5 points.
- The person who wrote the tests knew the schema, which may make the tests easier.
- Say "86% on our POC test set", **never** "JEV is 86% accurate".

---

## Part 12: Hands-on exercises

Do these in order. Use the Campaign Tester in the app, or the Python snippet from Part 4.3.

**Exercise 1: Your first call.**
Send the ticket-routing example from Part 2.3 with your own message, e.g. "The app crashes when I upload a photo." Which department did JEV pick? What's the confidence?

**Exercise 2: Check the score maths.**
Use the `score` question with a message of your choice. Calculate 0×p0 + 1×p1 + 2×p2 yourself and compare with `score`.

**Exercise 3: Ambiguity.**
Write a ticket that is half billing and half technical ("I was charged but the app crashed during payment"). Look at how the probabilities split.

**Exercise 4: Description quality.**
Take one `choice` question and replace the descriptions with single words ("billing": "billing"). Compare confidence before and after.

**Exercise 5: Option order.**
Send the same question twice with the criteria in a different order. Did the choice change? Did the numbers change? (Expect small changes; see Part 5.5.)

**Exercise 6: Campaign Tester.**
Test these in the app and write down choice + confidence:
- "Target male students." (easy)
- "Reach students who are struggling academically." (paraphrase)
- "Find students taking Deep Learning." (relational)
- "Find students interested in sports." (no right answer: does confidence drop?)

**Exercise 7: Many options.**
Make a `choice` question with 5 options, then 50 similar options. Compare confidence and output tokens.

**Exercise 8: The 255 limit.**
Send 300 options. Read the error message. Then find how the project's parser and client report it (`jev_request_rejected`).

**Exercise 9: Multi-condition campaigns.**
For "Find female students from Peshawar", design **one `noul` question per field** ("Does the campaign filter on gender?", "...on city?"). Do both come back high?

**Exercise 10: Read the tests.**
Open `backend/tests/test_jev_parser.py`. For each test, predict what it checks before reading it. Then add one new test: "a probability of 1.5 should be dropped."

**Exercise 11: Add a test case.**
Add a new campaign to `evaluation/test_cases.json` with an expected field, run the suite with `curl -X POST http://localhost:8001/api/tests/run`, and see the new result.

**Exercise 12: Design your own feature.**
Pick a real WoEngage decision (e.g. "Is this user message a complaint?", "Which segment fits this campaign?"). Write the `state`, `instructions` and `criteria`. Test it with 10 examples you already know the answer to, and calculate your own accuracy.

---

## Part 13: Cheat sheet

```text
ENDPOINT   POST https://openrouter.ai/api/alpha/decisions
AUTH       Authorization: Bearer <OPENROUTER_API_KEY>
MODEL      ~typesafe/jev-latest

REQUEST    { model, state, questions: { <name>: { type, instructions, criteria } } }

TYPES      noul    criteria {"true": "...", "false": "..."}      → { noul: 0..1 }
           choice  criteria {"key": "description", ...} (≤255)   → { choice, probabilities{}, confidence }
           score   criteria ["level0", "level1", ...]            → { score (expected value), legend,
                                                                     probabilities{"0":..}, confidence }

RESPONSE   { model, answers: { <name>: {...} }, usage: {input_tokens, output_tokens, cost}, id, provider }

LIMITS     32k tokens context · 255 options per choice

RULES      • confidence ≠ top probability ≠ correctness
           • never put the expected answer in state
           • shortlist before asking (fewer options → clearer answers)
           • retry only timeouts / 429 / 5xx, max 2
           • never fake missing values
```

---

## Part 14: Glossary

| Term | Meaning |
|---|---|
| **JEV** | TypeSafe's decision model; answers typed questions with probabilities |
| **State** | the information JEV reads (text or JSON) |
| **Question** | one typed decision you want JEV to make |
| **Instructions** | the question in plain words |
| **Criteria** | the possible answers and their meanings |
| **noul** | yes/no question type; answer is P(yes) |
| **choice** | pick-one question type |
| **score** | ordered-scale question type; answer is an expected value |
| **Probabilities** | JEV's belief spread over all options |
| **Confidence** | JEV's own trust in its answer (a separate number) |
| **Token** | a small piece of text (about ¾ of a word); the unit for size and cost |
| **Context window** | the maximum input size (32k tokens) |
| **Candidate / option** | a possible answer offered in `criteria` |
| **Shortlist** | picking the best candidates in your own code before asking JEV |
| **Ground truth / expected field** | the answer you know is right, used only for grading |
| **Accuracy** | correct ÷ scored |
| **Recall (shortlist)** | how often the right answer was among the options |
| **Provider** | the service you call JEV through (OpenRouter, Cloudflare) |
| **Mock mode** | fake answers for development, clearly labelled |

---

## Part 15: What is verified and what is not

| Fact | Status |
|---|---|
| OpenRouter endpoint, request and response format | ✅ verified with real calls |
| `noul`, `choice`, `score` answer formats | ✅ verified (real call, Part 2.4) |
| `score` = expected value of the levels | ✅ checked on 2 examples (real + docs) |
| Max 255 options per `choice` | ✅ real API error |
| Dotted option keys (`students.cgpa`) work | ✅ verified |
| Probabilities can be JSON integers | ✅ verified |
| Choice is stable across repeats; numbers vary about ±0.03 | ✅ 3 repeats of 1 case (small sample) |
| 32,000-token context | 📄 from Cloudflare docs; 18.4k tested fine |
| Cloudflare Workers AI path | 📄 built from docs, not tested live |
| Confidence predicts mistakes | ⚠ seen on 22 cases only; verify on your data |

Sources:
- [Cloudflare model page: typesafe/jev](https://developers.cloudflare.com/ai/models/typesafe/jev/)
- [OpenRouter blog: What Is Jev?](https://openrouter.ai/blog/insights/what-is-jev/)
- [OpenRouter docs: Alpha.Decisions](https://openrouter.ai/docs/client-sdks/go/sdks/decisions/README)
