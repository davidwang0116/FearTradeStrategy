#!/usr/bin/env python3
"""Print the Markdown tables used in SUMMARY.md from a finished analyze_vix.py run."""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from analyze_vix import EXPERIMENTS, describe_rule, episode_concentration, episode_outcomes
from indicators import FILTERS, entry_mask
from vix_paths import RESULTS


def load_days(output):
    days = pd.read_csv(output / "vix_signal_days.csv", index_col=0, parse_dates=True)
    for column in FILTERS:
        days[column] = days[column].astype("boolean")
    return days


def sample(days, period, rule):
    rows = days[days["period"].eq(period)]
    gate = entry_mask(rows, **rule)
    eligible = rows[gate.notna()]
    return eligible, eligible[gate[gate.notna()].astype(bool)]


def pp(value, sign=True):
    if value is None or pd.isna(value):
        return "—"
    text = f"{100 * value:{'+' if sign else ''}.2f}"
    return text.replace("-", "−")


def spread(rows, eligible):
    return rows["qqq_return"].mean() - eligible["qqq_return"].mean() if len(rows) else None


def rule_row(days, label, rule):
    """Training and later results, then the later checks for concentration."""
    train, train_hits = sample(days, "training", rule)
    later, hits = sample(days, "later", rule)
    rest, rest_hits = later[later.index.year != 2020], hits[hits.index.year != 2020]
    concentration = episode_concentration(hits, later)
    episodes = episode_outcomes(hits)[0]
    cells = [label, f"{pp(spread(train_hits, train))} ({len(train_hits)})", f"{pp(spread(hits, later))} ({len(hits)})",
             f"{pp(spread(rest_hits, rest))} ({len(rest_hits)})",
             f"{pp(concentration['weighted'])} ({episodes})",
             pp(concentration["without_largest"]), f"{pp(hits['qqq_return'].quantile(.1), False)}%" if len(hits) else "—",
             f"{100 * (hits['qqq_return'] > 0).mean():.0f}%" if len(hits) else "—"]
    return "| " + " | ".join(cells) + " |"


HEADER = ("| Rule | Training spread (days) | Later spread (days) | Later ex 2020 (days) | Later episode-weighted (episodes) "
          "| Later, largest episode removed | Later 10th pct. | Later positive |\n|---|---:|---:|---:|---:|---:|---:|---:|")


def print_sweep(days, title, rules):
    print(f"\n### {title}\n\n{HEADER}")
    for label, rule in rules:
        print(rule_row(days, label, rule))


def shift_test(days, period, rule):
    """Share of circular shifts of the signal dates whose mean return is at least as high.

    Shifting the whole pattern keeps the clustering of signals and the overlap of
    holding periods. It does not correct for the number of rules tried.
    """
    eligible, hits = sample(days, period, rule)
    mask, returns = eligible.index.isin(hits.index), eligible["qqq_return"].to_numpy()
    observed = returns[mask].mean()
    return float(np.mean([returns[np.roll(mask, shift)].mean() >= observed for shift in range(1, len(mask))]))


