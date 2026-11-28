"""Allocation study: basket drift/reset timing and costs, v2 regression, reserve accounting, inference helpers."""
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
import allocation_paths  # noqa: E402,F401  (puts the shared research/ on sys.path)
from common import RES, block_boot_sharpes, build_signals, load_panel, maxt_family, perf_stats  # noqa: E402
from strategy import VARIANTS, Cfg, bh, prepare, run  # noqa: E402
import allocation_study as al  # noqa: E402

CAP, C = 100_000.0, 0.0005
G = 1.01                        # QQQ +1%/day; SPY flat; T-bills 0


def toy(n=60, fire=(), ma=1.0, rf=0.0):
    """QQQ +1% a day, SPY flat. p = 0.9 on the closes in `fire`, else 0.5. ma200 low = trend on."""
    idx = pd.bdate_range("2020-01-01", periods=n)
    D = pd.DataFrame(index=idx)
    D["p"] = 0.5
    D.iloc[list(fire), D.columns.get_loc("p")] = 0.9
    D["qqq"] = 100 * G ** np.arange(n)
    D["ma200"] = ma
    D["vxn"], D["vxn_recede"] = 20.0, False
    D["r_qqq"], D["r_spy"], D["r_qld"], D["r_tqqq"], D["rf"], D["r_cash"] = G - 1, 0.0, 2 * (G - 1), 3 * (G - 1), rf, 0.0
    return D


CFG = Cfg("toy", core=(("qqq", .5), ("spy", .5)), tranche=0.075, trend_guard=True, trend_asset="core", basket_reset="event")
go = lambda D, c: run(D, c, D.index[0], D.index[-1], CAP)


@pytest.mark.parametrize("sig,two_sided", [(10, False), (30, True)])
def test_two_asset_drift_then_reset(sig, two_sided):
    """Signal on close `sig` -> executes after day sig+1's returns, resets exactly then, at the hand-computed cost."""
    res, tr = go(toy(fire=[sig]), CFG)
    t = sig + 1
    for i in range(t):                              # drift only: catches accidental daily rebalancing
        q, s = 35_000 * G ** i, 35_000.0
        V = q + s + 30_000
        assert res.nav.iloc[i] == pytest.approx(V, abs=1e-6)
        assert res.qqq_w.iloc[i] == pytest.approx(q / V, abs=1e-12)
        assert res.spy_w.iloc[i] == pytest.approx(s / V, abs=1e-12)
    q, s = 35_000 * G ** t, 35_000.0                # day t returns first, then the trade
    V = q + s + 30_000
    buy = 0.075 * V
    total = q + s + buy * (1 - C)                   # sleeve flow pays 5 bp
    dq, ds = total / 2 - q, total / 2 - s
    extra = abs(dq) + abs(ds) - abs(dq + ds)        # turnover beyond the one-sided buy
    assert (extra > 1) == two_sided                 # QQQ sold only in the second case
    if two_sided:
        assert dq < 0 and extra == pytest.approx(2 * (q - total / 2))
    total -= C * extra
    nav = total + 30_000 - buy
    assert res.nav.iloc[t] == pytest.approx(nav, abs=1e-6)
    assert V - res.nav.iloc[t] == pytest.approx(C * (buy + extra), abs=1e-6)
    assert res.qqq_w.iloc[t] * nav == pytest.approx(total / 2, abs=1e-6)
    assert res.spy_w.iloc[t] * nav == pytest.approx(total / 2, abs=1e-6)
    assert list(tr.date) == [res.index[t]]
    for i in range(t + 1, len(res)):                # drifts again afterwards
        qi = total / 2 * G ** (i - t)
        assert res.qqq_w.iloc[i] * res.nav.iloc[i] == pytest.approx(qi, rel=1e-10)


def test_no_event_never_resets_and_bh_does():
    D = toy()
    res, tr = go(D, CFG)
    assert len(tr) == 0
    share = res.qqq_w / (res.qqq_w + res.spy_w)
    assert (share.diff().dropna() > 0).all()
    daily = bh(D, {"qqq": .5, "spy": .5}, D.index[0], D.index[-1])       # fixed daily weights: different policy
    assert daily.pct_change().dropna().to_numpy() == pytest.approx(0.005)
    full = go(D, replace(CFG, core_target=1.0))[0]["nav"]
    assert full.iloc[-1] > daily.iloc[-1] / daily.iloc[0] * CAP * 1.01


