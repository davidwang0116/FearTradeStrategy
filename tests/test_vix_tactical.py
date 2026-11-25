"""Checks for staged entries: triggers, fills, cancellation, cash and the selection rule."""

from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "research" / "vix_entry"))
import tactical as t
from indicators import term_spread
from run_tactical import compare, evaluate_hold_lengths, split_episodes


def market(n=80, **changes):
    flat = dict(close=np.full(n, 100.), vix=np.full(n, 30.), rf=np.zeros(n), fear=np.ones(n, bool), calm=np.zeros(n, bool),
                reference=np.zeros(n, bool), confirm={"VIX easing 5d": np.zeros(n, bool)}, known={})
    flat.update(changes)
    return t.Market(**flat)


def flags(n, *hits):
    values = np.zeros(n, bool)
    values[list(hits)] = True
    return values


def test_new_episode_needs_a_calm_close_after_fear():
    fear, calm = flags(12, 1, 2, 4, 8, 10), flags(12, 3, 9)
    assert t.episode_triggers(fear, calm) == [1, 4, 10]
    assert t.episode_triggers(flags(6, 0, 1, 2), flags(6)) == [0]


def test_confirmation_uses_the_next_close_and_is_cancelled_by_calm_or_expiry():
    half = t.half_then("VIX easing 5d")
    assert half(market(confirm={"VIX easing 5d": flags(80, 5, 7)}), 2, 60) == [(3, .5), (6, .5)]
    assert half(market(confirm={"VIX easing 5d": flags(80, 2)}), 2, 60) == [(3, .5)]          # the trigger close itself does not count
    assert half(market(confirm={"VIX easing 5d": flags(80, 12)}), 2, 60) == [(3, .5), (13, .5)]
    assert half(market(confirm={"VIX easing 5d": flags(80, 13)}), 2, 60) == [(3, .5)]         # eleven sessions later
    assert half(market(confirm={"VIX easing 5d": flags(80, 6)}, calm=flags(80, 6)), 2, 60) == [(3, .5)]
    assert t.wait_for("VIX easing 5d")(market(), 2, 60) == []


def test_fixed_delay_control_matches_its_delay_and_cancels_on_normalization():
    assert t.half_then_delay(market(), 2, 60) == [(3, .5), (8, .5)]
    assert t.half_then_delay(market(calm=flags(80, 7)), 2, 60) == [(3, .5)]
    assert t.half_then_delay(market(calm=flags(80, 8)), 2, 60) == [(3, .5), (8, .5)]


def test_uncancelled_delay_ignores_normalization():
    for calm in (flags(80), flags(80, 4), flags(80, 8)):
        assert t.half_then_delay_always(market(calm=calm), 2, 60) == [(3, .5), (8, .5)]


def test_cancelled_plans_drop_orders_from_the_first_calm_close_on():
    fear = np.ones(80, bool)
    fear[15:18] = False
    plan = t.until_calm(t.persistent)
    assert [s for s, _ in plan(market(fear=fear), 0, 60)] == [1, 11, 21, 31]
    # Fear returns after the calm close at 16, but the old plan is over.
    assert [s for s, _ in t.persistent(market(fear=fear, calm=flags(80, 16)), 0, 60)] == [1, 11, 21, 31]
    assert [s for s, _ in plan(market(fear=fear, calm=flags(80, 16)), 0, 60)] == [1, 11]
    # A calm close cancels an order signalled on that close, and cannot cancel one filled on it.
    assert [s for s, _ in plan(market(calm=flags(80, 20)), 0, 60)] == [1, 11]
    assert [s for s, _ in plan(market(calm=flags(80, 21)), 0, 60)] == [1, 11, 21]
    falling = 100 * .9 ** np.arange(80)
    assert len(t.until_calm(t.ladder(False))(market(close=falling, calm=flags(80, 25)), 0, 79)) == 3


