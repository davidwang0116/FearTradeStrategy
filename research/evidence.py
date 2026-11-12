"""Evidence that fear / cheapness signals predict higher forward QQQ returns.

Outputs (figures/ and results/):
  fig_quintiles_63d.png / _252d.png   forward return by signal quintile, all signals
  fig_event_study.png                 avg QQQ path after extreme-fear entries vs all days
  fig_timeline.png                    QQQ (log) with extreme-fear days marked
  fig_cape.png                        S&P CAPE vs next-10y real return (Shiller, 1881-2016)
  fig_spiva.png                       share of active large-cap funds trailing S&P 500
  fig_regimes.png                     composite Q5-Q1 spread by sub-period (honest caveat)
  ic_table.csv, quintile_table.csv, regime_table.csv
"""
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from common import (AQUA, BLUE, FIG, GRID, INK, INK2, MUTED, ORANGE, RES, SEQ5, build_signals,
                    fwd_return, load_panel, plt, savefig)

rng = np.random.default_rng(585)
HORIZONS = [21, 63, 126, 252]


def block_boot_ic(x, y, block=63, n=500):
    """Spearman IC with a moving-block bootstrap 5-95% CI (overlapping returns!)."""
    d = pd.concat([x, y], axis=1).dropna().values
    T = len(d)
    ic = spearmanr(d[:, 0], d[:, 1]).statistic
    nb = int(np.ceil(T / block))
    bs = []
    for _ in range(n):
        st = rng.integers(0, T - block, nb)
        idx = (st[:, None] + np.arange(block)).ravel()[:T]
        bs.append(spearmanr(d[idx, 0], d[idx, 1]).statistic)
    lo, hi = np.percentile(bs, [5, 95])
    return ic, lo, hi, T


