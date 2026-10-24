"""S10: Kev's tip and the old trade every six to eight longs, never both."""

from __future__ import annotations

from types import SimpleNamespace

from pipeline import recurring_bits as rb
from pipeline.standing import ConfessionLedger


def _ship(settings, n: int, bit: str = "", start: int = 0) -> None:
    led = rb.BitLedger(settings)
    for k in range(start, start + n):
        led.note(f"T{k}/2026-07-{k + 1:02d}/long", f"T{k}", f"2026-07-{k + 1:02d}", bit)


def _long(text: str, confession=None):
    return SimpleNamespace(narration=text, chapter_list=[], confession=confession)


def test_nothing_due_until_the_gap(settings):
    _ship(settings, 5)
    assert rb.due_bit(settings) == ""
    _ship(settings, 3, start=5)
    assert rb.due_bit(settings) == "kev_tip"


def test_gap_is_seeded_and_in_window(settings):
    led = rb.BitLedger(settings)
    g = led.gap_for("kev_tip")
    assert rb.GAP[0] <= g <= rb.GAP[1]
    assert led.gap_for("kev_tip") == g
    _ship(settings, 1, bit="kev_tip")
    assert rb.GAP[0] <= led.gap_for("kev_tip") <= rb.GAP[1]


def test_old_trade_waits_for_confession_due(settings):
    _ship(settings, 8)
    led = rb.BitLedger(settings)
    led.note("K/2026-08-01/long", "K", "2026-08-01", "kev_tip")
    _ship(settings, 0)
    # Kev just ran; the old trade is past its gap but no confession is due.
    assert rb.due_bit(settings, confession_due=False) == ""
    assert rb.due_bit(settings, confession_due=True) == "old_trade"


def test_never_both(settings):
    _ship(settings, 9)
    assert rb.due_bit(settings, confession_due=True) in ("kev_tip", "old_trade")


def test_due_reads_the_confession_ledger(settings):
    _ship(settings, 9)
    rb.BitLedger(settings).note("K/2026-08-01/long", "K", "2026-08-01", "kev_tip")
    led = ConfessionLedger(settings)
    for k in range(3):
        led.note(f"C{k}", fmt="long")
    assert rb.due_bit(settings) == "old_trade"
    assert "OLD TRADE" in rb.old_trade_line(settings)


def test_kev_word_boundary():
    assert rb.detect_bit("Kevin from accounts.", confessed=False,
                         old_trade_ready=False) == ""
    assert rb.detect_bit("Kev texted me.", confessed=False,
                         old_trade_ready=False) == "kev_tip"
    assert rb.detect_bit("I bought it at nineteen.", confessed=True,
                         old_trade_ready=True) == "old_trade"


def test_kev_too_soon_warns(settings):
    _ship(settings, 2)
    found = rb.bits_lint(_long("Margins fell.\nKev texted me at six."), settings)
    assert len(found) == 1 and found[0].line == 2 and found[0].gate == "bits"
    assert rb.bits_lint(SimpleNamespace(narration="Kev texted."), settings) == []


def test_block_names_the_due_bit(settings):
    assert "No recurring bit is due" in rb.bits_block(settings)
    _ship(settings, 8)
    assert "KEV'S TIP" in rb.bits_block(settings)


def test_note_long_is_idempotent(settings):
    _ship(settings, 8)
    s = _long("Kev texted me.")
    assert rb.note_long(settings, "A/1/long", "A", "1", s) == "kev_tip"
    rb.note_long(settings, "A/1/long", "A", "1", s)
    assert len(rb.BitLedger(settings).rows()) == 9


def test_a_passing_mention_in_a_long_that_is_not_kev_s_keeps_his_place(settings):
    """`bits_lint` allows one line of Kev outside his video; recorded as the
    tip, that line pushed the real one back six to eight longs."""
    _ship(settings, 2)
    led = rb.BitLedger(settings)
    passing = _long("Margins fell. Even Kev would have sold here. The cash went.")
    assert rb.note_long(settings, "P/1/long", "P", "1", passing) == ""
    assert led.since("kev_tip") == 3
    # Kev through a whole passage is the bit, due or not.
    run = _long("Kev texted me at six. Kev says it is the next big thing. "
                "Kev is wrong.")
    assert rb.note_long(settings, "R/1/long", "R", "1", run) == "kev_tip"
    assert led.since("kev_tip") == 0


def test_junk_ledger(settings):
    (settings.state_dir / rb.BITS_FILE).write_text("{oops", encoding="utf-8")
    assert rb.due_bit(settings) == ""
    assert "No recurring bit is due" in rb.bits_block(settings)


def test_only_a_financial_confession_is_the_old_trade(settings):
    """The old trade is declared `financial | …`. A long whose confession
    was another kind did not carry it, and recording it as the old trade put
    the real one back six to eight longs."""
    _ship(settings, 9)
    rb.BitLedger(settings).note("K/2026-08-01/long", "K", "2026-08-01", "kev_tip")
    for k in range(3):
        ConfessionLedger(settings).note(f"C{k}", fmt="long")
    assert rb.due_bit(settings, confession_due=True) == "old_trade"
    other = _long("Margins fell.", SimpleNamespace(
        kind="epistemic", text="I said it would double. It halved."))
    assert rb.note_long(settings, "O/1/long", "O", "1", other) == ""
    trade = _long("Margins fell.", SimpleNamespace(
        kind="financial", text="I bought it at nineteen in 2019."))
    assert rb.note_long(settings, "F/1/long", "F", "1", trade) == "old_trade"
