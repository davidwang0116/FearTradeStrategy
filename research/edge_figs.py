"""Two headline charts: trading edge and DCA edge per indicator (from edge_study.py)."""
import numpy as np
import pandas as pd

from common import BLUE, GRID, INK, INK2, MUTED, ORANGE, RES, SEQ5, plt, savefig

T = pd.read_csv(RES / "edge_trading.csv")
D = pd.read_csv(RES / "edge_dca.csv")
C = pd.read_csv(RES / "edge_cape.csv")
SIG = SEQ5[3]
NS = "#b9cbe3"

SHORT = {"VIX level": "VIX", "VIX spike vs 20d avg": "VIX spike", "VXN level": "VXN (2008+)",
         "CNN Fear & Greed": "CNN Fear & Greed (2011–23)", "QQQ drawdown from 1y high": "QQQ drawdown",
         "QQQ below 200-day MA": "QQQ vs 200-day MA", "RSI(14) oversold": "RSI(14)",
         "Price-sentiment proxy": "Price-sentiment proxy", "Variance risk premium (pct)": "Variance risk premium (2010+)",
         "Dashboard composite (pct)": "Dashboard composite"}


def label_of(r):
    return f"{SHORT.get(r.name, r.name)}\n{r.param}"


# ---------------- (1) trading edge ----------------
full = T[T["sample"] == "full"].set_index("indicator")
five = T[T["sample"] == "5y"].set_index("indicator")
cb = C[C.episodes >= 8].sort_values("edge_12m").iloc[-1]
rows = []
for ind, r in full.iterrows():
    f5 = five.loc[ind] if ind in five.index else None
    rows.append(dict(label=label_of(r), edge=r.edge_252 * 100, p=r.p_shift, ep=int(r.episodes),
                     trig=r.mean_trig_252 * 100, base=r.mean_all_252 * 100,
                     e5=(f5.edge_252 * 100 if f5 is not None and f5.trig_days > 0 else np.nan),
                     ep5=(int(f5.episodes) if f5 is not None and not np.isnan(f5.episodes) else 0)))
rows.append(dict(label=f"Shiller CAPE (S&P 500, 1891–2022)\n{cb.param}", edge=cb.edge_12m * 100, p=cb.p_shift,
                 ep=int(cb.episodes), trig=np.nan, base=np.nan, e5=np.nan, ep5=0))
R = pd.DataFrame(rows).sort_values("edge")
fig, ax = plt.subplots(figsize=(13, 7.6))
y = np.arange(len(R))
ax.barh(y, R.edge, color=[SIG if p < 0.05 else NS for p in R.p], height=0.62)
ax.scatter(R.e5, y, marker="D", s=46, color=ORANGE, zorder=3, label="Same rule, last 5 years (2021-11 → 2025-11 entries)")
for yy, (_, r) in zip(y, R.iterrows()):
    x = np.nanmax([r.edge, 0, r.e5]) + 2.0
    tail = f"   ({r.trig:.0f}% vs {r.base:.0f}% any day)" if not np.isnan(r.trig) else "   (S&P real, 12-month)"
    ax.text(x, yy, f"{r.edge:+.1f} pp · p={r.p:.3f} · {r.ep} episodes{tail}",
            va="center", fontsize=9.5, color=INK2)
ax.set_yticks(y, R.label, fontsize=9.5)
ax.axvline(0, color=INK2, lw=0.9)
ax.set_xlim(min(-12, R.edge.min() - 3, np.nanmin(R.e5) - 3), 82)
ax.set_xlabel("Next-1-year QQQ return when bought on trigger days MINUS when bought on any day (percentage points)")
ax.grid(axis="y", visible=False)
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
ax.legend(handles=[Patch(color=SIG, label="significant (circular-shift p < 0.05)"), Patch(color=NS, label="not significant"),
                   Line2D([], [], marker="D", color=ORANGE, lw=0, label="same rule, last 5 years")],
          loc="lower right", fontsize=9.5)
ax.set_title("Trading edge: only extreme volatility triggers beat buying on a random day (QQQ, longest history)",
             loc="left", fontsize=12.5)
savefig(fig, "fig_edge_trading.png")

# ---------------- (2) DCA edge ----------------
fullD = D[D["sample"] == "full"].set_index("indicator")
fiveD = D[D["sample"] == "5y"].set_index("indicator")
rows = []
for ind, r in fullD.iterrows():
    f5 = fiveD.loc[ind] if ind in fiveD.index else None
    rows.append(dict(label=label_of(r), adv=r.dca_adv * 100, win=r.dca_win, xd=r.xirr_diff * 100, xw=r.xirr_win,
                     p=r.p_shift, share=r.trig_share, n=int(r.n_windows),
                     a5=(f5.dca_adv * 100 if f5 is not None and not np.isnan(f5.dca_adv) else np.nan)))
cbd = C.sort_values("dca_adv").iloc[-1]
rows.append(dict(label=f"Shiller CAPE (S&P 500, 1891–2022)\n{cbd.param}", adv=cbd.dca_adv * 100, win=cbd.dca_win,
                 xd=np.nan, xw=np.nan, p=np.nan, share=cbd.trig_share, n=0, a5=np.nan))
R = pd.DataFrame(rows).sort_values("adv")
fig, ax = plt.subplots(figsize=(13, 7.6))
y = np.arange(len(R))
ax.barh(y, R.adv, color=[SIG if (p < 0.05) else NS for p in R.p.fillna(1)], height=0.62)
ax.scatter(R.a5, y, marker="D", s=46, color=ORANGE, zorder=3)
for yy, (_, r) in zip(y, R.iterrows()):
    xirr = f" · XIRR {r.xd:+.2f} pp" if not np.isnan(r.xd) else " · 60-month plans"
    ax.text(np.nanmax([r.adv, 0, r.a5]) + 0.3, yy,
            f"{r.adv:+.1f}% · beats even DCA in {r.win:.0%} of plans{xirr} · 2x on {r.share:.0%} of {'months' if np.isnan(r.xd) else 'days'}",
            va="center", fontsize=9.5, color=INK2)
ax.set_yticks(y, R.label, fontsize=9.5)
ax.axvline(0, color=INK2, lw=0.9)
ax.set_xlim(-1.5, 12.5)
ax.set_xlabel("Extra terminal wealth vs spreading the same money evenly (%, = lower average cost) — mean over rolling 5-year DCA plans")
ax.grid(axis="y", visible=False)
ax.legend(handles=[Patch(color=SIG, label="significant (circular-shift p < 0.05)"), Patch(color=NS, label="not significant"),
                   Line2D([], [], marker="D", color=ORANGE, lw=0, label="the one 5-year plan Nov 2021 → Nov 2026")],
          loc="lower right", fontsize=9.5)
ax.set_title("DCA edge: doubling contributions on fear days buys 1–2% more QQQ per dollar — and 4–6% in the last 5 years",
             loc="left", fontsize=12.5)
savefig(fig, "fig_edge_dca.png")
print("ok")
