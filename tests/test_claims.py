"""S6: the sentences no gate can verify, listed for a human."""

from pipeline.claims import claims_lines, list_claims, script_claims
from pipeline.models import CostReport


def test_dated_event_is_a_claim():
    claims = list_claims("Revenue grew 12%.\nIn March 2023 the chief "
                         "executive resigned without notice.", "EXMPL")
    assert len(claims) == 1
    assert claims[0].line == 2
    assert "resigned" in claims[0].why


def test_a_year_said_in_words_dates_the_event():
    """The narration spells its figures out for the voice, years included,
    so a year in digits is the rare case: "fined in twenty nineteen"."""
    for said in ("twenty nineteen", "twenty twenty-two", "twenty twenty two",
                 "nineteen ninety-nine", "two thousand and eight",
                 "twenty oh nine"):
        claims = list_claims(f"They were fined in {said} for the accounts.",
                             "EXMPL")
        assert [c.why for c in claims] == ["a dated event: “fined”"], said
    assert list_claims("They cut two thousand jobs and kept going.", "EXMPL") == []


def test_named_event_is_a_claim():
    claims = list_claims("Last spring the company acquired Widget Holdings "
                         "for cash.", "EXMPL")
    assert [c.text for c in claims] == [
        "Last spring the company acquired Widget Holdings for cash."]


def test_workbook_figure_alone_is_not():
    assert list_claims("Revenue grew 12% to $4.1 billion. Margins held at "
                       "31%. EXMPL trades at nine times earnings.", "EXMPL") == []


def test_dennis_story_line_is_not():
    narration = ("I sold my whole account in March 2022, which was the "
                 "bottom.\nKev bought it on a Tuesday because his barber "
                 "said so.")
    assert list_claims(narration, "EXMPL") == []


def test_may_the_verb_is_not_a_date():
    assert list_claims("The margin may hold if pricing holds.", "EXMPL") == []
    assert list_claims("On May 4 the board approved the buyback.", "EXMPL")


def test_lines_follow_the_stored_script():
    raw = ("[BEAT: hook]\nRevenue grew 12%.\n\n[SHOW_FILING: 10-K p.4]\n"
           "In 2021 Example Corp acquired Widget Holdings for cash.")
    narration = ("Revenue grew 12%.\nIn 2021 Example Corp acquired Widget "
                 "Holdings for cash.")
    claims = list_claims(narration, "EXMPL", raw)
    assert [c.line for c in claims] == [5]
    assert claims_lines(claims)[0].startswith("L5: In 2021 Example Corp")


def test_short_scripts_read_their_audio():
    class Short:
        audio_script = "On Friday the regulator fined them $40 million."

    assert script_claims(Short(), "EXMPL")


def test_report_renders_claims():
    report = CostReport(ticker="EXMPL", fmt="long", words=10, chars=60,
                        tts_cached=True, est_tts_usd=0.0,
                        claims=["L3: one (why)", "L9: two (why)"])
    text = report.render_text()
    assert "Claims to check yourself (not workbook numbers):" in text
    assert "  • L3: one (why)" in text and "  • L9: two (why)" in text


def test_claims_empty():
    report = CostReport(ticker="EXMPL", fmt="short", words=10, chars=60,
                        tts_cached=True, est_tts_usd=0.0)
    assert "Claims to check" not in report.render_text()
    assert list_claims("", "EXMPL") == []
