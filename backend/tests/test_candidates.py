from app.services.candidate_service import (
    ambiguity_notes,
    fk_hop_distances,
    generate_candidates,
    stem,
    words_match,
)


def ids(candidates):
    return [c.field for c in candidates]


def test_stem_joins_word_forms():
    assert stem("enrolled") == stem("enrollments") == "enroll"
    assert stem("courses") == stem("course") == "course"
    assert stem("campus") == "campus"  # not 'campu'
    assert stem("class") == "class"


def test_words_match_allows_small_suffix_only():
    assert words_match("age", "aged")
    assert not words_match("age", "agent_name")
    assert not words_match("id", "idx")  # too short to prefix-match


def test_fields_are_table_qualified(snapshot):
    for c in generate_candidates("Find students with CGPA above 3.5.", snapshot.schema, snapshot.column_values):
        assert c.field == f"{c.table}.{c.column}"


def test_column_name_match_is_a_direct_reason(snapshot):
    cands = {c.field: c for c in generate_candidates("Find students with CGPA above 3.5.", snapshot.schema, snapshot.column_values)}
    assert "column name matches 'cgpa'" in cands["students.cgpa"].reasons


def test_value_match_surfaces_both_ambiguous_city_fields(snapshot):
    cands = {c.field: c for c in generate_candidates("Find students from Peshawar.", snapshot.schema, snapshot.column_values, max_fields=5)}
    assert "students.city" in cands and "campuses.city" in cands
    assert any("Peshawar" in r for r in cands["campuses.city"].reasons)


def test_relational_value_match_keeps_course_name(snapshot):
    result = ids(generate_candidates("Find students taking Machine Learning.", snapshot.schema, snapshot.column_values, max_fields=10))
    assert "courses.course_name" in result


def test_direct_matches_survive_the_cap(snapshot):
    result = ids(generate_candidates("Find female students from Peshawar.", snapshot.schema, snapshot.column_values, max_fields=2))
    assert {"students.gender", "students.city", "campuses.city"} <= set(result)


def test_cap_applies_when_schema_is_large(snapshot):
    assert len(generate_candidates("Target younger students.", snapshot.schema, snapshot.column_values, max_fields=10)) == 10


def test_small_schema_sends_everything(snapshot):
    total = len(snapshot.schema.field_ids())
    assert len(generate_candidates("anything", snapshot.schema, max_fields=total)) == total


def test_output_is_in_schema_order_not_score_order(snapshot):
    result = ids(generate_candidates("Find students with CGPA above 3.5.", snapshot.schema, snapshot.column_values))
    order = {f: i for i, f in enumerate(snapshot.schema.field_ids())}
    assert result == sorted(result, key=order.__getitem__)


def test_key_columns_are_penalised(snapshot):
    cands = {c.field: c for c in generate_candidates("Find students.", snapshot.schema, max_fields=100)}
    assert cands["students.student_id"].is_key
    assert cands["students.student_id"].score < cands["students.gender"].score


def test_fk_hops_follow_relationships(schema):
    hops = fk_hop_distances(schema, {"students"})
    assert hops["students"] == 0
    assert hops["enrollments"] == 1 and hops["departments"] == 1
    assert hops["courses"] == 2 and hops["campuses"] == 2
    assert "universities" not in hops  # 3 hops away


def test_generation_is_deterministic(snapshot):
    a = generate_candidates("Target currently active students.", snapshot.schema, snapshot.column_values)
    b = generate_candidates("Target currently active students.", snapshot.schema, snapshot.column_values)
    assert a == b


def test_ambiguity_notes_mention_same_named_candidates(snapshot):
    cands = generate_candidates("Find students from Peshawar.", snapshot.schema, snapshot.column_values)
    notes = ambiguity_notes("students.city", cands, snapshot.schema)
    assert notes and "campuses.city" in notes[0]
    assert ambiguity_notes("students.cgpa", cands, snapshot.schema) == []
