from datetime import date

from optwise.extract import extract, parse_span


def test_parse_span_pins_only_what_is_written():
    assert parse_span("2027-05-15").value == date(2027, 5, 15)
    assert parse_span("12/18/2027").value == date(2027, 12, 18)  # 18 cannot be a month
    assert parse_span("15.05.2027").value == date(2027, 5, 15)
    assert parse_span("May 15, 2027").value == date(2027, 5, 15)
    assert parse_span("6th of August 2027").value == date(2027, 8, 6)
    amb = parse_span("05/06/2027")
    assert amb.status == "ambiguous" and amb.candidates == (date(2027, 5, 6), date(2027, 6, 5))
    assert parse_span("may 20").status == "partial"  # year never assumed
    assert parse_span("summer 2027").candidates == (date(2027, 6, 1), date(2027, 8, 31))
    assert parse_span("winter 2027").candidates == (date(2027, 12, 1), date(2028, 2, 29))
    assert parse_span("this spring").status == "missing"
    assert parse_span("2027-02-30").status == "missing"


def test_extract_drops_invented_spans_and_flags_conflicts():
    q = "I-20 says program ends 2027-05-15, advisor says 2027-05-10; DSO rec on 2027-04-01"
    x = extract(q, [
        {"role": "program_end", "span": "2027-05-15"},
        {"role": "program_end", "span": "2027-05-10"},
        {"role": "ead_expiry", "span": "2028-01-01"},  # not in the question: invented
    ])
    assert x.rejected == ("2028-01-01",)
    assert "program_end" not in x.exact()  # two different dates for one role: ask, never pick
    assert x.unlabelled == ("2027-04-01",)  # regex saw a date the LLM did not label


def test_ead_expiry_label_needs_ead_context():
    q = "What's my OPT deadline (end 2027-12-18)?"
    assert "ead_expiry" not in extract(q, [{"role": "ead_expiry", "span": "2027-12-18"}]).exact()
    q = "My EAD card expires 2028-07-01"
    assert extract(q, [{"role": "ead_expiry", "span": "2028-07-01"}]).exact() == {"ead_expiry": date(2028, 7, 1)}
