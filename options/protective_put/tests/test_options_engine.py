"""Checks for the 12-month put hedge engine (research/options_overlay.py) and pricing (research/options_model.py)."""
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))     # options/protective_put/research
import _paths  # noqa: E402,F401  (puts the repo's research/ on sys.path)
import strategy  # noqa: E402
from common import build_signals, load_panel  # noqa: E402
from options_model import CENTRAL, OptionBook, bs  # noqa: E402
from options_overlay import V2, Hedge, run  # noqa: E402


@pytest.fixture(scope="module")
def D():
    P = load_panel()
    return strategy.prepare(P, build_signals(P))


def test_no_hedge_reproduces_strategy_run(D):
    ref, ref_tr = strategy.run(D, V2, "2007-02-01", "2026-09-11")
    mine, tr, hl, led = run(D, V2)
    assert np.allclose(ref["nav"].to_numpy(), mine["nav"].to_numpy(), rtol=0, atol=1e-9)
    assert len(ref_tr) == len(tr) and hl.empty and led == []


def test_put_call_parity():
    S, K, T, r, sig = 100.0, 85.0, 1.0, 0.03, 0.25
    p = bs(S, K, T, r, sig, "P")[0]
    c = bs(S, K, T, r, sig, "C")[0]
    assert abs(c - p - (S - K * np.exp(-r * T))) < 1e-10


def test_spread_costs_and_round_trip():
    b = OptionBook(CENTRAL)
    paid = b.open("P", 85.0, 1.0, 10.0, 100.0, 0.03, 0.20)
    got = b.close(0, 100.0, 0.03, 0.20)
    assert paid < 0 < got < -paid           # buy at the ask, sell at the bid
    assert b.legs == [] and len(b.ledger) == 2


def test_ledger_explains_nav_gap(D):
    """Static 70/30 (no v2 rules) with a P1 hedge: NAV(hedged) - NAV(static) must equal the option mark plus every
    option cash flow compounded at the T-bill rate from its date."""
    c = replace(V2, fear_off=True, trend_guard=False, lev=None)
    base, *_ = run(D, c, "2007-02-01", "2012-12-31")
    res, tr, hl, led = run(D, c, "2007-02-01", "2012-12-31", hedge=Hedge(exit="fear", proceeds="tbill"))
    gap = res["nav"] - base["nav"]
    rf = D.loc[res.index, "rf"] / 252
    growth = (1 + rf).cumprod()
    flows = res["opt_flow"]
    compounded = (flows / growth).cumsum() * growth
    assert len(led) > 0
    assert np.allclose(gap.to_numpy(), (res["opt_mark"] + compounded).to_numpy(), atol=1e-6)


def test_sale_funds_same_close_tranche(D):
    """P2 proceeds are credited before tranche sizing on the same close; P1 proceeds never fund a tranche."""
    t = pd.Timestamp("2008-10-21")                       # first close after the Oct 20, 2008 fear-exit signal
    out = {}
    for pr in ["tranche", "tbill"]:
        res, tr, hl, led = run(D, V2, hedge=Hedge(exit="fear", proceeds=pr))
        sale = hl[(hl.event == "fear exit") & (hl.date == t)]
        assert len(sale) == 1 and sale.cash.iloc[0] > 0
        out[pr] = (res, tr)
    # with P1 the proceeds sit in the bucket on the sale day, with P2 they are in the powder
    assert out["tbill"][0].loc[t, "bucket"] > 0
    assert out["tranche"][0].loc[t, "bucket"] == 0
    # same-close tranche buy is larger (or only possible) when the sale feeds the powder
    amt = {pr: out[pr][1][(out[pr][1].date == t) & (out[pr][1].action == "tranche")].amount.sum() for pr in out}
    assert amt["tranche"] >= amt["tbill"]
    # P1: the bucket is never drawn down by tranche / QLD buys — it only changes through hedge cash flows and interest
    res = out["tbill"][0]
    b = res["bucket"] * res["nav"]
    rf = D.loc[res.index, "rf"] / 252
    jumps = b - b.shift(1) * (1 + rf)
    hedge_days = res.index[(res["opt_flow"] != 0)]
    assert (jumps.drop(hedge_days).abs().dropna() < 1e-6).all()


def test_spreads_widen_in_stress():
    """The engine passes VXN in decimals; stress_vxn is in vol points."""
    s = CENTRAL
    assert s.h(0.15) == s.h(0.25) == s.half_spread
    assert abs(s.h(0.80) - s.half_spread * 80 / s.stress_vxn) < 1e-12


def test_no_token_puts(D):
    """Every put bought covers at least half of its target (Feb 25, 2019: a roll before the same-day QLD exit used
    to buy a put on 0.4% of NAV and hold it for eight months)."""
    for cover in ["all", "unguarded"]:
        res, tr, hl, led = run(D, V2, hedge=Hedge(cover=cover, exit="hold", proceeds="tranche"))
        L = pd.DataFrame(led)
        for x in L[L.units > 0].itertuples():
            r = res.loc[x.date]
            target = (r.core + 2 * r.lev + (r.trend if cover == "all" else 0)) * r.nav
            assert x.units * x.S >= 0.5 * target * 0.95, (cover, x.date)
