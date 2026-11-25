#!/usr/bin/env python3
"""Use each VIX signal as the entry point, instead of only VIX >= 24.

An episode starts at a signal's first close. The next one needs the signal's own
gauge to calm down: VIX at or below its expanding median when the rule has a VIX
floor, otherwise the rule's rank at or below 50%. Each episode buys once, at the
next close, and holds 63 sessions after that purchase.

Three comparisons, chosen on 2008-2019 only:
  Standalone  First-signal return minus the average 63-session return of dates on which the signal's
              data exist.
  Paired      Rules that include VIX >= 24 against buying at VIX >= 24 itself, in the same fear
              episodes over the same horizon. A rule that never fires leaves the money in T-bills.
  Exits       The exit rules from tactical.py on each entry, against holding 63 sessions.
A rule passes a comparison when the mean difference is positive, at least 60% of episodes are
better, and it stays positive without its best episode. A rule needs 8 training episodes.
"""

import argparse
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from analyze_vix import ROOT
from indicators import build_features, entry_mask, read_daily
from run_tactical import SPLIT, START, build_markets, portfolio_row, sample_sessions
from tactical import COST, EXITS, episode_triggers, paired, passes, settle_exit
from tactical_portfolio import matched_static, run_sleeve

HOLD = 63
LATEST_SIGNAL = 63          # a paired rule may fire up to this many sessions after the VIX >= 24 trigger
MINIMUM_EPISODES = 8
BASE = "VIX >= 24"


def signal_rules():
    """name -> entry_mask options. Rank is the 80th percentile unless stated."""
    rules = {}
    for floor in (None, 24):
        for window in (None, 252, 504, 1260):
            for easing in (None, 5, 10, 20):
                if not floor and not window:
                    continue            # easing alone has no fear condition
                parts = ([f"VIX >= {floor}"] if floor else []) + ([f"{window}d rank >= 80%"] if window else []) + (
                    [f"easing {easing}d"] if easing else [])
                rules[" + ".join(parts)] = dict(floor=floor or 0, rank=80 if window else 0, window=window or 504, easing=easing or 0)
    for floor in (20, 22, 26, 30):
        rules[f"VIX >= {floor}"] = dict(floor=floor)
    rules["VIX >= 24 + easing 1d"] = dict(floor=24, easing=1)
    rules["VIX >= 24 + easing 3d"] = dict(floor=24, easing=3)
    rules["504d rank >= 90%"] = dict(rank=90)
    rules["VIX >= 24 + 504d rank >= 50% + easing 20d"] = dict(floor=24, rank=50, easing=20)
    rules["VIX >= 20 + 504d rank >= 80%"] = dict(floor=20, rank=80)
    rules["VIX >= 24 + VIX above VIX3M"] = dict(floor=24, confirmation="term_inverted")
    rules["VIX >= 24 + VIX at or below VIX3M"] = dict(floor=24, confirmation="term_flat")
    rules["VIX >= 24 + easing 20d + QQQ breakout"] = dict(floor=24, easing=20, confirmation="breakout_5")
    rules["VIX high >= 24"] = dict(floor=24, level="high")
    rules["VIX traded at 24 and closed below"] = dict(confirmation="intraday_fade")
    return rules


def resets_on_rank(options):
    """Rules with a rank and no VIX floor reset on their own rank. All others reset on VIX."""
    return bool(options.get("rank") and not options.get("floor"))


def reset_label(options):
    return f"{options.get('window', 504)}d rank at or below 50%" if resets_on_rank(options) else "VIX at or below its median"


def signal_markets(base, features, vix_rank, rules):
    """One Market per signal. Re-arming never happens on a close where the signal is still on."""
    markets = {}
    for name, options in rules.items():
        gate = entry_mask(features, **options)
        fear = gate.fillna(False).to_numpy(bool)
        calm = (features[f"rank_{options.get('window', 504)}"] if resets_on_rank(options) else vix_rank).le(.5).to_numpy()
        markets[name] = replace(base, fear=fear, calm=calm & ~fear, known={**base.known, "signal": gate.notna().to_numpy()})
    return markets


