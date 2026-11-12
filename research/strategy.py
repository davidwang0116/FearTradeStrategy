"""Fixed-capital "Fear-Tranche Accumulator" with a conditional leverage sleeve.

Idea: turn sentiment-weighted DCA (which needs fresh monthly cash) into a
fixed-capital trading strategy. A slice of capital is held back as dry powder
(T-bills) and deployed in tranches when fear is extreme; at the very worst
fear, once it starts to recede, part of it goes into 2x/3x Nasdaq; when greed
returns, the leverage is sold and the core is trimmed back to rebuild powder,
so capital recycles instead of being spent once.

Pre-registered rules (decided before looking at results; every variant run is
reported in results/strategy_variants.csv — nothing is dropped):

  Signal     composite fear score from the nasdaq-mood-dashboard v4 formula
             (VXN + drawdown + price-sentiment proxy; no valuation term locally),
             converted to a causal expanding percentile p_t (min 2 years).
  Timing     signal at close t, trade at close t+1. Costs 5 bp/side ETFs,
             15 bp/side leveraged ETFs. Cash earns the T-bill rate.
  Neutral    core 70% beta (QQQ, or 50/50 QQQ+SPY as a QQQM+VOO stand-in),
             30% dry powder.
  Tranche    p_t >= 0.80, at least 10 trading days since the last tranche and
             QQQ <= 95% of the last tranche price (or first in an episode):
             move 10% of NAV from powder into core.
  Leverage   p_t >= 0.90 AND fear receding (VXN <= 85% of its 10-day max):
             buy the levered ETF with 10% of NAV from powder, sleeve cap 25% NAV.
  Exit lev.  sell the whole sleeve when (p_t <= 0.50 and QQQ > MA200), or the
             sleeve is up >= 60%, or it has been held 378 trading days.
  Recycle    greed (p_t <= 0.15 and QQQ >= 1.08 x MA200): trim core back to 70%
             (21-day cooldown). Powder above 30% after a sleeve exit is
             re-invested into core.
  Optional   trend guard: half of the core follows QQQ-vacation (hold if QQQ >=
             0.97 x MA200, else T-bills) — sells in crashes while the tranche
             rules buy, so the two timing rules hedge each other.
"""
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from common import (AQUA, BLUE, GRID, INK, INK2, MUTED, ORANGE, RES, VIOLET, build_signals, load_panel,
                    perf_stats, plt, savefig)


@dataclass
class Cfg:
    name: str
    core: tuple = (("qqq", 1.0),)          # core basket weights
    core_target: float = 0.70
    tranche: float = 0.10
    tranche_p: float = 0.80
    tranche_gap: int = 10
    tranche_step: float = 0.95
    lev: str | None = None                 # "qld" | "tqqq" | None
    lev_p: float = 0.90
    lev_size: float = 0.10
    lev_cap: float = 0.25
    lev_tp: float = 0.60
    lev_exit_p: float = 0.50
    lev_max_days: int = 378
    greed_p: float = 0.15
    greed_stretch: float = 1.08
    trend_guard: bool = False
    calm_lev: bool = False                 # trend half holds QLD (2x) when trend on AND fear pct <= 0.5
    fear_off: bool = False                 # True = static 70/30 (no signal), for comparison
    cost: float = 0.0005
    lev_cost: float = 0.0015


def prepare(P, S):
    comp = S["Composite (dashboard v4)"]
    D = pd.DataFrame(index=P.index)
    D["p"] = comp.expanding(504).rank(pct=True)
    D["qqq"] = P["qqq"]
    D["ma200"] = P["qqq"].rolling(200).mean()
    D["vxn"] = P["vxn"]
    D["vxn_recede"] = P["vxn"] <= 0.85 * P["vxn"].rolling(10).max()
    for k in ["qqq", "spy", "qld", "tqqq"]:
        D["r_" + k] = P["ret_" + k]
    D["rf"] = P["rf"]
    return D


