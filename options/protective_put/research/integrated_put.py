"""Model-price the funded protective put inside research/strategy.py."""
from math import ceil, floor

import numpy as np
import pandas as pd

from options_model import CENTRAL, OptionBook


class ModeledPut:
    """One long QQQ put, sized in whole contracts using the raw QQQ price."""

    def __init__(self, surface=CENTRAL, *, cover="unguarded", proceeds="tbill", exit="hold",
                 moneyness=0.85, tenor=365, roll_days=122):
        if cover not in ("all", "unguarded") or proceeds not in ("tbill", "tranche"):
            raise ValueError("invalid protective put coverage or cash routing")
        if exit not in ("hold", "fear", "rolldown") or not (0 < moneyness <= 1 and 0 <= roll_days < tenor):
            raise ValueError("invalid protective put exit, strike or maturity")
        self.surface, self.cover, self.proceeds, self.exit = surface, cover, proceeds, exit
        self.moneyness, self.tenor, self.roll_days = moneyness, tenor, roll_days

    def start(self, sessions, data):
        market = data[["raw_qqq", "vxn", "rf"]].to_numpy(dtype=float)
        if not len(data) or not np.isfinite(market).all() or not (market[:, :2] > 0).all():
            raise ValueError("the modeled put requires positive, complete raw QQQ and VXN closes and finite bill rates")
        self.sessions = sessions
        self.book = OptionBook(self.surface, fee_per_share=0.65 / 100)
        self.bucket = self.mark = self.daily_flow = 0.0
        self.expiry = self.last_date = self.signal_delta = None

    @property
    def value(self):
        return self.bucket + self.mark

    @staticmethod
    def _market(row):
        return row["raw_qqq"], row["rf"], row["vxn"] / 100

    def _route(self, flow, cash):
        self.daily_flow += flow
        if flow >= 0:
            if self.proceeds == "tbill":
                self.bucket += flow
                return cash
            return cash + flow
        paid_from_bucket = min(self.bucket, -flow)
        self.bucket -= paid_from_bucket
        return cash + (paid_from_bucket + flow)

    def _buy(self, date, market, cash, unguarded, guarded, reason):
        spot, rate, vxn = market
        desired = (unguarded + (guarded if self.cover == "all" else 0)) / (100 * spot)
        nominal = date + pd.Timedelta(days=self.tenor)
        if nominal <= self.sessions[-1]:
            expiry = self.sessions[self.sessions.searchsorted(nominal, side="right") - 1]
        else:
            expiry = nominal
        if expiry <= date:
            return cash
        years = (expiry - date).days / 365.25
        strike = self.moneyness * spot
        premium = 100 * self.book.cost_per_unit("P", strike, years, *market)
        contracts = min(floor(desired), floor((cash + self.bucket) / premium))
        if contracts < max(1, ceil(0.5 * desired)):
            return cash
        flow = self.book.open("P", strike, years, 100 * contracts, spot, rate, vxn, date, reason)
        self.expiry = expiry
        return self._route(flow, cash)

    def before_rules(self, date, row, prior, cash, unguarded, guarded):
        self.daily_flow = 0.0
        market = self._market(row)
        if self.last_date is not None:
            self.bucket *= 1 + row["rf"] / 252
            self.book.step((date - self.last_date).days)
        self.last_date = date
        if self.book.legs and date >= self.expiry:
            cash = self._route(self.book.expire(market[0], date), cash)
        if self.book.legs and prior is not None:
            reason, roll = None, False
            if self.exit == "fear" and prior["p"] >= 0.90 and prior["vxn_recede"]:
                reason = "fear exit"
            elif self.exit == "rolldown" and self.signal_delta is not None and self.signal_delta <= -0.60:
                reason, roll = "roll-down", True
            elif (self.expiry - prior.name).days < self.roll_days and prior["p"] <= 0.50:
                reason, roll = "roll", True
            if reason is not None and self.book.liquidation(*market) >= -(cash + self.bucket):
                flow = self.book.close_all(*market, date, reason + " sell" if roll else reason)
                cash = self._route(flow, cash)
                if roll:
                    cash = self._buy(date, market, cash, unguarded, guarded, reason + " buy")
        self.mark = self.book.mark(*market)
        return cash

    def after_rules(self, date, row, prior, cash, unguarded, guarded):
        market = self._market(row)
        if not self.book.legs and prior is not None and prior["p"] <= 0.50:
            cash = self._buy(date, market, cash, unguarded, guarded, "entry")
            if self.book.legs:
                cash += self.bucket
                self.bucket = 0.0
        self.mark = self.book.mark(*market)
        self.signal_delta = self.book.leg_delta(0, *market) if self.book.legs and self.exit == "rolldown" else None
        return cash