def quiet_starts(market):
    """First signal after at least 21 sessions without one, the study's episode definition. Robustness only."""
    hits = np.flatnonzero(market.fear)
    return hits[np.r_[True, np.diff(hits) > 21]] if len(hits) else hits


def starts_by_period(market, dates, window=HOLD, starter=None):
    """Trigger sessions with complete outcomes. Episodes before 2008 are not used, and training exits precede the split."""
    periods = {"training": [], "later": []}
    for start in (starter(market) if starter else episode_triggers(market.fear, market.calm)):
        deadline = start + 1 + window
        if dates[start] < START or deadline >= len(dates):
            continue
        if dates[deadline] < SPLIT:
            periods["training"].append(start)
        elif dates[start] >= SPLIT:
            periods["later"].append(start)
    return periods


def average_date_return(market, inside):
    """Average net return of buying on any date of the sample whose prior close had data for the signal."""
    entries = inside[market.known["signal"][inside - 1]]
    entries = entries[entries + HOLD <= inside[-1]]
    return (market.close[entries + HOLD] / market.close[entries]).mean() * (1 - COST) ** 2 - 1


def standalone(markets, dates, starter=None):
    """Episodes of every signal, and their return beyond an average date's."""
    rows = []
    for name, market in markets.items():
        for period, starts in starts_by_period(market, dates, starter=starter).items():
            if not len(starts):
                continue
            benchmark = average_date_return(market, sample_sessions(dates)[period])
            for start in starts:
                deadline = start + 1 + HOLD
                result = settle_exit([], market, start, deadline)
                rows.append(dict(rule=name, period=period, signal_date=dates[start].strftime("%Y-%m-%d"),
                                 entry_date=dates[start + 1].strftime("%Y-%m-%d"), vix=float(market.vix[start]),
                                 pnl=result["pnl"], excess=result["pnl"] - benchmark, worst_mark=result["worst_mark"]))
    return pd.DataFrame(rows)


def summarize_standalone(episodes, dates, rules):
    years = {period: len(sessions) / 252 for period, sessions in sample_sessions(dates).items()}
    rows = []
    for (rule, period), part in episodes.groupby(["rule", "period"], sort=False):
        row = dict(rule=rule, period=period, reset=reset_label(rules[rule]), **paired(part["excess"], np.zeros(len(part))))
        row.update(mean_pnl=part["pnl"].mean(), positive=float((part["pnl"] > 0).mean()), worst_mark=part["worst_mark"].mean(),
                   worst_trade=part["pnl"].min(), per_year=len(part) / years[period])
        row["passes"] = bool(passes(row) and row["n"] >= MINIMUM_EPISODES) if period == "training" else None
        rows.append(row)
    return pd.DataFrame(rows)


def paired_with_baseline(base, markets, dates, rules):
    """Same VIX >= 24 episodes: buy at the trigger, or wait for the rule, over a common horizon."""
    rows = []
    horizon = LATEST_SIGNAL + HOLD + 1
    for start in episode_triggers(base.fear, base.calm):
        end = start + 1 + horizon
        if dates[start] < START or end >= len(dates):
            continue
        period = "training" if dates[end] < SPLIT else "later" if dates[start] >= SPLIT else None
        if period is None:
            continue
        for name, options in rules.items():
            if name == BASE or options.get("floor", 0) < 24:
                continue
            market, entry = markets[name], None
            if not market.known["signal"][start:start + LATEST_SIGNAL + 1].all():
                continue
            for session in range(start, start + LATEST_SIGNAL + 1):
                if session > start and base.calm[session]:
                    break
                if market.fear[session]:
                    entry = session + 1
                    break
            results = []
            for at in (start + 1, entry):
                orders = [] if at is None else [(at, 1.0)]
                results.append(hold_value(orders, base, start, end))
            rows.append(dict(rule=name, period=period, trigger_date=dates[start].strftime("%Y-%m-%d"),
                             signal_date=dates[entry - 1].strftime("%Y-%m-%d") if entry else None,
                             wait=entry - 1 - start if entry else None, baseline_pnl=results[0], pnl=results[1]))
    return pd.DataFrame(rows)


