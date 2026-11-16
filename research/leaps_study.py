"""QQQ LEAPS calls instead of QLD / TQQQ — does convexity raise the Sharpe ratio?

MODEL-PRICED, not a real option chain (that is the QuantConnect task). Pricing:
  * Black-Scholes on the (dividend-adjusted) QQQ series, r = T-bill, q = 0.
  * ATM implied vol from VXN (30-day), mean-reverting toward LR_VOL with horizon:
        iv_atm(T) = LR + (VXN - LR) * (1 - exp(-k T)) / (k T)
  * skew: iv(K) = iv_atm(T) + SKEW * ln(S/K) / sqrt(T)   (ITM calls carry higher IV), floor 12%
  * bid/ask: SPREAD of premium paid on every buy and every sell; roll when the time left
    is below ROLL_FRAC of the original DTE (sell old, buy new at the same target delta and DTE).
Tests (QQQ+SPY core, 2007-02 -> 2026-09, $100k, same fear rules as research/strategy.py v2 + trend guard):
  A  leverage sleeve = LEAPS, exposure-matched to QLD (dollar delta = 2 x the QLD dollars;
     unspent dollars stay in T-bills)
  B  leverage sleeve = LEAPS, dollar-matched (same 10% of NAV per buy as QLD, cap 30%)
  C  static 70/30 (35% QQQ + 35% SPY + 30% T-bills) with the QQQ 35% replaced by LEAPS of the
     same dollar delta; checked monthly, only the difference is traded and only when the LEAPS
     dollar delta is outside ±20% of target — does LEAPS beta beat ETF beta on Sharpe?
Outputs: results/leaps_grid.csv, figures/fig_leaps_sharpe.png
"""
import numpy as np
import pandas as pd
from scipy.special import ndtr

from common import (BLUE, GRID, INK, INK2, MUTED, ORANGE, RES, SEQ5, build_signals, load_panel, perf_stats,
                    plt, savefig)
from strategy import Cfg, prepare

LR_VOL, KAPPA, SKEW, IV_FLOOR = 0.23, 2.0, 0.25, 0.12
SPREAD, ROLL_FRAC = 0.015, 0.25
DELTAS = [0.5, 0.6, 0.7, 0.8, 0.9]
DTES = [180, 365, 540, 730]
A_, B_ = "2007-02-01", "2026-09-11"


def iv_of(S, K, T, vxn):
    atm = LR_VOL + (vxn - LR_VOL) * (1 - np.exp(-KAPPA * T)) / (KAPPA * T)
    return max(atm + SKEW * np.log(S / K) / np.sqrt(T), IV_FLOOR)


def bs(S, K, T, r, sig):
    if T <= 1e-6:
        return max(S - K, 0.0), float(S > K)
    v = sig * np.sqrt(T)
    d1 = (np.log(S / K) + (r + 0.5 * sig * sig) * T) / v
    return S * ndtr(d1) - K * np.exp(-r * T) * ndtr(d1 - v), ndtr(d1)


def strike_for(S, T, r, vxn, target):
    lo, hi = S * 0.2, S * 3.0
    for _ in range(60):
        K = 0.5 * (lo + hi)
        _, d = bs(S, K, T, r, iv_of(S, K, T, vxn))
        if d > target:
            lo = K
        else:
            hi = K
    return K


class Leaps:
    """A position in one LEAPS line (fractional contracts, 1 unit = 1 share of QQQ)."""

    def __init__(self, delta, dte):
        self.delta_t, self.dte = delta, dte
        self.units, self.K, self.T, self.T0 = 0.0, None, 0.0, dte / 365

    def price(self, S, r, vxn):
        if self.units == 0:
            return 0.0, 0.0
        p, d = bs(S, self.K, self.T, r, iv_of(S, self.K, self.T, vxn))
        return p, d

    def value(self, S, r, vxn):
        return self.units * self.price(S, r, vxn)[0]

    def dollar_delta(self, S, r, vxn):
        return self.units * self.price(S, r, vxn)[1] * S

    def _open(self, S, r, vxn, dollars):
        self.T = self.T0
        self.K = strike_for(S, self.T, r, vxn, self.delta_t)
        p, d = bs(S, self.K, self.T, r, iv_of(S, self.K, self.T, vxn))
        self.units = dollars * (1 - SPREAD) / p
        return p, d

    def buy(self, S, r, vxn, dollars):
        """add dollars of premium: opens a new contract if flat, else buys more of the held contract."""
        if self.units > 0:
            p, _ = self.price(S, r, vxn)
            self.units += dollars * (1 - SPREAD) / p
            return
        return self._open(S, r, vxn, dollars)

    def trade_dollar_delta(self, S, r, vxn, dd_change):
        """buy (dd_change>0) or sell units of the held contract; returns cash flow (negative = paid)."""
        p, d = self.price(S, r, vxn)
        du = dd_change / (d * S)
        if du > 0:
            self.units += du
            return -du * p / (1 - SPREAD)
        du = min(-du, self.units)
        self.units -= du
        return du * p * (1 - SPREAD)

    def cost_for_dollar_delta(self, S, r, vxn, dd):
        T = self.T0
        K = strike_for(S, T, r, vxn, self.delta_t)
        p, d = bs(S, K, T, r, iv_of(S, K, T, vxn))
        return dd / (d * S) * p / (1 - SPREAD)

    def sell(self, S, r, vxn):
        v = self.value(S, r, vxn) * (1 - SPREAD)
        self.units, self.K = 0.0, None
        return v

    def step(self, days=1):
        if self.units:
            self.T -= days / 365.25

    def maybe_roll(self, S, r, vxn):
        if self.units and self.T <= ROLL_FRAC * self.T0:
            proceeds = self.sell(S, r, vxn)
            self._open(S, r, vxn, proceeds)
            return True
        return False


