"""Figures for the 12-month put hedge (reads results/options_*.csv written by research/options_overlay.py).

fig_options_frontier.png   CAGR vs max drawdown: every hedged cell against v2 scaled with T-bills (the cash
                           control), full window and the 2012-2026 window QC can check on real quotes
fig_options_episodes.png   drawdown in each of v2's seven declines, v2 vs two hedged cells
fig_options_sales.png      when the hedge was sold, against QQQ's drawdown, and how much further QQQ fell
"""
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

import _paths  # noqa: F401  (puts the repo's research/ on sys.path)
from _paths import RESULTS as RES, savefig
from common import AQUA, BLUE, INK, INK2, MUTED, ORANGE, SURF, build_signals, load_panel, perf_stats, plt
from options_overlay import A_, B_, QC_A, V2, run, scaled
from strategy import prepare

EXIT_COL = {"fear": BLUE, "rolldown": ORANGE, "hold": AQUA}
EXIT_LAB = {"fear": "Sell at fear peak", "rolldown": "Roll down at delta −0.6", "hold": "Hold to expiry"}
COVER_MK = {"all": "o", "unguarded": "s"}

P = load_panel()
rf = P["rf"]
D = prepare(P, build_signals(P))
T = pd.read_csv(RES / "options_trials.csv")
E = pd.read_csv(RES / "options_episodes.csv")
M = pd.read_csv(RES / "options_monetizations.csv", parse_dates=["date"])
base, *_ = run(D, V2)
c = T[T.pricing == "central"]

# ---------------------------------------------------------------- frontier
fig, axes = plt.subplots(1, 2, figsize=(15, 6.2))
for ax, (a, sfx, title) in zip(axes, [(A_, "", "Full window 2007–2026 (2008 is model-priced)"),
                                       (QC_A, "_1226", "2012–2026 (the window QC can check on real quotes)")]):
    bn = base["nav"].loc[a:B_]
    line = np.array([(-perf_stats(scaled(bn, rf, k), rf)["MaxDD"] * 100, perf_stats(scaled(bn, rf, k), rf)["CAGR"] * 100)
                     for k in np.linspace(0.3, 1.0, 15)])
    ax.plot(line[:, 0], line[:, 1], color=MUTED, lw=2, label="v2 + T-bills (cash control), 30% → 100% invested")
    s0 = perf_stats(bn, rf)
    ax.scatter(-s0["MaxDD"] * 100, s0["CAGR"] * 100, s=90, color=INK, zorder=4, edgecolor=SURF, linewidth=1.5)
    ax.annotate(f"v2 unhedged  {s0['CAGR']:.1%} / −{-s0['MaxDD']:.0%}", (-s0["MaxDD"] * 100, s0["CAGR"] * 100),
                xytext=(-8, 10), textcoords="offset points", ha="right", fontsize=9.5, color=INK)
    for _, rw in c.iterrows():
        x, y = -rw["MaxDD" + sfx] * 100, rw["CAGR" + sfx] * 100
        filled = rw.proceeds == "tranche"
        ax.scatter(x, y, s=70, marker=COVER_MK[rw.cover], zorder=3, linewidth=2,
                   facecolor=EXIT_COL[rw.exit] if filled else SURF, edgecolor=EXIT_COL[rw.exit])
    for (cv, ex), g in c.groupby(["cover", "exit"]):
        g = g.set_index("proceeds")
        ax.plot([-g.loc["tbill", "MaxDD" + sfx] * 100, -g.loc["tranche", "MaxDD" + sfx] * 100],
                [g.loc["tbill", "CAGR" + sfx] * 100, g.loc["tranche", "CAGR" + sfx] * 100],
                color=EXIT_COL[ex], lw=1, alpha=0.6, zorder=2)
    best = c[(c.cover == "unguarded") & (c.exit == "hold") & (c.proceeds == "tranche")].iloc[0]
    bx, by = -best["MaxDD" + sfx] * 100, best["CAGR" + sfx] * 100
    ax.annotate(f"core-only put, hold to expiry:\n{best['CAGR' + sfx]:.1%} CAGR, −{-best['MaxDD' + sfx]:.0%} max DD",
                (bx, by), xytext=(bx - 7, by + 0.9), textcoords="data", fontsize=9.5, color=INK, ha="right",
                arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8, shrinkB=6))
    ax.set_title(title, loc="left", fontsize=11.5)
    ax.set_xlabel("Maximum drawdown (%, smaller is better)")
    ax.set_ylabel("CAGR (%)")
handles = [Line2D([], [], color=MUTED, lw=2, label="v2 + T-bills (cash control)"),
           Line2D([], [], marker="o", ls="", color=INK, markersize=8, label="v2 unhedged")]