def test_none_mode_never_resets():
    """Legacy policy: the buy lands at target weights, existing holdings keep drifting."""
    res, _ = go(toy(fire=[30]), replace(CFG, basket_reset="none"))
    t = 31
    q, s = 35_000 * G ** t, 35_000.0
    buy = 0.075 * (q + s + 30_000) * (1 - C)
    assert res.qqq_w.iloc[t] * res.nav.iloc[t] == pytest.approx(q + buy / 2, abs=1e-6)
    assert res.spy_w.iloc[t] * res.nav.iloc[t] == pytest.approx(s + buy / 2, abs=1e-6)


def test_trend_flip_parks_and_restores():
    D = toy()
    D.iloc[20:30, D.columns.get_loc("ma200")] = 1e9              # trend off on closes 20..29
    res, tr = go(D, CFG)
    assert list(tr.action) == ["trend off", "trend on"]
    assert [res.index.get_loc(d) for d in tr.date] == [21, 31]        # off: close 20 -> day 21; back: close 30 -> day 31
    q, s = 17_500 * G ** 21, 17_500.0                            # each sleeve before the flip
    parked = (q + s) * (1 - C)
    dq, ds = (q + s) / 2 - 2 * q, (q + s) / 2 - 2 * s            # core half is reset too
    core = (q + s) - C * (abs(dq) + abs(ds) - abs(dq + ds))
    assert res.trend_parked.iloc[21] * res.nav.iloc[21] == pytest.approx(parked, abs=1e-6)
    assert res.qqq_w.iloc[21] * res.nav.iloc[21] == pytest.approx(core / 2, abs=1e-6)
    off = res.iloc[21:31]
    assert np.allclose(off.reserve * off.nav, 30_000)             # parked money is not reserve
    assert np.allclose(off.cash, off.reserve + off.trend_parked)
    on = res.iloc[31]
    assert on.trend_parked == 0 and on.qqq_w == pytest.approx(on.spy_w, abs=1e-12)


def test_parked_cash_is_never_spent():
    D = toy(fire=[25])
    D.iloc[20:30, D.columns.get_loc("ma200")] = 1e9
    res, tr = go(D, replace(CFG, core_target=1.0))                # no reserve at all
    assert "tranche" not in set(tr.action)
    assert res.tranche_want.iloc[26] == 0.075 and res.tranche_got.iloc[26] == 0
    assert res.trend_parked.iloc[26] > 0.4 and (res.reserve == 0).all()


# ------------------------------------------------------------------ real panel
@pytest.fixture(scope="module")
def data():
    P = load_panel(); D = prepare(P, build_signals(P)); D["r_cash"] = 0.0
    return P, D


def test_v2_results_unchanged(data):
    """Default engine reproduces the committed variant table."""
    P, D = data
    ref = pd.read_csv(RES / "strategy_variants.csv")
    for test, a, core in [("A", "2002-03-08", (("qqq", 1.0),)), ("B", "2007-02-01", (("qqq", .5), ("spy", .5)))]:
        sub = ref[ref.test.str.startswith(test)].set_index("strategy")
        for v in VARIANTS:
            res, tr = run(D, replace(v, core=core), a, "2026-09-11")
            for k, x in perf_stats(res["nav"], P["rf"]).items():
                assert x == pytest.approx(sub.loc[v.name, k], abs=1e-9), (test, v.name, k)
            assert len(tr) == sub.loc[v.name, "trades"]
            assert res["expo"].mean() == pytest.approx(sub.loc[v.name, "avg_expo"], abs=1e-9)


def test_qqq_only_modes_identical(data):
    _, D = data
    base = replace(al.V2, core=(("qqq", 1.0),))
    navs = [run(D, replace(base, trend_asset=t, basket_reset=r), al.A, al.B)[0]["nav"]
            for t, r in [("qqq", "none"), ("core", "none"), ("core", "event")]]
    for n in navs[1:]:
        assert np.allclose(n, navs[0], rtol=1e-9)


