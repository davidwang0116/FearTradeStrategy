"""Regression checks for end-of-day entry research."""

from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "vix_entry" / "research"))
from analyze_vix import COMPOSITE, NO_TRANCHES, episode_concentration, episode_outcomes, episode_starts, first_breakout, outcome_summary, outcomes, portfolio_runs
from indicators import constituent_breadth, entry_mask
from trades import episode_table, frequency, spaced_entries, trade_path


def test_outcome_uses_next_close_and_purges_boundary_dates():
    dates = pd.bdate_range("2019-01-01", periods=150)
    close = pd.Series(np.arange(100.0, 250.0), index=dates)
    panel = close.to_frame(name="qqq")
    features = pd.DataFrame({"close": 24.0, "rank_504": 0.8}, index=dates)
    frame = outcomes(panel, dates[0], dates[70], features)
    assert frame.at[dates[0], "entry_date"] == dates[1]
    assert frame.at[dates[0], "exit_date"] == dates[64]
    assert frame.at[dates[0], "qqq_return"] == pytest.approx(close.iloc[64] / close.iloc[1] - 1)
    assert frame.at[dates[5], "period"] == "training"
    assert frame.at[dates[6], "period"] == "boundary"
    assert frame.at[dates[70], "period"] == "later"


def test_gate_distinguishes_missing_input_and_a_failing_confirmation():
    features = pd.DataFrame({"close": [23., 25., 26., 27.], "rank_252": [0.9, 0.82, 0.8, 0.8],
                             "ease_5": [-1., -1., -1., -1.], "breakout_5": [True, False, True, pd.NA]})
    features["breakout_5"] = features["breakout_5"].astype("boolean")
    result = entry_mask(features, floor=24, rank=80, window=252, easing=5, confirmation="breakout_5")
    assert result.iloc[:3].tolist() == [False, False, True]
    assert pd.isna(result.iloc[3])


def test_breakout_skips_the_fear_day_and_times_out_after_ten_sessions():
    dates = pd.bdate_range("2020-01-01", periods=41)
    features = pd.DataFrame({"breakout_5": False}, index=dates)
    features.loc[dates[[1, 3, 29]], "breakout_5"] = True
    fear = pd.Series(False, index=dates, dtype="boolean")
    fear.iloc[[1, 2, 24]] = True
    assert episode_starts(fear, 21).tolist() == [1, 24]
    assert first_breakout(features, 1, 5) == dates[3]
    assert first_breakout(features, 18, 5) is None
    assert first_breakout(features, 19, 5) == dates[29]


def test_episode_spacing_uses_trading_session_gaps_between_starts():
    hits = pd.DataFrame({"session": [0, 4, 25, 47, 48, 80]})
    count, median_gap, starts = episode_outcomes(hits)
    assert starts["session"].tolist() == [0, 47, 80]
    assert (count, median_gap) == (3, 40.0)
    assert episode_outcomes(hits.iloc[:1])[:2] == (1, None)
    assert episode_outcomes(hits.iloc[:0])[:2] == (0, None)
    assert episode_outcomes(hits, independent_entries=True)[:2] == (6, 21.0)


def test_episode_concentration_counts_each_episode_once_and_drops_the_longest():
    eligible = pd.DataFrame({"qqq_return": [0.0, 0.02]})
    hits = pd.DataFrame({"session": [0, 1, 2, 40, 80], "qqq_return": [0.3, 0.3, 0.3, 0.0, -0.06]})
    result = episode_concentration(hits, eligible)
    assert result["weighted"] == pytest.approx((0.3 + 0.0 - 0.06) / 3 - 0.01)
    assert result["largest_days"] == 3
    assert result["without_largest"] == pytest.approx(-0.03 - 0.01)
    assert episode_concentration(hits.iloc[:3], eligible)["without_largest"] is None
    assert episode_concentration(hits.iloc[3:], eligible)["without_largest"] is None
    assert episode_concentration(hits.iloc[:0], eligible)["weighted"] is None
    independent = episode_concentration(hits, eligible, independent_entries=True)
    assert independent["weighted"] == pytest.approx(hits["qqq_return"].mean() - 0.01)