def test_ladder_needs_time_fear_and_a_lower_price():
    close = np.full(80, 100.)
    close[5:] = 91.
    assert t.ladder(False)(market(close=close), 0, 60) == [(1, .25), (11, .25)]
    fear = np.ones(80, bool)
    fear[10:14] = False
    assert t.ladder(False)(market(close=close, fear=fear), 0, 60) == [(1, .25), (15, .25)]
    assert t.ladder(False)(market(close=np.full(80, 93.)), 0, 60) == [(1, .25)]
    # A 45 VIX widens the rung from 8% to 15%.
    assert t.ladder(True)(market(close=close, vix=np.full(80, 45.)), 0, 60) == [(1, .25)]
    falling = 100 * .9 ** np.arange(80)
    assert len(t.ladder(False)(market(close=falling), 0, 79)) == 4


def test_persistent_and_late_tranches():
    fear = np.ones(80, bool)
    fear[20] = False
    assert [s for s, _ in t.persistent(market(fear=fear), 0, 60)] == [1, 11, 31]
    assert t.late_reference(market(reference=flags(80, 30)), 0, 64) == [(1, .25), (31, .25)]
    assert t.late_reference(market(reference=flags(80, 30), calm=flags(80, 29)), 0, 64) == [(1, .25)]


def test_settlement_charges_costs_and_credits_idle_cash():
    m = market(close=np.r_[np.full(2, 100.), np.full(78, 110.)], rf=np.full(80, .0252))
    result = t.settle([(1, .5)], m, 0, 11)
    expected_cash = .5 * (1 + .0001) ** 10
    assert result["pnl"] == pytest.approx(expected_cash + .5 * .9995 * 1.1 * .9995 - 1)
    assert result["deployed"] == .5
    assert t.settle([], m, 0, 11)["pnl"] == pytest.approx((1 + .0001) ** 10 - 1)
    assert t.settle([(1, .5), (11, .5)], m, 0, 11)["deployed"] == .5                         # nothing can fill on the deadline
    assert t.settle([(1, 1.)], m, 0, 11)["pnl"] == pytest.approx(.9995 ** 2 * 1.1 - 1)


def test_timing_value_compares_with_an_average_purchase():
    close = 100 * 1.01 ** np.arange(80)
    average = t.average_hold(close, np.arange(80))
    assert average(10) == pytest.approx(1.01 ** 10 - 1)
    assert t.timing_value([(1, .5)], market(close=close), 11, average) == pytest.approx(0)


def test_selling_at_63_earns_bills_while_the_longer_hold_stays_invested():
    n = 2200            # reaches past the 2020 split
    dates = pd.bdate_range("2012-01-02", periods=n)
    close = np.r_[np.full(80, 100.), np.full(n - 80, 120.)]          # the rise comes after the 63-session sale
    m = market(n, close=close, fear=flags(n, 5), rf=np.full(n, .0252))
    rows = pd.DataFrame(evaluate_hold_lengths(m, dates, "VIX >= 24"))
    pnl = rows.set_index("rule")["pnl"]
    assert pnl["Hold 126 sessions"] == pytest.approx(1.2 * .9995 ** 2 - 1)
    assert pnl["Sell after 63 sessions, then T-bills"] == pytest.approx(.9995 ** 2 * 1.0001 ** 63 - 1)
    [pair] = compare(rows, "Sell after 63 sessions, then T-bills", "pnl")
    assert pair["difference"] == pytest.approx(pnl.iloc[1] - pnl.iloc[0])


def test_missing_vix3m_file_leaves_the_spread_unknown(tmp_path):
    vix = pd.Series([20., 21.], index=pd.bdate_range("2012-01-02", periods=2))
    assert term_spread(vix, tmp_path).isna().all()
    (tmp_path / "vix3m.csv").write_text("DATE,OPEN,HIGH,LOW,CLOSE\n01/03/2012,0,0,0,19.5\n")
    assert term_spread(vix, tmp_path).iloc[1] == 1.5 and np.isnan(term_spread(vix, tmp_path).iloc[0])


def test_selection_rule_and_paired_summary():
    row = t.paired([1., 2., 3., -1., 2.], [0.] * 5)
    assert row["n"] == 5 and row["win_share"] == .8 and row["without_best"] == pytest.approx(1.)
    assert t.passes(row)
    assert not t.passes(t.paired([10., -1., -1., .5, .5], [0.] * 5))
    assert not t.passes(t.paired([3., -1., -1., 1., 1., -1.], [0.] * 6))
    assert t.paired([], [])["n"] == 0


