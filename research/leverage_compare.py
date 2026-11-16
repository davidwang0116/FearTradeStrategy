"""Leverage sleeve: QLD (2x) vs TQQQ (3x) under the same fear-timed rules, fixed $100k, 2007-2026.

Rules = research/strategy.py ("v2": 7.5% tranches every further -8%, leverage sleeve cap 30%,
trend guard on half the core). Only the leverage instrument / sizing changes:
  QLD            10% of NAV per leverage buy, cap 30%
  TQQQ           10% of NAV per buy, cap 30%  (same dollars, more exposure)
  TQQQ matched   6.67% per buy, cap 20%       (same 2x-equivalent exposure as QLD)
Outputs: results/leverage_compare.csv, figures/fig_strategy_equity_lev.png
"""
from dataclasses import replace

import numpy as np
import pandas as pd
from matplotlib.ticker import FixedLocator, FuncFormatter

from common import AQUA, BLUE, INK2, MUTED, ORANGE, RES, VIOLET, build_signals, load_panel, perf_stats, plt, savefig
from strategy import Cfg, bh, prepare, run

P = load_panel()
D = prepare(P, build_signals(P))
D["r_cash"] = 0.0
rf = P["rf"]
A, B = "2007-02-01", "2026-09-11"
core = (("qqq", 0.5), ("spy", 0.5))
V2 = dict(tranche=0.075, tranche_step=0.92, lev_cap=0.30, core=core, trend_guard=True)
cfgs = {
    "Fear-timed, QLD sleeve (2x)": Cfg("qld", lev="qld", **V2),
    "Fear-timed, TQQQ sleeve (3x)": Cfg("tqqq", lev="tqqq", **V2),
    "Fear-timed, TQQQ exposure-matched": Cfg("tqqq_m", lev="tqqq", **{**V2, "lev_size": 0.0667, "lev_cap": 0.20}),
    "Static 70/30, no timing": Cfg("static", fear_off=True, core=core),
}
navs, rows = {}, []
navs["Buy-and-hold 50/50 QQQ + SPY"] = bh(D, {"qqq": 0.5, "spy": 0.5}, A, B)
navs["Buy-and-hold QQQ"] = bh(D, {"qqq": 1.0}, A, B)
expo = {}
for k, c in cfgs.items():
    r, tr = run(D, c, A, B)
    navs[k] = r["nav"]
    expo[k] = (r["expo"].mean(), r["expo"].max(), len(tr))
for k, nav in navs.items():
    st = perf_stats(nav, rf)
    e = expo.get(k, (1.0, 1.0, 0))
    rows.append(dict(portfolio=k, **st, avg_expo=e[0], peak_expo=e[1], trades=e[2]))
T = pd.DataFrame(rows)
T.to_csv(RES / "leverage_compare.csv", index=False)
print(T[["portfolio", "Sharpe", "CAGR", "Vol", "MaxDD", "avg_expo", "peak_expo", "trades"]].round(3).to_string())

show = [("Buy-and-hold 50/50 QQQ + SPY", MUTED, "--", 1.4), ("Static 70/30, no timing", AQUA, "-", 1.5),
        ("Fear-timed, QLD sleeve (2x)", BLUE, "-", 2.0), ("Fear-timed, TQQQ sleeve (3x)", ORANGE, "-", 1.6),
        ("Buy-and-hold QQQ", VIOLET, ":", 1.4)]
fig, (ax, ax2) = plt.subplots(2, 1, figsize=(12, 7.2), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]})
for name, col, ls, lw in show:
    nav = navs[name]
    st = T[T.portfolio == name].iloc[0]
    ax.plot(nav.index, nav / 1000, color=col, ls=ls, lw=lw,
            label=f"{name}  (Sharpe {st.Sharpe:.2f}, CAGR {st.CAGR:.1%}, MaxDD {st.MaxDD:.0%})")
    ax2.plot(nav.index, (nav / nav.cummax() - 1) * 100, color=col, ls=ls, lw=lw * 0.75)
ax.set_yscale("log")
ax.yaxis.set_major_locator(FixedLocator([100, 200, 400, 800, 1600]))
ax.yaxis.set_minor_locator(FixedLocator([]))
ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:.0f}k"))
ax.set_ylabel("Portfolio value, $100k start (log)")
ax.legend(loc="upper left", fontsize=9.5)
ax.set_title("Fixed $100k, 2007–2026: QLD and TQQQ sleeves land on top of each other, and close to a static 70/30", loc="left")
ax2.set_ylabel("Drawdown (%)")
fig.tight_layout()
savefig(fig, "fig_strategy_equity_lev.png")
