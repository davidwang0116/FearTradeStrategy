"""Selling volatility when fear is elevated: cash-secured QQQ puts and put spreads.

MODEL-PRICED (no option chain locally; the QuantConnect version uses real quotes):
  * 30-calendar-day QQQ puts, Black-Scholes, r = T-bill.
  * implied vol from VXN (NDX 30-day implied vol): ATM IV = ATM_RATIO x VXN,
    skew  IV(K) = ATM IV x (1 + SKEW x ln(S/K)) for puts below spot (floor 0.8 x ATM above spot).
  * every sale receives premium x (1 - HAIRCUT) and pays at least MIN_TICK x spot per share
    (bid/ask), every daily mark uses the same model, positions are held to expiry
    (21 trading days), cash-settled: pay max(K - S_T, 0).
Signal at close t, sale at close t+1 (that day's VXN and price).

Part 1 — standalone sleeve: collateral = 100% of the sleeve in T-bills, notional = collateral
(cash-secured, no leverage). Grid: condition x strike x structure.
Part 2 — overlay on the fixed-capital strategy (v2 + QLD + trend guard, QQQ+SPY core): the
dry-powder cash collateralises the puts; option P&L flows into cash.
Outputs: results/vol_selling_standalone.csv, results/vol_selling_overlay.csv,
         figures/fig_vol_selling.png
"""
import numpy as np
import pandas as pd
from scipy.special import ndtr

from common import (AQUA, BLUE, INK, INK2, MUTED, ORANGE, RES, SEQ5, VIOLET, build_signals, load_panel,
                    perf_stats, plt, savefig)
from strategy import Cfg, prepare, run, bh

ATM_RATIO, SKEW, HAIRCUT, MIN_TICK = 0.92, 1.6, 0.03, 0.0002
TENOR_D, TENOR = 21, 30 / 365
A_, B_ = "2008-01-03", "2026-09-11"


def put_iv(S, K, vxn):
    atm = ATM_RATIO * vxn
    return max(atm * (1 + SKEW * np.log(S / K)), 0.8 * atm)


def bs_put(S, K, T, r, sig):
    if T <= 1e-6:
        return max(K - S, 0.0)
    v = sig * np.sqrt(T)
    d1 = (np.log(S / K) + (r + 0.5 * sig * sig) * T) / v
    return K * np.exp(-r * T) * ndtr(-(d1 - v)) - S * ndtr(-d1)


def conditions(P, S):
    pct = S["Composite (dashboard v4)"].expanding(504).rank(pct=True)
    vxn = P["vxn"]
    recede = vxn <= 0.9 * vxn.rolling(10).max()
    vxn_med = vxn.expanding(252).median()
    return {
        "always": pd.Series(True, index=P.index),
        "VXN ≥ its median": vxn >= vxn_med,
        "VXN ≥ 25": vxn >= 25,
        "fear ≥ 50th pct": pct >= 0.5,
        "fear 50–80th pct": (pct >= 0.5) & (pct < 0.8),
        "fear ≥ 50th & receding": (pct >= 0.5) & ((pct < 0.8) | recede),
        "fear ≥ 80th & receding": (pct >= 0.8) & recede,
    }


class PutBook:
    """One short put (or put spread) line at a time, rolled every 21 trading days."""

    def __init__(self, otm, spread_width):
        self.otm, self.width = otm, spread_width
        self.units = 0.0; self.K = self.K2 = None; self.left = 0

    def mark(self, S, r, vxn):
        if not self.units:
            return 0.0
        T = max(self.left, 0) / 252 * (TENOR * 252 / TENOR_D)
        v = bs_put(S, self.K, T, r, put_iv(S, self.K, vxn))
        if self.K2:
            v -= bs_put(S, self.K2, T, r, put_iv(S, self.K2, vxn))
        return -self.units * v                      # liability (negative value)

    def open(self, S, r, vxn, notional):
        self.K = S * (1 - self.otm)
        self.K2 = self.K * (1 - self.width) if self.width else None
        self.units = notional / self.K
        p = bs_put(S, self.K, TENOR, r, put_iv(S, self.K, vxn))
        prem = p * (1 - HAIRCUT) - MIN_TICK * S                   # sell the short leg at the bid
        if self.K2:
            p2 = bs_put(S, self.K2, TENOR, r, put_iv(S, self.K2, vxn))
            prem -= p2 * (1 + HAIRCUT) + MIN_TICK * S             # buy the long leg at the ask
        self.left = TENOR_D
        return self.units * prem

    def expire(self, S):
        pay = max(self.K - S, 0.0)
        if self.K2:
            pay -= max(self.K2 - S, 0.0)
        out = -self.units * pay
        self.units = 0.0; self.K = self.K2 = None
        return out