def run(D, c: Cfg, start, end, capital=100_000.0):
    D = D.loc[start:end].copy()
    D = D.dropna(subset=["r_qqq"] + [f"r_{k}" for k, _ in c.core])
    n = len(D)
    idx = D.index
    # holdings in dollars
    core = {k: capital * c.core_target * w for k, w in c.core}
    trend = 0.0                       # dollars in the trend-guarded half of core held in QQQ
    if c.trend_guard:
        half = sum(core.values()) / 2
        core = {k: v / 2 for k, v in core.items()}
        trend = half
    trend_on = True
    trend_lev = False
    lev = 0.0
    cash = capital - sum(core.values()) - trend
    lev_entry_val, lev_cost_basis, lev_days = 0.0, 0.0, 0
    last_tranche_i, last_tranche_px, last_trim_i = -999, np.inf, -999
    nav = np.empty(n)
    rec = {"core": np.empty(n), "lev": np.empty(n), "cash": np.empty(n), "trend": np.empty(n), "expo": np.empty(n)}
    trades = []
    prev = None
    for i in range(n):
        row = D.iloc[i]
        # 1) returns for day i on positions held since close i-1
        if i > 0:
            for k in core:
                core[k] *= 1 + row["r_" + k]
            if trend_on:
                trend *= 1 + (row["r_qld"] if trend_lev else row["r_qqq"])
            else:
                trend *= 1 + row["rf"] / 252
            if lev > 0:
                lev *= 1 + row["r_" + c.lev]
                lev_days += 1
            cash *= 1 + row["rf"] / 252
        V = sum(core.values()) + trend + lev + cash
        # 2) execute orders decided on yesterday's close signal (prev)
        if prev is not None and not c.fear_off:
            p, px, ma, recede = prev["p"], prev["qqq"], prev["ma200"], prev["vxn_recede"]
            core_v = sum(core.values()) + trend

            def buy_core(amt, why):
                nonlocal cash
                amt = min(amt, cash)
                if amt <= 1:
                    return
                tot_w = sum(w for _, w in c.core)
                for k, w in c.core:
                    core[k] += amt * w / tot_w * (1 - c.cost)
                cash -= amt
                trades.append((idx[i], why, amt))

            # leverage exit
            if lev > 0:
                gain = lev / lev_cost_basis - 1
                if (p <= c.lev_exit_p and px > ma) or gain >= c.lev_tp or lev_days >= c.lev_max_days:
                    cash += lev * (1 - c.lev_cost)
                    trades.append((idx[i], f"sell {c.lev} ({gain:+.0%})", lev))
                    lev, lev_cost_basis, lev_days = 0.0, 0.0, 0
                    excess = cash - (1 - c.core_target) * V
                    if excess > 0:
                        buy_core(excess, "reinvest")
            # tranche buy
            if not np.isnan(p) and p >= c.tranche_p and i - last_tranche_i >= c.tranche_gap and \
                    (px <= c.tranche_step * last_tranche_px or i - last_tranche_i > 126):
                if cash > 1:
                    buy_core(c.tranche * V, "tranche")
                    last_tranche_i, last_tranche_px = i, px
            # leverage entry
            if c.lev and not np.isnan(p) and p >= c.lev_p and recede and lev < c.lev_cap * V and cash > 1:
                amt = min(c.lev_size * V, c.lev_cap * V - lev, cash)
                if amt > 1:
                    lev += amt * (1 - c.lev_cost)
                    lev_cost_basis += amt
                    cash -= amt
                    trades.append((idx[i], f"buy {c.lev}", amt))
            # greed trim
            if not np.isnan(p) and p <= c.greed_p and px >= c.greed_stretch * ma and i - last_trim_i >= 21:
                core_v = sum(core.values()) + trend
                over = core_v - c.core_target * V
                if over > 0.01 * V:
                    f = over / core_v
                    for k in core:
                        cash += core[k] * f * (1 - c.cost)
                        core[k] *= 1 - f
                    cash += trend * f * (1 - c.cost) if trend_on else trend * f
                    trend *= 1 - f
                    last_trim_i = i
                    last_tranche_px = np.inf
                    trades.append((idx[i], "greed trim", over))
            # trend guard on half the core
            if c.trend_guard and not np.isnan(ma):
                want = px >= 0.97 * ma
                if want != trend_on:
                    trend *= 1 - c.cost
                    trend_on = want
                    trades.append((idx[i], "trend " + ("on" if want else "off"), trend))
                wl = c.calm_lev and trend_on and not np.isnan(p) and p <= 0.5
                if wl != trend_lev and (wl or p >= 0.7 or not trend_on):   # hysteresis: drop 2x when fear >= 70th pct
                    trend *= 1 - c.lev_cost
                    trend_lev = wl
                    trades.append((idx[i], "calm-lev " + ("on" if wl else "off"), trend))
        V = sum(core.values()) + trend + lev + cash
        nav[i] = V
        rec["core"][i] = sum(core.values()) / V
        rec["trend"][i] = trend / V if trend_on else 0.0
        rec["lev"][i] = lev / V
        rec["cash"][i] = (cash + (0 if trend_on else trend)) / V
        lev_mult = {"qld": 2, "tqqq": 3}.get(c.lev, 0)
        rec["expo"][i] = rec["core"][i] + rec["trend"][i] * (2 if trend_lev else 1) + lev_mult * rec["lev"][i]
        prev = row
    out = pd.DataFrame(rec, index=idx)
    out["nav"] = nav
    return out, pd.DataFrame(trades, columns=["date", "action", "amount"])


