"""Figures for the strategy section + leverage-instrument comparison (QLD vs LEAPS)."""
import numpy as np
import pandas as pd
from scipy.stats import norm

from common import (AQUA, BLUE, GRID, INK, INK2, MUTED, ORANGE, RES, SEQ5, VIOLET, YELLOW, plt, savefig)

curves, allocs = pd.read_pickle(RES / "strategy_curves.pkl")
T = pd.read_csv(RES / "strategy_variants.csv")

# ---------------- equity + drawdown, test B ----------------
tb = "B: QQQ+SPY core, 2007-02 → 2026-09"
show = [("Buy & hold 50/50 QQQ+SPY", MUTED, "--"), ("Static 70/30 QQQ/T-bill", AQUA, "-"),
        ("v2 + QLD + trend guard", BLUE, "-"), ("Buy & hold QQQ", ORANGE, ":")]
fig, (ax, ax2) = plt.subplots(2, 1, figsize=(12, 7.2), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]})
for name, col, ls in show:
    nav = curves[(tb, name)]
    row = T[(T.test == tb) & (T.strategy == name)].iloc[0]
    ax.plot(nav.index, nav / 1000, color=col, ls=ls, lw=2 if col == BLUE else 1.5,
            label=f"{name}  (Sharpe {row.Sharpe:.2f}, CAGR {row.CAGR:.1%}, MaxDD {row.MaxDD:.0%})")
    ax2.plot(nav.index, (nav / nav.cummax() - 1) * 100, color=col, ls=ls, lw=1.6 if col == BLUE else 1.1)
ax.set_yscale("log")
from matplotlib.ticker import FixedLocator, FuncFormatter
ax.yaxis.set_major_locator(FixedLocator([100, 200, 400, 800, 1600]))
ax.yaxis.set_minor_locator(FixedLocator([]))
ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:.0f}k"))
ax.set_ylabel("Portfolio value, $100k start (log)")
ax.legend(loc="upper left", fontsize=9.5)
ax.set_title("Fixed $100k, 2007–2026: fear tranches + QLD sleeve + trend guard cut the drawdown by a quarter", loc="left")
ax2.set_ylabel("Drawdown (%)")
fig.tight_layout()
savefig(fig, "fig_strategy_equity.png")

# ---------------- allocation over time ----------------
res = allocs[(tb, "v2 + QLD + trend guard")]
fig, ax = plt.subplots(figsize=(12, 3.8))
x = res.index
core_tot = res["core"] + res["trend"]
ax.stackplot(x, res["core"] * 100, res["trend"] * 100, res["lev"] * 100, res["cash"] * 100,
             colors=[SEQ5[3], SEQ5[1], ORANGE, "#e6e5e0"], labels=["Core (fear-tranched)", "Core (trend-guarded half)",
                                                              "QLD sleeve", "T-bills / dry powder"], lw=0)
ax.plot(x, res["expo"] * 100, color=INK, lw=1, label="Net equity exposure (QLD counted 2x)")
ax.set_ylim(0, 140)
ax.set_ylabel("% of NAV")
ax.legend(loc="upper left", ncol=5, fontsize=9)
ax.set_title("Where the money is: powder is spent into fear (2008–09, 2020, 2022) and rebuilt in greed", loc="left")
savefig(fig, "fig_strategy_alloc.png")

# ---------------- variant table chart (trial log) ----------------
fig, axes = plt.subplots(1, 2, figsize=(15, 5.6))
for ax, (tn, sub) in zip(axes, T.groupby("test", sort=False)):
    sub = sub.reset_index(drop=True)
    y = np.arange(len(sub))[::-1]
    cols = [MUTED if s.startswith("Buy") or s.startswith("Static") else (BLUE if s.startswith("v2") else SEQ5[0])
            for s in sub.strategy]
    ax.barh(y, sub.Sharpe, color=cols, height=0.62)
    for yy, (_, r) in zip(y, sub.iterrows()):
        ax.text(r.Sharpe + 0.01, yy, f"{r.Sharpe:.2f}  |  DD {r.MaxDD:.0%}", va="center", fontsize=9, color=INK2)
    ax.set_yticks(y, sub.strategy)
    ax.set_title(tn, loc="left", fontsize=11)
    ax.set_xlim(0, 0.95)
    ax.grid(axis="y", visible=False)