def standalone(P, cond, otm, width, capital=100_000.0):
    d = P.loc[A_:B_]
    c = cond.reindex(d.index).fillna(False).shift(1).fillna(False)      # signal t -> trade t+1
    book = PutBook(otm, width)
    cash = capital; nav = np.empty(len(d)); active = np.zeros(len(d), bool)
    for i, (t, row) in enumerate(d.iterrows()):
        S, r, vx = row["qqq"], row["rf"], row["vxn"] / 100
        if i > 0:
            cash *= 1 + r / 252
            if book.units:
                book.left -= 1
                if book.left <= 0:
                    cash += book.expire(S)
        if not book.units and c.iloc[i]:
            V = cash
            cash += book.open(S, r, vx, V)
        active[i] = book.units > 0
        nav[i] = cash + book.mark(S, r, vx)
    return pd.Series(nav, d.index), active.mean()


def overlay_run(P, D, cond, otm, width, frac, capital=100_000.0):
    """Fixed-capital strategy (v2 + QLD + trend guard) with puts written on frac x dry powder."""
    from strategy import Cfg
    c = Cfg("v2", core=(("qqq", 0.5), ("spy", 0.5)), tranche=0.075, tranche_step=0.92, lev_cap=0.30,
            trend_guard=True, lev="qld")
    base, _ = run(D, c, A_, B_, capital)
    # re-run with the overlay: we need the cash path, so replicate run() but add the option leg
    return _run_with_puts(D, c, P, cond, otm, width, frac, capital)


def _run_with_puts(D, c, P, cond, otm, width, frac, capital, block=False):
    D = D.loc[A_:B_].dropna(subset=["r_qqq", "r_spy"])
    idx = D.index
    sig = cond.reindex(idx).fillna(False).shift(1).fillna(False)
    core = {k: capital * c.core_target * w / 2 for k, w in c.core}
    trend = capital * c.core_target / 2; trend_on = True
    lev = 0.0; cash = capital - sum(core.values()) - trend
    lev_cost_basis, lev_days = 0.0, 0
    last_tranche_i, last_tranche_px, last_trim_i = -999, np.inf, -999
    book = PutBook(otm, width)
    nav = np.empty(len(D)); prev = None; opt_pnl = 0.0
    for i in range(len(D)):
        row = D.iloc[i]; S, r, vx = row["qqq"], row["rf"], row["vxn"] / 100
        if i > 0:
            for k in core:
                core[k] *= 1 + row["r_" + k]
            trend *= (1 + row["r_qqq"]) if trend_on else (1 + r / 252)
            if lev > 0:
                lev *= 1 + row["r_qld"]; lev_days += 1
            cash *= 1 + r / 252
            if book.units:
                book.left -= 1
                if book.left <= 0:
                    x = book.expire(S); cash += x; opt_pnl += x
        V = sum(core.values()) + trend + lev + cash + book.mark(S, r, vx)
        if prev is not None:
            p, px, ma, recede = prev["p"], prev["qqq"], prev["ma200"], prev["vxn_recede"]

            def buy_core(amt):
                nonlocal cash
                amt = min(amt, cash - (book.units * book.K if (block and book.units) else 0))   # block=True keeps collateral
                if amt <= 1:
                    return
                for k, w in c.core:
                    core[k] += amt * w * (1 - c.cost)
                cash -= amt

            if lev > 0:
                gain = lev / lev_cost_basis - 1
                if (p <= c.lev_exit_p and px > ma) or gain >= c.lev_tp or lev_days >= c.lev_max_days:
                    cash += lev * (1 - c.lev_cost); lev, lev_cost_basis, lev_days = 0.0, 0.0, 0
                    excess = cash - (1 - c.core_target) * V
                    if excess > 0:
                        buy_core(excess)
            if not np.isnan(p) and p >= c.tranche_p and i - last_tranche_i >= c.tranche_gap and \
                    (px <= c.tranche_step * last_tranche_px or i - last_tranche_i > 126):
                buy_core(c.tranche * V); last_tranche_i, last_tranche_px = i, px
            if not np.isnan(p) and p >= c.lev_p and recede and lev < c.lev_cap * V:
                free = cash - (book.units * book.K if (block and book.units) else 0)
                amt = min(c.lev_size * V, c.lev_cap * V - lev, free)
                if amt > 1:
                    lev += amt * (1 - c.lev_cost); lev_cost_basis += amt; cash -= amt
            if not np.isnan(p) and p <= c.greed_p and px >= c.greed_stretch * ma and i - last_trim_i >= 21:
                core_v = sum(core.values()) + trend; over = core_v - c.core_target * V
                if over > 0.01 * V:
                    f = over / core_v
                    for k in core:
                        cash += core[k] * f * (1 - c.cost); core[k] *= 1 - f
                    cash += trend * f * ((1 - c.cost) if trend_on else 1); trend *= 1 - f
                    last_trim_i, last_tranche_px = i, np.inf
            if not np.isnan(ma):
                want = px >= 0.97 * ma
                if want != trend_on:
                    trend *= 1 - c.cost; trend_on = want
        # write puts on the free powder
        if not book.units and sig.iloc[i] and frac > 0:
            notional = frac * max(cash, 0)
            if notional > 1000:
                x = book.open(S, r, vx, notional); cash += x; opt_pnl += x
        nav[i] = sum(core.values()) + trend + lev + cash + book.mark(S, r, vx)
        prev = row
    return pd.Series(nav, idx), opt_pnl


