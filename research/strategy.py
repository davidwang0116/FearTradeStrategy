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
  Basket     defaults (v2): the trend half holds QQQ and basket weights drift, so
             a "50/50" core starts at 75/25 QQQ/SPY while the trend is on.
             trend_asset="core" + basket_reset="event" follow qc/main.py instead.
  Lev. exit  v2 (lev_exit_close="same") reads the sleeve's gain and age at the close it trades on, one bar later
             than the stated signal-at-t rule. lev_exit_close="signal" reads them at the signal close, as
             qc/main.py does (2007-2026 50/50 v2: the 2020-04-29 sale moves to 04-30, Sharpe 0.70748 -> 0.70740).
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
    trend_asset: str = "qqq"               # "qqq" (v2) | "core": trend-guarded half holds the core basket, as qc/main.py does
    basket_reset: str = "none"             # "none" (v2): weights drift | "event": basket back to target on rebalance events (QC)
    lev_exit_close: str = "same"           # "same" (v2) | "signal": take-profit and max-days read at the signal close

    def __post_init__(self):
        if self.trend_asset not in ("qqq", "core") or self.basket_reset not in ("none", "event"):
            raise ValueError(f"bad trend_asset/basket_reset: {self.trend_asset}, {self.basket_reset}")
        if self.lev_exit_close not in ("same", "signal"):
            raise ValueError(f"lev_exit_close must be 'same' or 'signal', not {self.lev_exit_close!r}")
        if self.calm_lev and self.trend_asset == "core":
            raise ValueError("calm_lev holds QLD in the trend sleeve; it needs trend_asset='qqq'")
        if self.basket_reset == "event" and self.trend_guard and self.trend_asset != "core":
            raise ValueError("basket_reset='event' needs trend_asset='core' when the trend guard is on")


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
    # trend-guarded half of core: dollars per asset while on; `parked` T-bill dollars while off
    # (`parked` is NOT spendable: tranches and leverage buys use `cash` only)
    tw_sum = sum(w for _, w in c.core)
    trend_w = {"qqq": 1.0} if c.trend_asset == "qqq" else {k: w / tw_sum for k, w in c.core}
    trend = {k: 0.0 for k in trend_w}
    parked = 0.0
    if c.trend_guard:
        half = sum(core.values()) / 2
        core = {k: v / 2 for k, v in core.items()}
        trend = {k: half * w for k, w in trend_w.items()}
    trend_on = True
    trend_lev = False
    lev = 0.0
    cash = capital - sum(core.values()) - sum(trend.values())
    lev_entry_val, lev_cost_basis, lev_days = 0.0, 0.0, 0
    last_tranche_i, last_tranche_px, last_trim_i = -999, np.inf, -999
    nav = np.empty(n)
    rec = {"core": np.empty(n), "lev": np.empty(n), "cash": np.empty(n), "trend": np.empty(n), "expo": np.empty(n)}
    rec.update({k: np.zeros(n) for k in ("reserve", "trend_parked", "qqq_w", "spy_w", "lev_2x", "tranche_want", "tranche_got")})
    trades = []
    prev = None
    for i in range(n):
        row = D.iloc[i]
        lev_prev = lev                     # sleeve value at close i-1, the signal close for today's orders
        # 1) returns for day i on positions held since close i-1
        if i > 0:
            for k in core:
                core[k] *= 1 + row["r_" + k]
            if trend_on:
                for k in trend:
                    trend[k] *= 1 + (row["r_qld"] if trend_lev else row["r_" + k])
            else:
                parked *= 1 + row["rf"] / 252
            if lev > 0:
                lev *= 1 + row["r_" + c.lev]
                lev_days += 1
            cash *= 1 + row["rf"] / 252
        V = sum(core.values()) + sum(trend.values()) + parked + lev + cash
        # 2) execute orders decided on yesterday's close signal (prev)
        if prev is not None and not c.fear_off:
            p, px, ma, recede = prev["p"], prev["qqq"], prev["ma200"], prev["vxn_recede"]
            core_v = sum(core.values()) + sum(trend.values()) + parked
            before = {k: core.get(k, 0.0) + trend.get(k, 0.0) for k in {**core, **trend}}
            event = False                  # did anything execute today? (only used by basket_reset="event")

            def buy_core(amt, why):
                nonlocal cash
                amt = min(amt, cash)
                if amt <= 1:
                    return 0.0
                tot_w = sum(w for _, w in c.core)
                for k, w in c.core:
                    core[k] += amt * w / tot_w * (1 - c.cost)
                cash -= amt
                trades.append((idx[i], why, amt))
                return amt

            # leverage exit
            if lev > 0:
                at_signal = c.lev_exit_close == "signal"
                gain = (lev_prev if at_signal else lev) / lev_cost_basis - 1
                held = lev_days - 1 if at_signal else lev_days
                if (p <= c.lev_exit_p and px > ma) or gain >= c.lev_tp or held >= c.lev_max_days:
                    cash += lev * (1 - c.lev_cost)
                    trades.append((idx[i], f"sell {c.lev} ({gain:+.0%})", lev))
                    lev, lev_cost_basis, lev_days = 0.0, 0.0, 0
                    event = True
                    excess = cash - (1 - c.core_target) * V
                    if excess > 0:
                        buy_core(excess, "reinvest")
            # tranche buy
            if not np.isnan(p) and p >= c.tranche_p and i - last_tranche_i >= c.tranche_gap and \
                    (px <= c.tranche_step * last_tranche_px or i - last_tranche_i > 126):
                rec["tranche_want"][i] = c.tranche
                if cash > 1:
                    got = buy_core(c.tranche * V, "tranche")
                    rec["tranche_got"][i] = got / V
                    event = event or got > 0.001 * V
                    last_tranche_i, last_tranche_px = i, px
            # leverage entry
            if c.lev and not np.isnan(p) and p >= c.lev_p and recede and lev < c.lev_cap * V and cash > 1:
                amt = min(c.lev_size * V, c.lev_cap * V - lev, cash)
                if amt > 1:
                    lev += amt * (1 - c.lev_cost)
                    lev_cost_basis += amt
                    cash -= amt
                    trades.append((idx[i], f"buy {c.lev}", amt))
                    event = event or amt > 0.001 * V
            # greed trim
            if not np.isnan(p) and p <= c.greed_p and px >= c.greed_stretch * ma and i - last_trim_i >= 21:
                core_v = sum(core.values()) + sum(trend.values()) + parked
                over = core_v - c.core_target * V
                if over > 0.01 * V:
                    f = over / core_v
                    for k in core:
                        cash += core[k] * f * (1 - c.cost)
                        core[k] *= 1 - f
                    cash += sum(trend.values()) * f * (1 - c.cost) if trend_on else parked * f
                    trend = {k: v * (1 - f) for k, v in trend.items()}
                    parked *= 1 - f
                    event = True
                    last_trim_i = i
                    last_tranche_px = np.inf
                    trades.append((idx[i], "greed trim", over))
            # trend guard on half the core
            if c.trend_guard and not np.isnan(ma):
                want = px >= 0.97 * ma
                if want != trend_on:
                    amt = (sum(trend.values()) + parked) * (1 - c.cost)
                    parked = 0.0 if want else amt
                    trend = {k: (amt * w if want else 0.0) for k, w in trend_w.items()}
                    trend_on = want
                    event = True
                    trades.append((idx[i], "trend " + ("on" if want else "off"), amt))
                wl = c.calm_lev and trend_on and not np.isnan(p) and p <= 0.5
                if wl != trend_lev and (wl or p >= 0.7 or not trend_on):   # hysteresis: drop 2x when fear >= 70th pct
                    trend = {k: v * (1 - c.lev_cost) for k, v in trend.items()}
                    parked *= 1 - c.lev_cost
                    trend_lev = wl
                    trades.append((idx[i], "calm-lev " + ("on" if wl else "off"), sum(trend.values()) + parked))
            # basket back to target weights on executed events, as qc/main.py _rebalance() does.  Sleeve flows
            # already paid their cost above; pay only for the extra two-sided turnover the reset causes.
            if event and c.basket_reset == "event":
                ct, tt = sum(core.values()), sum(trend.values())
                after = {k: (ct + tt) * w / tw_sum for k, w in c.core}
                diff = [after.get(k, 0.0) - before.get(k, 0.0) for k in {**before, **after}]
                extra = sum(abs(x) for x in diff) - abs(sum(diff))
                keep = 1 - c.cost * extra / (ct + tt) if ct + tt > 0 else 1.0
                core = {k: ct * keep * w / tw_sum for k, w in c.core}
                trend = {k: tt * keep * w for k, w in trend_w.items()}
        V = sum(core.values()) + sum(trend.values()) + parked + lev + cash
        nav[i] = V
        rec["core"][i] = sum(core.values()) / V
        rec["trend"][i] = sum(trend.values()) / V
        rec["lev"][i] = lev / V
        rec["cash"][i] = (cash + parked) / V
        lev_mult = {"qld": 2, "tqqq": 3}.get(c.lev, 0)
        rec["reserve"][i] = cash / V                  # spendable dry powder only
        rec["trend_parked"][i] = parked / V
        rec["qqq_w"][i] = (core.get("qqq", 0.0) + trend.get("qqq", 0.0)) / V
        rec["spy_w"][i] = (core.get("spy", 0.0) + trend.get("spy", 0.0)) / V
        rec["lev_2x"][i] = lev_mult * lev / V         # Nasdaq exposure of the leverage sleeve
        rec["expo"][i] = rec["core"][i] + rec["trend"][i] * (2 if trend_lev else 1) + lev_mult * rec["lev"][i]
        prev = row
    out = pd.DataFrame(rec, index=idx)
    out["nav"] = nav
    return out, pd.DataFrame(trades, columns=["date", "action", "amount"])


def bh(D, weights, start, end, capital=100_000.0, name="", rebalance="daily"):
    """Buy and hold. rebalance="daily" keeps the weights fixed every day; "never" buys once and lets them drift."""
    d = D.loc[start:end]
    if rebalance == "never":
        grow = lambda k: (1 + (d["rf"] / 252 if k == "cash" else d["r_" + k]).fillna(0)).cumprod()
        return capital * sum(w * grow(k) for k, w in weights.items())
    if rebalance != "daily":
        raise ValueError(f"rebalance must be 'daily' or 'never', not {rebalance!r}")
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
            bench["Buy & hold 50/50 QQQ+SPY"] = bh(D, {"qqq": 0.5, "spy": 0.5}, a, b)            # rebalanced daily
            bench["Buy & hold 50/50 QQQ+SPY, bought once"] = bh(D, {"qqq": 0.5, "spy": 0.5}, a, b, rebalance="never")
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