@pytest.mark.parametrize("cell", [(0.70, 0.5, "scaled"), (0.80, 0.0, "fixed"), (0.75, 0.8, "scaled"), (0.80, 1.0, "scaled")])
def test_book_adds_up(data, cell):
    _, D = data
    res, _ = run(D, al.cell_cfg(*cell), al.A, al.B)
    assert np.allclose(res.qqq_w + res.spy_w + res.lev + res.reserve + res.trend_parked, 1, atol=1e-9)
    assert res.reserve.min() > -1e-12
    assert np.allclose(res.lev_2x, 2 * res.lev)
    assert np.allclose(res.expo, res.qqq_w + res.spy_w + res.lev_2x, atol=1e-9)
    if cell[1] == 0.0:
        assert (res.qqq_w == 0).all() and res.lev_2x.max() > 0    # SPY core still buys 2x Nasdaq


def test_ladder_sizes_and_family():
    s = al.ladder_sizes(0.70, "scaled")
    assert (s["tranche"], s["lev_size"], s["lev_cap"]) == pytest.approx((0.075, 0.10, 0.30))
    assert al.ladder_sizes(0.80, "scaled")["tranche"] == pytest.approx(0.05)
    assert len(al.cells()) == 25 and len(al.EQUITY) * len(al.MIXES) == 15


def test_bad_config_rejected():
    with pytest.raises(ValueError):
        Cfg("x", calm_lev=True, trend_asset="core")
    with pytest.raises(ValueError):
        Cfg("x", trend_guard=True, basket_reset="event")


def test_static_mix(data):
    _, D = data
    full = al.static_mix(D, 0.5, 1.0, al.A, al.B, rebal="D", cost=0.0)
    ref = bh(D, {"qqq": .5, "spy": .5}, al.A, al.B)
    assert np.allclose(full.pct_change().dropna(), ref.pct_change().dropna(), atol=1e-12)
    drift = al.static_mix(D, 0.5, 0.70, al.A, al.B, rebal=None, cost=0.0)
    eng = run(D, Cfg("s", fear_off=True, core=al.core_of(.5)), al.A, al.B)[0]["nav"]
    assert np.allclose(drift, eng, rtol=1e-10)
    m = al.static_mix(D, 0.5, 0.70, al.A, al.B)
    free = al.static_mix(D, 0.5, 0.70, al.A, al.B, cost=0.0)
    assert m.iloc[-1] < free.iloc[-1] and not np.allclose(m, drift, rtol=1e-3)


def test_static_monthly_reset_by_hand():
    D = toy(n=45)
    nav = al.static_mix(D, 0.5, 0.70, D.index[0], D.index[-1], cost=C)
    last = D.index.get_loc(D.index[D.index.month == 1][-1])
    q, s, b = 35_000 * G ** last, 35_000.0, 30_000.0
    assert nav.iloc[last - 1] == pytest.approx(q / G + s + b)
    V = q + s + b
    V -= C * (abs(.35 * V - q) + abs(.35 * V - s))
    assert nav.iloc[last] == pytest.approx(V)
    assert nav.iloc[last + 1] == pytest.approx(V * (1 + .35 * (G - 1)))


def test_equal_drawdown_solver(data):
    _, D = data
    k = al.equal_drawdown_share(D, 0.5, -0.35, al.A, al.B)
    assert al.mdd(al.static_mix(D, 0.5, k, al.A, al.B)) == pytest.approx(-0.35, abs=1e-4)
    assert np.isnan(al.equal_drawdown_share(D, 0.5, -0.90, al.A, al.B))


