"""The canonical schema, its examples and the invalid set; the schema and ara_loop.validate_proposal agree on every case."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ara_loop as L  # noqa: E402
import ara_proposal_schema as P  # noqa: E402


def test_valid_examples_pass_both_rule_sets():
    assert len(P.VALID) == 3
    for name, p in P.VALID.items():
        assert P.problems(P.wrap(p)) == [], name
        assert L.validate_proposal(p) == [], name


def test_every_invalid_case_fails_both_rule_sets_and_the_set_is_large_enough():
    assert len(P.INVALID) >= 12 and len({r for r, _ in P.INVALID}) == len(P.INVALID)
    for rule, p in P.INVALID:
        assert P.problems(P.wrap(p)), rule
        assert L.validate_proposal(p), rule


def test_output_shape_is_part_of_the_schema():
    assert P.problems({"proposals": "x"}) and P.problems([P.VALID["attach"]]) and P.problems({})
    assert P.problems({"proposals": []}) == []
    assert P.problems({"proposals": [P.VALID["attach"], P.INVALID[0][1]]})


def test_extra_fields_and_rationale_are_allowed():
    p = dict(P.VALID["attach"], proposal_id="x", run_id="y", rationale="anything at all")
    assert P.problems(P.wrap(p)) == [] and L.validate_proposal(p) == []


def test_committed_schema_file_matches():
    f = pathlib.Path(__file__).resolve().parent.parent / "data" / "ara-m6" / "proposal.schema.json"
    assert json.loads(f.read_text()) == P.SCHEMA