def hold_value(orders, market, start, end):
    """Value at `end` of one order held 63 sessions, with T-bill interest before and after."""
    value = 1.0
    fill = orders[0][0] if orders else None
    for session in range(start + 2, end + 1):
        if fill is None or not fill < session <= fill + HOLD:
            value *= 1 + market.rf[session] / 252
    return value * (market.close[fill + HOLD] / market.close[fill] * (1 - COST) ** 2 if orders else 1) - 1


def summarize_paired(table):
    rows = []
    for (rule, period), part in table.groupby(["rule", "period"], sort=False):
        row = dict(rule=rule, period=period, **paired(part["pnl"], part["baseline_pnl"]))
        row.update(fired=int(part["wait"].notna().sum()), median_wait=part["wait"].median(), mean_pnl=part["pnl"].mean(),
                   baseline_pnl=part["baseline_pnl"].mean())
        row["passes"] = bool(passes(row) and row["n"] >= MINIMUM_EPISODES) if period == "training" else None
        rows.append(row)
    return pd.DataFrame(rows)


def exits_by_signal(markets, dates):
    rows = []
    for name, market in markets.items():
        for period, starts in starts_by_period(market, dates).items():
            results = {exit_name: [settle_exit(rule(market, s, s + 1 + HOLD), market, s, s + 1 + HOLD) for s in starts]
                       for exit_name, rule in EXITS.items()}
            hold = [r["pnl"] for r in results["X1 hold to the deadline"]]
            for exit_name, values in results.items():
                if exit_name.startswith("X1") or not starts:
                    continue
                row = dict(rule=name, period=period, exit=exit_name, **paired([r["pnl"] for r in values], hold))
                row.update(mean_pnl=float(np.mean([r["pnl"] for r in values])), baseline_pnl=float(np.mean(hold)),
                           exposure=float(np.mean([r["exposure"] for r in values])),
                           worst_mark=float(np.mean([r["worst_mark"] for r in values])),
                           baseline_worst_mark=float(np.mean([r["worst_mark"] for r in results["X1 hold to the deadline"]])))
                row["passes"] = bool(passes(row) and row["n"] >= MINIMUM_EPISODES) if period == "training" else None
                rows.append(row)
    return pd.DataFrame(rows)


def family_test(markets, dates, close, rules):
    """Chance that the best of all the signals looks this good in training, when their dates are slid together.

    All signals' training dates move by the same random number of sessions, so their overlap and
    clustering are kept. A date that slides to before a signal's data exist is dropped for that
    signal, and a signal left with too few dates sits that slide out. The statistic is the largest
    mean excess relative to its sampling error. Excess is against dates with the signal's data.
    """
    sessions = np.array([t for t in range(len(dates) - HOLD - 1) if dates[t] >= START and dates[t + 1 + HOLD] < SPLIT])
    returns = close[sessions + 1 + HOLD] / close[sessions + 1] - 1
    spot = {t: i for i, t in enumerate(sessions)}
    spots = {name: np.array([spot[s] for s in starts_by_period(markets[name], dates)["training"]]) for name in rules}
    spots = {name: at for name, at in spots.items() if len(at) >= MINIMUM_EPISODES}
    covered = {name: markets[name].known["signal"][sessions] for name in spots}
    excess = {name: np.where(known, returns - returns[known].mean(), np.nan) for name, known in covered.items()}
    scale = {name: np.nanstd(values) for name, values in excess.items()}
    shifts = range(1, len(sessions))

    def slide(name, shift):
        values = excess[name][(spots[name] + shift) % len(sessions)]
        values = values[~np.isnan(values)]
        return values if len(values) >= MINIMUM_EPISODES else None

    def statistics(shift):
        moved = {name: slide(name, shift) for name in spots}
        return {name: values.mean() * np.sqrt(len(values)) / scale[name] for name, values in moved.items() if values is not None}

    def count_passes(shift):
        """How many signals pass the selection rule when their dates carry no information."""
        moved = [slide(name, shift) for name in spots]
        return sum(passes(dict(n=len(values), difference=values.mean(), win_share=float((values > 0).mean()),
                               without_best=np.delete(values, values.argmax()).mean())) for values in moved if values is not None)

    def single_signal(name):
        """One signal's own luck, sliding only within the dates that have its data."""
        own = excess[name][covered[name]]
        at = np.searchsorted(np.flatnonzero(covered[name]), spots[name])
        return float(np.mean([own[(at + shift) % len(own)].mean() >= own[at].mean() for shift in range(1, len(own))]))

    observed_by_signal = statistics(0)
    best = max(observed_by_signal, key=observed_by_signal.get)
    observed = observed_by_signal[best]
    share = float(np.mean([max(statistics(shift).values(), default=-np.inf) >= observed for shift in shifts]))
    single = {name: single_signal(name) for name in spots}
    counts = [count_passes(shift) for shift in shifts]
    return dict(signals_tested=len(spots), best_signal=best, best_statistic=float(observed), chance_of_best=share,
                passes_observed=count_passes(0), passes_by_luck_mean=float(np.mean(counts)),
                passes_by_luck_95th=float(np.quantile(counts, .95)),
                chance_of_this_many_passes=float(np.mean(np.array(counts) >= count_passes(0)))), single