def test_inference_helpers():
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2010-01-01", periods=2000)
    f = rng.normal(0.0004, 0.01, 2000)
    R = pd.DataFrame({"a": f, "b": f.copy(), "c": f + rng.normal(0, .003, 2000), "d": f + .0015}, idx)
    rf = pd.Series(0.02, idx)
    pt, bt = block_boot_sharpes(R, rf, n=500)
    for j, k in enumerate(R):
        nav = pd.concat([pd.Series([1.0], [idx[0] - pd.Timedelta(days=1)]), (1 + R[k]).cumprod()])
        assert pt[j] == pytest.approx(perf_stats(nav, rf)["Sharpe"], abs=1e-9)
    T, crit = maxt_family(pt[1:] - pt[0], bt[:, 1:] - bt[:, [0]])
    assert T["diff"][0] == 0 and T.lb_simultaneous[0] == 0 and T.p_stepdown[0] == 1      # series vs itself
    assert (T.lb_simultaneous <= T.lb_unadjusted + 1e-12).all()
    assert T.lb_simultaneous[2] > 0 and T.p_stepdown[2] < 0.01                            # a genuine edge is found
    assert T.lb_simultaneous[1] < 0


def test_family_error_rate_under_null():
    """Equal population Sharpe everywhere: some candidate 'passes' in roughly 5% of samples, below the unadjusted rate."""
    n, sims, vol = 1500, 300, np.hypot(0.01, 0.002)
    idx = pd.bdate_range("2010-01-01", periods=n); rf = pd.Series(0.0, idx)
    adj = raw = 0
    for s in range(sims):
        rng = np.random.default_rng(s)
        f = rng.normal(0, 0.01, n)
        R = pd.DataFrame({j: 0.04 * vol + f + rng.normal(0, .002, n) for j in range(11)}, idx)
        pt, bt = block_boot_sharpes(R, rf, block=21, n=300, seed=s)
        T, _ = maxt_family(pt[1:] - pt[0], bt[:, 1:] - bt[:, [0]])
        adj += (T.lb_simultaneous > 0).any(); raw += (T.lb_unadjusted > 0).any()
    print("family error", adj / sims, "unadjusted", raw / sims)
    assert adj / sims < 0.10 and raw > 2 * adj


# ---------------------------------------------------------------- reviewer fixes (benchmark, exit timing)
def test_bh_bought_once_drifts():
    idx = pd.bdate_range("2020-01-01", periods=50)
    D = pd.DataFrame({"r_qqq": 0.01, "r_spy": 0.0, "rf": 0.0}, index=idx)
    nav = bh(D, {"qqq": .5, "spy": .5}, idx[0], idx[-1], capital=100.0, rebalance="never")
    assert nav.iloc[-1] == pytest.approx(50 * 1.01 ** 50 + 50)
    daily = bh(D, {"qqq": .5, "spy": .5}, idx[0], idx[-1], capital=100.0)
    assert daily.iloc[-1] == pytest.approx(100 * 1.005 ** 50)
    with pytest.raises(ValueError):
        bh(D, {"qqq": 1.0}, idx[0], idx[-1], rebalance="monthly")


def test_bought_once_benchmark_numbers(data):
    P, D = data
    st = perf_stats(bh(D, {"qqq": .5, "spy": .5}, al.A, al.B, rebalance="never"), P["rf"])
    assert st["Sharpe"] == pytest.approx(0.660, abs=0.001) and st["CAGR"] == pytest.approx(0.1367, abs=0.0005)


def test_lev_exit_at_signal_close(data):
    P, D = data
    sells = lambda tr: tr[tr.action.str.startswith("sell")].date.dt.strftime("%Y-%m-%d").tolist()
    r0, t0 = run(D, al.V2, al.A, al.B)
    r1, t1 = run(D, replace(al.V2, lev_exit_close="signal"), al.A, al.B)
    assert "2020-04-29" in sells(t0) and "2020-04-30" in sells(t1) and "2020-04-29" not in sells(t1)
    assert perf_stats(r1.nav, P["rf"])["Sharpe"] == pytest.approx(0.70740, abs=2e-5)
    with pytest.raises(ValueError):
        Cfg("x", lev_exit_close="later")


def test_scaled_ladder_matches_qc_formula():
    # tests/test_qc_params.py pins qc/main.py's SCALED ladder to the same formula
    for e in al.EQUITY:
        r = 1 - e
        assert al.ladder_sizes(e, "scaled") == pytest.approx(dict(tranche=r / 4, lev_size=r / 3, lev_cap=r))
