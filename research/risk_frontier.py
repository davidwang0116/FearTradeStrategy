"""Equal-risk evaluation of the fear-timed strategy: CAGR vs max drawdown against 'just hold less' lines.

The strategy's equity is ~75% QQQ / 25% SPY (the trend-guarded half of the core holds QQQ only),
so the fair 'hold less' benchmark is 75/25 QQQ/SPY mixed with T-bills (daily rebalanced).
Outputs: results/risk_metrics.csv, figures/fig_return_vs_drawdown.png
"""
import numpy as np
import pandas as pd
from scipy.optimize import brentq

from common import AQUA, BLUE, INK, INK2, MUTED, ORANGE, RES, SURF, build_signals, load_panel, perf_stats, plt, savefig
from strategy import Cfg, bh, prepare, run

P = load_panel(); D = prepare(P, build_signals(P)); D["r_cash"] = 0.0; rf = P["rf"]
A, B = "2007-02-01", "2026-09-11"; core = (("qqq", .5), ("spy", .5))
V2 = dict(tranche=0.075, tranche_step=0.92, lev_cap=0.30, core=core, trend_guard=True)
d = D.loc[A:B]; rfd = d.rf / 252
mix = lambda wq: wq * d.r_qqq.fillna(0) + (1 - wq) * d.r_spy.fillna(0)
scaled = lambda rr, k: 1e5 * (1 + k * rr + (1 - k) * rfd).cumprod()
mdd = lambda n: (n / n.cummax() - 1).min()

navs = {"Buy-and-hold 50/50": bh(D, {"qqq": .5, "spy": .5}, A, B), "Buy-and-hold QQQ": bh(D, {"qqq": 1.}, A, B),
        "Static 70/30": run(D, Cfg("s", fear_off=True, core=core), A, B)[0]["nav"]}
res_q, _ = run(D, Cfg("q", lev="qld", **V2), A, B)
navs["Fear-timed + QLD"] = res_q["nav"]
navs["Fear-timed + TQQQ"] = run(D, Cfg("t", lev="tqqq", **V2), A, B)[0]["nav"]
strat = navs["Fear-timed + QLD"]
for wq, lab in [(0.5, "50/50"), (0.75, "75/25 QQQ/SPY")]:
    k = brentq(lambda k: mdd(scaled(mix(wq), k)) - mdd(strat), 0.2, 1.0)
    navs[f"{lab} + T-bills, same MaxDD ({k:.2f}x)"] = scaled(mix(wq), k)

rows = []
bmm = navs["Buy-and-hold 50/50"].resample("ME").last().pct_change().dropna()
for k, n in navs.items():
    st = perf_stats(n, rf); dd = n / n.cummax() - 1
    m = n.resample("ME").last().pct_change().dropna()
    rows.append(dict(portfolio=k, CAGR=st["CAGR"], Vol=st["Vol"], Sharpe=st["Sharpe"], Sortino=st["Sortino"],
                     MaxDD=st["MaxDD"], Calmar=st["Calmar"], Ulcer=np.sqrt((dd ** 2).mean()),
                     CVaR5_monthly=m[m <= m.quantile(.05)].mean(), skew_monthly=m.skew(),
                     up_capture=m[bmm > 0].mean() / bmm[bmm > 0].mean(), down_capture=m[bmm < 0].mean() / bmm[bmm < 0].mean()))
T = pd.DataFrame(rows); T.to_csv(RES / "risk_metrics.csv", index=False)
pd.set_option("display.width", 250); print(T.round(3).to_string())

def line(rr):
    out = []
    for k in np.linspace(0.3, 1.0, 15):
        st = perf_stats(scaled(rr, k), rf); out.append((-st["MaxDD"] * 100, st["CAGR"] * 100))
    return np.array(out)

fig, ax = plt.subplots(figsize=(11, 6.4))
for wq, ls, lw, lab in [(0.5, "-", 2.0, "50/50 QQQ+SPY"), (0.75, "-", 2.6, "75/25 QQQ/SPY (the strategy’s own mix)"), (1.0, "--", 1.4, "QQQ")]:
    L = line(mix(wq)); ax.plot(L[:, 0], L[:, 1], color=INK2 if wq == 0.75 else MUTED, ls=ls, lw=lw, label=f"{lab} + T-bills, 30% → 100% invested")
lab_pos = {"Buy-and-hold 50/50": (52.2, 13.3, "left"), "Buy-and-hold QQQ": (52.0, 16.6, "left"), "Static 70/30": (36.6, 12.9, "right"),
           "Fear-timed + QLD": (40.0, 10.9, "left"), "Fear-timed + TQQQ": (40.0, 12.45, "left")}
cols = {"Buy-and-hold 50/50": MUTED, "Buy-and-hold QQQ": MUTED, "Static 70/30": AQUA, "Fear-timed + QLD": BLUE, "Fear-timed + TQQQ": ORANGE}
for k, (lx, ly, ha) in lab_pos.items():
    st = perf_stats(navs[k], rf); x, y = -st["MaxDD"] * 100, st["CAGR"] * 100
    ax.scatter(x, y, s=80 if "TQQQ" not in k else 55, color=cols[k], zorder=3, edgecolor=SURF, linewidth=1.5)
    ax.text(lx, ly, f"{k}: CAGR {y:.1f}%, MaxDD −{x:.0f}%", fontsize=9.5, color=INK, ha=ha)
st = perf_stats(strat, rf); x0 = -st["MaxDD"] * 100
for wq, col in [(0.5, MUTED), (0.75, INK2)]:
    yl = np.interp(x0, *line(mix(wq)).T)
    ax.plot([x0, x0], [yl, st["CAGR"] * 100], color=BLUE, lw=1.2, ls=":")
    ax.text(x0 - 0.5, yl, f"{st['CAGR']*100 - yl:+.1f} pp/yr vs {'50/50' if wq == 0.5 else '75/25'}", ha="right", va="center", fontsize=9.5, color=BLUE)
ax.set_xlabel("Maximum drawdown 2007–2026 (%, smaller is better)"); ax.set_ylabel("CAGR (%)")
ax.set_xlim(14, 70); ax.set_ylim(4.5, 17.5); ax.legend(loc="lower right", fontsize=9.5)
ax.set_title("Judge timing at equal risk: points above their own grey line earn more for the same worst fall", loc="left")
savefig(fig, "fig_return_vs_drawdown.png")
for wq in (0.5, 0.75):
    print(wq, "gap at same MaxDD:", st["CAGR"] * 100 - np.interp(x0, *line(mix(wq)).T))
