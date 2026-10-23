"""V5: type too small to read when the long plays on a phone.

A phone held sideways shows the 1920-wide frame about 640 px across, so a
line set at 21 units of a 1920 canvas is 7 px tall there, and anything under
that is a smudge. The kit's own declared sizes all clear it; what this
catches is a line the fitter shrank to fit, and a two-shot whose plate is
drawn so small beside him that not even its biggest line reads. One line per
beat, so a warning never comes as a list he learns to skip.
"""

from __future__ import annotations

from types import SimpleNamespace

from pipeline import phone_type
from pipeline.phone_type import MIN_PHONE_PX, PHONE_W


def _plate(key="charts/bars-6y", w=1920):
    return SimpleNamespace(key=key, canvas=(w, 1080))


def _slot(name="axis-1"):
    return SimpleNamespace(name=name)


def _row(units, *, seg=3, t=134.0, slot="axis-1", text="FY21", w=1920):
    rows: list[dict] = []
    with phone_type.at_beat(rows, seg, t):
        phone_type.note(_plate(w=w), _slot(slot), text, units)
    return rows


def test_the_numbers_are_a_phone_held_sideways():
    assert PHONE_W == 640
    assert MIN_PHONE_PX == 7.0


def test_a_line_at_the_kits_smallest_size_passes():
    assert phone_type.findings(_row(22)) == []
    assert phone_type.findings(_row(21)) == []


def _beat(seg, t, lines, w=1920):
    rows: list[dict] = []
    with phone_type.at_beat(rows, seg, t):
        for slot, text, units in lines:
            phone_type.note(_plate(w=w), _slot(slot), text, units)
    return rows


def test_a_shrunk_line_is_named_with_its_plate_slot_and_time():
    got = phone_type.findings(_row(16, text="Revenue, FY21 to LTM"))
    assert got == [{"t": 134.0, "plate": "charts/bars-6y", "slot": "axis-1",
                    "text": "Revenue, FY21 to LTM", "phone_px": 5.3,
                    "beside": False, "shown": 1.0, "more": 0}]


def test_a_beat_is_one_finding_by_its_smallest_line():
    rows = _beat(3, 134.0, [("axis-1", "FY21", 18), ("axis-2", "FY22", 15),
                            ("title", "Revenue", 60)])
    got = phone_type.findings(rows)
    assert len(got) == 1
    assert (got[0]["slot"], got[0]["phone_px"], got[0]["more"]) == ("axis-2", 5.0, 1)


def test_a_two_shot_with_small_print_and_a_readable_point_is_quiet():
    # Beside him at a third of the frame the kicker is 3 px, but the
    # statement still reads: that is the trade the writer chose.
    rows = _beat(4, 48.0, [("kicker", "BOTH TRUE", 28),
                           ("statement-1", "Contracted.", 120)])
    assert phone_type.findings(rows, shown={4: 0.33}, beside={4}) == []


def test_a_two_shot_where_nothing_reads_is_named_by_its_biggest_line():
    rows = _beat(4, 48.0, [("kicker", "BOTH TRUE", 28),
                           ("statement-1", "Forty percent is contracted.", 62)])
    got = phone_type.findings(rows, shown={4: 0.3}, beside={4})
    assert got == [{"t": 48.0, "plate": "charts/bars-6y", "slot": "statement-1",
                    "text": "Forty percent is contracted.", "phone_px": 6.2,
                    "beside": True, "shown": 0.3, "more": 0}]


def test_a_plate_drawn_small_without_him_is_measured_at_its_size():
    rows = _row(30)
    assert phone_type.findings(rows) == []
    got = phone_type.findings(rows, shown={3: 0.5})
    assert got and got[0]["phone_px"] == 5.0 and not got[0]["beside"]


def test_nothing_is_noted_outside_a_beat():
    phone_type.note(_plate(), _slot(), "FY21", 10)
    rows = _row(30)
    assert len(rows) == 1


def test_a_counted_figure_is_measured_as_the_figure_it_lands_on():
    rows: list[dict] = []
    with phone_type.at_beat(rows, 5, 200.0):
        for text, units in (("$0", 15), ("$6M", 15), ("$12M", 14)):
            phone_type.note(_plate(), _slot("figure"), text, units)
    got = phone_type.findings(rows)
    assert len(got) == 1
    assert (got[0]["text"], got[0]["phone_px"]) == ("$12M", 4.7)


def test_the_report_says_where_and_what_to_do():
    text = phone_type.report({"phone_type": [
        {"t": 134.0, "plate": "charts/bars-6y", "slot": "axis-1",
         "text": "Revenue, FY21 to LTM", "phone_px": 5.3, "beside": False,
         "shown": 1.0, "more": 2}]})
    assert "2:14" in text
    assert "Revenue, FY21 to LTM" in text
    assert "charts/bars-6y" in text
    assert "2 more lines on it" in text
    assert "Shorten the line or split it" in text


def test_the_report_tells_a_two_shot_to_fill_the_frame():
    text = phone_type.report({"phone_type": [
        {"t": 48.0, "plate": "structure/both-true-16x9", "slot": "statement-1",
         "text": "Forty percent is contracted.", "phone_px": 6.2,
         "beside": True, "shown": 0.3, "more": 0}]})
    assert "0:48" in text and "30%" in text
    assert "Drop with=" in text
    assert "Shorten" not in text


def test_an_old_manifest_reports_nothing():
    assert phone_type.report({}) == ""
    assert phone_type.report({"phone_type": []}) == ""


def test_a_long_list_is_cut_to_the_first_few():
    many = [{"t": 60.0 * i, "plate": "p", "slot": f"s{i}", "text": f"t{i}",
             "phone_px": 5.0} for i in range(9)]
    text = phone_type.report({"phone_type": many})
    assert text.startswith("9 plates with type too small")
    assert "and 6 more" in text
    assert "t8" not in text
