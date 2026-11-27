"""Model pricing for the 12-month QQQ put hedge (research/options_overlay.py).

MODEL-PRICED. There are no option quotes locally. qc/options_quote_audit.ipynb pulls real 2012-2026 QQQ
quotes and writes results/options_surface_fit.csv; load_surface() picks those parameters up automatically.
Until then the defaults below are provisional, and 2008 always stays a model result (QC quotes start in 2012).

Surface (VXN is a ~30-day Nasdaq-100 implied vol, so longer tenors need a term-structure assumption):
    ATM(T)   = LR + (RATIO x VXN - LR) x (1 - exp(-KAPPA T)) / (KAPPA T)       mean reversion toward LR
    IV(K, T) = ATM(T) x (1 + SKEW x sqrt(T_REF / T) x ln(S / K))               SKEW_PUT below spot,
                                                                                SKEW_CALL above spot
    floor FLOOR x ATM(T)
Black-Scholes with r = T-bill and q = 0 on the dividend-adjusted QQQ series (an option on the total-return
index; the adjusted path drifts ~0.6%/yr above the price path, which slightly understates put payoffs).
Costs: buyers pay mid x (1 + h) + tick, sellers get mid x (1 - h) - tick, with
    h = HALF_SPREAD x max(1, VXN / STRESS_VXN)   (VXN and STRESS_VXN in vol points; spreads widen in stress)
    and tick = TICK x S, added on top of the proportional half-spread.
Positions are marked at mid; the spread is paid when trading.
"""
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
from scipy.special import ndtr

ROOT = Path(__file__).resolve().parents[1]
FIT_FILE = ROOT / "results" / "options_surface_fit.csv"
T_REF = 30 / 365


@dataclass(frozen=True)
class Surface:
    ratio: float = 0.92          # 30-day ATM IV / VXN (VXN includes skew, so ATM sits below it)
    lr: float = 0.23             # long-run ATM vol the term structure reverts to
    kappa: float = 2.0           # mean-reversion speed (per year)
    skew_put: float = 3.0        # IV slope in ln(S/K) at 30 days, puts below spot
    skew_call: float = 1.0       # same for calls above spot (ln(S/K) < 0, so IV falls)
    floor: float = 0.6           # IV floor as a fraction of ATM
    half_spread: float = 0.02    # half bid/ask as a fraction of mid
    stress_vxn: float = 25.0     # spreads scale up with VXN above this level
    tick: float = 0.0002         # extra half-spread per share, as a fraction of spot
    source: str = "provisional defaults"

    def atm(self, T, vxn):
        x = self.kappa * T
        return self.lr + (self.ratio * vxn - self.lr) * (1 - np.exp(-x)) / x

    def iv(self, S, K, T, vxn):
        a = self.atm(T, vxn)
        m = np.log(S / K)
        s = self.skew_put if K < S else self.skew_call
        return max(a * (1 + s * np.sqrt(T_REF / T) * m), self.floor * a)

    def h(self, vxn):
        """Half-spread; vxn is in decimals (0.20), stress_vxn in vol points (25)."""
        return self.half_spread * max(1.0, 100 * vxn / self.stress_vxn)


CENTRAL = Surface()


def pessimistic(s: Surface) -> Surface:
    """Buyer-unfriendly band from the plan: steeper put skew, double spreads, ATM IV = VXN."""
    return replace(s, skew_put=1.5 * s.skew_put, half_spread=2 * s.half_spread, ratio=max(s.ratio, 1.0),
                   source=s.source + " / pessimistic")


def load_surface(path=FIT_FILE):
    """Central surface from the QC quote fit if it exists, else the provisional defaults."""
    if not Path(path).exists():
        return CENTRAL
    import pandas as pd
    f = pd.read_csv(path).set_index("param")["value"]
    kw = {k: float(f[k]) for k in ("ratio", "lr", "kappa", "skew_put", "skew_call", "floor", "half_spread",
                                   "stress_vxn", "tick") if k in f.index}
    return replace(CENTRAL, source=f"fit: {Path(path).name}", **kw)


def bs(S, K, T, r, sig, right):
    """Black-Scholes price, delta and vega (per 1 vol point = 0.01) for one share."""
    if T <= 1e-8:
        intr = max(K - S, 0.0) if right == "P" else max(S - K, 0.0)
        d = (-1.0 if S < K else 0.0) if right == "P" else (1.0 if S > K else 0.0)
        return intr, d, 0.0
    v = sig * np.sqrt(T)
    d1 = (np.log(S / K) + (r + 0.5 * sig * sig) * T) / v
    d2 = d1 - v
    vega = S * np.exp(-0.5 * d1 * d1) / np.sqrt(2 * np.pi) * np.sqrt(T) / 100
    if right == "P":
        return K * np.exp(-r * T) * ndtr(-d2) - S * ndtr(-d1), ndtr(d1) - 1.0, vega
    return S * ndtr(d1) - K * np.exp(-r * T) * ndtr(d2), ndtr(d1), vega