def portfolio_by_signal(markets, panel):
    from common import perf_stats

    dates, last = panel.index, panel["spy"].last_valid_index()
    returns = {name: panel[f"ret_{name}"].fillna(0).to_numpy() for name in ("qqq", "spy")}
    rows = []
    for period, (first, end) in {"training": (START, SPLIT - pd.Timedelta(days=1)), "later": (SPLIT, last)}.items():
        first, end = dates[dates.searchsorted(first)], dates[dates.searchsorted(end, side="right") - 1]
        for name, market in markets.items():
            if not market.fear.any():
                continue            # its input file is absent
            for size in (.075, .30):
                frame, stats = run_sleeve(market, returns, dates, first, end, size, EXITS["X1 hold to the deadline"], HOLD)
                stat = perf_stats(frame["nav"], panel["rf"])
                matched = matched_static(market, returns, dates, first, end, float(frame["tactical"].mean()))
                rows.append(dict(period=period, rule=name, size=size, **portfolio_row(frame, stat, panel, market, dates), **stats,
                                 sharpe_minus_matched=stat["Sharpe"] - perf_stats(matched, panel["rf"])["Sharpe"]))
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--inputs", type=Path, default=ROOT / "data/raw/vix_entry")
    parser.add_argument("--output", type=Path, default=ROOT / "results/vix_entry")
    args = parser.parse_args()
    from common import build_signals, load_panel
    from strategy import prepare

    panel = load_panel()
    vix_path = ROOT / "data/raw/vix_daily.csv"
    history = read_daily(vix_path, "DATE", "CLOSE")
    features = build_features(panel, args.inputs, vix_path, None)
    base = build_markets(panel, features, prepare(panel, build_signals(panel)), history, args.inputs)[BASE]
    vix_rank = history.expanding(504).rank(pct=True).reindex(panel.index).ffill(limit=3)
    rules = signal_rules()
    markets = signal_markets(base, features, vix_rank, rules)
    dates, close = panel.index, base.close

    episodes = standalone(markets, dates)
    summary = summarize_standalone(episodes, dates, rules)
    family, single = family_test(markets, dates, close, rules)
    summary["shift_p"] = [single.get(rule) if period == "training" else None for rule, period in zip(summary["rule"], summary["period"])]
    pairs = paired_with_baseline(base, markets, dates, rules)
    quiet = summarize_standalone(standalone(markets, dates, quiet_starts), dates, rules)
    outputs = {"trigger_standalone_quiet": quiet, "trigger_episodes": episodes, "trigger_standalone": summary, "trigger_pairs_episodes": pairs,
               "trigger_pairs": summarize_paired(pairs), "trigger_exits": exits_by_signal(markets, dates),
               "trigger_portfolio": portfolio_by_signal(markets, panel), "trigger_family": pd.DataFrame([family])}
    args.output.mkdir(parents=True, exist_ok=True)
    for name, table in outputs.items():
        table.to_csv(args.output / f"{name}.csv", index=False)
    print(len(rules), "signals;", family)


if __name__ == "__main__":
    main()
