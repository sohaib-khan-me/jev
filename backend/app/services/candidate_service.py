"""Deterministic candidate-field generation (no embeddings, no LLM).

Goal: hand JEV a *recall-first* shortlist of 'table.column' fields. Candidate
generation must not decide the answer. It only removes obviously irrelevant
fields when the schema is larger than `max_fields`.

Scoring signals (all derived from the live schema, nothing hardcoded):

  +5  column-name match     a campaign word matches a word in the column name
                            ('cgpa' -> students.cgpa, 'semester' -> students.semester)
  +2  generic-name match    same, but for generic words (year, status, type, ...)
  +6  value phrase match    the campaign contains a stored value of the column
                            ('Peshawar' -> students.city AND campuses.city)
  +3  value word match      a campaign word matches a word inside a stored value
                            ('merit' -> 'Merit Scholarship' in students.scholarship_status)
  +3  anchor table          the campaign names the table ('students' -> students.*)
  +2/+1  related table      1 or 2 foreign-key hops from an anchor table
  -2  key column            primary/foreign keys are join plumbing, not audience conditions

Fields with a direct match (name or value) are always kept. The remaining slots
up to `max_fields` are filled by score. The final list is returned in schema
order, not score order, so the ranking cannot bias JEV through option position.
"""

import re
from collections import defaultdict, deque
from collections.abc import Mapping

from app.database.schema_inspector import SchemaSnapshot
from app.models.schemas import Candidate, DatabaseSchema

_WORD_RE = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset(
    "a an the and or of in on at to for from with by who whom that which is are was were be been "
    "find target get show list all any some their them they those these than above below over under "
    "more less have has had do does did not no into currently".split()
)
# Column-name words that carry little meaning on their own.
GENERIC_NAME_WORDS = frozenset({"id", "name", "status", "type", "code", "year", "level", "date"})

W_NAME, W_GENERIC_NAME, W_VALUE_PHRASE, W_VALUE_WORD = 5.0, 2.0, 6.0, 3.0
W_ANCHOR, W_HOP = 3.0, {1: 2.0, 2: 1.0}
W_KEY_PENALTY = -2.0


def stem(word: str) -> str:
    """Tiny suffix stripper so 'enrolled'/'enrollments' and 'course'/'courses' meet."""
    for suffix, repl in (("ments", ""), ("ment", ""), ("ies", "y"), ("ing", ""), ("ed", "")):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)] + repl
    # Plural 's', but not 'class', 'campus', 'analysis'.
    if word.endswith("s") and not word.endswith(("ss", "us", "is")) and len(word) > 3:
        return word[:-1]
    return word


def tokens(text: str, *, drop_stopwords: bool = True) -> list[str]:
    words = _WORD_RE.findall(text.lower())
    return [stem(w) for w in words if not (drop_stopwords and w in STOPWORDS)]


def words_match(a: str, b: str) -> bool:
    """Equal stems, or one is a slightly longer form of the other ('age'/'aged')."""
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 3 and long_.startswith(short) and len(long_) - len(short) <= 2


def _any_match(needles: set[str], haystack: set[str]) -> str | None:
    for n in sorted(needles):
        for h in haystack:
            if words_match(n, h):
                return n
    return None


def fk_hop_distances(schema: DatabaseSchema, anchors: set[str], max_hops: int = 2) -> dict[str, int]:
    """Breadth-first search over foreign keys (treated as undirected edges)."""
    graph: dict[str, set[str]] = defaultdict(set)
    for rel in schema.relationships:
        graph[rel.from_table].add(rel.to_table)
        graph[rel.to_table].add(rel.from_table)

    distances = {a: 0 for a in anchors}
    queue = deque(anchors)
    while queue:
        table = queue.popleft()
        if distances[table] >= max_hops:
            continue
        for neighbour in graph[table]:
            if neighbour not in distances:
                distances[neighbour] = distances[table] + 1
                queue.append(neighbour)
    return distances


def _value_phrase_hit(campaign_lower: str, values: tuple[str, ...]) -> str | None:
    for value in values:
        v = value.strip().lower()
        if len(v) >= 3 and re.search(rf"\b{re.escape(v)}s?\b", campaign_lower):
            return value
    return None