handles += [Line2D([], [], marker="o", ls="", markerfacecolor=col, markeredgecolor=col, markersize=8, label=EXIT_LAB[k])
            for k, col in EXIT_COL.items()]
handles += [Line2D([], [], marker="o", ls="", markerfacecolor=INK2, markeredgecolor=INK2, markersize=8, label="Put on all equity"),
            Line2D([], [], marker="s", ls="", markerfacecolor=INK2, markeredgecolor=INK2, markersize=8, label="Put on core only (not the trend half)"),
            Line2D([], [], marker="o", ls="", markerfacecolor=INK2, markeredgecolor=INK2, markersize=8, label="Filled: proceeds fund tranches"),
            Line2D([], [], marker="o", ls="", markerfacecolor=SURF, markeredgecolor=INK2, markeredgewidth=2, markersize=8,
                   label="Hollow: proceeds kept in T-bills")]
fig.legend(handles=handles, loc="lower center", ncol=5, fontsize=9.2, bbox_to_anchor=(0.5, -0.08))
fig.suptitle("A 12-month 85% put beats holding less equity at the same drawdown — but buys risk reduction, not higher CAGR\n"
             "Provisional model pricing from VXN; points above the grey line earn more for the same worst fall",
             x=0.01, ha="left", fontsize=12.5, fontweight="bold", color=INK)
fig.tight_layout(rect=(0, 0.04, 1, 0.93))
savefig(fig, "fig_options_frontier.png")

# ---------------------------------------------------------------- episodes
ec = E[E.pricing == "central"]
cells = [("v2 unhedged", None, MUTED), ("Core-only put, hold to expiry", "unguarded · hold · tranche", AQUA),
         ("All-equity put, sell at fear peak, T-bills", "all · fear · tbill", BLUE)]
peaks = ec.peak.unique()
labels = [f"{pd.Timestamp(p):%b %Y}" for p in peaks]
fig, ax = plt.subplots(figsize=(13, 5.4))
w = 0.26
for j, (lab, cell, col) in enumerate(cells):
    vals = [ec[ec.peak == p].dd_v2.iloc[0] if cell is None else ec[(ec.peak == p) & (ec.cell == cell)].dd_cell.iloc[0]
            for p in peaks]
    xs = np.arange(len(peaks)) + (j - 1) * w
    ax.bar(xs, np.array(vals) * 100, width=w - 0.03, color=col, label=lab)
    if j < 2:
        for x, v in zip(xs, vals):
            ax.text(x, v * 100 - 0.6, f"{v:.0%}", ha="center", va="top", fontsize=8.5, color=INK2)
ax.set_xticks(np.arange(len(peaks)), [f"from {l}" for l in labels])
ax.axhline(0, color=INK2, lw=0.8)
ax.set_ylabel("Drawdown within v2's decline (%)")
ax.set_ylim(-45, 2)
ax.grid(axis="x", visible=False)
ax.legend(loc="lower right", fontsize=9.5)
ax.set_title("The put helps in every decline, most in 2008, 2020 and 2022 (provisional model pricing; 2008 can't be checked on real quotes)",
             loc="left", fontsize=11.5)
fig.tight_layout()
savefig(fig, "fig_options_episodes.png")

# ---------------------------------------------------------------- sales timeline
q = D["qqq"].loc[A_:B_]
qdd = q / q.cummax() - 1
fig, ax = plt.subplots(figsize=(13, 5.2))
ax.fill_between(qdd.index, qdd * 100, 0, color=MUTED, alpha=0.25, lw=0)
ax.plot(qdd.index, qdd * 100, color=INK2, lw=1)
mc = M[(M.pricing == "central") & (M.cell.isin(["all · fear · tranche", "all · rolldown · tranche"]))]
for ev, col, lab in [("fear exit", BLUE, "Sold at fear peak (p ≥ 90th, VXN receding)"),
                     ("roll-down", ORANGE, "Rolled down at delta −0.6")]:
    g = mc[mc.event == ev]
    ax.scatter(g.date, g.qqq_dd_at_sale * 100, s=70, color=col, zorder=3, edgecolor=SURF, linewidth=1.5, label=lab)
    for _, rw in g.iterrows():
        if rw.qqq_further_fall < -0.03:
            ax.annotate(f"then {rw.qqq_further_fall:.0%}", (rw.date, rw.qqq_dd_at_sale * 100), xytext=(6, -14),
                        textcoords="offset points", fontsize=9, color=INK)
ax.set_ylabel("QQQ below its prior high (%)")
ax.legend(loc="lower right", fontsize=9.5)
ax.set_title("The fear-peak exit is a trading signal, not a bottom: in 2008 and 2022 QQQ fell another 16–19% after the sale",
             loc="left", fontsize=11.5)
fig.tight_layout()
savefig(fig, "fig_options_sales.png")
print("figures written")
