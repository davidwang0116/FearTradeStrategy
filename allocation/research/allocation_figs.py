"""Figures for the allocation study (reads allocation/results/allocation_*.csv, writes allocation/figures/)."""
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

import allocation_paths  # noqa: F401  (puts the shared research/ on sys.path)
from allocation_paths import FIGURES, RESULTS
from common import AQUA, GRID, INK, INK2, MUTED, ORANGE, BLUE, SEQ5, SURF, plt


def savefig(fig, name):
    fig.savefig(FIGURES / name, dpi=200, bbox_inches="tight")
    plt.close(fig)


ST = pd.read_csv(RESULTS / "allocation_static.csv"); ST = ST[ST.kind == "static monthly"]
SA = pd.read_csv(RESULTS / "allocation_strategy.csv")
V2 = SA[SA.name == "frozen v2"].iloc[0]
EQ, MX = (0.70, 0.75, 0.80), (0.0, 0.5, 0.7, 0.8, 1.0)
XL = ["100% SPY", "50/50", "70/30", "80/20", "100% QQQ"]
CAVEAT = ("SPY caveat: panel SPY understates both total return (2013–22: 10.8%/yr vs 12.4% published) and volatility (2022: −16.0% vs −18.2%), so cells with SPY are distorted.\n"
          "Any preferred QQQ weight is provisional until re-run on verified SPY total returns. 2007-02 → 2026-09; the sample starts after the dot-com crash.")
SEQ = LinearSegmentedColormap.from_list("seq", ["#eef4fc", "#b7d1f4", SEQ5[0]])


def cell(df, e, q, col):
    r = df[np.isclose(df.equity, e) & np.isclose(df.qqq_share, q)]
    return r[col].iloc[0] if len(r) else np.nan


# ---------------- grid ----------------
rows = [("Static, monthly rebalanced", ST, EQ), ("Strategy, scaled ladder", SA[SA.ladder == "scaled"], EQ),
        ("Fixed ladder\n(70% = scaled)", SA[SA.ladder == "fixed"], EQ[1:])]
cols = [("Sharpe", "Sharpe (over T-bills)", "{:.2f}"), ("CAGR", "CAGR", "{:.1%}"), ("MaxDD", "Max drawdown (darker = shallower)", "{:.0%}")]
fig, axes = plt.subplots(3, 3, figsize=(15, 8.4), gridspec_kw={"height_ratios": [3, 3, 2]})
for j, (col, title, fmt) in enumerate(cols):
    allv = np.concatenate([[cell(d, e, q, col) for e in es for q in MX] for _, d, es in rows])
    for i, (lab, d, es) in enumerate(rows):
        ax = axes[i, j]
        M = np.array([[cell(d, e, q, col) for q in MX] for e in es])
        ax.pcolormesh(M, cmap=SEQ, vmin=allv.min(), vmax=allv.max(), edgecolor=SURF, lw=2.5)
        for a in range(len(es)):
            for b in range(len(MX)):
                ax.text(b + .5, a + .5, fmt.format(M[a, b]).replace("-", "−"), ha="center", va="center", fontsize=11, color=INK)
        ax.set_xticks(np.arange(5) + .5, XL, fontsize=9.5); ax.set_yticks(np.arange(len(es)) + .5, [f"{e:.0%}" for e in es])
        ax.invert_yaxis(); ax.grid(False); ax.tick_params(length=0)
        for s in ax.spines.values():
            s.set_visible(False)
        if i == 0:
            ax.set_title(title, loc="left")
        if j == 0:
            ax.set_ylabel(lab + "\nequity share")
        if i == 2:
            ax.set_xlabel("core mix (QQQ/SPY)")
fig.suptitle("More QQQ looks better in this sample; more equity costs the static mix drawdown but not the trend-guarded strategy",
             x=0.01, ha="left", fontsize=13.5, fontweight="bold")
fig.text(0.01, -0.005, CAVEAT + "\nThe 100% SPY core still buys QLD (2x Nasdaq) and follows QQQ signals. Frozen v2 (QQQ trend half, drifting weights): "
         f"Sharpe {V2.Sharpe:.2f}, CAGR {V2.CAGR:.1%}, max drawdown −{abs(V2.MaxDD):.0%}.", fontsize=9.5, color=INK2, va="top")
fig.tight_layout(rect=(0, 0.01, 1, 0.97))
savefig(fig, "fig_allocation_grid.png")