def bh(D, weights, start, end, capital=100_000.0, name=""):
    d = D.loc[start:end]
    r = sum(d["r_" + k].fillna(0) * w for k, w in weights.items())
    if "cash" in weights:
        r = r - d["r_cash"].fillna(0) * weights["cash"] + d["rf"] / 252 * weights["cash"]
    nav = capital * (1 + r).cumprod()
    return nav


V2 = dict(tranche=0.075, tranche_step=0.92, lev_cap=0.30)
VARIANTS = [
    Cfg("Static 70/30 QQQ/T-bill", fear_off=True),
    # ---- v1: pre-registered, run first (kept, counts toward the trial total) ----
    Cfg("v1 Fear tranches"),
    Cfg("v1 + QLD sleeve", lev="qld"),
    Cfg("v1 + TQQQ sleeve", lev="tqqq"),
    Cfg("v1 + QLD + trend guard", lev="qld", trend_guard=True),
    # ---- v2: one diagnosed revision (powder ran out early in 2008) ----
    Cfg("v2 Ladder tranches", **V2),
    Cfg("v2 + QLD sleeve", lev="qld", **V2),
    Cfg("v2 + TQQQ sleeve", lev="tqqq", **V2),
    Cfg("v2 + QLD + trend guard", lev="qld", trend_guard=True, **V2),
    Cfg("v2 + QLD + trend guard + calm 2x", lev="qld", trend_guard=True, calm_lev=True, **V2),
    Cfg("Trend guard + calm 2x only (no fear)", trend_guard=True, calm_lev=True, tranche_p=2.0, lev=None),
]


def sub_stats(nav, rf, periods):
    out = {}
    for a, b in periods:
        s = nav.loc[a:b]
        if len(s) > 60:
            st = perf_stats(s, rf)
            out[f"{a}–{b}"] = st["Sharpe"], st["CAGR"], st["MaxDD"]
    return out


def main():
    P = load_panel()
    S = build_signals(P)
    D = prepare(P, S)
    D["r_cash"] = 0.0
    rf = P["rf"]
    rows, curves, allocs = [], {}, {}
    tests = {
        "A: QQQ core, 2002-03 → 2026-09": ("2002-03-08", "2026-09-11", (("qqq", 1.0),)),
        "B: QQQ+SPY core, 2007-02 → 2026-09": ("2007-02-01", "2026-09-11", (("qqq", 0.5), ("spy", 0.5))),
    }
    periods = [("2002", "2007"), ("2008", "2009"), ("2010", "2019"), ("2020", "2021"), ("2022", "2022"), ("2023", "2026")]
    for tname, (a, b, core) in tests.items():
        bench = {"Buy & hold QQQ": bh(D, {"qqq": 1.0}, a, b)}
        if any(k == "spy" for k, _ in core):
            bench["Buy & hold 50/50 QQQ+SPY"] = bh(D, {"qqq": 0.5, "spy": 0.5}, a, b)
        for bn, nav in bench.items():
            st = perf_stats(nav, rf)
            rows.append(dict(test=tname, strategy=bn, **st, avg_expo=1.0, trades=0, **{
                f"Sharpe {k}": v[0] for k, v in sub_stats(nav, rf, periods).items()}))
            curves[(tname, bn)] = nav
        for v in VARIANTS:
            c = replace(v, core=core)
            res, tr = run(D, c, a, b)
            st = perf_stats(res["nav"], rf)
            rows.append(dict(test=tname, strategy=c.name, **st, avg_expo=res["expo"].mean(), trades=len(tr), **{
                f"Sharpe {k}": v[0] for k, v in sub_stats(res["nav"], rf, periods).items()}))
            curves[(tname, c.name)] = res["nav"]
            allocs[(tname, c.name)] = res
            if tname.startswith("A") and c.name == "Fear tranches + QLD sleeve":
                tr.to_csv(RES / "trades_A_qld.csv", index=False)
    T = pd.DataFrame(rows)
    T.to_csv(RES / "strategy_variants.csv", index=False)
    pd.set_option("display.width", 250)
    print(T[["test", "strategy", "CAGR", "Vol", "Sharpe", "Sortino", "MaxDD", "Calmar", "avg_expo", "trades"]].round(3).to_string())
    print(T.filter(like="Sharpe 20").assign(s=T.strategy, t=T.test.str[:1]).round(2).to_string())
    pd.to_pickle((curves, allocs), RES / "strategy_curves.pkl")


if __name__ == "__main__":
    main()
