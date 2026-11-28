#!/usr/bin/env python3
"""Compare staged entries and exits after a VIX fear trigger, episode by episode.

Rules are chosen on 2008-2019 only. 2020-2026 is reported as secondary.

Two questions are kept apart because they spend different amounts:
  First order   one tranche. Baseline: buy all of it at the trigger. Measured by paired P&L.
  Reserve       four tranches. Baseline: buy all of it at the trigger. Plans that buy more
                earn more simply because QQQ rises, so they are measured by timing value:
                profit beyond buying on an average date and holding as long.

Exits buy the whole order at the trigger. X1, holding to the deadline, is the baseline.
The 63-session window decides. 126 sessions is reported so "let it run" is visible, and
holding 126 sessions is compared directly with selling at 63 and earning T-bills.
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from vix_paths import INPUTS, RESULTS, VIX3M, VIX_OHLC
from indicators import build_features, entry_mask, read_daily, term_spread
from tactical_portfolio import block_bootstrap_sharpe, episode_low_reserve, matched_static, run_sleeve
from tactical import (CONFIRMATIONS, EXIT_REFERENCE, EXITS, FIRST_ORDER, FIRST_ORDER_SENSITIVITY, HOLD_LENGTHS, Market,
                      RESERVE, average_hold, episode_triggers, exit_timing_value, normalization, breakdown, paired, passes,
                      settle, settle_exit, timing_value)

START, SPLIT = pd.Timestamp("2008-01-03"), pd.Timestamp("2020-01-01")
WINDOWS = (63, 126)
MAIN_TRIGGER = "VIX >= 24"


def build_markets(panel, features, states, vix_history, vix3m):
    """One Market per trigger definition. VIX normalizes at its expanding median since 1990.

    The two sensitivity triggers normalize on their own gauge, so their names say so. The
    rank trigger has fewer episodes here than in run_triggers.py, where the same entry
    condition has a VIX floor and therefore resets on VIX.
    """
    vix, close = panel["vix"], panel["qqq"]
    vix_rank = vix_history.expanding(504).rank(pct=True).reindex(panel.index).ffill(limit=3)
    curve = term_spread(vix, vix3m)
    prior_high = close.shift().rolling(5).max()
    confirm = {
        "VIX easing 5d": vix.lt(vix.shift(5)), "VXN 15% below 10d high": panel["vxn"].le(.85 * panel["vxn"].rolling(10).max()),
        "QQQ 5-close breakout": close.gt(prior_high),
        "VIX/VIX3M back below 1": curve.lt(0) & curve.shift().ge(0),
    }
    known = {"VIX easing 5d": vix.shift(5).notna(), "VXN 15% below 10d high": panel["vxn"].rolling(10).max().notna(),
             "QQQ 5-close breakout": prior_high.notna(), "VIX/VIX3M back below 1": curve.notna() & curve.shift().notna()}
    shared = dict(close=close.to_numpy(), vix=vix.to_numpy(), rf=panel["rf"].to_numpy(),
                  reference=entry_mask(features, floor=24, easing=20).fillna(False).to_numpy(bool),
                  confirm={name: values.fillna(False).to_numpy(bool) for name, values in confirm.items()},
                  known={name: values.to_numpy(bool) for name, values in known.items()})
    rank = features["rank_504"]
    triggers = {
        MAIN_TRIGGER: (vix.ge(24), vix_rank.le(.5)),
        "Composite >= 80th (resets at its median)": (states["p"].ge(.8), states["p"].le(.5)),
        "VIX rank >= 80% and VIX >= 20 (resets at rank 50%)": (rank.ge(.8) & vix.ge(20), rank.le(.5)),
    }
    return {name: Market(fear=fear.to_numpy(bool), calm=calm.to_numpy(bool), **shared)
            for name, (fear, calm) in triggers.items()}


def sample_sessions(dates):
    return {"training": np.flatnonzero((dates >= START) & (dates < SPLIT)), "later": np.flatnonzero(dates >= SPLIT)}


def split_episodes(market, dates, window):
    """Trigger sessions with complete outcomes, by period. Training exits must precede the split."""
    periods = {"training": [], "later": []}
    for start in episode_triggers(market.fear, market.calm):
        deadline = start + 1 + window
        if dates[start] < START or deadline >= len(dates):
            continue
        if dates[deadline] < SPLIT:
            periods["training"].append(start)
        elif dates[start] >= SPLIT:
            periods["later"].append(start)
    return periods


def evaluate(market, dates, trigger, window, rules, group):
    """Every rule's result in every episode."""
    rows = []
    for period, starts in split_episodes(market, dates, window).items():
        average = average_hold(market.close, sample_sessions(dates)[period])
        for start in starts:
            deadline = start + 1 + window
            for name, rule in rules.items():
                required = next((c for c in CONFIRMATIONS if name.endswith(c)), None)
                if required and not market.known[required][start:start + 11].all():
                    continue
                orders = rule(market, start, deadline)
                result = settle(orders, market, start, deadline)
                rows.append(dict(trigger=trigger, window=window, period=period, group=group, rule=name,
                                 trigger_date=dates[start].strftime("%Y-%m-%d"), vix=float(market.vix[start]),
                                 fills="; ".join(f"{dates[s].date()}:{a:g}" for s, a in orders if s < deadline),
                                 timing_value=timing_value(orders, market, deadline, average), **result))
    return rows