def test_training_episodes_must_exit_before_the_split():
    dates = pd.bdate_range("2019-06-03", periods=400)
    fear, calm = flags(400, 5, 120, 200), flags(400, 60, 170)
    periods = split_episodes(market(400, close=np.full(400, 100.), fear=fear, calm=calm), dates, 63)
    assert [dates[s] < pd.Timestamp("2020-01-01") for s in periods["training"]] == [True]
    assert periods["training"] == [5] and periods["later"] == [200]
    assert all(dates[s] >= pd.Timestamp("2020-01-01") for s in periods["later"])


def exit_market(close, calm=(), breakout=(), vix=None, n=80):
    values = np.full(n, 100.)
    values[:len(close)] = close
    values[len(close):] = close[-1]
    return market(n, close=values, calm=flags(n, *calm), vix=np.full(n, 30.) if vix is None else vix,
                  confirm={"VIX easing 5d": np.zeros(n, bool), "QQQ 5-close breakout": flags(n, *breakout)})


def test_normalization_sells_at_the_next_close():
    m = exit_market([100.] * 60, calm=[20])
    assert t.on_normalization(m, 5, 60) == [(21, 1.0)]
    assert t.on_normalization(exit_market([100.] * 60, calm=[5]), 5, 60) == []       # before the purchase
    assert t.on_normalization(exit_market([100.] * 60, calm=[60]), 5, 60) == []      # on the deadline


def test_breakdown_needs_a_recovery_before_it_is_armed():
    close = [100.] * 12 + [95.] + [96.] * 10 + [97.] * 8 + [94.] + [94.] * 30
    early = exit_market(close, breakout=[25])
    assert t.on_breakdown(False)(early, 5, 60) == [(13, 1.0)]
    assert t.on_breakdown(True)(early, 5, 60) == [(32, 1.0)]
    assert t.on_breakdown(True)(exit_market(close), 5, 60) == []
    # The arming close cannot also be the breakdown.
    assert t.breakdown(exit_market([100.] * 12 + [90.] + [90.] * 40, breakout=[12]), 6, 60, True) is None


def test_x4_and_x5_agree_when_fear_normalizes_first_and_differ_when_price_breaks_first():
    close = [100.] * 12 + [101.] + [100.] * 12 + [90.] + [90.] * 40
    broken_first = exit_market(close, calm=[40], breakout=[12])
    assert t.independent_halves(broken_first, 5, 60) == [(41, .5), (26, .5)]
    assert t.half_then_all_on_breakdown(broken_first, 5, 60) == [(26, 1.0)]
    calm_first = exit_market(close, calm=[20], breakout=[12])
    assert sorted(t.independent_halves(calm_first, 5, 60)) == sorted(t.half_then_all_on_breakdown(calm_first, 5, 60))
    same_day = exit_market(close, calm=[25], breakout=[12])
    assert t.half_then_all_on_breakdown(same_day, 5, 60) == [(26, 1.0)]


def test_vix_peak_exit_uses_the_running_peak():
    vix = np.full(80, 30.)
    vix[10:15] = 50.
    vix[15:30] = 31.
    vix[30:] = 29.9
    m = exit_market([100.] * 60, vix=vix)
    assert t.on_vix_off_peak(m, 5, 60) == [(31, 1.0)]
    assert t.staged_time(m, 5, 69) == [(27, 1 / 3), (48, 1 / 3)]


def test_exit_settlement_matches_by_hand():
    m = exit_market([100.] * 12 + [110.] * 60)
    m.rf[:] = .0252
    flat = t.settle_exit([], m, 5, 69)
    assert flat["pnl"] == pytest.approx(.9995 ** 2 * 1.1 - 1)
    assert flat["exposure"] == 1
    half = t.settle_exit([(20, .5)], m, 5, 69)
    expected = .5 * .9995 * 1.1 * .9995 * (1.0001) ** 49 + .5 * .9995 ** 2 * 1.1
    assert half["pnl"] == pytest.approx(expected - 1)
    assert half["sold_early"] == .5
    assert t.settle_exit([(69, 1.0)], m, 5, 69)["pnl"] == pytest.approx(flat["pnl"])


