"""Option-cost fixes from the outside review: LEAPS top-ups and put-spread pricing (model-priced research studies)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "research")]
import leaps_study as L  # noqa: E402
import vol_selling as V  # noqa: E402


def test_leaps_top_up_adds_the_requested_dollar_delta():
    """Topping up an older contract is priced with that contract, not a fresh one."""
    book = L.Leaps(0.7, 540)
    book.buy(100.0, 0.03, 0.25, 10_000)
    book.step(200)
    S = 130.0                                                         # rally: the held contract is now deeper ITM
    before = book.dollar_delta(S, 0.03, 0.25)
    want = 5_000.0
    book.buy(S, 0.03, 0.25, book.cost_for_dollar_delta(S, 0.03, 0.25, want))
    assert book.dollar_delta(S, 0.03, 0.25) - before == pytest.approx(want, rel=1e-9)


def test_put_spread_pays_the_ask_on_the_long_leg():
    S, r, vxn = 100.0, 0.03, 0.25
    book = V.PutBook(0.0, 0.10)
    prem = book.open(S, r, vxn, notional=100.0)
    p1 = V.bs_put(S, 100.0, V.TENOR, r, V.put_iv(S, 100.0, vxn))
    p2 = V.bs_put(S, 90.0, V.TENOR, r, V.put_iv(S, 90.0, vxn))
    bid_short = p1 * (1 - V.HAIRCUT) - V.MIN_TICK * S
    ask_long = p2 * (1 + V.HAIRCUT) + V.MIN_TICK * S
    assert prem == pytest.approx(book.units * (bid_short - ask_long))
    naked = V.PutBook(0.0, 0.0).open(S, r, vxn, notional=100.0)
    assert naked == pytest.approx(book.units * bid_short)
