#!/usr/bin/env python3
"""Test VIX entry rules and generate an offline comparison dashboard."""

import argparse
from itertools import product
import json
from pathlib import Path

import numpy as np
import pandas as pd

from indicators import EASING_DAYS, FILTERS, FLOORS, RANK_CUTOFFS, RANK_WINDOWS, build_features, entry_mask
from trades import episode_entries, signal_frequency
# Puts the repo's research/ on the path. The portfolio engine is imported only when a funded run needs it.
from vix_paths import INPUTS, PANEL, RESULTS, VIX3M, VIX_OHLC

HOLD = 63
PERIODS = ("training", "later", "all")
BASELINE = {"floor": 24, "easing": 20}
COMPOSITE, NO_TRANCHES = "Existing composite", "Core tranches disabled"

EXPERIMENTS = [
    ("VIX close vs intraday high", {"floor": 24}, {"floor": 24, "level": "high"}),
    ("Intraday spike that fades", {"floor": 24}, {"confirmation": "intraday_fade"}),
    ("Shorter trailing rank", {"rank": 80}, {"rank": 80, "window": 252}),
    ("Longer trailing rank", {"rank": 80}, {"rank": 80, "window": 1260}),
    ("Add a VIX floor to the rank", {"rank": 80}, {"rank": 80, "floor": 24}),
    ("VIX easing", {"floor": 24}, BASELINE),
    ("Easing lookback", {"floor": 24, "easing": 10}, BASELINE),
    ("Add a rank filter to VIX easing", BASELINE, {**BASELINE, "rank": 50}),
    ("QQQ recovery", BASELINE, {**BASELINE, "confirmation": "breakout_5"}),
    ("VIX term structure", {"floor": 24, "confirmation": "term_flat"},
     {"floor": 24, "confirmation": "term_inverted"}),
    ("Equal-weight breadth proxy", BASELINE, {**BASELINE, "confirmation": "breadth_proxy_up"}),
    ("Constituent breadth", BASELINE, {**BASELINE, "confirmation": "breadth_up"}),
    ("High-yield credit", {"floor": 24, "confirmation": "credit_widening"},
     {"floor": 24, "confirmation": "credit_stable"}),
]

SOURCES = {
    "QQQ and VIX": "https://github.com/davidwang0116/FearTradeStrategy/blob/main/data/panel.csv",
    "VIX OHLC and VIX3M": "https://www.cboe.com/tradable-products/vix/vix-historical-data",
    "QQQE adjusted close": "https://finance.yahoo.com/quote/QQQE/history/",
    "High-yield OAS": "https://fred.stlouisfed.org/series/BAMLH0A0HYM2",
}


def describe_rule(rule):
    level = "VIX high" if rule.get("level") == "high" else "VIX close"
    parts = [f'{level} ≥ {rule["floor"]}'] if rule.get("floor") else []
    if rule.get("rank"):
        parts.append(f'{rule.get("window", 504)}d rank ≥ {rule["rank"]}%')
    if rule.get("easing"):
        parts.append(f'VIX easing {rule["easing"]}d')
    if rule.get("confirmation"):
        parts.append(FILTERS[rule["confirmation"]])
    return " + ".join(parts) or "Any eligible close"


def outcomes(panel, start, split, features):
    """Keep the ZIP's next-close/63-session return and split conventions."""
    dates = panel.index.to_series()
    close = panel["qqq"]
    frame = features.copy()
    frame["entry_date"] = dates.shift(-1)
    frame["exit_date"] = dates.shift(-HOLD - 1)
    frame["qqq_return"] = close.shift(-HOLD - 1) / close.shift(-1) - 1
    paths = np.lib.stride_tricks.sliding_window_view(close.to_numpy()[1:], HOLD + 1)
    peaks = np.maximum.accumulate(paths, axis=1)
    frame["max_drawdown"] = pd.Series((paths / peaks - 1).min(axis=1), index=panel.index[:-HOLD - 1])
    frame["session"] = np.arange(len(frame))
    frame = frame.loc[start:].dropna(subset=["rank_504", "qqq_return"]).copy()
    frame["period"] = np.select([frame["exit_date"] < split, frame.index >= split],
                                ["training", "later"], default="boundary")
    if len(frame) >= 5:
        frame["original_quintile"] = pd.qcut(frame["close"].rank(method="first"), 5, labels=False) + 1
    frame.index.name = "signal_date"
    return frame