# ---------------- CAGR vs max drawdown ----------------
fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True, sharex=True)
for ax, (lab, d) in zip(axes, [("Static, monthly rebalanced", ST), ("Strategy, scaled ladder", SA[SA.ladder == "scaled"])]):
    for q, xl, col in zip(MX, XL, SEQ5):
        x = [-cell(d, e, q, "MaxDD") * 100 for e in EQ]; y = [cell(d, e, q, "CAGR") * 100 for e in EQ]
        ax.plot(x, y, color=col, lw=2, zorder=2)
        ax.scatter(x, y, s=[38, 62, 92], color=col, edgecolor=SURF, lw=1.2, zorder=3)
        if lab.startswith("Static"):
            ax.text(x[-1] + .25, y[-1], xl, fontsize=9.5, color=INK, va="center")
        else:
            ax.text(x[0] + .3, y[0], xl, fontsize=9.5, color=INK, va="center")
    ax.scatter(-V2.MaxDD * 100, V2.CAGR * 100, marker="D", s=70, color=ORANGE, edgecolor=SURF, lw=1.2, zorder=4)
    left = lab.startswith("Static")
    ax.annotate("frozen v2", (-V2.MaxDD * 100, V2.CAGR * 100), xytext=(-10 if left else 12, 0), textcoords="offset points", fontsize=9.5,
                color=INK, ha="right" if left else "left", va="center")
    ax.set_title(lab, loc="left"); ax.set_xlabel("Max drawdown (%, smaller is better)")
axes[0].set_ylabel("CAGR (%)"); axes[0].set_xlim(36.5, 47.5)
axes[1].text(0.98, 0.03, "marker size = equity share:\nsmall 70%, medium 75%, large 80%", transform=axes[1].transAxes, ha="right", fontsize=9.5, color=INK2)
fig.suptitle("Static mixes trade drawdown for return; the strategy's is set by 2007–09, with the reserve already spent",
             x=0.01, ha="left", fontsize=13, fontweight="bold")
fig.text(0.01, -0.01, CAVEAT + "\nWithout the trend guard the strategy's drawdown deepens with equity too (results/allocation_drawdown_check.csv): "
         "the shallower drawdowns come from one episode.", fontsize=9.5, color=INK2, va="top")
fig.tight_layout(rect=(0, 0.01, 1, 0.97))
savefig(fig, "fig_allocation_risk_return.png")

# ---------------- the 45 tests ----------------
fig, axes = plt.subplots(1, 2, figsize=(15, 8.6), sharex=True)
for ax, f, title in [(axes[0], "mix", "QQQ mix vs 50/50, same equity and ladder (20 tests)"), (axes[1], "v3", "Candidate vs frozen v2 (25 tests)")]:
    T = pd.read_csv(RESULTS / f"allocation_{f}_tests.csv")
    y = np.arange(len(T))[::-1].astype(float)
    grp = T.ladder + T.equity.astype(str)
    y -= 0.6 * (grp != grp.shift()).cumsum().to_numpy()
    ax.axvline(0, color=INK2, lw=1)
    for k, r in enumerate(T.itertuples()):
        ax.plot([r.lb_simultaneous, r.diff], [y[k]] * 2, color=SEQ5[0], lw=2, zorder=2)
        ax.plot([r.lb_simultaneous] * 2, [y[k] - .22, y[k] + .22], color=SEQ5[0], lw=2, zorder=2)
        ax.plot([r.lb_unadjusted] * 2, [y[k] - .22, y[k] + .22], color=MUTED, lw=1.4, zorder=2)
    ax.scatter(T["diff"], y, s=48, color=BLUE, edgecolor=SURF, lw=1, zorder=3)
    ax.set_yticks(y, [f"{r.equity:.0%} {r.ladder} · {XL[MX.index(r.qqq_share)]}" for r in T.itertuples()], fontsize=9)
    ax.set_title(title, loc="left"); ax.grid(axis="y", visible=False); ax.set_xlabel("Sharpe difference")
h = [plt.Line2D([], [], color=BLUE, marker="o", ls="", ms=7), plt.Line2D([], [], color=SEQ5[0], lw=2, marker="|", ms=9),
     plt.Line2D([], [], color=MUTED, lw=0, marker="|", ms=9, mew=1.4)]
fig.legend(h, ["observed difference", "simultaneous lower bound (decides; 5% family-wise, 45 tests)", "unadjusted lower bound (does not decide)"],
           loc="upper left", bbox_to_anchor=(0.005, 0.965), ncol=3, fontsize=10)
fig.suptitle("No mix and no v3 candidate clears the pre-set rule: every simultaneous lower bound is below zero", x=0.01, ha="left", fontsize=13.5,
             fontweight="bold")
fig.text(0.01, -0.005, CAVEAT, fontsize=9.5, color=INK2, va="top")
fig.tight_layout(rect=(0, 0.01, 1, 0.94))
savefig(fig, "fig_allocation_tests.png")
