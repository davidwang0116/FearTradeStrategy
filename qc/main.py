# region imports
from AlgorithmImports import *
# endregion
"""Fear-Tranche Accumulator — QuantConnect algorithm (backtest + paper/live).

Same rules as research/strategy.py (variant "v2 + QLD + trend guard"); every
threshold is a QC parameter so the optimizer / walk-forward can sweep it.

Sleeves (tracked in a virtual book so the same ETF can sit in two sleeves):
  core   fear-tranched beta  (CORE, e.g. "QQQ:1" or "QQQM:0.5,VOO:0.5")
  trend  trend-guarded half of the core (the same CORE basket while QQQ >= 0.97 x MA200, else powder)
  lev    leverage sleeve: "QLD" | "TQQQ" | "LEAPS" | "NONE"
  powder dry powder in POWDER ETF (BIL/SGOV) or cash

Parameter sleeves = BASKET (default, described above) | HEADLINE (the README's 50/50 v2, research/strategy.py defaults):
  HEADLINE  the trend half holds QQQ only, core weights drift (no reset to target on trades), and T-bills parked by the
            trend guard stay separate from powder.  CORE then defaults to "QQQ:0.5,VOO:0.5".

Timing: signal on the daily bar that closes on day t (arrives after the close),
orders are market-on-open for t+1 (QC fills at the next open in backtests).

Percentile: today's composite is ranked against every composite since 2000-03-08, as research does; VXN before
2008-01-03 (QC's first VXN bar) is VIX x 1.0555, as in data/build_dataset.py.
Live restarts: state is saved to the ObjectStore every bar (live only) and restored, so a restart never trades by itself.

tranche_signal = COMPOSITE (default) | VIX_EASING | OFF. VIX_EASING requires a VIX close
at least 24 and lower than 20 QQQ sessions ago. Only the core tranche gate changes.
overlay = NONE (default) | HEDGE12M (backtest only). See hedge.py for execution and cash accounting.
LEAPS remains a separate experimental leverage sleeve.
"""
import json
from collections import deque
from datetime import datetime, timedelta
from math import isfinite

import numpy as np
import pandas as pd

from signals import (SEED_FROM, VIX_SEED_URL, VXN_VIX_RATIO, backfill_vxn, close_series, composite_frame,
                     extend_vix_history, pct_of, seed_composite)
from hedge import ProtectivePut


def _p(algo, name, default, cast=float):
    v = algo.get_parameter(name)
    return cast(v) if v not in (None, "") else default


def parse_core(spec):
    """"QQQ:0.8,VOO:0.2" -> {"QQQ": 0.8, "VOO": 0.2}, normalised to 1; rejects bad or non-positive weights."""
    w = {}
    for part in spec.split(","):
        t, sep, v = part.strip().partition(":")
        t, v = t.strip().upper(), float(v) if sep else float("nan")
        if not t or t in w or not 0 < v < float("inf"):
            raise ValueError(f"bad core spec {spec!r}: use TICKER:weight with distinct tickers and positive weights")
        w[t] = v
    tot = sum(w.values())
    if not isfinite(tot):
        raise ValueError("core weights must have a finite sum")
    return {t: v / tot for t, v in w.items()}


def ladder_defaults(mode, core_target):
    """FIXED = v2 sizes whatever the target; SCALED = powder/4 per tranche, powder/3 per leverage buy, cap = powder."""
    if mode == "FIXED":
        return dict(tranche=0.075, lev_size=0.10, lev_cap=0.30)
    if mode == "SCALED":
        r = 1 - core_target
        return dict(tranche=r / 4, lev_size=r / 3, lev_cap=r)
    raise ValueError(f"ladder must be FIXED or SCALED, not {mode!r}")


