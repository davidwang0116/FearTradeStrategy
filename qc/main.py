# region imports
from AlgorithmImports import *
# endregion
"""Fear-Tranche Accumulator — QuantConnect algorithm (backtest + paper/live).

Same rules as research/strategy.py (variant "v2 + QLD + trend guard"); every
threshold is a QC parameter so the optimizer / walk-forward can sweep it.

Sleeves (tracked in a virtual book so the same ETF can sit in two sleeves):
  core   fear-tranched beta  (CORE, e.g. "QQQ:1" or "QQQM:0.5,VOO:0.5")
  trend  trend-guarded half of the core (QQQ while QQQ >= 0.97 x MA200, else powder)
  lev    leverage sleeve: "QLD" | "TQQQ" | "LEAPS" | "NONE"
  powder dry powder in POWDER ETF (BIL/SGOV) or cash

Timing: signal on the daily bar that closes on day t (arrives after the close),
orders are market-on-open for t+1 (QC fills at the next open in backtests).

STATUS — written and logic-checked offline, NOT yet run on QC.  First run:
  1. Check the log lines tagged [PROBE]: data start dates for QQQ/VXN/QLD/TQQQ/BIL.
  2. Compare the [SIGNAL] composite for a few dates against results/signal_reference.csv.
  3. LEAPS mode is a skeleton (TODO-5): check chain filter, Greeks and marks first.
"""
from collections import deque

import numpy as np
import pandas as pd

from signals import composite_frame


def _p(algo, name, default, cast=float):
    v = algo.get_parameter(name)
    return cast(v) if v not in (None, "") else default


