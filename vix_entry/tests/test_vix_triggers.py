"""Checks for using each VIX signal as an entry point."""

from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "vix_entry" / "research"))
import run_triggers as r
import tactical as t
from test_vix_tactical import flags, market


def test_signal_grid_covers_every_combination_and_never_easing_alone():
    rules = r.signal_rules()
    assert "VIX >= 24" in rules and "252d rank >= 80%" in rules
    assert "VIX >= 24 + 1260d rank >= 80% + easing 10d" in rules
    assert "easing 10d" not in rules
    assert len([n for n in rules if "rank >= 80%" in n and "easing" in n and not n.startswith("VIX")]) == 9
    assert all(options.get("floor") or options.get("rank") or options.get("confirmation") for options in rules.values())


def test_summary_labels_each_signal_with_how_its_episodes_reset():
    dates = pd.bdate_range("2008-01-03", "2021-12-31")
    episodes = pd.DataFrame({"rule": ["floor"] * 3 + ["rank"] * 3, "period": "training", "excess": [.01, .02, -.01] * 2,
                             "pnl": .03, "worst_mark": -.05})
    rules = {"floor": dict(floor=24), "rank": dict(rank=80, window=252)}
    own = r.summarize_standalone(episodes, dates, rules).set_index("rule")["reset"]
    assert own.to_dict() == {"floor": "VIX at or below its median", "rank": "252d rank at or below 50%"}
    quiet = r.summarize_standalone(episodes, dates, rules, r.QUIET_RESET)["reset"]
    assert quiet.eq("21 sessions without a signal").all()


def test_rank_rules_rearm_on_their_own_rank_and_floor_rules_on_the_vix_median():
    dates = pd.bdate_range("2020-01-01", periods=8)
    features = pd.DataFrame({"close": [10., 30., 30., 10., 10., 30., 30., 10.], "high": 30.,
                             "rank_252": [.4, .9, .9, .9, .4, .9, .9, .4]}, index=dates)
    vix_rank = pd.Series([.1, .9, .9, .1, .1, .9, .9, .1], index=dates)
    base = market(8, close=np.full(8, 100.))
    markets = r.signal_markets(base, features, vix_rank, {"rank": dict(rank=80, window=252), "floor": dict(floor=24)})
    assert t.episode_triggers(markets["rank"].fear, markets["rank"].calm) == [1, 5]
    assert t.episode_triggers(markets["floor"].fear, markets["floor"].calm) == [1, 5]
    assert markets["rank"].known["signal"].all() and "signal" not in base.known
    # A close that is both calm and a signal must not re-arm the same episode.
    both = r.signal_markets(base, features.assign(rank_252=.9), vix_rank, {"rank": dict(rank=80, window=252)})["rank"]
    assert t.episode_triggers(both.fear, both.calm) == [0]


def test_reset_labels_follow_the_rearming_rule():
    rules = r.signal_rules()
    assert r.reset_label(rules["VIX >= 20 + 504d rank >= 80%"]) == "VIX at or below its median"
    assert r.reset_label(rules["252d rank >= 80% + easing 5d"]) == "252d rank at or below 50%"
    assert r.reset_label(rules["VIX traded at 24 and closed below"]) == "VIX at or below its median"


def test_average_date_uses_only_dates_with_the_signals_data():
    n = 300
    close = np.r_[np.full(150, 100.), 100 * 1.001 ** np.arange(150)]
    inside = np.arange(50, n)
    everywhere = market(n, close=close, known={"signal": np.ones(n, bool)})
    recent = market(n, close=close, known={"signal": np.arange(n) >= 150})
    net = lambda entries: (close[entries + 63] / close[entries]).mean() * (1 - t.COST) ** 2 - 1
    assert r.average_date_return(everywhere, inside) == pytest.approx(net(np.arange(50, n - 63)))
    assert r.average_date_return(recent, inside) == pytest.approx(net(np.arange(151, n - 63)))
    assert r.average_date_return(recent, inside) > r.average_date_return(everywhere, inside)
    # Missing observations at the end of the sample do not shorten the last outcome.
    tail = market(n, close=close, known={"signal": np.arange(n) < n - 30})
    assert r.average_date_return(tail, inside) == pytest.approx(r.average_date_return(everywhere, inside))


