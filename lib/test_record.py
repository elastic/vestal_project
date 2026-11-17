"""Offline tests for record.py: typed free fields (span id, integer, date) and the unchanged option fields."""
import builtins
import contextlib
import io
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import record as R  # noqa: E402


def feed(monkeypatch, answers):
    it = iter(answers)
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(it))


def test_parse_value_table():
    ok = [("span_id", " 69DA95B611A285CE ", "69da95b611a285ce"), ("integer", "12,345", 12345), ("integer", "9_000", 9000),
          ("integer", "-3", -3), ("date", "2026-11-03", "2026-11-03"), ("text", "  hi ", "hi")]
    for kind, raw, want in ok:
        assert R.parse_value(kind, raw) == want, (kind, raw)
    bad = [("span_id", "69da95b611a285c"), ("span_id", "zzzzzzzzzzzzzzzz"), ("span_id", ""), ("integer", "12.5"), ("integer", "ten"),
           ("integer", ""), ("date", "2026-13-01"), ("date", "2026-02-30"), ("date", "11/03/2026"), ("date", "2026-1-3"), ("bogus", "x")]
    for kind, raw in bad:
        try:
            R.parse_value(kind, raw)
        except ValueError:
            continue
        raise AssertionError((kind, raw))


def test_collect_reprompts_and_types(monkeypatch):
    schema = [{"key": "failing_span_id", "label": "Failing span", "type": "span_id"},
              {"key": "costly_input_tokens", "label": "Tokens", "type": "integer"},
              {"key": "change_point_date", "label": "Date", "type": "date"},
              {"key": "note", "label": "Note"},
              {"key": "failure_class", "label": "Class", "options": ["a", "b"]}]
    feed(monkeypatch, ["nope", "69da95b611a285ce", "9k", "9,000", "2026-02-30", "2026-11-03", " free ", "9", "2"])
    with contextlib.redirect_stdout(io.StringIO()) as out:
        got = R.collect(schema)
    assert got == {"failing_span_id": "69da95b611a285ce", "costly_input_tokens": 9000, "change_point_date": "2026-11-03",
                   "note": "free", "failure_class": "b"}
    assert "A span id is 16 hex characters." in out.getvalue() and "Enter a whole number." in out.getvalue()
    assert "correct" not in out.getvalue().lower()


def test_unknown_field_type_is_a_schema_error(monkeypatch):
    feed(monkeypatch, ["x"])
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            R.collect([{"key": "k", "label": "L", "type": "uuid"}])
    except ValueError as e:
        assert "unknown type" in str(e)
    else:
        raise AssertionError
