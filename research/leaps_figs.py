"""Heatmaps of Sharpe across LEAPS delta x DTE, against the ETF baselines."""
import numpy as np
import pandas as pd
from matplotlib.colors import TwoSlopeNorm, LinearSegmentedColormap

from common import INK, INK2, RES, plt, savefig

G = pd.read_csv(RES / "leaps_grid.csv")
base = {"A: fear sleeve, exposure-matched": (0.707, "QLD sleeve 0.71"),
        "B: fear sleeve, dollars-matched": (0.707, "QLD sleeve 0.71"),
        "C: static 70/30, QQQ leg as LEAPS": (pd.read_csv(RES / "leaps_baselines.csv").Sharpe.iloc[0], "ETF 35/35/30 0.64")}
titles = {"A: fear sleeve, exposure-matched": "A · Fear sleeve as LEAPS\n(same 2x exposure as QLD)",
          "B: fear sleeve, dollars-matched": "B · Fear sleeve as LEAPS\n(same dollars as QLD)",
          "C: static 70/30, QQQ leg as LEAPS": "C · QQQ part of the core as LEAPS\n(static 35% QQQ / 35% SPY / 30% T-bills)"}
cmap = LinearSegmentedColormap.from_list("div", ["#eb6834", "#f2f0ea", "#2a78d6"])
fig, axes = plt.subplots(1, 3, figsize=(16, 5.6))
for ax, (t, g) in zip(axes, G.groupby("test", sort=False)):
    M = g.pivot(index="delta", columns="dte", values="Sharpe").sort_index(ascending=False)
    b, lab = base[t]
    norm = TwoSlopeNorm(vcenter=b, vmin=b - 0.12, vmax=b + 0.12)
    ax.imshow(M.values, cmap=cmap, norm=norm, aspect="auto")
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            v = M.values[i, j]
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=11,
                    color=INK, fontweight="bold" if v > b else "normal")
    ax.set_xticks(range(M.shape[1]), [f"{c}d" for c in M.columns])
    ax.set_yticks(range(M.shape[0]), [f"Δ {d:.1f}" for d in M.index])
    ax.set_xlabel("Days to expiry at purchase")
    ax.set_title(titles[t] + f"\nbaseline: {lab}", loc="left", fontsize=11)
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
fig.suptitle("QQQ LEAPS calls do not reliably lift the Sharpe ratio: orange = below the ETF version, blue = above (bold)",
             x=0.01, ha="left", fontsize=13, fontweight="bold")
fig.text(0.01, -0.02, "Model-priced (Black-Scholes, implied vol from VXN with term-structure mean reversion and skew, 1.5% bid/ask per side), "
         "QQQ + SPY 2007–2026, costs included. The blue cells in C (long-dated, Δ ≤ 0.7) come from exposure drifting up "
         "(to about 2x) in the 2020–26 rally — Δ 0.5/730d: Sharpe 0.86 vs 0.72 there, +0.04 before 2020 — and neighbouring cells disagree.", fontsize=9, color=INK2, wrap=True)
fig.tight_layout()
savefig(fig, "fig_leaps_sharpe.png")
print("ok")