def test_family_shuffle_never_uses_dates_before_a_signal_has_data():
    n = 700
    dates = pd.bdate_range("2012-01-02", periods=n)
    close = 100 * np.cumprod(1 + np.random.default_rng(3).normal(.0005, .01, n))
    starts = [320 + 30 * k for k in range(10)]
    fear, calm = flags(n, *starts), flags(n, *[s + 10 for s in starts])
    covered = np.arange(n) >= 300
    late = market(n, close=close, fear=fear, calm=calm, known={"signal": covered})
    wild = close.copy()
    wild[:300] = 1e6                                   # prices the signal could never have traded on
    wild_late = market(n, close=wild, fear=fear, calm=calm, known={"signal": covered})
    rules = {"rule": dict(floor=24)}
    a, single_a = r.family_test({"rule": late}, dates, close, rules)
    b, single_b = r.family_test({"rule": wild_late}, dates, wild, rules)
    assert a == b and single_a == single_b
    full, _ = r.family_test({"rule": market(n, close=close, fear=fear, calm=calm, known={"signal": np.ones(n, bool)})}, dates, close, rules)
    assert full["best_statistic"] != a["best_statistic"]


def test_held_value_earns_tbills_before_and_after_the_holding_period():
    m = market(200, rf=np.full(200, .0252), close=np.r_[np.full(50, 100.), np.full(150, 110.)])
    end = 1 + 127
    idle = (1 + .0001) ** 126
    assert r.hold_value([], m, 0, 1 + 127) == pytest.approx((1 + .0001) ** 127 - 1)
    # Bought at session 1, held through 64, then T-bills to the end.
    expected = (110 / 100) * (1 - t.COST) ** 2 * (1 + .0001) ** 64
    assert r.hold_value([(1, 1.)], m, 0, end) == pytest.approx(expected - 1)
    waited = r.hold_value([(11, 1.)], m, 0, end)
    assert waited == pytest.approx((110 / 100) * (1 - t.COST) ** 2 * (1 + .0001) ** 64 - 1)


def test_starts_are_split_and_training_exits_precede_the_split():
    dates = pd.bdate_range("2018-01-01", periods=900)
    m = market(900, fear=flags(900, 5, 100, 500, 560), calm=flags(900, 50, 300, 530))
    periods = r.starts_by_period(m, dates)
    assert all(dates[s + 1 + 63] < pd.Timestamp("2020-01-01") for s in periods["training"])
    assert all(dates[s] >= pd.Timestamp("2020-01-01") for s in periods["later"])


def test_paired_wait_stops_at_the_horizon_and_when_fear_calms():
    n = 400
    dates = pd.bdate_range("2012-01-02", periods=n)
    base = market(n, fear=flags(n, 10), calm=np.zeros(n, bool))
    signal = market(n, fear=flags(n, 40), calm=np.zeros(n, bool), known={"signal": np.ones(n, bool)})
    rules = {"VIX >= 24 + easing 20d": dict(floor=24, easing=20)}
    table = r.paired_with_baseline(base, {"VIX >= 24 + easing 20d": signal}, dates, rules)
    assert table["wait"].tolist() == [30]
    late = market(n, fear=flags(n, 90), known={"signal": np.ones(n, bool)})
    assert r.paired_with_baseline(base, {"VIX >= 24 + easing 20d": late}, dates, rules)["wait"].isna().all()
    calmed = market(n, fear=flags(n, 10), calm=flags(n, 30))
    assert r.paired_with_baseline(calmed, {"VIX >= 24 + easing 20d": signal}, dates, rules)["wait"].isna().all()
    assert "VIX >= 24" not in set(table["rule"])