def metrics(rows):
    returns = rows["qqq_return"].to_numpy()
    if not len(returns):
        return dict(days=0, mean=None, median=None, positive=None, p10=None, drawdown=None)
    return dict(days=len(returns), mean=float(returns.mean()), median=float(np.median(returns)),
                positive=float((returns > 0).mean()), p10=float(np.quantile(returns, .10)),
                drawdown=float(rows["max_drawdown"].mean()))


def get_period(frame, period):
    return frame if period == "all" else frame[frame["period"].eq(period)]


def grid_search(frame):
    grid = []
    samples = {period: get_period(frame, period) for period in PERIODS}
    for window, floor, rank, easing in product(RANK_WINDOWS, FLOORS, RANK_CUTOFFS, EASING_DAYS):
        options = dict(window=window, floor=floor, rank=rank, easing=easing)
        gate = entry_mask(frame, **options)
        for period, sample in samples.items():
            covered = sample.loc[gate.loc[sample.index].notna()]
            summary = metrics(covered.loc[gate.loc[covered.index]])
            summary["spread"] = (summary["mean"] - covered["qqq_return"].mean()
                                 if summary["mean"] is not None else None)
            grid.append(dict(period=period, **options, eligible=len(covered), **summary))

    def select(window=None):
        train = [row for row in grid if row["period"] == "training"]
        baseline = next(row for row in train if (row["window"], row["rank"], row["floor"], row["easing"])
                        == (504, 80, 0, 0))
        eligible = [row for row in train if row["days"] >= 100 and baseline["drawdown"] is not None
                    and row["drawdown"] >= baseline["drawdown"] and (window is None or row["window"] == window)]
        if not eligible:
            return None
        best = max(eligible, key=lambda row: (row["mean"], row["days"]))
        keys = ("window", "floor", "rank", "easing")
        return {row["period"]: row for row in grid if all(row[key] == best[key] for key in keys)}

    return grid, select(504), select()


def compare_experiments(frame):
    rows = []
    for label, rule_a, rule_b in EXPERIMENTS:
        a, b = entry_mask(frame, **rule_a), entry_mask(frame, **rule_b)
        covered = frame.loc[a.notna() & b.notna()]
        for period in PERIODS:
            sample = get_period(covered, period)
            a_metrics = metrics(sample.loc[a.loc[sample.index]])
            b_metrics = metrics(sample.loc[b.loc[sample.index]])
            record = dict(experiment=label, period=period, eligible=len(sample),
                          first=sample.index.min().strftime("%Y-%m-%d") if len(sample) else None,
                          last=sample.index.max().strftime("%Y-%m-%d") if len(sample) else None,
                          a_rule=describe_rule(rule_a), b_rule=describe_rule(rule_b))
            record.update({f"{side}_{key}": value for side, stats in (("a", a_metrics), ("b", b_metrics))
                           for key, value in stats.items()})
            record["difference"] = b_metrics["mean"] - a_metrics["mean"] if a_metrics["days"] and b_metrics["days"] else None
            rows.append(record)
    return rows


def episode_starts(gate, quiet):
    hits = np.flatnonzero(gate.fillna(False).to_numpy(dtype=bool))
    return hits[np.r_[True, np.diff(hits) > quiet]] if hits.size else hits