def risk_row(nav, rf):
    st = perf_stats(nav, rf)
    m = nav.resample("ME").last().pct_change().dropna()
    return dict(**st, skew_m=m.skew(), worst_month=m.min(), cvar5_m=m[m <= m.quantile(0.05)].mean(),
                ret_2008=nav.loc["2008"].iloc[-1] / nav.loc["2008"].iloc[0] - 1,
                ret_2020q1=nav.loc["2020-01":"2020-03"].iloc[-1] / nav.loc["2020-01"].iloc[0] - 1,
                ret_2022=nav.loc["2022"].iloc[-1] / nav.loc["2022"].iloc[0] - 1)


def main():
    P = load_panel(); S = build_signals(P); rf = P["rf"]
    C = conditions(P, S)
    rows = []
    for cn, cond in C.items():
        for otm in [0.0, 0.05, 0.10]:
            for width in [0.0, 0.10]:
                nav, act = standalone(P, cond, otm, width)
                rows.append(dict(condition=cn, strike=f"{otm:.0%} OTM", structure="spread (long 10% lower)" if width else "naked cash-secured",
                                 active=act, **risk_row(nav, rf)))
    T = pd.DataFrame(rows)
    tb = perf_stats((1 + P.loc[A_:B_, "rf"] / 252).cumprod(), rf)
    T.to_csv(RES / "vol_selling_standalone.csv", index=False)
    pd.set_option("display.width", 250)
    print(T[["condition", "strike", "structure", "active", "CAGR", "Vol", "Sharpe", "Sortino", "MaxDD", "skew_m", "worst_month",
             "ret_2008", "ret_2020q1", "ret_2022"]].round(3).to_string())
    # benchmarks for the standalone sleeve
    qqq = bh(prepare(P, S), {"qqq": 1.0}, A_, B_)
    print("QQQ B&H", {k: round(v, 3) for k, v in risk_row(qqq, rf).items()})


if __name__ == "__main__":
    main()


def overlay_main():
    P = load_panel(); S = build_signals(P); rf = P["rf"]; D = prepare(P, S)
    C = conditions(P, S)
    picks = [("always", 0.0, 0.0), ("always", 0.05, 0.0), ("always", 0.05, 0.10), ("VXN ≥ its median", 0.05, 0.0),
             ("fear 50–80th pct", 0.0, 0.0), ("fear ≥ 50th & receding", 0.0, 0.0), ("fear ≥ 50th & receding", 0.05, 0.0),
             ("fear ≥ 80th & receding", 0.0, 0.0)]
    rows = []
    base, _ = _run_with_puts(D, Cfg("v2", core=(("qqq", 0.5), ("spy", 0.5)), tranche=0.075, tranche_step=0.92,
                                    lev_cap=0.30, trend_guard=True, lev="qld"), P, C["always"], 0, 0, 0.0, 100_000.0)
    rows.append(dict(overlay="none (strategy as on slide 11)", frac=0.0, **risk_row(base, rf), opt_pnl=0.0))
    navs = {"none": base}
    cfg = Cfg("v2", core=(("qqq", 0.5), ("spy", 0.5)), tranche=0.075, tranche_step=0.92, lev_cap=0.30,
              trend_guard=True, lev="qld")
    for block in [False, True]:
        for cn, otm, w in picks:
            for frac in [0.33, 0.67, 1.0]:
                nav, pnl = _run_with_puts(D, cfg, P, C[cn], otm, w, frac, 100_000.0, block)
                lab = f"{cn} · {otm:.0%} OTM{' spread' if w else ''}"
                rows.append(dict(overlay=lab, frac=frac, collateral_locked=block, **risk_row(nav, rf), opt_pnl=pnl))
                navs[(lab, frac, block)] = nav
    T = pd.DataFrame(rows)
    T.to_csv(RES / "vol_selling_overlay.csv", index=False)
    pd.to_pickle(navs, "/tmp/vol_overlay_navs.pkl")
    pd.set_option("display.width", 250)
    print(T[["overlay", "frac", "collateral_locked", "CAGR", "Vol", "Sharpe", "Sortino", "MaxDD", "Calmar", "skew_m", "worst_month", "ret_2008",
             "ret_2020q1", "ret_2022", "opt_pnl"]].round(3).to_string())