def evaluate_exits(market, dates, trigger, window):
    """Every exit in every episode, with the order in which the two exit signals came."""
    rows = []
    for period, starts in split_episodes(market, dates, window).items():
        average = average_hold(market.close, sample_sessions(dates)[period])
        for start in starts:
            deadline = start + 1 + window
            calm, broken = normalization(market, start + 1, deadline), breakdown(market, start + 1, deadline, True)
            first = ("none" if calm is None and broken is None else "breakdown" if calm is None or
                     (broken is not None and broken <= calm) else "normalization")
            for name, rule in {**EXITS, **EXIT_REFERENCE}.items():
                sales = rule(market, start, deadline)
                rows.append(dict(trigger=trigger, window=window, period=period, group="exit", rule=name,
                                 trigger_date=dates[start].strftime("%Y-%m-%d"), vix=float(market.vix[start]),
                                 entry_date=dates[start + 1].strftime("%Y-%m-%d"), first_signal=first,
                                 sales="; ".join(f"{dates[t].date()}:{a:.3g}" for t, a in sales if t < deadline),
                                 timing_value=exit_timing_value(sales, market, start, deadline, average),
                                 **settle_exit(sales, market, start, deadline)))
    return rows


def evaluate_hold_lengths(market, dates, trigger):
    """Holding 126 sessions against selling at 63 and earning T-bills to the same day."""
    rows = []
    for period, starts in split_episodes(market, dates, 126).items():
        average = average_hold(market.close, sample_sessions(dates)[period])
        for start in starts:
            deadline = start + 1 + 126
            for name, rule in HOLD_LENGTHS.items():
                sales = rule(market, start, deadline)
                rows.append(dict(trigger=trigger, window=126, period=period, group="hold length", rule=name,
                                 trigger_date=dates[start].strftime("%Y-%m-%d"),
                                 timing_value=exit_timing_value(sales, market, start, deadline, average),
                                 **settle_exit(sales, market, start, deadline)))
    return rows


def disputed_half(ledger):
    """X4a and X5a only differ when price breaks down while fear is still high."""
    rows = []
    for (trigger, window, period), part in ledger.groupby(["trigger", "window", "period"], sort=False):
        part = part[part["first_signal"].eq("breakdown")]
        table = part.pivot(index="trigger_date", columns="rule", values="pnl")
        if not len(table):
            continue
        x4, x5 = table["X4a half on normalization, half on breakdown"], table["X5a half on normalization, all on breakdown"]
        rows.append(dict(trigger=trigger, window=window, period=period, episodes_total=int(
            ledger[(ledger["trigger"].eq(trigger)) & (ledger["window"].eq(window)) & (ledger["period"].eq(period))]["trigger_date"].nunique()),
            **{f"x5_minus_x4_{key}": value for key, value in paired(x5, x4).items()}))
    return rows


def portfolio_check(market, panel):
    """The chosen rule, the static account, and the unselected exits for description."""
    from common import perf_stats

    last, dates = panel["spy"].last_valid_index(), panel.index
    returns = {name: panel[f"ret_{name}"].fillna(0).to_numpy() for name in ("qqq", "spy")}
    periods = {"training": (START, SPLIT - pd.Timedelta(days=1)), "later": (SPLIT, last), "all": (START, last)}
    plans = {name: rule for name, rule in EXITS.items()}
    rows = []
    for period, (first, end) in periods.items():
        first, end = dates[dates.searchsorted(first)], dates[dates.searchsorted(end, side="right") - 1]
        static, _ = run_sleeve(market, returns, dates, first, end, 0, plans["X1 hold to the deadline"], 63)
        static_stat = perf_stats(static["nav"], panel["rf"])
        rows.append(dict(period=period, size=0.0, rule="Static 70/30", **portfolio_row(static, static_stat, panel, market, dates)))
        for size in (.075, .30):
            for name, rule in plans.items():
                frame, stats = run_sleeve(market, returns, dates, first, end, size, rule, 63)
                stat = perf_stats(frame["nav"], panel["rf"])
                matched = matched_static(market, returns, dates, first, end, float(frame["tactical"].mean()))
                row = dict(period=period, size=size, rule=name, **portfolio_row(frame, stat, panel, market, dates), **stats)
                row["matched_sharpe"] = perf_stats(matched, panel["rf"])["Sharpe"]
                for label, other in (("static", static["nav"]), ("matched", matched)):
                    diff, low, high = block_bootstrap_sharpe(frame["nav"], other, panel["rf"])
                    row.update({f"sharpe_minus_{label}": diff, f"sharpe_minus_{label}_low": low, f"sharpe_minus_{label}_high": high})
                rows.append(row)
    return rows