def first_breakout(features, start, width):
    """Find the first eligible confirmation on the ten sessions after a fear signal."""
    lookup = features[f"breakout_{width}"].iloc[start + 1:start + 11]
    matches = lookup[lookup.fillna(False)]
    return matches.index[0] if len(matches) else None


def recovery_episodes(panel, features, frame):
    """Compare immediate and breakout entries from the same VIX ≥24 episodes."""
    rows = []
    for start in episode_starts(entry_mask(features, floor=24), quiet=21):
        trigger = panel.index[start]
        if start + 10 >= len(panel) or trigger not in frame.index:
            continue
        last = panel.index[start + 10]
        # Require a measurable 63-day outcome at every possible confirmation date.
        if last not in frame.index or frame.at[last, "period"] != frame.at[trigger, "period"]:
            continue
        early = frame.loc[trigger]
        for width in (3, 5, 10):
            confirmation = first_breakout(features, start, width)
            later = frame.loc[confirmation] if confirmation is not None else None
            rows.append(dict(
                period=early["period"], breakout=width, trigger=trigger.strftime("%Y-%m-%d"),
                confirmation=confirmation.strftime("%Y-%m-%d") if confirmation is not None else None,
                delay=int(later["session"] - early["session"]) if later is not None else None,
                immediate_return=early["qqq_return"],
                delayed_return=later["qqq_return"] if later is not None else None,
                same_exit_return=(panel.at[early["exit_date"], "qqq"] / panel.at[later["entry_date"], "qqq"] - 1
                                  if later is not None else None),
            ))
    return rows


def study_cases(features):
    for title, rule_a, rule_b in EXPERIMENTS:
        a, b = entry_mask(features, **rule_a), entry_mask(features, **rule_b)
        yield title, describe_rule(rule_a), describe_rule(rule_b), a, b

    fear = entry_mask(features, floor=24)
    immediate = pd.Series(False, index=features.index, dtype="boolean")
    delayed = immediate.copy()
    for start in episode_starts(fear, quiet=21):
        immediate.iloc[start] = True
        confirmation = first_breakout(features, start, width=5)
        if confirmation is not None:
            delayed.loc[confirmation] = True
    valid = fear.notna() & features["breakout_5"].notna()
    yield (
        "Wait for QQQ recovery", "First VIX ≥24 close", "First QQQ breakout within 10 sessions",
        immediate.where(valid), delayed.where(valid),
    )


def engine_setup(panel):
    from common import build_signals
    from strategy import Cfg, V2, prepare

    return prepare(panel, build_signals(panel)), Cfg(
        "VIX entry comparison", core=(("qqq", .5), ("spy", .5)), lev="qld", trend_guard=True, **V2)


def longest_underwater(nav):
    """Longest run of sessions below an earlier portfolio high."""
    below = nav.lt(nav.cummax())
    return int(below.groupby((~below).cumsum()).sum().max())


def account_metrics(nav, trades, rf, perf_stats):
    stat = perf_stats(nav["nav"], rf)
    monthly = nav["nav"].resample("ME").last().pct_change().dropna()
    action = trades["action"]
    return dict(tranches=int(action.eq("tranche").sum()), cagr=stat["CAGR"], sharpe=stat["Sharpe"],
                drawdown=stat["MaxDD"], volatility=stat["Vol"], sortino=stat["Sortino"], calmar=stat["Calmar"],
                longest_underwater=longest_underwater(nav["nav"]), worst_month=float(monthly.min()),
                positive_months=float(monthly.gt(0).mean()), average_exposure=float(nav["expo"].mean()),
                average_cash=float(nav["cash"].mean()),
                qld_buys=int(action.str.startswith("buy ").sum()), greed_trims=int(action.eq("greed trim").sum()))


