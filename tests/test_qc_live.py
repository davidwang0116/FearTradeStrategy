"""qc/main.py live-readiness fixes on the offline harness (NOT LEAN): percentile parity with research, restarts,
take-profit gain from actual fills."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "research"), str(ROOT / "tests"), str(ROOT / "qc")]
import qc_harness as h  # noqa: E402
import signals  # noqa: E402
from common import build_signals, load_panel  # noqa: E402
from strategy import prepare, run  # noqa: E402
from test_qc_headline import A, B, V2  # noqa: E402


@pytest.fixture(scope="module")
def data():
    P = load_panel(); D = prepare(P, build_signals(P)); D["r_cash"] = 0.0
    D["vix"], D["vxn_backfilled"] = P["vix"], P["vxn_backfilled"]      # the harness then feeds QC-like VXN (2008 on)
    return P, D


# ---------------------------------------------------------------- percentile
def test_pct_of_matches_expanding_pct():
    x = pd.Series(np.round(np.random.default_rng(1).normal(size=1500), 1))      # many ties
    ref = signals.expanding_pct(x)
    got = [signals.pct_of(x.iloc[:i].to_numpy(), x.iloc[i]) for i in range(len(x))]
    assert np.allclose(np.asarray(got, float), ref.to_numpy(), equal_nan=True, atol=1e-12)


def test_vxn_ratio_matches_panel(data):
    P, _ = data
    b = P["vxn_backfilled"].astype(bool)
    assert (P["vxn"] / P["vix"])[b].to_numpy() == pytest.approx(signals.VXN_VIX_RATIO, abs=1e-12)


@pytest.mark.parametrize("start,end", [("2011-01-03", "2012-06-29"), ("2007-06-01", "2008-03-31")])
def test_qc_percentile_matches_research(data, start, end):
    """The real QC signal path (full-history seed, VXN from 2008 + VIX back-fill, daily composite) gives research's p.
    The second window starts before QC has any VXN, so the daily VIX fill is used too."""
    _, D = data
    r, a = h.run_qc(D, start, end, dict(lev="NONE"), real_signals=True)
    assert a.comp_from == pd.Timestamp("2000-03-08").date()
    assert (r.p - D["p"].reindex(r.index)).abs().max() < 1e-9


def test_short_seed_raises(data):
    _, D = data
    D2 = D.copy(); D2.loc[:"2003-12-31", "vix"] = np.nan
    with pytest.raises(ValueError, match="allow_short_seed"):
        h.run_qc(D2, "2011-01-03", "2011-01-10", real_signals=True)
    r, a = h.run_qc(D2, "2011-01-03", "2011-01-10", dict(allow_short_seed=1), real_signals=True)
    assert a.comp_from >= pd.Timestamp("2004-01-01").date()


# ---------------------------------------------------------------- take-profit gain from fills
def test_take_profit_uses_fill_price():
    """QLD gaps +10% between the signal and the fill; the 60% take-profit counts from the fill price."""
    n = 320
    idx = pd.bdate_range("2019-01-01", periods=n)
    D = pd.DataFrame(index=idx)
    D["qqq"], D["r_qqq"], D["r_spy"], D["rf"], D["r_tqqq"] = 100.0, 0.0, 0.0, 0.0, 0.0
    D["p"], D["vxn"] = 0.6, 30.0
    D.iloc[290, D.columns.get_loc("p")] = 0.95                        # signal at bar 30
    D.iloc[290:, D.columns.get_loc("vxn")] = 20.0                      # VXN receding
    r_qld = np.zeros(n); r_qld[291] = 0.10; r_qld[292:] = 0.02         # gap on the fill bar, then +2%/day
    D["r_qld"] = r_qld
    r, a = h.run_qc(D, idx[260], idx[-1])
    buy, exits = r.qld.gt(0).idxmax(), [m for m in a.logs if "lev exit" in m]
    assert buy == idx[291] and len(exits) == 1
    # from the fill price: 1.02^24 = 1.61 -> bar 291 + 24; the planned-dollar basis would have exited at 1.1 * 1.02^19
    assert idx[291 + 24].strftime("%Y-%m-%d") in exits[0]
    assert "+61%" in exits[0]


def test_headline_2020_exit_matches_local(data):
    _, D = data
    _, a = h.run_qc(D, A, B, dict(sleeves="HEADLINE"))
    _, tr = run(D, V2, A, B)
    qc = [m.split()[1] for m in a.logs if "lev exit" in m]
    local = tr[tr.action.str.startswith("sell")].date.dt.strftime("%Y-%m-%d").tolist()
    assert "2020-04-29" in qc and "2020-04-29" in local


# ---------------------------------------------------------------- restarts
def acct(a):
    return dict(qty=a.qty, cash=a.cash, cost=a.cost, pending=a.pending)


@pytest.mark.parametrize("params", [{}, dict(sleeves="HEADLINE")])
def test_restart_with_saved_state_continues_unchanged(data, params):
    _, D = data
    full, _ = h.run_qc(D, "2017-01-03", "2021-06-30", params, live=True, store=h.Store())
    mid = full.loc["2020-03":"2020-06"].qld.gt(0.01).idxmax()
    assert full.qld.loc[mid] > 0.01                                    # restart while holding QLD
    st = h.Store()
    p1, a1 = h.run_qc(D, "2017-01-03", mid, params, live=True, store=st)
    saved = json.loads(st["fear_tranche/state"])
    assert saved["book"]["lev"] > 0 and saved["date"].startswith(str(mid.date()))
    nxt = full.index[full.index.get_loc(mid) + 1]
    p2, a2 = h.run_qc(D, nxt, "2021-06-30", params, live=True, store=st, account=acct(a1))
    assert any("[RESTART]" in m for m in a2.logs)
    both = pd.concat([p1.nav, p2.nav])
    assert np.allclose(both.to_numpy(), full.nav.to_numpy(), rtol=1e-10)


def test_restart_without_state_keeps_holdings(data):
    _, D = data
    D2 = D.copy(); D2.loc["2020-06-01":"2020-06-19", "p"] = 0.95       # strong fear signal for 15 bars
    t = pd.Timestamp("2020-06-01"); f = h.feed_from_panel(D2).loc[t]
    hold = {"QQQ": 40_000 / f.QQQ, "QLD": 20_000 / f.QLD, "BIL": 40_000 / f.BIL}
    cost = {s: q * f[s] for s, q in hold.items()}
    r, a = h.run_qc(D2, t, "2020-06-19", dict(lev_p=1.1), live=True, store=h.Store(),
                    account=dict(qty=hold, cash=0.0, cost=cost, pending={}))
    assert any("[WARN] restart" in m for m in a.logs)
    assert a.n_rebalance == 0                                           # no tranche within the 10-bar gap, QLD kept
    assert a.qty["QLD"] == pytest.approx(hold["QLD"])
    assert r.book_lev.iloc[0] == pytest.approx(0.2, abs=0.01) and r.book_core.iloc[0] == pytest.approx(0.4, abs=0.01)


def test_backtest_never_touches_the_store(data):
    _, D = data
    st = h.Store({"fear_tranche/state": "stale state from another run"})
    a = h.run_qc(D, "2007-02-01", "2007-06-29", store=st)[1]
    assert dict(st) == {"fear_tranche/state": "stale state from another run"} and a.book["core"] > 0.3


def test_put_writing_updates_fear_while_a_put_is_open(data):
    """qc/put_writing.py used to skip the percentile history on days a put was open; now every bar counts."""
    _, D = data
    mod = h.load_qc("put_writing.py")
    feed, start, end = h.feed_from_panel(D), pd.Timestamp("2011-01-03"), pd.Timestamp("2011-06-30")
    a = mod.PutWriting()
    a.params, a.feed, a.start, a.time, a.logs, a.qty, a.cost = {}, feed, start, start, [], {}, {}   # no holdings: a.px unused
    a.cash = 100_000.0
    a.initialize()
    a.next_sale = pd.Timestamp("2100-01-01")                             # as if a put were always open
    n0, seen = len(a.comp_hist), {}
    for t, row in feed.loc[start:end].iterrows():
        a.time = t
        bars = {s: h.NS(close=row[s]) for s in feed.columns if row[s] == row[s]}
        a.on_data(h.Slice(bars))
        seen[t] = a.p_now
    assert len(a.comp_hist) == n0 + len(seen)
    p = pd.Series(seen)
    assert (p - D["p"].reindex(p.index)).abs().max() < 1e-9


def test_top10_keeps_one_share_class_per_company():
    """qc/top10_dollar_volume.py read company_profile.company_id, which LEAN does not have (AttributeError)."""
    mod = h.load_qc("top10_dollar_volume.py")
    mod.Universe = h.NS(UNCHANGED="UNCHANGED")
    a = mod.Top10DollarVolume.__new__(mod.Top10DollarVolume)
    a.time, a._last_month = pd.Timestamp("2020-01-02"), -1
    f = lambda sym, dv, cid: h.NS(symbol=sym, has_fundamental_data=True, price=100.0, dollar_volume=dv,
                                  company_reference=h.NS(company_id=cid), company_profile=h.NS())   # no company_id here
    out = a._select([f("GOOGL", 9e9, "C1"), f("GOOG", 8e9, "C1"), f("AAPL", 7e9, "C2"), f("XYZ", 6e9, "")])
    assert out == ["GOOGL", "AAPL", "XYZ"]
