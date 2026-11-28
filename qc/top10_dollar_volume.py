# region imports
from AlgorithmImports import *
# endregion
"""Top-N US stocks by dollar volume — point-in-time universe, several weighting rules.

Why QC: the universe must be the stocks that WERE the most traded at each date (including later
delisted / shrunk names). Picking today's mega-caps and backtesting them is survivorship bias.

Each month: coarse filter = top 60 by that day's dollar volume (US equities with fundamentals,
price > $5, so ETFs drop out); at the first trading day of the month we rank those by 21-day average
dollar volume from history and keep the top N. One share class per company.

Parameters (QC "Parameters" tab):
  rule   equal | invvol | dollarvol | reversal | momentum | drawdown      (default equal)
  n      universe size (default 10);  k  names held by reversal/momentum/drawdown (default 5)
  trend  1 = cut gross exposure to 50% while QQQ < 0.97 x its 200-day average (default 0)
  start_year / end_year
Compare every rule with rule=equal (same names) and with QQQ / SPY buy-and-hold over the same dates.
STATUS: written offline, not yet run on QC.
"""
import numpy as np
import pandas as pd


class Top10DollarVolume(QCAlgorithm):

    def initialize(self):
        self.set_start_date(int(self.get_parameter("start_year") or 2005), 1, 1)
        ey = self.get_parameter("end_year")
        if ey:
            self.set_end_date(int(ey), 12, 31)
        self.set_cash(100_000)
        self.set_brokerage_model(BrokerageName.INTERACTIVE_BROKERS_BROKERAGE, AccountType.MARGIN)
        self.rule = (self.get_parameter("rule") or "equal").lower()
        self.n = int(self.get_parameter("n") or 10)
        self.k = int(self.get_parameter("k") or 5)
        self.trend = (self.get_parameter("trend") or "0") == "1"

        self.universe_settings.resolution = Resolution.DAILY
        self.universe_settings.data_normalization_mode = DataNormalizationMode.TOTAL_RETURN
        self._last_month = -1
        self.add_universe(self._select)
        self.qqq = self.add_equity("QQQ", Resolution.DAILY,
                                   data_normalization_mode=DataNormalizationMode.TOTAL_RETURN).symbol
        self.set_benchmark(self.qqq)
        self.schedule.on(self.date_rules.month_start(self.qqq), self.time_rules.after_market_open(self.qqq, 30),
                         self._rebalance)
        self.qqq_sma = self.sma(self.qqq, 200, Resolution.DAILY)
        self.set_warm_up(timedelta(days=300))
        self.held = []

    # ---------------- universe ----------------
    def _select(self, fundamental):
        if self.time.month == self._last_month:
            return Universe.UNCHANGED
        self._last_month = self.time.month
        eq = [f for f in fundamental if f.has_fundamental_data and f.price > 5 and f.dollar_volume > 0]
        eq.sort(key=lambda f: f.dollar_volume, reverse=True)
        out, seen = [], set()
        for f in eq:
            # one share class per company; LEAN keeps the company id on company_reference (company_profile has none)
            cid = f.company_reference.company_id or str(f.symbol)
            if cid in seen:
                continue
            seen.add(cid); out.append(f.symbol)
            if len(out) >= 60:
                break
        return out

    # ---------------- rebalance ----------------
    def _rebalance(self):
        if self.is_warming_up:
            return
        cands = [s for s in self.active_securities.keys if s != self.qqq and s.security_type == SecurityType.EQUITY]
        if not cands:
            return
        h = self.history(cands, 280, Resolution.DAILY)
        if h.empty:
            return
        close = h["close"].unstack(0)
        vol = h["volume"].unstack(0)
        adv = (close * vol).tail(21).mean().dropna()
        top = list(adv.sort_values(ascending=False).index[: self.n])
        c = close[top].dropna(axis=1, how="all")
        r = c.pct_change()
        if self.rule == "equal":
            w = pd.Series(1.0, index=c.columns)
        elif self.rule == "invvol":
            w = 1 / r.tail(63).std()
        elif self.rule == "dollarvol":
            w = adv[c.columns]
        elif self.rule == "reversal":
            w = pd.Series(1.0, index=(c.iloc[-1] / c.iloc[-22] - 1).nsmallest(self.k).index)
        elif self.rule == "momentum":
            w = pd.Series(1.0, index=(c.iloc[-22] / c.iloc[-253] - 1).dropna().nlargest(self.k).index)
        elif self.rule == "drawdown":
            w = pd.Series(1.0, index=(c.iloc[-1] / c.tail(252).max() - 1).nsmallest(self.k).index)
        else:
            raise ValueError(self.rule)
        w = w.replace([np.inf, -np.inf], np.nan).dropna()
        w = w / w.sum()
        gross = 1.0
        if self.trend and self.qqq_sma.is_ready and self.securities[self.qqq].price < 0.97 * self.qqq_sma.current.value:
            gross = 0.5
        targets = []
        for sym_str, wt in w.items():
            sym = sym_str if isinstance(sym_str, Symbol) else self.symbol(sym_str)
            targets.append(PortfolioTarget(sym, float(gross * wt * 0.99)))
        self.set_holdings(targets, liquidate_existing_holdings=True)
        names = [self.securities[t.symbol].symbol.value for t in targets]
        self.log(f"[REBAL] {self.time.date()} rule={self.rule} gross={gross:.2f} {names}")
        self.plot("Universe", "names held", len(targets))
