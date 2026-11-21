# region imports
from AlgorithmImports import *
# endregion
"""Cash-secured QQQ put writing on real option quotes — checks research/vol_selling.py (model-priced).

Standalone sleeve: all capital sits in cash (or BIL) as collateral; every ~30 days, if the condition
holds, sell the QQQ put closest to the target moneyness with 25-40 days to expiry, sized so that
strike x 100 x contracts <= collateral. Fills at the bid (conservative). Held to expiry; assignment
is closed out the next day (sell the shares), so the sleeve stays a pure option P&L.

Parameters:
  cond   always | vxn_median | fear50_receding | fear80_receding        (default always)
  otm    0.00 / 0.05 / 0.10 below spot                                    (default 0.00)
  start_year (default 2012 — check option data start on your account)
Signals use qc/signals.py (same fear composite as the deck, slide 5).
STATUS: written offline, not yet run on QC.
"""
from collections import deque

import numpy as np
import pandas as pd

from signals import composite_frame


class PutWriting(QCAlgorithm):

    def initialize(self):
        self.set_start_date(int(self.get_parameter("start_year") or 2012), 1, 1)
        self.set_cash(100_000)
        self.cond = (self.get_parameter("cond") or "always").lower()
        self.otm = float(self.get_parameter("otm") or 0.0)
        eq = self.add_equity("QQQ", Resolution.DAILY, data_normalization_mode=DataNormalizationMode.RAW)
        self.qqq = eq.symbol
        opt = self.add_option(self.qqq, Resolution.DAILY)
        opt.set_filter(lambda u: u.include_weeklys().puts_only().strikes(-30, 2).expiration(25, 40))
        self.opt = opt.symbol
        self.vxn = self.add_index("VXN", Resolution.DAILY).symbol
        self.px, self.vx = deque(maxlen=900), deque(maxlen=900)
        hq = self.history(self.qqq, 900, Resolution.DAILY)
        hv = self.history(self.vxn, 900, Resolution.DAILY)
        for t, row in hq.loc[self.qqq].iterrows():
            self.px.append((pd.Timestamp(t).normalize(), float(row["close"])))
        for t, row in hv.loc[self.vxn].iterrows():
            self.vx.append((pd.Timestamp(t).normalize(), float(row["close"])))
        self.comp_hist = list(composite_frame(pd.Series(dict(self.px)), pd.Series(dict(self.vx)))["composite"].dropna())
        self.next_sale = self.start_date
        self.set_benchmark(self.qqq)

    def _signal(self):
        f = composite_frame(pd.Series(dict(self.px)).sort_index(), pd.Series(dict(self.vx)).sort_index())
        comp = float(f["composite"].iloc[-1])
        if not np.isnan(comp):
            self.comp_hist.append(comp)
        h = np.asarray(self.comp_hist)
        p = float((h <= comp).mean()) if len(h) >= 504 else np.nan
        v = np.array([x for _, x in self.vx])
        recede = len(v) >= 10 and v[-1] <= 0.9 * v[-10:].max()
        med = np.median(v[-504:]) if len(v) >= 252 else np.nan
        return {"always": True,
                "vxn_median": v[-1] >= med,
                "fear50_receding": (p >= 0.5) and ((p < 0.8) or recede),
                "fear80_receding": (p >= 0.8) and recede}[self.cond]

    def on_data(self, data: Slice):
        if data.bars.contains_key(self.qqq):
            self.px.append((pd.Timestamp(self.time.date()), float(data.bars[self.qqq].close)))
        if data.bars.contains_key(self.vxn):
            self.vx.append((pd.Timestamp(self.time.date()), float(data.bars[self.vxn].close)))
        # close out any assigned shares
        if self.portfolio[self.qqq].quantity != 0:
            self.liquidate(self.qqq, tag="close assignment")
        if self.time < self.next_sale or any(s.security_type == SecurityType.OPTION and h.invested
                                            for s, h in self.portfolio.items()):
            return
        chain = data.option_chains.get(self.opt)
        if chain is None or not self._signal():
            return
        spot = self.securities[self.qqq].price
        target = spot * (1 - self.otm)
        puts = [c for c in chain if c.right == OptionRight.PUT and c.bid_price > 0.05]
        if not puts:
            return
        c = min(puts, key=lambda c: (abs(c.strike - target), abs((c.expiry - self.time).days - 30)))
        n = int(self.portfolio.cash / (c.strike * 100))
        if n > 0:
            self.limit_order(c.symbol, -n, c.bid_price, tag=f"sell put K={c.strike} exp={c.expiry.date()} bid={c.bid_price}")
            self.next_sale = c.expiry