from tactical_portfolio import block_bootstrap_sharpe, matched_static, run_sleeve


def sleeve_inputs(n=120, qqq=0., spy=0., fear=(20,)):
    dates = pd.bdate_range("2020-01-01", periods=n)
    m = market(n, fear=flags(n, *fear), rf=np.zeros(n), close=100 * (1 + qqq) ** np.arange(n))
    return m, {"qqq": np.full(n, qqq), "spy": np.full(n, spy)}, dates


def test_static_account_matches_buy_and_hold():
    m, returns, dates = sleeve_inputs(qqq=.001, spy=.002, fear=())
    frame, stats = run_sleeve(m, returns, dates, dates[0], dates[-1], 0, t.hold_to_deadline, 63)
    assert frame["nav"].iloc[-1] == pytest.approx(.35 * 1.001 ** 119 + .35 * 1.002 ** 119 + .3)
    assert stats["lots"] == 0


def test_lot_buys_at_the_next_close_and_returns_cash_at_its_deadline():
    m, returns, dates = sleeve_inputs()
    frame, stats = run_sleeve(m, returns, dates, dates[0], dates[-1], .075, t.hold_to_deadline, 63)
    assert frame["tactical"].iloc[20] == 0
    assert frame["tactical"].iloc[21] == pytest.approx(.075 * (1 - t.COST), rel=1e-3)
    assert frame["tactical"].iloc[21 + 63] == 0 and frame["tactical"].iloc[21 + 62] > 0
    assert frame["nav"].iloc[-1] == pytest.approx(1 - .075 * (1 - (1 - t.COST) ** 2), abs=1e-4)
    early, _ = run_sleeve(m, returns, dates, dates[0], dates[-1], .075, lambda a, s, d: [(s + 11, .5)], 63)
    assert early["tactical"].iloc[31] == pytest.approx(frame["tactical"].iloc[30] / 2, rel=1e-3)


def test_sleeve_never_spends_more_cash_than_it_has():
    n = 120
    m, returns, dates = sleeve_inputs(n, fear=(10, 30))
    m.calm[20] = True
    frame, stats = run_sleeve(m, returns, dates, dates[0], dates[-1], .30, t.hold_to_deadline, 63)
    assert stats == dict(lots=2, short_of_cash=1)
    assert frame["cash"].min() >= -1e-12
    assert frame["nav"].iloc[0] == pytest.approx(1)


def test_matched_static_and_bootstrap_are_neutral_when_nothing_differs():
    m, returns, dates = sleeve_inputs(qqq=.001, spy=.001, fear=())
    static, _ = run_sleeve(m, returns, dates, dates[0], dates[-1], 0, t.hold_to_deadline, 63)
    assert matched_static(m, returns, dates, dates[0], dates[-1], 0.).iloc[-1] == pytest.approx(static["nav"].iloc[-1])
    noisy = static["nav"] * (1 + .001 * np.sin(np.arange(len(static))))
    diff, low, high = block_bootstrap_sharpe(noisy, noisy, pd.Series(0., index=dates), draws=50)
    assert diff == 0 and low == 0 and high == 0


def test_bootstrap_uses_the_reported_sharpe():
    from common import perf_stats
    dates, rng = pd.bdate_range("2012-01-02", periods=600), np.random.default_rng(1)
    rf = pd.Series(np.r_[np.full(300, .001), np.full(300, .05)], index=dates)
    a, b = (pd.Series((1 + rng.normal(.0005, scale, 600)).cumprod(), index=dates) for scale in (.01, .015))
    diff, low, high = block_bootstrap_sharpe(a, b, rf, draws=50)
    assert diff == pytest.approx(perf_stats(a, rf)["Sharpe"] - perf_stats(b, rf)["Sharpe"], abs=1e-12)
    assert low <= high