@dataclass
class Leg:
    right: str        # "P" or "C"
    K: float
    T: float          # years left
    units: float      # shares; + long, - short
    T0: float
    opened: object = None
    reduced: bool = False


@dataclass
class OptionBook:
    """Option legs on QQQ with a cash-flow ledger. Every method that trades returns the cash flow
    (negative = paid) and appends it to self.ledger, so ledger cash flows + mark explain the book's P&L."""
    surface: Surface = CENTRAL
    legs: list = field(default_factory=list)
    ledger: list = field(default_factory=list)

    fee_per_share: float = 0.0

    def quote(self, leg, S, r, vxn):
        sig = self.surface.iv(S, leg.K, max(leg.T, 1e-8), vxn)
        return bs(S, leg.K, leg.T, r, sig, leg.right)

    def mark(self, S, r, vxn):
        return sum(l.units * self.quote(l, S, r, vxn)[0] for l in self.legs)

    def liquidation(self, S, r, vxn):
        """Cash obtained by crossing the spread on each long or short position."""
        return sum(self._fill(self.quote(leg, S, r, vxn)[0], -leg.units, S, vxn)
                   for leg in self.legs)

    def delta(self, S, r, vxn):
        """Dollar delta of the whole book."""
        return sum(l.units * self.quote(l, S, r, vxn)[1] * S for l in self.legs)

    def leg_delta(self, i, S, r, vxn):
        return self.quote(self.legs[i], S, r, vxn)[1]

    def _fill(self, mid, units, S, vxn):
        """Cash flow for trading `units` (+ buy, - sell) at mid with the spread and tick."""
        h, tick = self.surface.h(vxn), self.surface.tick * S
        if units > 0:
            return -units * (mid * (1 + h) + tick + self.fee_per_share)
        return -units * (max(mid * (1 - h) - tick, 0.0) - self.fee_per_share)

    def open(self, right, K, T, units, S, r, vxn, when=None, why="open"):
        leg = Leg(right, K, T, units, T, when)
        mid = self.quote(leg, S, r, vxn)[0]
        cash = self._fill(mid, units, S, vxn)
        self.legs.append(leg)
        self.ledger.append(dict(date=when, event=why, right=right, K=K, T=T, units=units, mid=mid, S=S,
                                vxn=vxn, cash=cash))
        return cash

    def cost_per_unit(self, right, K, T, S, r, vxn):
        """Cash needed to buy one unit (positive number)."""
        leg = Leg(right, K, T, 1.0, T)
        return -self._fill(self.quote(leg, S, r, vxn)[0], 1.0, S, vxn)

    def close(self, i, S, r, vxn, when=None, why="close"):
        leg = self.legs.pop(i)
        mid = self.quote(leg, S, r, vxn)[0]
        cash = self._fill(mid, -leg.units, S, vxn)
        self.ledger.append(dict(date=when, event=why, right=leg.right, K=leg.K, T=leg.T, units=-leg.units,
                                mid=mid, S=S, vxn=vxn, cash=cash))
        return cash

    def reduce(self, i, units, S, r, vxn, when=None):
        leg = self.legs[i]
        if not 0 < units <= leg.units:
            raise ValueError("Partial sale exceeds long units")
        if units == leg.units:
            return self.close(i, S, r, vxn, when, "partial")
        leg.units -= units
        self.legs.append(replace(leg, units=units))
        return self.close(-1, S, r, vxn, when, "partial")

    def close_all(self, S, r, vxn, when=None, why="close"):
        return sum(self.close(len(self.legs) - 1, S, r, vxn, when, why) for _ in range(len(self.legs)))

    def step(self, days):
        for l in self.legs:
            l.T -= days / 365.25

    def expire(self, S, when=None):
        """Cash-settle legs whose time has run out (no spread on settlement)."""
        cash = 0.0
        for i in reversed(range(len(self.legs))):
            l = self.legs[i]
            if l.T <= 1e-8:
                intr = max(l.K - S, 0.0) if l.right == "P" else max(S - l.K, 0.0)
                cf = l.units * intr
                self.ledger.append(dict(date=when, event="expire", right=l.right, K=l.K, T=0.0, units=-l.units,
                                        mid=intr, S=S, vxn=np.nan, cash=cf))
                cash += cf
                self.legs.pop(i)
        return cash