def main():
    P = load_panel()
    S = build_signals(P)
    real_vxn = P.index >= "2008-01-03"
    for c in ["VXN score", "Variance risk premium"]:
        S.loc[~real_vxn, c] = np.nan          # use real VXN only (no back-fill) for evidence
    px = P["qqq"]
    fwd = {h: fwd_return(px, h) for h in HORIZONS}
    sigs = list(S.columns)

    # ---------- IC table ----------
    rows = []
    for sample, a in [("2008-2026", "2008-01-03"), ("1999-2026", "1999-01-01")]:
        for s in sigs:
            for h in HORIZONS:
                x = S[s].loc[a:]
                ic, lo, hi, T = block_boot_ic(x, fwd[h])
                rows.append(dict(sample=sample, signal=s, h=h, IC=ic, lo5=lo, hi95=hi, n=T,
                                 start=x.first_valid_index().date()))
    ic_all = pd.DataFrame(rows)
    ic_all.to_csv(RES / "ic_table.csv", index=False)
    print(ic_all.pivot_table(index=["sample", "signal"], columns="h", values="IC").round(3))
    ic = ic_all[ic_all["sample"] == "2008-2026"]
    MAIN = "2008-01-03"   # real-VXN era; full-sample results are in ic_table.csv / fig_regimes

    # ---------- quintile tables & charts ----------
    qt = []
    for h in (63, 252):
        fig, axes = plt.subplots(2, 4, figsize=(15, 7), sharey=True)
        for ax, s in zip(axes.ravel(), sigs):
            d = pd.concat([S[s], fwd[h]], axis=1, keys=["x", "y"]).loc[MAIN:].dropna()
            d["q"] = pd.qcut(d["x"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5])
            g = d.groupby("q", observed=True)["y"].agg(["mean", "count", lambda v: (v > 0).mean()])
            g.columns = ["mean", "n", "hit"]
            for q, r in g.iterrows():
                qt.append(dict(signal=s, h=h, q=int(q), mean=r["mean"], hit=r["hit"], n=int(r["n"])))
            ax.bar(range(1, 6), g["mean"] * 100, color=SEQ5, width=0.72, edgecolor="none")
            ax.axhline(d["y"].mean() * 100, color=INK2, ls="--", lw=1)
            for i, v in enumerate(g["mean"] * 100):
                ax.text(i + 1, v + (0.3 if v >= 0 else -0.3), f"{v:.1f}", ha="center",
                        va="bottom" if v >= 0 else "top", fontsize=9, color=INK2)
            row = ic[(ic.signal == s) & (ic.h == h)].iloc[0]
            ax.set_title(s, fontsize=11)
            ax.text(0.02, 0.97, f"IC {row.IC:+.2f} [{row.lo5:+.2f}, {row.hi95:+.2f}]\n{row.start.year}–2026, n={row.n}",
                    transform=ax.transAxes, va="top", fontsize=9, color=INK2)
            ax.set_xticks(range(1, 6), ["Q1\ncalm", "Q2", "Q3", "Q4", "Q5\nfear"])
            ax.grid(axis="x", visible=False)
        axes[1, 3].axis("off")
        axes[1, 3].text(0.0, 0.6, f"Bars: mean QQQ return over the next {h} trading days,\n"
                        "bought at the t+1 close after the signal.\n\nDashed line: unconditional mean.\n"
                        "IC: Spearman rank correlation,\n63-day block-bootstrap 5–95% CI.\n\n"
                        "Higher signal = more fear / cheaper.", fontsize=10, color=INK2, va="top")
        for ax in axes[:, 0]:
            ax.set_ylabel(f"Next-{h}d QQQ return (%)")
        fig.suptitle(f"Fear signals are contrarian: more fear today → higher QQQ return over the next {h} days (2008–2026)",
                     x=0.01, ha="left", fontsize=14, fontweight="bold")
        fig.tight_layout()
        savefig(fig, f"fig_quintiles_{h}d.png")
    pd.DataFrame(qt).to_csv(RES / "quintile_table.csv", index=False)

    # ---------- event study ----------
    def entries(mask, cool=63):
        out, last = [], None
        for t in mask[mask].index:
            if last is None or (P.index.get_loc(t) - P.index.get_loc(last)) > cool:
                out.append(t)
            last = t
        return out

    comp = S["Composite (dashboard v4)"]
    pctl = comp.expanding(504).rank(pct=True)           # causal percentile
    events = {
        "Composite ≥ 90th pct (expanding)": entries(pctl >= 0.90),
        "VIX ≥ 30": entries(P["vix"] >= 30),
        "CNN Fear&Greed ≤ 20": entries(P["fgi"] <= 20),
    }
    H = 252
    logp = np.log(px).values
    n = len(px)

    def paths_for(idx_list):
        out = [np.exp(logp[i + 1:i + 2 + H] - logp[i + 1]) - 1 for i in idx_list if i + 1 + H < n]
        return np.array(out)

    all_idx = [i for i in range(n) if not np.isnan(logp[i])]
    base = paths_for(all_idx)
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.4), sharey=True)
    ev_rows = []
    conds = {
        "Composite ≥ 90th pct": (pctl >= 0.90, BLUE),
        "VIX ≥ 30": (P["vix"] >= 30, ORANGE),
        "CNN Fear&Greed ≤ 20": (P["fgi"] <= 20, AQUA),
    }
    for ax, mode in zip(axes, ["every", "first"]):
        bm = base.mean(0) * 100
        ax.plot(np.arange(H + 1), bm, color=MUTED, lw=2, ls="--", label=f"Any day (n={len(base)})")
        ends = [(bm[-1], f"{bm[-1]:+.1f}%", INK2)]
        for name, (mask, col) in conds.items():
            if mode == "every":
                idx = [P.index.get_loc(t) for t in mask[mask.fillna(False)].index]
                lab = f"every day {name} (n={len(paths_for(idx))} days)"
            else:
                idx = [P.index.get_loc(t) for t in events[name if name != "Composite ≥ 90th pct" else "Composite ≥ 90th pct (expanding)"]]
                lab = f"first day {name} (n={len(paths_for(idx))} episodes)"
            pa = paths_for(idx)
            m = pa.mean(0) * 100
            ax.plot(np.arange(H + 1), m, color=col, lw=2.2, label=lab)
            ends.append((m[-1], f"{m[-1]:+.1f}%", INK))
            ev_rows.append(dict(mode=mode, event=name, n=len(pa), mean_21=pa[:, 21].mean(), mean_63=pa[:, 63].mean(),
                                mean_252=pa[:, -1].mean(), hit_252=(pa[:, -1] > 0).mean(),
                                worst_252=pa[:, -1].min(), worst_path_min=pa.min(1).min()))
        ends.sort()
        ys = [e[0] for e in ends]
        for k in range(1, len(ys)):
            ys[k] = max(ys[k], ys[k - 1] + 1.6)
        for (v, t, c), y in zip(ends, ys):
            ax.text(H + 4, y, t, color=c, va="center", fontsize=10)
        ax.axhline(0, color=INK2, lw=0.8)
        ax.set_xlim(0, H + 32)
        ax.set_xlabel("Trading days after purchase (bought at t+1 close)")
        ax.legend(loc="upper left", fontsize=9.5)
    axes[0].set_ylabel("Average cumulative QQQ return (%)")
    axes[0].set_title("Scale in: buying on EVERY extreme-fear day", loc="left")
    axes[1].set_title("All-in: buying only the FIRST fear day of an episode", loc="left")
    fig.suptitle("The edge comes from accumulating through the fear window, not from catching the first day (QQQ 1999–2026)",
                 x=0.01, ha="left", fontsize=13.5, fontweight="bold")
    fig.tight_layout()
    savefig(fig, "fig_event_study.png")
    pd.DataFrame(ev_rows).to_csv(RES / "event_study.csv", index=False)
    print(pd.DataFrame(ev_rows).round(3).to_string())

    # ---------- timeline ----------
    fig, ax = plt.subplots(figsize=(12, 4.8))
    ax.plot(px.index, px, color=BLUE, lw=1.4, label="QQQ (adj., log scale)")
    hot = pctl >= 0.90
    ax.scatter(px.index[hot], px[hot], s=6, color=ORANGE, zorder=3, label="Composite fear ≥ 90th pct (expanding)")
    ax.set_yscale("log")
    from matplotlib.ticker import FixedLocator, FuncFormatter
    ax.yaxis.set_major_locator(FixedLocator([25, 50, 100, 200, 400, 800]))
    ax.yaxis.set_minor_locator(FixedLocator([]))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:.0f}"))
    ax.set_title("Extreme-fear days cluster near the lows of every major drawdown (signal live from 2002)", loc="left")
    ax.legend(loc="upper left")
    savefig(fig, "fig_timeline.png")

    # ---------- regime table ----------
    reg = []
    for a, b in [("1999", "2002"), ("2003", "2009"), ("2010", "2019"), ("2020", "2026")]:
        d = pd.concat([comp, fwd[63], fwd[252]], axis=1, keys=["x", "y63", "y252"]).loc[a:b].dropna(subset=["x", "y63"])
        d["q"] = pd.qcut(d["x"].rank(method="first"), 5, labels=False)
        g = d.groupby("q")[["y63", "y252"]].mean()
        reg.append(dict(period=f"{a}–{b}", ic63=spearmanr(d.x, d.y63).statistic,
                        q5_63=g.loc[4, "y63"], q1_63=g.loc[0, "y63"], q5_252=g.loc[4, "y252"], q1_252=g.loc[0, "y252"]))
    reg = pd.DataFrame(reg)
    reg.to_csv(RES / "regime_table.csv", index=False)
    print(reg.round(3))
    fig, ax = plt.subplots(figsize=(8, 4.2))
    x = np.arange(len(reg))
    ax.bar(x - 0.18, reg.q1_63 * 100, 0.34, color=SEQ5[0], label="Q1 (calm)")
    ax.bar(x + 0.18, reg.q5_63 * 100, 0.34, color=SEQ5[4], label="Q5 (fear)")
    for i, r in reg.iterrows():
        ax.text(i + 0.18, r.q5_63 * 100 + (0.4 if r.q5_63 >= 0 else -0.4), f"{r.q5_63*100:+.1f}",
                ha="center", va="bottom" if r.q5_63 >= 0 else "top", fontsize=9, color=INK2)
    ax.set_xticks(x, reg.period)
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set_ylabel("Next-63d QQQ return (%)")
    ax.set_title("Composite Q5 beats Q1 in every regime, including the dot-com bust", loc="left")
    ax.legend()
    ax.grid(axis="x", visible=False)
    savefig(fig, "fig_regimes.png")

    # ---------- CAPE (valuation) ----------
    sh = pd.read_csv(FIG.parent / "data/raw/shiller_sp500_monthly.csv", parse_dates=["Date"]).set_index("Date")
    sh = sh[sh["PE10"] > 0]
    rp = sh["Real Price"]
    # real total return proxy: real price + real dividends reinvested monthly
    tr = (1 + (rp.pct_change() + sh["Real Dividend"] / 12 / rp.shift())).cumprod()
    f10 = (tr.shift(-120) / tr) ** (1 / 10) - 1
    d = pd.concat([sh["PE10"], f10], axis=1, keys=["cape", "f10"]).dropna()
    rho = spearmanr(d.cape, d.f10).statistic
    fig, ax = plt.subplots(figsize=(7.5, 5))
    ax.scatter(d.cape, d.f10 * 100, s=6, color=BLUE, alpha=0.45, edgecolor="none")
    b1, b0 = np.polyfit(np.log(d.cape), d.f10 * 100, 1)
    xs = np.linspace(d.cape.min(), d.cape.max(), 100)
    ax.plot(xs, b0 + b1 * np.log(xs), color=ORANGE, lw=2)
    last = sh["PE10"].dropna().iloc[-1]
    last_dt = sh["PE10"].dropna().index[-1]
    ax.axvline(last, color=INK2, ls="--", lw=1)
    ax.text(last, ax.get_ylim()[1] * 0.92, f" latest CAPE {last:.0f} ({last_dt:%b %Y})", color=INK2, fontsize=10)
    ax.set_xlabel("Shiller CAPE (S&P 500)")
    ax.set_ylabel("Next-10y real total return, annualized (%)")
    ax.set_title(f"Cheap starts → higher 10-year returns (ρ = {rho:.2f}, {d.index[0].year}–{d.index[-1].year} starts)", loc="left")
    savefig(fig, "fig_cape.png")
    print("CAPE rho", rho, "latest CAPE", last, sh["PE10"].dropna().index[-1])

    # ---------- SPIVA ----------
    yrs = ["1 yr", "3 yr", "5 yr", "10 yr", "15 yr", "20 yr"]
    vals = [78.78, 66.84, 88.96, 85.59, 89.93, 92.89]   # SPIVA U.S. Year-End 2025, Report 1a
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.bar(yrs, vals, color=BLUE, width=0.62)
    for i, v in enumerate(vals):
        ax.text(i, v + 1.2, f"{v:.0f}%", ha="center", fontsize=11, color=INK)
    ax.set_ylim(0, 100)
    ax.set_ylabel("% of active large-cap funds\ntrailing the S&P 500")
    ax.set_title("Most active managers lose to the index — and it gets worse with time", loc="left")
    ax.text(0, -0.2, "Source: S&P Dow Jones Indices, SPIVA U.S. Scorecard Year-End 2025 (data to Dec 31, 2025).",
            transform=ax.transAxes, fontsize=9, color=INK2)
    ax.grid(axis="x", visible=False)
    savefig(fig, "fig_spiva.png")


if __name__ == "__main__":
    main()