def test_carried_run_keeps_training_holdings_and_reports_only_the_later_period():
    panel = pd.read_csv(ROOT / "data/panel.csv", index_col=0, parse_dates=True)
    start, split = pd.Timestamp("2019-01-02"), pd.Timestamp("2020-01-01")
    gate = panel["vix"].ge(24).astype("boolean")
    late = gate.where(panel.index >= pd.Timestamp("2020-06-01"))
    rows, _ = portfolio_runs(panel, [("full", "A", "B", gate, gate), ("late", "A", "B", late, late)], start, split)
    rows = pd.DataFrame(rows).set_index(["experiment", "period", "rule"])
    assert {period for experiment, period, _ in rows.index if experiment == "late"} == {"later"}
    carried, fresh = rows.loc[("full", "carried", "A")], rows.loc[("full", "later", "A")]
    assert (carried["started"], carried["first"]) == ("2019-01-02", "2020-01-02")
    assert (fresh["started"], fresh["first"]) == ("2020-01-02", "2020-01-02")
    assert carried["last"] == fresh["last"]
    assert carried["sharpe"] != fresh["sharpe"]
    assert rows.loc[("full", "carried", NO_TRANCHES), "tranches"] == 0
    assert ("full", "carried", COMPOSITE) in rows.index


def test_frequency_measures_gaps_episodes_and_quiet_stretches():
    dates = pd.bdate_range("2020-01-01", periods=252)
    eligible = pd.DataFrame({"session": range(100, 352)}, index=dates)
    signals = eligible.iloc[[10, 12, 40, 130]]
    stats = frequency(signals, eligible)
    assert (stats["signal_days"], stats["episodes"], stats["signal_days_per_year"]) == (4, 3, 4)
    assert (stats["median_gap"], stats["shortest_gap"], stats["longest_gap"]) == (60, 30, 90)
    assert (stats["gaps_of_63_or_more"], stats["gaps_of_90_or_more"]) == (0.5, 0.5)
    assert stats["longest_stretch_without_signal"] == 121
    assert spaced_entries([0, 62, 63, 125, 126]) == 3
    assert episode_table([5, 26, 48])["days"].tolist() == [2, 1]
    assert frequency(signals.iloc[:0], eligible)["longest_stretch_without_signal"] == 252


def test_trade_path_reports_worst_close_and_recovery():
    path = trade_path(np.r_[100., 100., 95., 85., 130., 131.], 1, 4)
    assert (path["sessions_to_low"], path["sessions_to_recover"]) == (2, 3)
    assert path["worst"] == pytest.approx(-.15) and path["trade_return"] == pytest.approx(.3)


def test_outcome_rows_join_the_controls_from_the_same_experiment_and_period():
    dates = pd.bdate_range("2019-06-03", periods=300)
    frame = pd.DataFrame({"close": 25.0, "qqq_return": 0.1, "max_drawdown": -0.1, "original_quintile": 5,
                          "session": range(300), "period": ["training"] * 150 + ["later"] * 150}, index=dates)
    gate = pd.Series(True, index=dates, dtype="boolean")
    portfolio = [dict(experiment=e, period=p, rule=r, sharpe=len(e) + 10 * len(p) + 100 * len(r), drawdown=-.1, cagr=.1,
                      tranches=1, first="a", last="b")
                 for e in ("x", "yy") for p in ("training", "later", "carried") for r in ("A", "B", COMPOSITE, NO_TRANCHES)]
    cases = [("x", "A", "B", gate, gate), ("yy", "A", "B", gate, gate)]
    table = pd.DataFrame(outcome_summary(frame, cases, portfolio)).set_index(["experiment", "side"])
    assert table.at[("yy", "A"), "carried_no_tranche_sharpe"] == 2 + 70 + 100 * len(NO_TRANCHES)
    assert table.at[("x", "B"), "training_composite_sharpe"] == 1 + 80 + 100 * len(COMPOSITE)
    assert table.at[("x", "A"), "later_portfolio_sharpe"] == 1 + 50 + 100


def test_breadth_uses_members_on_the_signal_date_and_prior_prices(tmp_path):
    dates = pd.bdate_range("2022-01-03", periods=25)
    rows = [(date, asset, close, member) for i, date in enumerate(dates)
            for asset, close, member in (("A", 100 + i, int(i < 22)),
                                         ("B", 100 - i, 1),
                                         ("C", 100 - i, int(i >= 22)))]
    path = tmp_path / "breadth.csv"
    pd.DataFrame(rows, columns=["date", "security", "close", "member"]).to_csv(path, index=False)
    breadth, coverage = constituent_breadth(path, dates)
    assert np.isnan(breadth.iloc[18])
    assert breadth.iloc[19:].tolist() == [0.5] * 3 + [0.0] * 3
    assert (coverage.iloc[19:] == 1).all()