def portfolio_runs(panel, cases, start, split):
    """Run the existing funded v2 engine on each experiment's common date coverage.

    "training" and "later" start a new portfolio at the beginning of their period.
    "carried" starts at the first shared training date and is measured over the
    later period only, so it keeps the holdings and powder built up beforehand.
    """
    from common import perf_stats
    from strategy import run

    states, cfg = engine_setup(panel)
    rows, ledger, seen = [], [], set()
    last_spy = panel["spy"].last_valid_index()
    for title, label_a, label_b, a, b in cases:
        shared = a.notna() & b.notna()
        for period, lower, upper in (("training", start, min(split - pd.Timedelta(days=1), last_spy)),
                                     ("later", split, last_spy), ("carried", start, last_spy)):
            available = shared.loc[lower:upper]
            dates = available.index[available]
            measured = dates[dates >= split] if period == "carried" else dates
            # With no shared date before the split there is nothing to carry forward.
            if len(measured) < 2 or (period == "carried" and dates[0] >= split):
                continue
            for label, gate in ((label_a, a & shared), (label_b, b & shared),
                                (COMPOSITE, states["p"].ge(cfg.tranche_p) & shared),
                                (NO_TRANCHES, shared & False)):
                nav, trades = run(states, cfg, dates[0], dates[-1], tranche_entry=gate)
                started = nav.index[0]
                nav = nav.loc[measured[0]:]
                trades = trades[trades["date"] >= measured[0]]
                # Guard switches are left out: they do not depend on the tranche rule.
                if (period, label, nav.index[0]) not in seen:
                    seen.add((period, label, nav.index[0]))
                    ledger += trade_ledger(panel, nav, trades, period, label)
                rows.append(dict(experiment=title, period=period, rule=label, started=started.strftime("%Y-%m-%d"),
                                 first=nav.index[0].strftime("%Y-%m-%d"), last=nav.index[-1].strftime("%Y-%m-%d"),
                                 **account_metrics(nav, trades, panel["rf"], perf_stats)))
    return rows, ledger


def trade_ledger(panel, nav, trades, period, rule):
    position = panel.index.get_indexer(trades["date"])
    qqq, vix = panel["qqq"].to_numpy(), panel["vix"].to_numpy()
    rows = []
    for i, date, action, amount in zip(position, trades["date"], trades["action"], trades["amount"]):
        if action.startswith("trend"):
            continue
        buy = action in ("tranche", "reinvest") or action.startswith("buy ")
        rows.append(dict(
            period=period, rule=rule, measured_from=nav.index[0].strftime("%Y-%m-%d"), date=date.strftime("%Y-%m-%d"),
            side="buy" if buy else "sell", action=action, share_of_account=float(amount / nav.at[date, "nav"]),
            qqq_close=float(qqq[i]), vix_at_signal=float(vix[i - 1]), cash_after=float(nav.at[date, "cash"]),
            exposure_after=float(nav.at[date, "expo"]),
            qqq_next_63=float(qqq[i + HOLD] / qqq[i] - 1) if i + HOLD < len(qqq) else None))
    return rows


def episode_start_mask(signals, *, independent_entries=False):
    sessions = signals["session"].to_numpy()
    return np.r_[True, np.diff(sessions) > 21] if len(sessions) and not independent_entries else (
        np.ones(len(sessions), dtype=bool))


def episode_concentration(signals, eligible, *, independent_entries=False):
    """Spreads that stop long episodes from dominating the day-weighted mean.

    The episode-weighted spread averages each episode's mean return, so every
    episode counts once. The other drops the episode with the most signal days
    (the earliest one on a tie), and is undefined when every episode is a single
    day. Both are measured against the same eligible mean.
    """
    if not len(signals):
        return dict(weighted=None, largest_days=0, without_largest=None)
    episode = episode_start_mask(signals, independent_entries=independent_entries).cumsum()
    returns, benchmark = signals["qqq_return"], eligible["qqq_return"].mean()
    sizes = np.bincount(episode)
    rest = returns[episode != sizes.argmax()]
    return dict(weighted=float(returns.groupby(episode).mean().mean() - benchmark), largest_days=int(sizes.max()),
                without_largest=float(rest.mean() - benchmark) if len(rest) and sizes.max() > 1 else None)