class CandidateService:
    def __init__(self, max_fields: int = 25) -> None:
        self.max_fields = max_fields

    def generate(self, campaign: str, snapshot: SchemaSnapshot) -> list[Candidate]:
        return generate_candidates(campaign, snapshot.schema, snapshot.column_values, self.max_fields)


def generate_candidates(
    campaign: str,
    schema: DatabaseSchema,
    column_values: Mapping[str, tuple[str, ...]] | None = None,
    max_fields: int = 25,
) -> list[Candidate]:
    column_values = column_values or {}
    campaign_lower = campaign.lower()
    campaign_words = set(tokens(campaign))

    table_stems = {t.name: stem(t.name.lower()) for t in schema.tables}
    anchors = {name for name, s in table_stems.items() if any(words_match(s, w) for w in campaign_words)}
    hops = fk_hop_distances(schema, anchors)

    scored: list[tuple[Candidate, bool, int]] = []  # (candidate, has_direct_match, schema_position)
    position = 0
    for table in schema.tables:
        for col in table.columns:
            field = f"{table.name}.{col.name}"
            score, reasons, direct = 0.0, [], False

            # Words of the column name, minus table names it merely repeats:
            # its own table ('student_status' -> 'status') and, for foreign keys,
            # the referenced table ('enrollments.student_id' -> 'id').
            ignore = {table_stems[table.name]}
            if col.foreign_key and col.foreign_key.references_table in table_stems:
                ignore.add(table_stems[col.foreign_key.references_table])
            name_words = {
                w
                for w in tokens(col.name.replace("_", " "), drop_stopwords=False)
                if not any(words_match(w, t) for t in ignore)
            }
            specific = {w for w in name_words if w not in GENERIC_NAME_WORDS}
            generic = name_words - specific
            if hit := _any_match(campaign_words, specific):
                score += W_NAME
                reasons.append(f"column name matches '{hit}'")
                direct = True
            elif hit := _any_match(campaign_words, generic):
                score += W_GENERIC_NAME
                reasons.append(f"column name matches generic word '{hit}'")

            values = column_values.get(field, ())
            if hit := _value_phrase_hit(campaign_lower, values):
                score += W_VALUE_PHRASE
                reasons.append(f"campaign mentions stored value '{hit}'")
                direct = True
            else:
                value_words = {w for v in values for w in tokens(v)}
                if hit := _any_match({w for w in campaign_words if len(w) >= 4}, value_words):
                    score += W_VALUE_WORD
                    reasons.append(f"campaign word '{hit}' appears in stored values")
                    direct = True

            distance = hops.get(table.name)
            if distance == 0:
                score += W_ANCHOR
                reasons.append(f"campaign mentions table '{table.name}'")
            elif distance in W_HOP:
                score += W_HOP[distance]
                reasons.append(f"{distance} foreign-key hop(s) from a mentioned table")

            is_key = col.primary_key or col.foreign_key is not None
            if is_key:
                score += W_KEY_PENALTY
                reasons.append("key column (join plumbing)")

            candidate = Candidate(
                field=field,
                table=table.name,
                column=col.name,
                column_type=col.column_type,
                is_key=is_key,
                score=score,
                reasons=reasons,
            )
            scored.append((candidate, direct, position))
            position += 1

    if len(scored) <= max_fields:
        selected = scored
    else:
        must_keep = [s for s in scored if s[1]]
        rest = sorted((s for s in scored if not s[1]), key=lambda s: (-s[0].score, s[2]))
        selected = must_keep + rest[: max(0, max_fields - len(must_keep))]

    return [c for c, _, _ in sorted(selected, key=lambda s: s[2])]


def ambiguity_notes(selected_field: str, candidates: list[Candidate], schema: DatabaseSchema) -> list[str]:
    """Explain when the selected field shares its column name with other fields JEV could see."""
    candidate_ids = {c.field for c in candidates}
    notes = []
    for group in schema.ambiguous_columns:
        if selected_field in group.fields:
            others = [f for f in group.fields if f != selected_field and f in candidate_ids]
            if others:
                notes.append(f"'{group.column_name}' also exists as {', '.join(others)}; the schema alone cannot disambiguate.")
    return notes