def portfolio_row(frame, stat, panel, market, dates):
    return dict(first=frame.index[0].strftime("%Y-%m-%d"), last=frame.index[-1].strftime("%Y-%m-%d"),
                cagr=stat["CAGR"], sharpe=stat["Sharpe"], max_drawdown=stat["MaxDD"], volatility=stat["Vol"],
                average_equity=float(frame["equity"].mean()), average_tactical=float(frame["tactical"].mean()),
                reserve_at_episode_lows=episode_low_reserve(frame, market, dates, 63))


def compare(ledger, baseline, metric):
    """Paired summary of each rule against the baseline on the episodes both have."""
    rows = []
    keys = ["trigger", "window", "period", "group"]
    for values, part in ledger.groupby(keys, sort=False):
        table = part.pivot(index="trigger_date", columns="rule", values=metric)
        if baseline not in table:
            continue
        for rule in part["rule"].unique():
            if rule == baseline:
                continue
            both = table[[rule, baseline]].dropna()
            own = part[part["rule"].eq(rule) & part["trigger_date"].isin(both.index)]
            base = part[part["rule"].eq(baseline) & part["trigger_date"].isin(both.index)]
            row = dict(zip(keys, values), rule=rule, baseline=baseline, metric=metric, **paired(both[rule], both[baseline]))
            row.update(mean_pnl=own["pnl"].mean(), baseline_pnl=base["pnl"].mean(),
                       worst_mark=own["worst_mark"].mean(), baseline_worst_mark=base["worst_mark"].mean(),
                       timing_value=own["timing_value"].mean(), baseline_timing_value=base["timing_value"].mean())
            row.update({column: own[column].mean() for column in ("deployed", "cash_at_low", "exposure", "sold_early") if column in own})
            row["passes"] = passes(row) if row["period"] == "training" else None
            rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--inputs", type=Path, default=INPUTS, help="Folder with the optional QQQE and credit files")
    parser.add_argument("--vix3m", type=Path, default=VIX3M, help="Cboe VIX3M history; rules that need it are left out if missing")
    parser.add_argument("--output", type=Path, default=RESULTS)
    args = parser.parse_args()

    from common import build_signals, load_panel
    from strategy import prepare

    panel = load_panel()
    features = build_features(panel, args.inputs, VIX_OHLC, None, args.vix3m)
    markets = build_markets(panel, features, prepare(panel, build_signals(panel)), read_daily(VIX_OHLC, "DATE", "CLOSE"), args.vix3m)
    ledger = []
    for trigger, market in markets.items():
        for window in WINDOWS:
            ledger += evaluate(market, panel.index, trigger, window, {**FIRST_ORDER, **FIRST_ORDER_SENSITIVITY}, "first order")
            ledger += evaluate(market, panel.index, trigger, window, RESERVE, "reserve")
    ledger = pd.DataFrame(ledger)
    first, reserve = ledger[ledger["group"].eq("first order")], ledger[ledger["group"].eq("reserve")]
    e5, controls = "E5 half now, half on VIX easing 5d", [name for name in FIRST_ORDER if name.startswith("E6")]
    pairs = compare(first, "E0 all at the trigger", "pnl")
    for control in controls:
        pairs += compare(first[first["rule"].isin([e5, control])], control, "pnl")
    # Profit is reported beside timing value: it is what the investor earns, but it rewards buying more.
    for baseline, metric in (("R0 whole reserve at the trigger", "timing_value"), ("R0 whole reserve at the trigger", "pnl"),
                             ("R1 first tranche only", "timing_value")):
        pairs += compare(reserve, baseline, metric)
    args.output.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(args.output / "tactical_entry_ledger.csv", index=False)
    pd.DataFrame(pairs).to_csv(args.output / "tactical_entry_pairs.csv", index=False)
    exits = []
    for trigger, market in markets.items():
        for window in WINDOWS:
            exits += evaluate_exits(market, panel.index, trigger, window)
    exits = pd.DataFrame(exits)
    exits.to_csv(args.output / "tactical_exit_ledger.csv", index=False)
    pd.DataFrame(compare(exits, "X1 hold to the deadline", "pnl")).to_csv(args.output / "tactical_exit_pairs.csv", index=False)
    pd.DataFrame(disputed_half(exits)).to_csv(args.output / "tactical_exit_disputed.csv", index=False)
    lengths = pd.DataFrame([row for trigger, market in markets.items() for row in evaluate_hold_lengths(market, panel.index, trigger)])
    short = next(iter(HOLD_LENGTHS))
    pd.DataFrame(compare(lengths, short, "pnl") + compare(lengths, short, "timing_value")).to_csv(
        args.output / "tactical_hold_length.csv", index=False)
    main = markets[MAIN_TRIGGER]
    pd.DataFrame(portfolio_check(main, panel)).to_csv(args.output / "tactical_portfolio.csv", index=False)
    counts = ledger[ledger["rule"].eq("E0 all at the trigger")].groupby(["trigger", "window", "period"], sort=False).size()
    print(counts.to_string())


if __name__ == "__main__":
    main()