def episode_outcomes(signals, *, independent_entries=False):
    """Use QQQ trading sessions to measure starts and the gaps between them."""
    starts = episode_start_mask(signals, independent_entries=independent_entries)
    first_entries = signals.iloc[starts]
    gaps = np.diff(first_entries["session"].to_numpy())
    return len(first_entries), float(np.median(gaps)) if len(gaps) else None, first_entries


def outcome_summary(frame, cases, portfolio):
    """Join matched signal outcomes to the corresponding funded experiment and its controls."""
    funded = {(row["experiment"], row["period"], row["rule"]): row for row in portfolio}
    training = get_period(frame, "training")
    cutoff = training["close"].sort_values().iloc[int(.8 * len(training))] if len(training) else None
    frozen = (frame["close"].ge(cutoff) if cutoff is not None
              else pd.Series(pd.NA, index=frame.index, dtype="boolean"))
    frozen_label = f"VIX close ≥ {cutoff:.2f} (frozen training cutoff)" if cutoff is not None else "Frozen training cutoff"
    comparisons = [*cases, (
        "Historical VIX quintile", "Original top quintile (descriptive)", frozen_label,
        frame["original_quintile"].eq(5), frozen,
    )]

    def excess(results, eligible):
        return results["qqq_return"].mean() - eligible["qqq_return"].mean() if len(results) else None

    def funded_columns(experiment, rule):
        columns = {}
        for period in ("training", "later", "carried"):
            for name, label in (("portfolio", rule), ("composite", COMPOSITE), ("no_tranche", NO_TRANCHES)):
                account = funded.get((experiment, period, label), {})
                columns[f"{period}_{name}_sharpe"] = account.get("sharpe")
                columns[f"{period}_{name}_max_drawdown"] = account.get("drawdown")
        return columns

    rows = []
    for experiment, label_a, label_b, gate_a, gate_b in comparisons:
        independent = experiment == "Wait for QQQ recovery"
        a, b = gate_a.reindex(frame.index), gate_b.reindex(frame.index)
        shared = frame.loc[a.notna() & b.notna()]
        train, later = get_period(shared, "training"), get_period(shared, "later")
        outside_2020 = later.loc[later.index.year != 2020]
        for side, rule, gate in (("A", label_a, a), ("B", label_b, b)):
            train_signals = train.loc[gate.loc[train.index]]
            signals = later.loc[gate.loc[later.index]]
            stats = metrics(signals)
            n_episodes, median_gap, first_entries = episode_outcomes(signals, independent_entries=independent)
            train_episodes, _, train_first = episode_outcomes(train_signals, independent_entries=independent)
            concentration = episode_concentration(signals, later, independent_entries=independent)
            train_concentration = episode_concentration(train_signals, train, independent_entries=independent)
            signals_outside_2020 = outside_2020.loc[gate.loc[outside_2020.index]]
            account = funded.get((experiment, "later", rule), {})
            rows.append(dict(
                experiment=experiment, side=side, rule=rule, later_mean_return=stats["mean"],
                training_spread=excess(train_signals, train), later_spread=excess(signals, later),
                later_signal_days=stats["days"], later_p10_return=stats["p10"], later_episodes=n_episodes,
                median_episode_gap_sessions=median_gap, **funded_columns(experiment, rule),
                later_mean_trade_drawdown=stats["drawdown"],
                later_worst_trade_drawdown=signals["max_drawdown"].min() if len(signals) else None,
                later_median_return=stats["median"], later_positive_rate=stats["positive"],
                later_first_entry_spread=excess(first_entries, later),
                later_episode_weighted_spread=concentration["weighted"],
                later_largest_episode_days=concentration["largest_days"],
                later_spread_excluding_largest_episode=concentration["without_largest"],
                later_spread_excluding_2020=excess(signals_outside_2020, outside_2020),
                later_signal_days_excluding_2020=len(signals_outside_2020),
                training_episodes=train_episodes, training_first_entry_spread=excess(train_first, train),
                training_episode_weighted_spread=train_concentration["weighted"],
                later_portfolio_cagr=account.get("cagr"), later_funded_tranches=account.get("tranches"),
                training_signal_days=len(train_signals), training_eligible_days=len(train),
                later_eligible_days=len(later),
                training_first_eligible_date=train.index[0].strftime("%Y-%m-%d") if len(train) else None,
                later_first_eligible_date=later.index[0].strftime("%Y-%m-%d") if len(later) else None,
                later_last_eligible_date=later.index[-1].strftime("%Y-%m-%d") if len(later) else None,
                later_portfolio_start=account.get("first"), later_portfolio_end=account.get("last"),
            ))
    return rows


