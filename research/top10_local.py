"""ILLUSTRATIVE ONLY — top-10-by-dollar-volume rules on 11 hand-picked tech stocks (2016-2026).

The 11 names (AMD, AMZN, AVGO, GOOG, INTC, META, MSFT, MU, NVDA, ORCL, TSLA) come from a public
GitHub repo assembled in 2026: they are survivors and winners, AAPL is missing. Levels are
meaningless; only the comparison of rules *within the same names* is informative, and even that
is biased. The rigorous test is qc/top10_dollar_volume.py (point-in-time universe on QC).

Each month-end: universe = top 10 by trailing 21-day average dollar volume; trade at the next close;
price returns (no dividends) for stocks and QQQ alike; 10 bp per unit of turnover.
Outputs: results/top10_local.csv, figures/fig_top10_local.png
"""
from pathlib import Path

import numpy as np
import pandas as pd

from common import (AQUA, BLUE, INK2, MUTED, ORANGE, RES, ROOT, SEQ5, VIOLET, load_panel, perf_stats, plt,
                    savefig)

RAW = ROOT / "data" / "raw" / "stocks_illustrative"
NAMES = ["amd", "amzn", "avgo", "goog", "intc", "meta", "msft", "mu", "nvda", "orcl", "tsla"]
COST = 0.001


def load():
    px, dv = {}, {}
    for t in NAMES + ["qqq"]:
        d = pd.read_csv(RAW / f"{t}.csv", parse_dates=["date"]).set_index("date")
        px[t] = d["close"]
        dv[t] = d["close"] * d["volume"]
    return pd.DataFrame(px), pd.DataFrame(dv)


def weights_for(rule, px, dv, t):
    hist = px.loc[:t, NAMES]
    adv = dv.loc[:t, NAMES].tail(21).mean()
    uni = adv.sort_values(ascending=False).index[:10]
    h = hist[uni]
    r = h.pct_change()
    if rule == "Equal weight top 10":
        w = pd.Series(1.0, uni)
    elif rule == "Inverse volatility (63d)":
        w = 1 / r.tail(63).std()
    elif rule == "Dollar-volume weighted":
        w = adv[uni]
    elif rule == "Short-term reversal: 5 worst 1-month":
        w = pd.Series(1.0, (h.iloc[-1] / h.iloc[-22] - 1).nsmallest(5).index)
    elif rule == "Momentum: 5 best 12-1 month":
        if len(h) < 253:
            return None
        w = pd.Series(1.0, (h.iloc[-22] / h.iloc[-253] - 1).nlargest(5).index)
    elif rule == "Stock-level fear: 5 deepest drawdowns":
        w = pd.Series(1.0, (h.iloc[-1] / h.tail(252).max() - 1).nsmallest(5).index)
    else:
        raise ValueError(rule)
    return (w / w.sum()).reindex(NAMES).fillna(0.0)


def backtest(rule, px, dv):
    rets = px[NAMES].pct_change().fillna(0.0)
    month_end = px.index.to_series().groupby(px.index.to_period("M")).last().values
    start = px.index[252]
    w = pd.Series(0.0, NAMES); nav = [1.0]; dates = [start]; turnover = []
    pending = None
    for i, t in enumerate(px.index):
        if t <= start:
            continue
        nav_t = nav[-1] * (1 + (w * rets.loc[t]).sum())
        w = w * (1 + rets.loc[t]); w = w / w.sum() if w.sum() > 0 else w
        if pending is not None:                       # trade at this close, decided at last month-end
            to = (pending - w).abs().sum(); turnover.append(to)
            nav_t *= 1 - COST * to; w = pending; pending = None
        if t in month_end:
            nw = weights_for(rule, px, dv, t)
            if nw is not None:
                pending = nw
        nav.append(nav_t); dates.append(t)
    return pd.Series(nav, dates), np.sum(turnover) / ((dates[-1] - dates[0]).days / 365.25)


def main():
    px, dv = load()
    rf = load_panel()["rf"]
    rules = ["Equal weight top 10", "Inverse volatility (63d)", "Dollar-volume weighted",
             "Short-term reversal: 5 worst 1-month", "Momentum: 5 best 12-1 month", "Stock-level fear: 5 deepest drawdowns"]
    navs, rows = {}, []
    q = px["qqq"].loc[px.index[252]:]; navs["QQQ (price only)"] = q / q.iloc[0]
    for rl in rules:
        nav, to = backtest(rl, px, dv); navs[rl] = nav
        rows.append(dict(rule=rl, turnover_per_yr=to))
    out = []
    ew = navs["Equal weight top 10"].pct_change()
    for k, n in navs.items():
        st = perf_stats(n, rf)
        rr = n.pct_change()
        out.append(dict(rule=k, **st, corr_vs_EW=rr.corr(ew),
                        turnover_per_yr=next((r["turnover_per_yr"] for r in rows if r["rule"] == k), 0.0)))
    T = pd.DataFrame(out)
    T.to_csv(RES / "top10_local.csv", index=False)
    pd.set_option("display.width", 220)
    print(T.round(3).to_string())

    fig, ax = plt.subplots(figsize=(11, 5.4))
    order = T.sort_values("Sharpe")
    cols = [MUTED if r.startswith("QQQ") else (BLUE if r.startswith("Equal") else SEQ5[1]) for r in order.rule]
    ax.barh(order.rule, order.Sharpe, color=cols, height=0.6)
    for y, (_, r) in enumerate(order.iterrows()):
        ax.text(r.Sharpe + 0.01, y, f"{r.Sharpe:.2f} · CAGR {r.CAGR:.0%} · vol {r.Vol:.0%} · MaxDD {r.MaxDD:.0%}",
                va="center", fontsize=9.5, color=INK2)
    ax.set_xlim(0, max(T.Sharpe) + 0.55)
    ax.set_xlabel("Sharpe (excess over T-bills), Nov 2017 – Nov 2026")
    ax.grid(axis="y", visible=False)
    ax.set_title("ILLUSTRATIVE: rules on 11 hand-picked tech winners (survivorship-biased) — compare rules, not levels",
                 loc="left", fontsize=11.5)
    savefig(fig, "fig_top10_local.png")


if __name__ == "__main__":
    main()
