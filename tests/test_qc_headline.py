"""qc/main.py sleeves=HEADLINE vs the local headline v2, on the offline harness (NOT a LEAN run)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "research"), str(ROOT / "tests")]
import qc_harness as h  # noqa: E402
from common import build_signals, load_panel, perf_stats  # noqa: E402
from strategy import Cfg, prepare, run  # noqa: E402

G = 1.01
A, B = "2007-02-01", "2026-09-11"
# README headline v2 (the same Cfg as allocation/research/allocation_study.py's V2)
V2 = Cfg("frozen v2", core=(("qqq", 0.5), ("spy", 0.5)), tranche=0.075, tranche_step=0.92, lev_cap=0.30,
         lev="qld", trend_guard=True)


def basket_cfg(q):
    """QC-like model at 70% equity: trend half holds the basket, reset on events (allocation study's 70% cell)."""
    core = tuple((k, w) for k, w in (("qqq", q), ("spy", 1 - q)) if w > 1e-12)
    return Cfg(f"70% basket, {q:.0%} QQQ", core=core, core_target=0.70, tranche=0.075, tranche_step=0.92,
               lev="qld", lev_size=0.10, lev_cap=0.30, trend_guard=True, trend_asset="core", basket_reset="event")


@pytest.fixture(scope="module")
def data():
    P = load_panel(); D = prepare(P, build_signals(P)); D["r_cash"] = 0.0
    return P, D


def toy(n=320, fire=(), off=()):
    """First 260 bars flat history, then QQQ +1%/day while SPY and T-bills are flat. Indices count from bar 260."""
    idx = pd.bdate_range("2019-01-01", periods=n)
    D = pd.DataFrame(index=idx)
    r = np.where(np.arange(n) > 260, G - 1, 0.0)
    D["qqq"], D["r_qqq"], D["r_spy"], D["r_qld"], D["r_tqqq"] = 100 * np.cumprod(1 + r), r, 0.0, 2 * r, 3 * r
    D["rf"], D["vxn"], D["p"] = 0.0, 20.0, 0.5
    for i in fire:
        D.iloc[260 + i, D.columns.get_loc("p")] = 0.9
    return D, idx[260], idx[-1]


def test_headline_matches_local_v2(data):
    P, D = data
    ref, tr = run(D, V2, A, B)
    r, a = h.run_qc(D, A, B, dict(sleeves="HEADLINE"))
    x, y = perf_stats(r.nav, P["rf"]), perf_stats(ref.nav, P["rf"])
    assert x["Sharpe"] == pytest.approx(y["Sharpe"], abs=0.01)
    assert x["CAGR"] == pytest.approx(y["CAGR"], abs=0.002)
    assert x["MaxDD"] == pytest.approx(y["MaxDD"], abs=0.005)
    assert r.nav.pct_change().corr(ref.nav.pct_change()) > 0.999
    for q, l in [("qqq", "qqq_w"), ("spy", "spy_w"), ("qld", "lev"), ("book_powder", "reserve")]:
        assert (r[q] - ref[l]).abs().mean() < 0.005, q
    assert (r.book_trend - ref.trend - ref.trend_parked).abs().mean() < 0.005
    assert abs(len([m for m in a.logs if "[TRADE]" in m]) - len(tr)) <= 5


def test_headline_starts_75_25_and_drifts():
    D, s, e = toy()
    r, a = h.run_qc(D, s, e, dict(sleeves="HEADLINE", lev="NONE", greed_p=-1))
    assert a.n_rebalance == 1                                           # only the opening trade
    # sized at the first close, filled after QQQ rose 1% (the one-bar order delay)
    assert r.qqq.iloc[1] == pytest.approx(0.525 * G, abs=0.001) and r.spy.iloc[1] == pytest.approx(0.175, abs=0.003)
    q0, v0 = r.qqq.iloc[1] * r.nav.iloc[1], r.spy.iloc[1] * r.nav.iloc[1]
    assert r.qqq.iloc[-1] * r.nav.iloc[-1] == pytest.approx(q0 * G ** (len(r) - 2))
    assert r.spy.iloc[-1] * r.nav.iloc[-1] == pytest.approx(v0)


def test_headline_buy_does_not_reset_the_basket():
    """A tranche adds 50/50; VOO is never sold to rebalance (BASKET mode would sell QQQ here)."""
    D, s, e = toy(fire=[30])
    out = {}
    for mode in ("HEADLINE", "BASKET"):
        r, _ = h.run_qc(D, s, e, dict(sleeves=mode, core="QQQ:0.5,VOO:0.5", lev="NONE", greed_p=-1, trend_guard=0))
        out[mode] = r
    r = out["HEADLINE"]
    before, after = r.iloc[30], r.iloc[31]
    buy = 0.075 * before.nav
    assert after.spy * after.nav - before.spy * before.nav == pytest.approx(buy / 2, rel=0.01)
    assert after.qqq * after.nav - before.qqq * before.nav * G == pytest.approx(buy / 2 * G, rel=0.02)
    assert after.qqq / after.spy > 1.2
    assert (r.iloc[31:].qqq > r.iloc[31:].spy).all()


@pytest.mark.parametrize("sleeves", ["HEADLINE", "BASKET"])
@pytest.mark.parametrize("core", ["QQQ:0.5,VOO:0.5", "VOO:1", "QQQ:1"])
def test_parked_money_stays_parked(data, core, sleeves):
    """2008: trend half leaves the market; parked T-bills are not spent on tranches and the book always sums to 1."""
    _, D = data
    r, a = h.run_qc(D, "2007-02-01", "2010-12-31", dict(sleeves=sleeves, core=core))
    b = r[["book_core", "book_trend", "book_lev", "book_powder"]]
    # sizing at t and filling at t+1 can overdraw cash slightly (costs) once powder is spent: < 0.1% of NAV
    assert np.allclose(b.sum(axis=1), 1, atol=1e-3) and (b >= -1e-12).all().all()
    off = r.loc["2008-11"]
    assert (off.book_trend > 0.25).all() and (off.book_powder < 0.05).all()
    assert (off.bil >= off.book_trend - 0.02).all()                     # really held in T-bills
    if core == "VOO:1":
        assert (off.qqq.abs() < 1e-9).all()


def test_bad_mode_rejected(data):
    with pytest.raises(ValueError):
        h.run_qc(data[1], "2007-02-01", "2007-03-01", dict(sleeves="OTHER"))


@pytest.mark.parametrize("params", [{}, dict(core="QQQ:0.5,VOO:0.5")])
def test_default_is_basket(data, params):
    a, b = (h.run_qc(data[1], "2007-02-01", "2008-12-31", {**params, **x})[0] for x in ({}, dict(sleeves="BASKET")))
    assert a.equals(b)


def test_default_first_tranche_buys(data):
    """Regression: BASKET used to re-base the book on the bar that created it, before the opening orders filled, so core
    and trend became 0 and the first tranche (2007-08-16) sold equity from 70% down to 7.5%."""
    r, a = h.run_qc(data[1], "2007-02-01", "2007-08-31", dict(core="QQQ:0.5,VOO:0.5"))
    eq = r.qqq + r.spy
    t = r.index.get_loc(pd.Timestamp("2007-08-15"))                     # first tranche signal
    assert eq.iloc[t] > 0.6
    assert eq.iloc[t + 1] - eq.iloc[t] == pytest.approx(0.075, abs=0.01)
    assert (r.book_core.iloc[2:] > 0.3).all()


@pytest.mark.parametrize("q,core", [(0.5, "QQQ:0.5,VOO:0.5"), (1.0, "QQQ:1")])
def test_basket_matches_study_cell(data, q, core):
    """Fixed BASKET mode is the allocation study's QC-like model (trend half in the basket, reset on events)."""
    P, D = data
    ref, _ = run(D, basket_cfg(q), A, B)
    r, _ = h.run_qc(D, A, B, dict(core=core))
    x, y = perf_stats(r.nav, P["rf"]), perf_stats(ref.nav, P["rf"])
    assert x["Sharpe"] == pytest.approx(y["Sharpe"], abs=0.01)
    assert x["CAGR"] == pytest.approx(y["CAGR"], abs=0.003)
    assert x["MaxDD"] == pytest.approx(y["MaxDD"], abs=0.01)
    assert r.nav.pct_change().corr(ref.nav.pct_change()) > 0.998