class FearTrancheAccumulator(QCAlgorithm):

    def initialize(self):
        self.set_start_date(_p(self, "start_year", 2011, int), 1, 1)
        end_year = _p(self, "end_year", 0, int)
        if end_year:
            self.set_end_date(end_year, 12, 31)
        self.set_cash(_p(self, "capital", 100_000))
        self.set_brokerage_model(BrokerageName.INTERACTIVE_BROKERS_BROKERAGE, AccountType.MARGIN)

        # ---- parameters (defaults = pre-registered v2) ----
        self.core_target = _p(self, "core_target", 0.70)
        self.tranche = _p(self, "tranche", 0.075)
        self.tranche_p = _p(self, "tranche_p", 0.80)
        self.tranche_gap = _p(self, "tranche_gap", 10, int)
        self.tranche_step = _p(self, "tranche_step", 0.92)
        self.lev_mode = (self.get_parameter("lev") or "QLD").upper()
        self.lev_p = _p(self, "lev_p", 0.90)
        self.lev_size = _p(self, "lev_size", 0.10)
        self.lev_cap = _p(self, "lev_cap", 0.30)
        self.lev_tp = _p(self, "lev_tp", 0.60)
        self.lev_exit_p = _p(self, "lev_exit_p", 0.50)
        self.lev_max_days = _p(self, "lev_max_days", 378, int)
        self.greed_p = _p(self, "greed_p", 0.15)
        self.greed_stretch = _p(self, "greed_stretch", 1.08)
        self.trend_guard = _p(self, "trend_guard", 1, int) == 1
        self.trend_band = _p(self, "trend_band", 0.97)

        core_spec = self.get_parameter("core") or "QQQ:1"
        self.core_w = {t.split(":")[0]: float(t.split(":")[1]) for t in core_spec.split(",")}
        powder = self.get_parameter("powder") or "BIL"

        norm = DataNormalizationMode.ADJUSTED if self.live_mode else DataNormalizationMode.TOTAL_RETURN
        if self.lev_mode == "LEAPS":
            norm = DataNormalizationMode.RAW   # option strikes need the raw underlying price
        add = lambda t: self.add_equity(t, Resolution.DAILY, data_normalization_mode=norm).symbol
        self.qqq = add("QQQ")
        self.core_syms = {t: add(t) for t in self.core_w}
        self.powder = add(powder) if powder != "CASH" else None
        self.lev_sym = add(self.lev_mode) if self.lev_mode in ("QLD", "TQQQ") else None
        self.vxn = self.add_index("VXN", Resolution.DAILY).symbol
        if self.lev_mode == "LEAPS":
            self._init_leaps()

        # ---- seed signal history (no look-ahead: history ends before start) ----
        hist = self.history([self.qqq], 900, Resolution.DAILY)
        vh = self.history([self.vxn], 900, Resolution.DAILY)
        self.px_hist = deque(maxlen=900)
        self.vxn_hist = deque(maxlen=900)
        if not hist.empty:
            for t, row in hist.loc[self.qqq].iterrows():
                self.px_hist.append((pd.Timestamp(t).normalize(), float(row["close"])))
        if not vh.empty:
            for t, row in vh.loc[self.vxn].iterrows():
                self.vxn_hist.append((pd.Timestamp(t).normalize(), float(row["close"])))
        self.comp_hist = []          # composite history for the expanding percentile
        self._seed_composite()

        # ---- virtual book (fractions of NAV, re-based daily from realised returns) ----
        self.book = None
        self.trend_on = True
        self.lev_cost_basis = 0.0
        self.lev_days = 0
        self.last_tranche_i = -999
        self.last_tranche_px = float("inf")
        self.last_trim_i = -999
        self.i = 0
        self.prev_close = {}
        self.vxn_max10 = deque(maxlen=10)
        self.set_warm_up(timedelta(days=5))
        self.log(f"[PROBE] seeded {len(self.px_hist)} QQQ bars, {len(self.vxn_hist)} VXN bars, "
                 f"{len(self.comp_hist)} composite values")

    # ------------------------------------------------------------------ signals
    def _frame(self):
        px = pd.Series(dict(self.px_hist)).sort_index()
        vx = pd.Series(dict(self.vxn_hist)).sort_index()
        return composite_frame(px, vx)

    def _seed_composite(self):
        if len(self.px_hist) < 300 or len(self.vxn_hist) < 200:
            return
        f = self._frame()
        self.comp_hist = f["composite"].dropna().tolist()

    def _pct(self, x):
        h = np.asarray(self.comp_hist)
        if len(h) < 504 or np.isnan(x):        # needs 2y of history, else no signal
            return float("nan")
        return float((h <= x).mean())

    # ------------------------------------------------------------------ main loop
    def on_data(self, data: Slice):
        if self.is_warming_up or not data.bars.contains_key(self.qqq):
            return
        t = self.time.date()
        close = float(data.bars[self.qqq].close)
        self.px_hist.append((pd.Timestamp(t), close))
        vbar = data.bars.get(self.vxn) if data.bars.contains_key(self.vxn) else None
        if vbar is not None:
            v = float(vbar.close)
            self.vxn_hist.append((pd.Timestamp(t), v))
            self.vxn_max10.append(v)
        f = self._frame()
        comp = float(f["composite"].iloc[-1])
        ma200 = float(pd.Series([p for _, p in self.px_hist]).iloc[-200:].mean())
        p = self._pct(comp)
        if not np.isnan(comp):
            self.comp_hist.append(comp)
        recede = len(self.vxn_max10) == 10 and self.vxn_max10[-1] <= 0.85 * max(self.vxn_max10)
        self.plot("Signal", "composite", comp)
        self.plot("Signal", "pctile x100", 0 if np.isnan(p) else 100 * p)

        nav = self.portfolio.total_portfolio_value
        if self.book is None:
            self._init_book()
        self._drift_book(data)
        self.i += 1
        changed = False
        why = []

        # leverage exit
        lev_val = self.book["lev"] * nav
        if self.book["lev"] > 0:
            self.lev_days += 1
            gain = lev_val / max(self.lev_cost_basis, 1e-9) - 1
            if (p <= self.lev_exit_p and close > ma200) or gain >= self.lev_tp or self.lev_days >= self.lev_max_days:
                self.book["powder"] += self.book["lev"]
                self.book["lev"] = 0.0
                self.lev_cost_basis, self.lev_days = 0.0, 0
                excess = self.book["powder"] - (1 - self.core_target)
                if excess > 0:
                    self.book["powder"] -= excess
                    self.book["core"] += excess
                changed = True; why.append(f"lev exit {gain:+.0%}")
        # tranche buy
        if not np.isnan(p) and p >= self.tranche_p and self.i - self.last_tranche_i >= self.tranche_gap and \
                (close <= self.tranche_step * self.last_tranche_px or self.i - self.last_tranche_i > 126):
            amt = min(self.tranche, self.book["powder"])
            if amt > 0.001:
                self.book["powder"] -= amt; self.book["core"] += amt
                self.last_tranche_i, self.last_tranche_px = self.i, close
                changed = True; why.append(f"tranche {amt:.1%}")
        # leverage entry
        if self.lev_mode != "NONE" and not np.isnan(p) and p >= self.lev_p and recede \
                and self.book["lev"] < self.lev_cap and self.book["powder"] > 0.001:
            amt = min(self.lev_size, self.lev_cap - self.book["lev"], self.book["powder"])
            if amt > 0.001:
                self.book["powder"] -= amt; self.book["lev"] += amt
                self.lev_cost_basis += amt * nav
                changed = True; why.append(f"lev buy {amt:.1%}")
        # greed trim
        if not np.isnan(p) and p <= self.greed_p and close >= self.greed_stretch * ma200 \
                and self.i - self.last_trim_i >= 21:
            core_tot = self.book["core"] + self.book["trend"]
            over = core_tot - self.core_target
            if over > 0.01:
                k = over / core_tot
                self.book["powder"] += over
                self.book["core"] *= 1 - k; self.book["trend"] *= 1 - k
                self.last_trim_i = self.i; self.last_tranche_px = float("inf")
                changed = True; why.append(f"greed trim {over:.1%}")
        # trend guard
        if self.trend_guard:
            want = close >= self.trend_band * ma200
            if want != self.trend_on:
                self.trend_on = want
                changed = True; why.append("trend " + ("on" if want else "off"))

        self.log(f"[SIGNAL] {t} close={close:.2f} comp={comp:.2f} p={p:.3f} recede={recede} book={self._fmt()}")
        if changed:
            self.log(f"[TRADE] {t} {', '.join(why)}")
            self._rebalance()

    # ------------------------------------------------------------------ book helpers
    def _init_book(self):
        c = self.core_target
        self.book = {"core": c / 2 if self.trend_guard else c, "trend": c / 2 if self.trend_guard else 0.0,
                     "lev": 0.0, "powder": 1 - c}
        self._rebalance()

    def _drift_book(self, data):
        """Re-base sleeve fractions from actual holdings so the book tracks the account."""
        nav = self.portfolio.total_portfolio_value
        if nav <= 0:
            return
        core_val = sum(self.portfolio[s].holdings_value for s in self.core_syms.values())
        lev_val = self._lev_value()
        powder_val = nav - core_val - lev_val
        tot_core = self.book["core"] + (self.book["trend"] if self.trend_on else 0)
        if tot_core > 0:
            share = self.book["core"] / tot_core
            self.book["core"] = core_val * share / nav
            if self.trend_on:
                self.book["trend"] = core_val * (1 - share) / nav
        if not self.trend_on:
            # trend sleeve sits in powder: keep its fraction, powder = rest
            powder_val -= self.book["trend"] * nav
        self.book["lev"] = lev_val / nav
        self.book["powder"] = max(powder_val / nav, 0.0)

    def _lev_value(self):
        if self.lev_sym is not None:
            return self.portfolio[self.lev_sym].holdings_value
        if self.lev_mode == "LEAPS":
            return sum(h.holdings_value for s, h in self.portfolio.items()
                       if s.security_type == SecurityType.OPTION and h.invested)
        return 0.0

    def _rebalance(self):
        targets = []
        core_frac = self.book["core"] + (self.book["trend"] if self.trend_on else 0.0)
        tot_w = sum(self.core_w.values())
        for t, s in self.core_syms.items():
            targets.append(PortfolioTarget(s, core_frac * self.core_w[t] / tot_w))
        if self.lev_sym is not None:
            targets.append(PortfolioTarget(self.lev_sym, self.book["lev"]))
        if self.powder is not None:
            powder_frac = self.book["powder"] + (0.0 if self.trend_on else self.book["trend"])
            targets.append(PortfolioTarget(self.powder, max(powder_frac - 0.01, 0.0)))   # 1% cash buffer
        self.set_holdings(targets)
        if self.lev_mode == "LEAPS":
            self._rebalance_leaps()

    def _fmt(self):
        return " ".join(f"{k}={v:.1%}" for k, v in self.book.items()) + f" trend_on={self.trend_on}"

    # ------------------------------------------------------------------ LEAPS (TODO-5 skeleton)
    def _init_leaps(self):
        opt = self.add_option(self.qqq, Resolution.DAILY)
        opt.set_filter(lambda u: u.calls_only().strikes(-40, 5).expiration(450, 800))
        self.opt_symbol = opt.symbol
        self.leaps_target_delta = _p(self, "leaps_delta", 0.75)
        self.leaps_roll_dte = _p(self, "leaps_roll_dte", 250, int)

    def _rebalance_leaps(self):
        """Hold LEAPS calls whose $-delta = 2 x lev sleeve dollars (2x exposure, defined risk).
        TODO-5: validate chain coverage, Greeks availability at daily resolution, mid-price marks,
        roll at DTE <= leaps_roll_dte, and the cash ledger before trusting any result."""
        chain = self.current_slice.option_chains.get(self.opt_symbol) if self.current_slice else None
        nav = self.portfolio.total_portfolio_value
        want_dollar_delta = 2 * self.book["lev"] * nav
        held = [s for s, h in self.portfolio.items() if s.security_type == SecurityType.OPTION and h.invested]
        if want_dollar_delta <= 0:
            for s in held:
                self.liquidate(s, tag="LEAPS exit")
            return
        if held or chain is None:
            return
        calls = [c for c in chain if c.greeks is not None and c.greeks.delta]
        if not calls:
            self.log("[LEAPS] no contracts with Greeks today — skipped")
            return
        best = min(calls, key=lambda c: (abs(c.greeks.delta - self.leaps_target_delta), -c.expiry.toordinal()))
        mid = (best.bid_price + best.ask_price) / 2 if best.ask_price > 0 else best.last_price
        if mid <= 0:
            return
        n = int(want_dollar_delta / (best.greeks.delta * best.underlying_last_price * 100))
        if n > 0:
            self.market_order(best.symbol, n, tag=f"LEAPS d={best.greeks.delta:.2f} K={best.strike}")

    def on_end_of_algorithm(self):
        self.log(f"[END] book={self._fmt()} NAV={self.portfolio.total_portfolio_value:,.0f}")