class FearTrancheAccumulator(QCAlgorithm):

    def initialize(self):
        start_year = _p(self, "start_year", 2011, int)
        end_year = _p(self, "end_year", 0, int)
        start = datetime.fromisoformat(self.get_parameter("start_date") or f"{start_year:04d}-01-01")
        end_text = self.get_parameter("end_date") or (f"{end_year:04d}-12-31" if end_year else "")
        end = datetime.fromisoformat(end_text) if end_text else None
        capital = _p(self, "capital", 100_000)
        if (end is not None and end < start) or not isfinite(capital) or capital <= 0:
            raise ValueError("the end date must follow the start date and capital must be positive")
        self.set_start_date(start.year, start.month, start.day)
        if end is not None:
            self.set_end_date(end.year, end.month, end.day)
        self.set_cash(capital)
        self.set_brokerage_model(BrokerageName.INTERACTIVE_BROKERS_BROKERAGE, AccountType.MARGIN)
        # Underlying and Cboe indices have different closing times. In backtests synchronize
        # daily bars at midnight and use the bar's session date for all close signals.
        self.midnight_bars = not self.live_mode and hasattr(self, "settings")
        if self.midnight_bars:
            self.settings.daily_precise_end_time = False

        # ---- parameters (defaults = pre-registered v2) ----
        self.core_target = _p(self, "core_target", 0.70)
        if not 0 < self.core_target < 1:
            raise ValueError(f"core_target must be between 0 and 1, got {self.core_target}")
        ladder = ladder_defaults((self.get_parameter("ladder") or "FIXED").upper(), self.core_target)
        self.tranche = _p(self, "tranche", ladder["tranche"])      # an explicit parameter wins over the ladder
        self.tranche_p = _p(self, "tranche_p", 0.80)
        self.tranche_gap = _p(self, "tranche_gap", 10, int)
        self.tranche_step = _p(self, "tranche_step", 0.92)
        self.lev_mode = (self.get_parameter("lev") or "QLD").upper()
        self.lev_p = _p(self, "lev_p", 0.90)
        self.lev_size = _p(self, "lev_size", ladder["lev_size"])
        self.lev_cap = _p(self, "lev_cap", ladder["lev_cap"])
        self.lev_tp = _p(self, "lev_tp", 0.60)
        self.lev_exit_p = _p(self, "lev_exit_p", 0.50)
        self.lev_max_days = _p(self, "lev_max_days", 378, int)
        self.greed_p = _p(self, "greed_p", 0.15)
        self.greed_stretch = _p(self, "greed_stretch", 1.08)
        guard = _p(self, "trend_guard", 1, int)
        self.trend_guard = guard == 1
        self.trend_band = _p(self, "trend_band", 0.97)
        self.tranche_signal = (self.get_parameter("tranche_signal") or "COMPOSITE").strip().upper()
        self.vix_floor = _p(self, "vix_floor", 24.0)
        self.vix_easing_days = _p(self, "vix_easing_days", 20, int)
        self.cash_buffer = _p(self, "cash_buffer", 0.01)
        self.align_vix = self.midnight_bars or (self.live_mode and self.tranche_signal == "VIX_EASING")
        if self.tranche_signal not in ("COMPOSITE", "VIX_EASING", "OFF"):
            raise ValueError("tranche_signal must be COMPOSITE, VIX_EASING or OFF")
        if self.lev_mode not in ("QLD", "TQQQ", "LEAPS", "NONE"):
            raise ValueError("lev must be QLD, TQQQ, LEAPS or NONE")
        if not (guard in (0, 1) and 0 <= self.cash_buffer < 1
                and isfinite(self.vix_floor) and self.vix_floor > 0
                and 1 <= self.vix_easing_days <= 899):
            raise ValueError("invalid trend_guard, cash_buffer, vix_floor or vix_easing_days")
        if not (0 <= self.tranche <= 1 and 0 <= self.lev_size <= self.lev_cap <= 1
                and 0 < self.tranche_step <= 1 and self.tranche_gap >= 1 and self.lev_max_days >= 1
                and all(isfinite(v) and v >= 0 for v in (self.tranche_p, self.lev_tp, self.lev_p))
                and 0 <= self.lev_exit_p <= 1
                and -1 <= self.greed_p <= 1
                and all(isfinite(v) and v > 0 for v in (self.trend_band, self.greed_stretch))):
            raise ValueError("invalid tranche, leverage, greed or trend parameters")
        self.audit_dates = set((self.get_parameter("audit_dates") or "").split(","))
        self.trace_signals = _p(self, "trace_signals", 1, int) == 1

        mode = (self.get_parameter("sleeves") or "BASKET").upper()
        if mode not in ("BASKET", "HEADLINE"):
            raise ValueError(f"sleeves must be BASKET or HEADLINE, not {mode!r}")
        self.headline = mode == "HEADLINE"
        core_spec = self.get_parameter("core") or ("QQQ:0.5,VOO:0.5" if self.headline else "QQQ:1")
        self.core_w = parse_core(core_spec)
        powder = (self.get_parameter("powder") or "BIL").strip().upper()
        if powder in self.core_w or powder == self.lev_mode or powder == "QQQ" or self.lev_mode in self.core_w:
            raise ValueError("core, powder and leverage must use distinct tickers")

        overlay = (self.get_parameter("overlay") or "NONE").strip().upper()
        price_mode = (self.get_parameter("price_mode") or "AUTO").strip().upper()
        if overlay not in ("NONE", "HEDGE12M") or price_mode not in ("AUTO", "RAW", "ADJUSTED"):
            raise ValueError("overlay must be NONE or HEDGE12M and price_mode must be AUTO, RAW or ADJUSTED")
        if overlay == "HEDGE12M" and (self.lev_mode == "LEAPS" or self.live_mode):
            raise ValueError("HEDGE12M is a backtest overlay and requires ETF leverage or lev=NONE")
        if overlay == "HEDGE12M" and start.year < 2012:
            raise ValueError("HEDGE12M requires the QuantConnect option quote era (2012 onward)")
        if price_mode == "ADJUSTED" and (overlay == "HEDGE12M" or self.lev_mode == "LEAPS"):
            raise ValueError("QQQ options require raw underlying prices")

        norm = DataNormalizationMode.ADJUSTED if self.live_mode or price_mode == "ADJUSTED" else DataNormalizationMode.TOTAL_RETURN
        if self.lev_mode == "LEAPS" or overlay == "HEDGE12M" or price_mode == "RAW":
            norm = DataNormalizationMode.RAW   # option strikes need the raw underlying price
        add = lambda t: self.add_equity(t, Resolution.DAILY, data_normalization_mode=norm).symbol
        self.qqq = add("QQQ")
        self.core_syms = {t: self.qqq if t == "QQQ" else add(t) for t in self.core_w}
        self.powder = add(powder) if powder != "CASH" else None
        self.lev_sym = add(self.lev_mode) if self.lev_mode in ("QLD", "TQQQ") else None
        self.equity_symbols = set(self.core_syms.values()) | {self.qqq, self.powder, self.lev_sym}
        self.equity_symbols.discard(None)
        if self.midnight_bars:
            # A midnight daily bar spans time before a 01:00 order. Intraday bars let
            # LEAN fill opening orders before the following day's sleeve attribution.
            tickers = set(self.core_w) | {"QQQ", powder, self.lev_mode}
            for ticker in sorted(tickers - {"CASH", "NONE", "LEAPS"}):
                self.add_equity(ticker, Resolution.HOUR, data_normalization_mode=norm)
        self.vxn = self.add_index("VXN", Resolution.DAILY, fill_forward=False).symbol
        # A fill-forward observation can release the daily decision, but cannot trigger a VIX entry.
        self.vix = self.add_index("VIX", Resolution.DAILY).symbol
        self.hedge = ProtectivePut(self) if overlay == "HEDGE12M" else None
        self.pending_daily = self.latest_vix = None
        if self.lev_mode == "LEAPS":
            self._init_leaps()

        # ---- seed signal history (no look-ahead: history ends before start) ----
        # The percentile ranks today's composite against EVERY value since 2000, as research does
        # (strategy.prepare: expanding rank). The rolling inputs only need the last 900 bars.
        since = datetime.strptime(SEED_FROM, "%Y-%m-%d")
        hist = lambda s: close_series(self.history([s], since, self.time, Resolution.DAILY), s, midnight=self.midnight_bars)
        px, vx_raw, vix = hist(self.qqq), hist(self.vxn), hist(self.vix)
        if len(px) and (not len(vix) or vix.index[0] > px.index[0]) and hasattr(self, "download"):
            qc_count = len(vix)
            vix = extend_vix_history(vix, self.download(VIX_SEED_URL), px.index[0], pd.Timestamp(self.time.date()))
            self.log(f"[PROBE] prepended {len(vix) - qc_count} Cboe VIX closes before QC coverage")
        self.vxn_seen = len(vx_raw) > 0          # once real VXN exists, VIX is no longer used
        vx = backfill_vxn(vx_raw, vix)
        self.px_hist = deque(zip(px.index, px.to_numpy()), maxlen=900)
        self.vxn_hist = deque(zip(vx.index, vx.to_numpy()), maxlen=900)
        self.vxn_max10 = deque(vx.to_numpy()[-10:], maxlen=10)
        self.vix_history = deque(vix.reindex(px.index).to_numpy()[-self.vix_easing_days:], maxlen=self.vix_easing_days + 1)
        self.comp_hist, self.comp_from = [], None     # composite history for the expanding percentile
        self._seed_composite(px, vx)

        # ---- virtual book (fractions of NAV, re-based daily from realised returns) ----
        self.book = None
        self.trend_on = True
        self.lev_days = 0
        self.last_tranche_i = -999
        self.last_tranche_px = float("inf")
        self.last_trim_i = -999
        self.i = 0
        self.data_missing = {"vix": 0, "vxn": 0, "composite": 0}
        self.equity_delays = 0
        self.state_key = self.get_parameter("state_key") or "fear_tranche/state"
        self.set_warm_up(timedelta(days=5))
        self.log(f"[PROBE] seeded {len(px)} QQQ bars from {px.index[0].date() if len(px) else None}, {len(vx)} VXN bars "
                 f"from {vx.index[0].date() if len(vx) else None}, {len(self.comp_hist)} composite values from "
                 f"{self.comp_from}")

    # ------------------------------------------------------------------ signals
    def _frame(self):
        px = pd.Series(dict(self.px_hist)).sort_index()
        vx = pd.Series(dict(self.vxn_hist)).sort_index()
        return composite_frame(px, vx)

    def _seed_composite(self, px, vx):
        comp = seed_composite(px, vx, allow_short=_p(self, "allow_short_seed", 0, int) == 1)
        self.comp_hist = comp.tolist()
        self.comp_from = comp.index[0].date() if len(comp) else None

    def _pct(self, x):
        """Same as research's expanding rank: x ranked among all past composites and itself (needs 504 values)."""
        return pct_of(self.comp_hist, x)

    # ------------------------------------------------------------------ main loop
    def on_data(self, data: Slice):
        if self.is_warming_up:
            return
        if self.hedge is not None:
            self.hedge.on_data(data)
        qbar = data.bars.get(self.qqq)
        daily_qqq = qbar is not None and getattr(qbar, "period", timedelta(days=1)) >= timedelta(hours=3)
        vix_bar = data.bars.get(self.vix)
        if not self.align_vix:
            if daily_qqq:
                valid_vix = vix_bar if not getattr(vix_bar, "is_fill_forward", False) else None
                self._on_daily(self.time.date(), float(qbar.close), data.bars.get(self.vxn), valid_vix)
            return
        if vix_bar is not None:
            self.latest_vix = vix_bar.time.date(), vix_bar
        if daily_qqq:
            if self.pending_daily is not None:
                # A session with no VIX delivery is still counted, with the tranche gate closed.
                self._flush_daily(None)
            self.pending_daily = qbar.time.date(), float(qbar.close), data.bars.get(self.vxn)
        if self.pending_daily is not None:
            if self.latest_vix is not None and self.latest_vix[0] == self.pending_daily[0]:
                bar = self.latest_vix[1]
                self._flush_daily(bar if not bar.is_fill_forward else None)
            elif 2 <= self.time.hour < 9:
                self._flush_daily(None)

    def _flush_daily(self, vix_bar):
        t, close, vbar = self.pending_daily
        self.pending_daily = None
        self._on_daily(t, close, vbar, vix_bar)

    def _on_daily(self, t, close, vbar, vix_bar):
        self.px_hist.append((pd.Timestamp(t), close))
        vix_close = float(vix_bar.close) if vix_bar is not None else float("nan")
        self.vix_history.append(vix_close)
        self.data_missing["vix"] += vix_bar is None
        if vbar is not None:
            self.vxn_seen = True
        elif not self.vxn_seen and vix_bar is not None:
            vbar = type("Bar", (), {"close": vix_close * VXN_VIX_RATIO})()   # pre-2008 days
        if vbar is not None:
            v = float(vbar.close)
            self.vxn_hist.append((pd.Timestamp(t), v))
            self.vxn_max10.append(v)
        self.data_missing["vxn"] += vbar is None
        f = self._frame()
        comp = float(f["composite"].iloc[-1])
        ma200 = float(pd.Series([p for _, p in self.px_hist]).iloc[-200:].mean())
        p = self._pct(comp) if np.isfinite(comp) else float("nan")
        if np.isfinite(comp):
            self.comp_hist.append(comp)
            self.plot("Signal", "composite", comp)
        else:
            self.data_missing["composite"] += 1
        recede = vbar is not None and len(self.vxn_max10) == 10 and self.vxn_max10[-1] <= 0.85 * max(self.vxn_max10)
        self.plot("Signal", "pctile x100", 0 if np.isnan(p) else 100 * p)

        self.p_last = p
        nav = self.portfolio.total_portfolio_value
        new_book = self.book is None
        self.i += 1
        if not new_book and hasattr(self, "transactions") and any(
                order.symbol in self.equity_symbols for order in self.transactions.get_open_orders()):
            self.equity_delays += 1
            self.log(f"[ETF PENDING] {t} kept sleeve weights until the previous rebalance completes")
            return
        if new_book:
            if self.live_mode and self.portfolio.invested:
                self._restore_book(close, ma200)  # a restart: never trade just because the algorithm restarted
                new_book = False
            else:
                self._init_book()
        if not new_book:                       # the opening orders have not filled yet on the first bar
            if self.headline:
                self._drift_headline()
            else:
                self._drift_book()
        changed = False
        why = []

        # leverage exit (gain on what the position actually cost: average fill price x quantity)
        if self.book["lev"] > 0:
            self.lev_days += 1
            cost = self._lev_cost()
            gain = self._lev_value() / cost - 1 if cost > 0 else 0.0
            if (p <= self.lev_exit_p and close > ma200) or gain >= self.lev_tp or self.lev_days >= self.lev_max_days:
                self.book["powder"] += self.book["lev"]
                self.book["lev"] = 0.0
                self.lev_days = 0
                excess = self.book["powder"] - (1 - self.core_target)
                if excess > 0:
                    self.book["powder"] -= excess
                    self._buy_core(excess)
                changed = True; why.append(f"lev exit {gain:+.0%}")
        # tranche buy
        if self._tranche_allowed(p) and self.i - self.last_tranche_i >= self.tranche_gap and \
                (close <= self.tranche_step * self.last_tranche_px or self.i - self.last_tranche_i > 126):
            amt = min(self.tranche, self.book["powder"])
            if amt > 0.001:
                self.book["powder"] -= amt; self._buy_core(amt)
                self.last_tranche_i, self.last_tranche_px = self.i, close
                changed = True; why.append(f"tranche {amt:.1%}")
        # leverage entry
        if self.lev_mode != "NONE" and not np.isnan(p) and p >= self.lev_p and recede \
                and self.book["lev"] < self.lev_cap and self.book["powder"] > 0.001:
            amt = min(self.lev_size, self.lev_cap - self.book["lev"], self.book["powder"])
            if amt > 0.001:
                self.book["powder"] -= amt; self.book["lev"] += amt
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
                self.core_parts = {t: x * (1 - k) for t, x in self.core_parts.items()}
                self.last_trim_i = self.i; self.last_tranche_px = float("inf")
                changed = True; why.append(f"greed trim {over:.1%}")
        # trend guard
        if self.trend_guard:
            want = close >= self.trend_band * ma200
            if want != self.trend_on:
                self.trend_on = want
                changed = True; why.append("trend " + ("on" if want else "off"))

        if self.trace_signals:
            self.log(f"[SIGNAL] {t} close={close:.2f} comp={comp:.2f} p={p:.3f} recede={recede} book={self._fmt()}")
        if str(t) in self.audit_dates:
            self.log(f"[AUDIT] {t} QQQ={close:.4f} VXN={float(vbar.close) if vbar else float('nan'):.4f} "
                     f"VIX={vix_close:.4f} comp={comp:.5f} p={p:.5f} NAV={nav:.2f}")
        if changed:
            self.log(f"[TRADE] {t} {', '.join(why)}")
        if changed or new_book:
            self._rebalance()
        if self.hedge is not None:
            self.hedge.plan(t, close, p, recede)
        if self.live_mode:
            self._save_state(t)

    def _tranche_allowed(self, p):
        if self.tranche_signal == "COMPOSITE":
            return p >= self.tranche_p
        if self.tranche_signal == "OFF" or len(self.vix_history) < self.vix_easing_days + 1:
            return False
        prior, current = self.vix_history[0], self.vix_history[-1]
        return current >= self.vix_floor and current < prior

    # ------------------------------------------------------------------ book helpers
    def _init_book(self):
        c = self.core_target
        self.book = {"core": c / 2 if self.trend_guard else c, "trend": c / 2 if self.trend_guard else 0.0,
                     "lev": 0.0, "powder": 1 - c}
        self.core_parts = {t: self.book["core"] * w for t, w in self.core_w.items()}   # used by HEADLINE only

    def _buy_core(self, amt):
        """Sleeve flow at target weights; in HEADLINE mode existing holdings keep their drifted weights."""
        self.book["core"] += amt
        for t, w in self.core_w.items():
            self.core_parts[t] += amt * w

    def _drift_headline(self):
        """Re-base every sleeve leg from actual holdings. QQQ held by both core and trend splits by book share (same
        return); parked trend money and powder split the rest by book share (same T-bill return)."""
        nav = self.portfolio.total_portfolio_value
        if nav <= 0:
            return
        frac = lambda s: self.portfolio[s].holdings_value / nav
        trend = self.book["trend"] if self.trend_on else 0.0
        held = 0.0
        trend_new = frac(self.qqq) if self.trend_on and self.qqq not in self.core_syms.values() else 0.0
        if self.qqq not in self.core_syms.values():
            held += frac(self.qqq)
        for t, s in self.core_syms.items():
            f = frac(s)
            held += f
            if s == self.qqq and trend > 0:
                tot = self.core_parts[t] + trend
                trend_new = f * trend / tot
                f -= trend_new
            self.core_parts[t] = f
        self.book["core"] = sum(self.core_parts.values())
        self.book["lev"] = self._lev_value() / nav
        rest = max(1 - held - self.book["lev"] - self._hedge_value() / nav, 0.0)
        if self.trend_on:
            self.book["trend"], self.book["powder"] = trend_new, rest
        else:
            tot = self.book["trend"] + self.book["powder"]
            share = self.book["trend"] / tot if tot > 0 else 0.0
            self.book["trend"], self.book["powder"] = rest * share, rest * (1 - share)

    def _drift_book(self):
        """Re-base sleeve fractions from actual holdings so the book tracks the account."""
        nav = self.portfolio.total_portfolio_value
        if nav <= 0:
            return
        core_val = sum(self.portfolio[s].holdings_value for s in self.core_syms.values())
        lev_val = self._lev_value()
        powder_val = nav - core_val - lev_val - self._hedge_value()
        tot_core = self.book["core"] + (self.book["trend"] if self.trend_on else 0)
        if tot_core > 0:
            share = self.book["core"] / tot_core
            self.book["core"] = core_val * share / nav
            if self.trend_on:
                self.book["trend"] = core_val * (1 - share) / nav
        self.book["lev"] = lev_val / nav
        rest = max(powder_val / nav, 0.0)
        if self.trend_on:
            self.book["powder"] = rest
        else:
            # parked trend money and powder both sit in T-bills: split the rest by book share, so parked money
            # earns the same return as powder and never becomes spendable when NAV moves
            tot = self.book["trend"] + self.book["powder"]
            share = self.book["trend"] / tot if tot > 0 else 0.0
            self.book["trend"], self.book["powder"] = rest * share, rest * (1 - share)

    # ------------------------------------------------------------------ live restarts
    # QC restores brokerage holdings on a restart but re-runs initialize, so without this the book would be rebuilt at
    # target weights and the first bar would sell QLD and reset the tranche counters. Backtests never use the store:
    # it persists across backtests in a project.
    def _state(self, t):
        f = lambda x: None if x == float("inf") else x
        return dict(date=str(t), sleeves="HEADLINE" if self.headline else "BASKET", core=self.core_w,
                    book={k: float(v) for k, v in self.book.items()},
                    core_parts=self.core_parts, trend_on=bool(self.trend_on), lev_days=self.lev_days, i=self.i,
                    last_tranche_i=self.last_tranche_i, last_tranche_px=f(self.last_tranche_px),
                    last_trim_i=self.last_trim_i, tranche_signal=self.tranche_signal)

    def _save_state(self, t):
        self.object_store.save(self.state_key, json.dumps(self._state(t)))

    def _restore_book(self, close, ma200):
        st = json.loads(self.object_store.read(self.state_key)) if self.object_store.contains_key(self.state_key) else None
        if (st and st["sleeves"] == ("HEADLINE" if self.headline else "BASKET") and st["core"] == self.core_w
                and st.get("tranche_signal", "COMPOSITE") == self.tranche_signal):
            self.book, self.core_parts, self.trend_on = st["book"], st["core_parts"], st["trend_on"]
            self.lev_days, self.i, self.last_tranche_i, self.last_trim_i = (
                st["lev_days"], st["i"], st["last_tranche_i"], st["last_trim_i"])
            self.last_tranche_px = float("inf") if st["last_tranche_px"] is None else st["last_tranche_px"]
            self.log(f"[RESTART] state from {st['date']} restored; book re-based on actual holdings, no trade")
            return
        # No usable state: describe what the account holds and wait for real signals.
        nav = self.portfolio.total_portfolio_value
        frac = lambda s: self.portfolio[s].holdings_value / nav
        self.core_parts = {t: frac(s) for t, s in self.core_syms.items()}
        extra_qqq = frac(self.qqq) if self.qqq not in self.core_syms.values() else 0.0   # HEADLINE's trend half
        self.trend_on = close >= self.trend_band * ma200 if self.trend_guard else True
        lev = self._lev_value() / nav
        core = sum(self.core_parts.values())
        self.book = {"core": core, "trend": extra_qqq, "lev": lev, "powder": max(1 - core - extra_qqq - lev, 0.0)}
        self.lev_days = 0
        self.last_tranche_i, self.last_tranche_px = self.i + 1, close   # next tranche needs the gap and a lower price
        self.log(f"[WARN] restart with holdings but no saved state ({self.state_key}): book rebuilt from holdings "
                 f"{self._fmt()}, trend sleeve 0, tranche spacing restarts today. Check the account.")

    def _lev_cost(self):
        """What the leverage position cost (average fill price x quantity), from the brokerage holdings."""
        if self.lev_sym is not None:
            return self.portfolio[self.lev_sym].holdings_cost
        if self.lev_mode == "LEAPS":
            return sum(h.holdings_cost for s, h in self.portfolio.items()
                       if s.security_type == SecurityType.OPTION and h.invested)
        return 0.0

    def _lev_value(self):
        if self.lev_sym is not None:
            return self.portfolio[self.lev_sym].holdings_value
        if self.lev_mode == "LEAPS":
            return sum(h.holdings_value for s, h in self.portfolio.items()
                       if s.security_type == SecurityType.OPTION and h.invested)
        return 0.0

    def _hedge_value(self):
        return self.hedge.nonspendable_value() if self.hedge is not None else 0.0

    def _rebalance(self):
        targets = []
        trend_frac = self.book["trend"] if self.trend_on else 0.0
        if self.headline:
            want = {s: self.core_parts[t] for t, s in self.core_syms.items()}
            want[self.qqq] = want.get(self.qqq, 0.0) + trend_frac
            targets += [PortfolioTarget(s, f) for s, f in want.items()]
        else:
            core_frac = self.book["core"] + trend_frac
            tot_w = sum(self.core_w.values())
            for t, s in self.core_syms.items():
                targets.append(PortfolioTarget(s, core_frac * self.core_w[t] / tot_w))
        if self.lev_sym is not None:
            targets.append(PortfolioTarget(self.lev_sym, self.book["lev"]))
        if self.powder is not None:
            powder_frac = self.book["powder"] + (0.0 if self.trend_on else self.book["trend"])
            targets.append(PortfolioTarget(self.powder, max(powder_frac - self.cash_buffer, 0.0)))
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
        if self.hedge is not None:
            self.hedge.report()
        self.log(f"[DATA SUMMARY] sessions={self.i} missing={self.data_missing} equity_delays={self.equity_delays}")
        book = self._fmt() if self.book is not None else "uninitialized"
        self.log(f"[END] book={book} NAV={self.portfolio.total_portfolio_value:,.0f}")

    def on_order_event(self, event):
        if self.hedge is not None:
            self.hedge.on_order_event(event)