def p_text(value):
    return "<0.001" if value < .001 else f"{value:.3f}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=RESULTS)
    days = load_days(parser.parse_args().output)

    print("### Quintiles\n\n| Quintile | VIX range | Training mean (days) | Later mean (days) |\n|---|---|---:|---:|")
    for number, rows in days.groupby("original_quintile"):
        cell = lambda part: f"{pp(part['qqq_return'].mean(), False)}% ({len(part)})"
        print(f"| {int(number)} | {rows['close'].min():.2f}–{rows['close'].max():.2f} | "
              f"{cell(rows[rows['period'].eq('training')])} | {cell(rows[rows['period'].eq('later')])} |")

    print_sweep(days, "VIX floor", [(f"VIX ≥{f}", dict(floor=f)) for f in (20, 22, 24, 26, 30)])
    print_sweep(days, "Easing with a VIX ≥24 floor", [(f"{e}-day" if e else "none", dict(floor=24, easing=e)) for e in (0, 1, 3, 5, 10, 20)])
    print_sweep(days, "Easing with no floor", [(f"{e}-day", dict(easing=e)) for e in (1, 3, 5, 10, 20)])
    print_sweep(days, "Floor with 20-day easing", [(f"VIX ≥{f}" if f else "none", dict(floor=f, easing=20)) for f in (0, 20, 22, 24, 26, 30)])
    print_sweep(days, "504-day rank", [(f"rank ≥{r}%", dict(rank=r)) for r in range(50, 100, 5)])
    print_sweep(days, "Rank window", [(f"{w}-day rank ≥{r}%", dict(rank=r, window=w)) for r in (80, 90) for w in (252, 504, 1260)])
    print_sweep(days, "Rank combined with VIX ≥24", [(f"rank ≥{r}%", dict(rank=r, floor=24)) for r in (50, 80, 90, 95)])
    print_sweep(days, "Rank combined with VIX ≥24 and 20-day easing", [(f"rank ≥{r}%" if r else "none", dict(rank=r, floor=24, easing=20)) for r in (0, 50, 80, 90)])
    presets = {describe_rule(rule): rule for _, a, b in EXPERIMENTS for rule in (a, b)}
    print_sweep(days, "Preset rules", [(label, rule) for label, rule in presets.items() if rule.get("confirmation") != "breadth_up"])

    grid = pd.read_csv(parser.parse_args().output / "vix_parameter_grid.csv")
    grid = grid[(grid["rank"] > 0) | (grid["window"] == 504)]
    keys = ["window", "floor", "rank", "easing"]
    both = grid[grid["period"].eq("training")].merge(grid[grid["period"].eq("later")], on=keys, suffixes=("", "_later"))
    ample = both[(both["days"] >= 100) & (both["days_later"] >= 50)]
    baseline = both.loc[(both[keys] == [504, 0, 80, 0]).all(axis=1), "drawdown"].item()
    screened = both[(both["days"] >= 100) & (both["drawdown"] >= baseline)].sort_values("mean", ascending=False)
    print(f"\n### Grid\n\ndistinct rules {len(both)}; with ≥100 training and ≥50 later days {len(ample)}; "
          f"positive in training {int((ample['spread'] > 0).sum())}, later {int((ample['spread_later'] > 0).sum())}, "
          f"both {int(((ample['spread'] > 0) & (ample['spread_later'] > 0)).sum())}; "
          f"rank correlation of spreads {ample['spread'].corr(ample['spread_later'], method='spearman'):.2f}; "
          f"pass selection screen {len(screened)}; top-50 median later spread {pp(screened.head(50)['spread_later'].median())}, "
          f"range {pp(screened.head(50)['spread_later'].min())} to {pp(screened.head(50)['spread_later'].max())}")
    print("\n| Window | Floor | Rank | Easing | Training days | Training mean | Later days | Later spread |\n|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, row in screened.drop_duplicates(["days", "mean", "days_later"]).head(6).iterrows():
        print(f"| {row['window']:.0f} | {row['floor']:.0f} | {row['rank']:.0f}% | {row['easing']:.0f} | {row['days']:.0f} | "
              f"{pp(row['mean'], False)}% | {row['days_later']:.0f} | {pp(row['spread_later'])} |")

    print("\n### Shift test\n\n| Rule | Training | Later |\n|---|---:|---:|")
    for label in ("VIX close ≥ 24", "504d rank ≥ 80%", "VIX close ≥ 24 + VIX easing 10d", "VIX close ≥ 24 + VIX easing 20d",
                  "VIX close ≥ 24 + VIX easing 20d + QQQ above its previous 5 closes", "VIX close ≥ 24 + VIX above VIX3M",
                  "VIX close ≥ 24 + VIX at or below VIX3M"):
        print(f"| {label} | " + " | ".join(p_text(shift_test(days, period, presets[label])) for period in ("training", "later")) + " |")


if __name__ == "__main__":
    main()