def records(frame):
    return json.loads(frame.to_json(orient="records", date_format="iso", date_unit="s", double_precision=15))


def tactical_results(output):
    """Entry and exit tests written by run_tactical.py and run_triggers.py, when run into the same directory."""
    read = lambda name: pd.read_csv(output / f"tactical_{name}.csv") if (output / f"tactical_{name}.csv").exists() else None
    tables = {name: read(name) for name in ("entry_pairs", "exit_pairs", "exit_disputed", "hold_length", "portfolio")}
    entry, leave = read("entry_ledger"), read("exit_ledger")
    if entry is not None and leave is not None:
        entry = entry.rename(columns={"fills": "actions"})
        leave = leave.rename(columns={"sales": "actions"})
        episodes = pd.concat([entry, leave], ignore_index=True)
        tables["episodes"] = episodes[episodes["trigger"].eq("VIX >= 24") & episodes["window"].eq(63)]
    for name in ("trigger_standalone", "trigger_standalone_quiet", "trigger_pairs", "trigger_exits", "trigger_portfolio",
                 "trigger_family", "trigger_episodes"):
        path = output / f"{name}.csv"
        tables[name] = pd.read_csv(path) if path.exists() else None
    return {name: records(table) for name, table in tables.items() if table is not None}


def input_coverage(frame):
    columns = {
        "VIX close": "close", "VIX intraday high": "high", "QQQ five-day breakout": "breakout_5",
        "VIX and VIX3M": "term_inverted", "QQQE / QQQ": "breadth_proxy_up",
        "Nasdaq-100 constituent breadth": "breadth_up", "High-yield spread": "credit_stable",
    }
    coverage = []
    for source, column in columns.items():
        known = frame[column].dropna()
        coverage.append(dict(source=source, days=len(known),
                             first=known.index.min().strftime("%Y-%m-%d") if len(known) else None,
                             last=known.index.max().strftime("%Y-%m-%d") if len(known) else None))
    return coverage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=PANEL)
    parser.add_argument("--vix-ohlc", type=Path, default=VIX_OHLC)
    parser.add_argument("--inputs", type=Path, default=INPUTS, help="Folder with the optional QQQE and credit files")
    parser.add_argument("--vix3m", type=Path, default=VIX3M, help="Cboe VIX3M history; rules that need it are left out if missing")
    parser.add_argument("--constituents", type=Path, help="Daily date, security, close, member CSV")
    parser.add_argument("--output", type=Path, default=RESULTS)
    parser.add_argument("--start", type=pd.Timestamp, default=pd.Timestamp("2008-01-03"))
    parser.add_argument("--split", type=pd.Timestamp, default=pd.Timestamp("2020-01-01"))
    parser.add_argument("--skip-portfolio", action="store_true")
    args = parser.parse_args()
    if args.split <= args.start:
        parser.error("--split must be later than --start")

    panel = pd.read_csv(args.panel, index_col=0, parse_dates=True)
    if (not isinstance(panel.index, pd.DatetimeIndex)
            or not panel.index.is_unique or not panel.index.is_monotonic_increasing or len(panel) <= HOLD + 1
            or not np.isfinite(panel["qqq"]).all() or not panel["qqq"].gt(0).all()):
        parser.error("The panel needs unique ascending dates and a complete positive QQQ price history.")
    features = build_features(panel, args.inputs, args.vix_ohlc, args.constituents, args.vix3m)
    frame = outcomes(panel, args.start, args.split, features)
    if len(frame) < 5:
        parser.error("At least five eligible sessions with complete rank and outcome windows are required.")

    grid, zip_pick, extended_pick = grid_search(frame)
    experiments = compare_experiments(frame)
    episodes = recovery_episodes(panel, features, frame)
    cases = list(study_cases(features))
    portfolio, ledger = ([], []) if args.skip_portfolio else portfolio_runs(panel, cases, args.start, args.split)
    rules = {label: gate for _, label_a, label_b, a, b in cases for label, gate in ((label_a, a), (label_b, b))}
    frequency = signal_frequency(rules, frame)
    entries = episode_entries(rules, panel, frame)
    summary = outcome_summary(frame, cases, portfolio)
    daily = frame.reset_index()
    for column in ("signal_date", "entry_date", "exit_date"):
        daily[column] = daily[column].dt.strftime("%Y-%m-%d")
    args.output.mkdir(parents=True, exist_ok=True)
    outputs = {
        "vix_signal_days": daily, "vix_parameter_grid": pd.DataFrame(grid),
        "vix_indicator_comparisons": pd.DataFrame(experiments), "vix_recovery_episodes": pd.DataFrame(episodes),
        "vix_portfolio_comparisons": pd.DataFrame(portfolio),
        "vix_input_coverage": pd.DataFrame(input_coverage(frame)),
        "vix_outcome_summary": pd.DataFrame(summary),
        "vix_signal_frequency": pd.DataFrame(frequency), "vix_episode_entries": pd.DataFrame(entries),
        "vix_portfolio_trades": pd.DataFrame(ledger),
    }
    for file, table in outputs.items():
        table.to_csv(args.output / f"{file}.csv", index=False)

    payload = dict(
        days=records(daily), grid=records(outputs["vix_parameter_grid"]), input_coverage=input_coverage(frame),
        episodes=records(outputs["vix_recovery_episodes"]), portfolio=records(outputs["vix_portfolio_comparisons"]),
        outcomes=records(outputs["vix_outcome_summary"]), frequency=records(outputs["vix_signal_frequency"]),
        entries=records(outputs["vix_episode_entries"]),
        ledger=records(outputs["vix_portfolio_trades"]),
        reference=describe_rule(BASELINE), tactical=tactical_results(args.output),
        presets=[dict(name=label, a=a, b=b) for label, a, b in EXPERIMENTS],
        filters=FILTERS, sources=SOURCES, split=args.split.strftime("%Y-%m-%d"),
        ranks=RANK_CUTOFFS, floors=FLOORS, windows=RANK_WINDOWS, lags=EASING_DAYS,
        zip_pick=zip_pick, extended_pick=extended_pick,
    )
    template = Path(__file__).with_name("dashboard.html.in").read_text()
    exported = json.dumps(payload, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")
    (args.output / "vix_signal_dashboard.html").write_text(
        template.replace("__VIX_RESEARCH_DATA__", exported), encoding="utf-8")
    print(f"{len(frame):,} eligible sessions · {len(grid) // len(PERIODS):,} VIX configurations · {len(episodes):,} episode/lookback rows")
    for column in ("breakout_5", "term_inverted", "breadth_proxy_up", "breadth_up", "credit_stable"):
        valid = frame[column].dropna()
        print(f"{column}: {len(valid):,} sessions" +
              (f" ({valid.index.min().date()} to {valid.index.max().date()})" if len(valid) else " (no data)"))
    print(args.output / "vix_signal_dashboard.html")


if __name__ == "__main__":
    main()