def run_fear(D, c, leaps_delta, leaps_dte, sizing, capital=100_000.0):
    """Copy of strategy.run with the leverage sleeve held as LEAPS."""
    D = D.loc[A_:B_].dropna(subset=["r_qqq", "r_spy"])
    idx = D.index
    core = {k: capital * c.core_target * w / 2 for k, w in c.core}       # trend guard on: half
    trend = capital * c.core_target / 2
    trend_on = True
    cash = capital - sum(core.values()) - trend
    L = Leaps(leaps_delta, leaps_dte)
    lev_cost_basis, lev_days = 0.0, 0
    last_tranche_i, last_tranche_px, last_trim_i = -999, np.inf, -999
    nav = np.empty(len(D)); expo = np.empty(len(D)); prev = None
    rolls = 0
    for i in range(len(D)):
        row = D.iloc[i]
        S, r, vx = row["qqq"], row["rf"], row["vxn"] / 100
        if i > 0:
            for k in core:
                core[k] *= 1 + row["r_" + k]
            trend *= (1 + row["r_qqq"]) if trend_on else (1 + r / 252)
            cash *= 1 + r / 252
            dt = (idx[i] - idx[i - 1]).days
            L.step(dt)
            if L.units:
                lev_days += 1
                rolls += L.maybe_roll(S, r, vx)
        lev = L.value(S, r, vx)
        V = sum(core.values()) + trend + lev + cash
        if prev is not None:
            p, px, ma, recede = prev["p"], prev["qqq"], prev["ma200"], prev["vxn_recede"]

            def buy_core(amt):
                nonlocal cash
                amt = min(amt, cash)
                if amt <= 1:
                    return
                for k, w in c.core:
                    core[k] += amt * w * (1 - c.cost)
                cash -= amt

            if L.units:
                gain = lev / lev_cost_basis - 1
                if (p <= c.lev_exit_p and px > ma) or gain >= c.lev_tp or lev_days >= c.lev_max_days:
                    cash += L.sell(S, r, vx)
                    lev_cost_basis, lev_days = 0.0, 0
                    excess = cash - (1 - c.core_target) * V
                    if excess > 0:
                        buy_core(excess)
            if not np.isnan(p) and p >= c.tranche_p and i - last_tranche_i >= c.tranche_gap and \
                    (px <= c.tranche_step * last_tranche_px or i - last_tranche_i > 126):
                if cash > 1:
                    buy_core(c.tranche * V)
                    last_tranche_i, last_tranche_px = i, px
            if not np.isnan(p) and p >= c.lev_p and recede and cash > 1:
                if sizing == "exposure":
                    # QLD equivalent: dollar delta target = 2 x lev_size x V, cap 2 x lev_cap x V
                    cur = L.dollar_delta(S, r, vx)
                    want = min(2 * c.lev_size * V, 2 * c.lev_cap * V - cur)
                    amt = L.cost_for_dollar_delta(S, r, vx, want) if want > 0 else 0
                else:
                    amt = min(c.lev_size * V, c.lev_cap * V - lev)
                amt = min(amt, cash)
                if amt > 1:
                    cash -= amt
                    lev_cost_basis += amt
                    L.buy(S, r, vx, amt)
            if not np.isnan(p) and p <= c.greed_p and px >= c.greed_stretch * ma and i - last_trim_i >= 21:
                core_v = sum(core.values()) + trend
                over = core_v - c.core_target * V
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
        lev = L.value(S, r, vx)
        V = sum(core.values()) + trend + lev + cash
        nav[i] = V
        expo[i] = (sum(core.values()) + (trend if trend_on else 0) + L.dollar_delta(S, r, vx)) / V
        prev = row
    return pd.Series(nav, idx), pd.Series(expo, idx), rolls


