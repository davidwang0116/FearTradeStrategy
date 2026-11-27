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
  hedge  overlay=HEDGE12M: one ~12-month QQQ put at hedge_moneyness (0.85) of spot, research/options_overlay.py
         (bought when fear pct <= 0.50; rolled with < 4 months left only while pct <= 0.50; otherwise held and
         sold 2 days before expiry). hedge_cover = all | unguarded, hedge_exit = fear | rolldown | hold,
         hedge_proceeds = tbill (P1, kept out of the powder) | tranche (P2, powder before same-day tranche sizing).
         Run with capital = 1,000,000 (one QQQ contract is ~$68k of stock). Default overlay=NONE keeps v2 as is.
         The overlay needs RAW prices (strikes), which also changes the signal inputs slightly (no dividend
         adjustment). For the unhedged control run, set price_mode=raw so both runs see the same signal.

Timing: signal on the daily bar that closes on day t (arrives after the close),
orders are market-on-open for t+1 (QC fills at the next open in backtests).

STATUS — written and logic-checked offline, NOT yet run on QC.  First run:
  1. Check the log lines tagged [PROBE]: data start dates for QQQ/VXN/QLD/TQQQ/BIL.
  2. Compare the [SIGNAL] composite for a few dates against results/signal_reference.csv.
  3. LEAPS mode is a skeleton (TODO-5): check chain filter, Greeks and marks first.
  4. overlay=HEDGE12M: written offline, not yet run. Check the [OPT] lines (fills at ask/bid, contract counts,
     no stale quotes) against qc/options_quote_audit.ipynb before trusting the result.
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

        # ---- options overlay (research/options_overlay.py) ----
        self.overlay = (self.get_parameter("overlay") or "NONE").upper()
        self.hedge_cover = (self.get_parameter("hedge_cover") or "unguarded").lower()
        self.hedge_exit = (self.get_parameter("hedge_exit") or "hold").lower()
        self.hedge_proceeds = (self.get_parameter("hedge_proceeds") or "tranche").lower()
        self.hedge_m = _p(self, "hedge_moneyness", 0.85)
        self.hedge_dte = _p(self, "hedge_dte", 365, int)
        self.hedge_roll_dte = _p(self, "hedge_roll_dte", 122, int)
        self.hedge_entry_p = _p(self, "hedge_entry_p", 0.50)
        self.hedge_exit_p = _p(self, "hedge_exit_p", 0.90)
        self.hedge_rolldown = _p(self, "hedge_rolldown_delta", -0.60)
        if self.overlay != "NONE" and self.lev_mode == "LEAPS":
            raise ValueError("overlay=HEDGE12M and lev=LEAPS both hold QQQ options; run them separately")

        norm = DataNormalizationMode.ADJUSTED if self.live_mode else DataNormalizationMode.TOTAL_RETURN
        force_raw = (self.get_parameter("price_mode") or "auto").lower() == "raw"   # unhedged control for HEDGE12M
        if self.lev_mode == "LEAPS" or self.overlay != "NONE" or force_raw:
            norm = DataNormalizationMode.RAW   # option strikes need the raw underlying price
        add = lambda t: self.add_equity(t, Resolution.DAILY, data_normalization_mode=norm).symbol
        self.qqq = add("QQQ")
        self.core_syms = {t: add(t) for t in self.core_w}
        self.powder = add(powder) if powder != "CASH" else None
        self.lev_sym = add(self.lev_mode) if self.lev_mode in ("QLD", "TQQQ") else None
        self.vxn = self.add_index("VXN", Resolution.DAILY).symbol
        if self.lev_mode == "LEAPS":
            self._init_leaps()
        self.hedge_sym, self.hedge_bucket, self.hedge_delta = None, 0.0, 0.0
        if self.overlay == "HEDGE12M":
            hopt = self.add_option(self.qqq, Resolution.DAILY)
            # wide filter: a held put stays in the universe as it ages and goes deep in the money; the purchase
            # itself only considers contracts within +-120 days of hedge_dte (see _hedge_buy)
            hopt.set_filter(lambda u: u.puts_only().strikes(-200, 200).expiration(0, self.hedge_dte + 120))
            self.hedge_opt = hopt.symbol

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

        # options overlay, step 1: exits / rolls on today's signal, credited before tranche sizing
        if self.overlay == "HEDGE12M" and self.hedge_sym is not None:
            changed |= self._hedge_exit(data, p, recede, nav, why)

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

        # options overlay, step 4: entry in calm
        if self.overlay == "HEDGE12M" and self.hedge_sym is None and not np.isnan(p) and p <= self.hedge_entry_p:
            changed |= self._hedge_buy(data, nav, "entry", why)

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
        powder_val = nav - core_val - lev_val - self._hedge_value() - self.hedge_bucket   # puts and P1 cash are not powder
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
            powder_frac += self.hedge_bucket / max(self.portfolio.total_portfolio_value, 1e-9)   # P1 cash sits in T-bills too
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

    # ------------------------------------------------------------------ 12-month put hedge (overlay=HEDGE12M)
    def _hedge_value(self):
        if self.overlay == "NONE" or self.hedge_sym is None:
            return 0.0
        return self.portfolio[self.hedge_sym].holdings_value

    def _cover_dollars(self, nav):
        cover = self.book["core"] + 2 * self.book["lev"]
        if self.hedge_cover == "all" and self.trend_on:
            cover += self.book["trend"]
        return cover * nav

    def _quote(self, data, sym):
        """Chain entry for sym (for Greeks), or None."""
        chain = data.option_chains.get(self.hedge_opt) if data.option_chains.contains_key(self.hedge_opt) else None
        if chain is None:
            return None
        for c in chain:
            if c.symbol == sym:
                return c
        return None

    def _put_delta(self, sym):
        """Black-Scholes put delta from the held contract's own mid price (IV by bisection), used when the
        chain has no Greeks for it. Quotes come from self.securities, which keeps a held contract subscribed."""
        sec = self.securities[sym]
        mid = (sec.bid_price + sec.ask_price) / 2 if sec.ask_price > 0 else sec.price
        S = float(self.securities[self.qqq].price)
        K = float(sym.id.strike_price)
        T = max((sym.id.date - self.time).days, 1) / 365.0
        r = 0.03
        if mid <= 0 or S <= 0:
            return None
        from math import erf, exp, log, sqrt
        N = lambda x: 0.5 * (1 + erf(x / sqrt(2)))
        def price_delta(sig):
            v = sig * sqrt(T); d1 = (log(S / K) + (r + 0.5 * sig * sig) * T) / v
            return K * exp(-r * T) * N(-(d1 - v)) - S * N(-d1), N(d1) - 1.0
        lo, hi = 0.01, 3.0
        for _ in range(60):
            mid_s = 0.5 * (lo + hi)
            if price_delta(mid_s)[0] > mid:
                hi = mid_s
            else:
                lo = mid_s
        return price_delta(0.5 * (lo + hi))[1]

    def _route(self, cash, nav):
        """Credit sale proceeds now (fills come at the next open) so same-day tranche sizing sees them (P2)."""
        if cash <= 0:
            return
        if self.hedge_proceeds == "tbill":
            self.hedge_bucket += cash
        else:
            self.book["powder"] += cash / nav

    def _hedge_sell(self, data, nav, why_tag, why):
        h = self.portfolio[self.hedge_sym]
        q = self.securities[self.hedge_sym]          # held contract: always subscribed, even outside the chain
        bid = q.bid_price
        if bid <= 0:
            self.log(f"[OPT] {self.time.date()} {why_tag}: no bid for {self.hedge_sym.value}, kept")
            return False
        n = h.quantity
        proceeds = bid * 100 * n
        self.market_order(self.hedge_sym, -n, tag=f"{why_tag} bid={bid:.2f}")
        self.log(f"[OPT] {self.time.date()} SELL {n} {self.hedge_sym.value} bid={bid:.2f} ask={q.ask_price:.2f} "
                 f"oi={q.open_interest} proceeds={proceeds:,.0f} ({proceeds / nav:.1%} NAV) -> {self.hedge_proceeds}")
        self._route(proceeds, nav)
        self.hedge_sym = None
        self.hedge_delta = 0.0
        why.append(why_tag)
        return True

    def _hedge_buy(self, data, nav, why_tag, why):
        chain = data.option_chains.get(self.hedge_opt) if data.option_chains.contains_key(self.hedge_opt) else None
        if chain is None:
            return False
        spot = float(self.securities[self.qqq].price)
        puts = [c for c in chain if c.right == OptionRight.PUT and c.ask_price > 0 and c.bid_price > 0
                and abs((c.expiry - self.time).days - self.hedge_dte) <= 120]
        if not puts:
            return False
        best = min(puts, key=lambda c: (abs(c.strike / spot - self.hedge_m) * 4 +
                                        abs((c.expiry - self.time).days - self.hedge_dte) / 365))
        want = int(round(self._cover_dollars(nav) / (100 * spot)))
        n = want
        cost = best.ask_price * 100 * n
        avail = self.book["powder"] * nav + self.hedge_bucket
        while n > 0 and cost > avail:
            n -= 1; cost = best.ask_price * 100 * n
        if n <= 0 or n < 0.5 * want:              # same rule as research/options_overlay.MIN_FILL: no token puts
            self.log(f"[OPT] {self.time.date()} {why_tag}: cash funds {n} of {want} contracts, skipped (retry later)")
            return False
        self.market_order(best.symbol, n, tag=f"{why_tag} ask={best.ask_price:.2f}")
        from_bucket = min(self.hedge_bucket, cost)
        self.hedge_bucket -= from_bucket
        self.book["powder"] -= (cost - from_bucket) / nav
        if why_tag == "entry" and self.hedge_bucket > 0:          # leftover P1 cash rejoins the powder in calm
            self.book["powder"] += self.hedge_bucket / nav
            self.hedge_bucket = 0.0
        self.hedge_sym = best.symbol
        self.hedge_delta = float(best.greeks.delta) if best.greeks is not None and best.greeks.delta else 0.0
        target = self._cover_dollars(nav)
        self.log(f"[OPT] {self.time.date()} BUY {n} {best.symbol.value} K={best.strike} exp={best.expiry.date()} "
                 f"ask={best.ask_price:.2f} bid={best.bid_price:.2f} oi={best.open_interest} cost={cost:,.0f} "
                 f"({cost / nav:.2%} NAV) cover={n * 100 * spot / max(target, 1e-9):.0%} of target")
        why.append(why_tag)
        return True

    def _hedge_exit(self, data, p, recede, nav, why):
        """Returns True if anything was traded. A failed re-buy after a sale leaves hedge_sym None, so the
        entry step retries after today's v2 rules (same as the local engine)."""
        q = self._quote(data, self.hedge_sym)
        days_left = (self.hedge_sym.id.date - self.time).days
        if q is not None and q.greeks is not None and q.greeks.delta:
            self.hedge_delta = float(q.greeks.delta)
        else:
            d = self._put_delta(self.hedge_sym)          # fresh every day: never act on a stale delta
            self.hedge_delta = d if d is not None else 0.0
        if days_left <= 2:                                                   # avoid exercise: sell instead
            return self._hedge_sell(data, nav, "expiry sale", why)
        if self.hedge_exit == "fear" and not np.isnan(p) and p >= self.hedge_exit_p and recede:
            return self._hedge_sell(data, nav, "fear exit", why)
        if self.hedge_exit == "rolldown" and self.hedge_delta <= self.hedge_rolldown:
            if self._hedge_sell(data, nav, "roll-down sell", why):
                self._hedge_buy(data, nav, "roll-down buy", why)
                return True
            return False
        if days_left < self.hedge_roll_dte and not np.isnan(p) and p <= self.hedge_entry_p:
            if self._hedge_sell(data, nav, "roll sell", why):
                self._hedge_buy(data, nav, "roll buy", why)
                return True
            return False
        return False

    def on_end_of_algorithm(self):
        self.log(f"[END] book={self._fmt()} NAV={self.portfolio.total_portfolio_value:,.0f}")