fig.suptitle("Every variant we ran (excess-return Sharpe over T-bills, costs included) — none is above 1 yet",
             x=0.01, ha="left", fontsize=13, fontweight="bold")
fig.tight_layout()
savefig(fig, "fig_trial_log.png")

# ---------------- leverage instruments: QLD vs margin vs LEAPS ----------------
def bs_call(S, K, T, r, s):
    d1 = (np.log(S / K) + (r + 0.5 * s * s) * T) / (s * np.sqrt(T))
    return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d1 - s * np.sqrt(T))

r, iv = 0.04, 0.22
S0, K, T0 = 100.0, 90.0, 2.0          # ITM ~0.75-delta LEAPS, 2y, sold after 1y
prem = bs_call(S0, K, T0, r, iv)
delta = norm.cdf((np.log(S0 / K) + (r + 0.5 * iv * iv) * T0) / (iv * np.sqrt(T0)))
eff_lev = delta * S0 / prem
R = np.linspace(-0.5, 0.6, 221)
fig, ax = plt.subplots(figsize=(10, 5.6))
ax.plot(R * 100, R * 100, color=MUTED, lw=1.5, ls="--", label="QQQ (1x)")
# margin 2x: borrow 1x at r+1.5%
ax.plot(R * 100, (2 * R - (r + 0.015)) * 100, color=VIOLET, lw=1.6, label="2x on margin (borrow at T-bill+1.5%)")
for vol, col, lab in [(0.20, BLUE, "QLD 2x daily-reset, path vol 20%"), (0.40, AQUA, "QLD 2x daily-reset, path vol 40%")]:
    # E[ln] approx: daily-reset 2x terminal multiple = (1+R)^2 * exp(-vol^2) less financing & fee
    q = (1 + R) ** 2 * np.exp(-vol ** 2 - (r + 0.006) - 0.0095) - 1
    ax.plot(R * 100, q * 100, color=col, lw=2, label=lab)
S1 = S0 * (1 + R)
leaps_val = bs_call(S1, K, T0 - 1, r, iv)
# size LEAPS so that $ delta exposure = 2x the capital (capital = 2 x premium-delta units → hold cash remainder)
units = 2 * S0 / (delta * S0)             # contracts' underlying units for 2x delta exposure on $100 capital
cost = units * prem
cash = S0 - cost
leaps_ret = (units * leaps_val + cash * (1 + r)) / S0 - 1
ax.plot(R * 100, leaps_ret * 100, color=ORANGE, lw=2.4,
        label=f"LEAPS call K=90% spot, 2y (Δ≈{delta:.2f}), sized to 2x delta, rest in T-bills")
ax.axhline(0, color=INK2, lw=0.8); ax.axvline(0, color=INK2, lw=0.8)
ax.axhline(-100, color=MUTED, lw=0.8, ls=":")
ax.set_xlabel("QQQ 1-year return (%)")
ax.set_ylabel("Return on capital after 1 year (%)")
ax.set_ylim(-110, 130)
ax.legend(loc="upper left", fontsize=9)
ax.set_title("Same 2x starting exposure, different crash behaviour: LEAPS cap the loss, QLD bleeds in chop", loc="left")
ax.text(0.99, 0.03, f"BSM, IV {iv:.0%}, r {r:.0%}; LEAPS uses {cost:.0f}% of capital, {cash:.0f}% stays in T-bills.\n"
        "Illustrative pricing — QC option-chain backtest is a teammate task.", transform=ax.transAxes,
        ha="right", fontsize=8.5, color=INK2)
savefig(fig, "fig_leverage_instruments.png")
print(f"LEAPS premium {prem:.2f} ({prem/S0:.1%} of spot), delta {delta:.2f}, eff. leverage per contract {eff_lev:.2f}x, "
      f"capital used for 2x: {cost:.1f}%")
for q in [-0.4, -0.2, 0, 0.2, 0.4]:
    i = np.argmin(abs(R - q))
    print(q, "LEAPS", round(leaps_ret[i], 3), "QLD20", round(((1+R[i])**2*np.exp(-0.04-0.046-0.0095)-1), 3),
          "margin", round(2*R[i]-0.055, 3))