def run_static_leaps(D, leaps_delta, leaps_dte, capital=100_000.0):
    """35% SPY + 35% QQQ-equivalent via LEAPS (same dollar delta) + rest T-bills, monthly re-size."""
    D = D.loc[A_:B_].dropna(subset=["r_qqq", "r_spy"])
    idx = D.index
    spy = 0.35 * capital
    L = Leaps(leaps_delta, leaps_dte)
    row = D.iloc[0]
    S, r, vx = row["qqq"], row["rf"], row["vxn"] / 100
    c0 = L.cost_for_dollar_delta(S, r, vx, 0.35 * capital)
    L.buy(S, r, vx, c0)
    cash = capital - spy - c0
    nav = np.empty(len(D)); expo = np.empty(len(D)); last_m = idx[0].month
    for i in range(len(D)):
        row = D.iloc[i]
        S, r, vx = row["qqq"], row["rf"], row["vxn"] / 100
        if i > 0:
            spy *= 1 + row["r_spy"]
            cash *= 1 + r / 252
            L.step((idx[i] - idx[i - 1]).days)
            L.maybe_roll(S, r, vx)
        V = spy + L.value(S, r, vx) + cash
        if idx[i].month != last_m:                     # monthly check: back to 35/35/30 in delta terms
            last_m = idx[i].month
            spy_t = 0.35 * V
            cash += spy - spy_t; spy = spy_t
            dd, tgt = L.dollar_delta(S, r, vx), 0.35 * V
            if dd < 0.8 * tgt or dd > 1.2 * tgt:         # trade only the difference, only outside a ±20% band
                cash += L.trade_dollar_delta(S, r, vx, tgt - dd)
        V = spy + L.value(S, r, vx) + cash
        nav[i] = V
        expo[i] = (spy + L.dollar_delta(S, r, vx)) / V
    return pd.Series(nav, idx), pd.Series(expo, idx)


def run_static_etf(D, capital=100_000.0):
    D = D.loc[A_:B_].dropna(subset=["r_qqq", "r_spy"])
    r = 0.35 * D["r_qqq"] + 0.35 * D["r_spy"] + 0.30 * D["rf"] / 252   # monthly-rebalanced ≈ daily here
    return capital * (1 + r).cumprod()


def main():
    P = load_panel()
    D = prepare(P, build_signals(P))
    rf = P["rf"]
    c = Cfg("v2", core=(("qqq", 0.5), ("spy", 0.5)), tranche=0.075, tranche_step=0.92, lev_cap=0.30,
            trend_guard=True, lev="qld")
    rows = []
    for sizing in ["exposure", "dollars"]:
        for d in DELTAS:
            for T in DTES:
                nav, ex, rolls = run_fear(D, c, d, T, sizing)
                st = perf_stats(nav, rf)
                rows.append(dict(test=f"{'A' if sizing == 'exposure' else 'B'}: fear sleeve, {sizing}-matched",
                                 delta=d, dte=T, **st, avg_expo=ex.mean(), peak_expo=ex.max(), rolls=rolls))
                print(rows[-1]["test"][:2], d, T, round(st["Sharpe"], 3), f"{st['CAGR']:.3%}", f"{st['MaxDD']:.1%}",
                      round(ex.max(), 2), flush=True)
    for d in DELTAS:
        for T in DTES:
            nav, ex = run_static_leaps(D, d, T)
            st = perf_stats(nav, rf)
            rows.append(dict(test="C: static 70/30, QQQ leg as LEAPS", delta=d, dte=T, **st,
                             avg_expo=ex.mean(), peak_expo=ex.max(), rolls=np.nan))
            print("C", d, T, round(st["Sharpe"], 3), f"{st['CAGR']:.3%}", f"{st['MaxDD']:.1%}", round(ex.mean(), 2), flush=True)
    G = pd.DataFrame(rows)
    st = perf_stats(run_static_etf(D), rf)
    G.attrs["static_etf"] = st
    G.to_csv(RES / "leaps_grid.csv", index=False)
    pd.DataFrame([dict(name="static 70/30 ETF", **st)]).to_csv(RES / "leaps_baselines.csv", index=False)
    print("static ETF", {k: round(v, 3) for k, v in st.items()})


if __name__ == "__main__":
    main()
