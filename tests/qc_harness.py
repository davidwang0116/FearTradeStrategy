"""Minimal offline stand-in for LEAN, enough to drive qc/main.py on the local panel.

NOT a LEAN replacement: fractional shares, no margin model, signals injected from the local panel.
Orders sent in on_data fill on the NEXT bar's close (before that bar's on_data), because the panel has no opens and
strategy.run() also trades at the next close; LEAN fills at the next open. sync=True fills immediately instead, to
isolate what the one-bar order delay does.

real_signals=True runs the algorithm's own composite and percentile (slow); otherwise p is injected from the panel.
live=True with store= (a dict) exercises the live-only state saving; account= restores holdings to simulate a restart."""
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace as NS

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


class Bars(dict):
    contains_key = dict.__contains__


class Store(dict):
    """Stand-in for QC's ObjectStore."""
    def save(self, k, v): self[k] = v
    def read(self, k): return self[k]
    def contains_key(self, k): return k in self


class QCAlgorithm:
    params, live_mode, is_warming_up = {}, False, False

    def get_parameter(self, k): return self.params.get(k)
    def set_start_date(self, *a): pass
    set_end_date = set_brokerage_model = set_warm_up = plot = set_start_date
    def set_cash(self, c): self.cash0 = c
    def add_equity(self, t, *a, **k): return NS(symbol=t)
    def add_index(self, t, *a, **k): return NS(symbol=t)
    def add_option(self, t, *a, **k): return NS(symbol=t + "_OPT", set_filter=lambda f: None)
    def set_benchmark(self, *a): pass
    start_date = property(lambda self: self.start)
    def log(self, m): self.logs.append(m)

    def history(self, syms, n, res, *rest):
        """history(syms, bar_count, res) or history(syms, start, end, res); bars strictly before the start bar."""
        px = self.feed[syms[0]].loc[:self.start].dropna()
        px = px[px.index < self.start]
        px = px.iloc[-n:] if isinstance(n, int) else px.loc[pd.Timestamp(n):]
        return pd.DataFrame({"close": px.to_numpy()}, index=pd.MultiIndex.from_product([syms, px.index]))

    @property
    def portfolio(self):
        a = self

        class P(dict):
            total_portfolio_value = a.nav()
            invested = any(q != 0 for q in a.qty.values())
            def __missing__(p, s): return NS(holdings_value=0.0, invested=False, quantity=0.0, holdings_cost=0.0, average_price=0.0)
        return P({s: NS(holdings_value=q * a.px[s], invested=q != 0, quantity=q, holdings_cost=a.cost.get(s, 0.0),
                        average_price=a.cost.get(s, 0.0) / q if q else 0.0) for s, q in a.qty.items()})

    def nav(self): return self.cash + sum(q * self.px[s] for s, q in self.qty.items())

    def set_holdings(self, targets):
        v = self.nav()
        self.pending = {t.symbol: t.quantity * v / self.px[t.symbol] for t in targets}   # sized now, filled later
        self.n_rebalance += 1
        if self.sync:
            self.fill()

    def fill(self):
        for s, q in self.pending.items():
            dq = q - self.qty.get(s, 0.0)
            rate = 0.0 if s == "BIL" else 0.0015 if s in ("QLD", "TQQQ") else 0.0005
            self.cash -= dq * self.px[s] + abs(dq) * self.px[s] * rate
            q0 = self.qty.get(s, 0.0)
            self.cost[s] = self.cost.get(s, 0.0) + dq * self.px[s] if dq > 0 else (self.cost.get(s, 0.0) * q / q0 if q0 else 0.0)
            self.qty[s] = q
            self.turnover[s] = self.turnover.get(s, 0.0) + abs(dq) * self.px[s]
        self.pending = {}


INDEXES = ("VXN", "VIX")


class Slice:
    def __init__(self, bars): self.bars = Bars(bars)


def load_qc(file="main.py"):
    stub = types.ModuleType("AlgorithmImports")
    any_ = type("Any_", (), {"__getattr__": lambda s, k: k})()
    stub.__dict__.update(QCAlgorithm=QCAlgorithm, Slice=Slice, Resolution=any_, BrokerageName=any_, AccountType=any_,
                         DataNormalizationMode=any_, SecurityType=any_,
                         PortfolioTarget=lambda s, q: NS(symbol=s, quantity=q),
                         timedelta=lambda days: days)
    sys.modules["AlgorithmImports"] = stub
    if str(ROOT / "qc") not in sys.path:
        sys.path.insert(0, str(ROOT / "qc"))
    spec = importlib.util.spec_from_file_location("qc_" + Path(file).stem, ROOT / "qc" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def feed_from_panel(D):
    """Total-return price series: one growth index per ETF. QQQ keeps its level (the signals need it)."""
    g = lambda r: 100 * (1 + r.fillna(0)).cumprod()
    f = pd.DataFrame({"QQQ": D["qqq"], "VOO": g(D["r_spy"]), "QLD": g(D["r_qld"]), "TQQQ": g(D["r_tqqq"]), "BIL": g(D["rf"] / 252), "VXN": D["vxn"]})
    if "vxn_backfilled" in D:          # what QC has: VXN only from 2008-01-03, plus VIX
        f["VXN"] = D["vxn"].where(~D["vxn_backfilled"].fillna(False).astype(bool))
    f["VIX"] = D["vix"] if "vix" in D else float("nan")
    f["SPY"] = f["VOO"]
    return f


def run_qc(D, start, end, params=None, sync=False, mod=None, real_signals=False, live=False, store=None, account=None):
    """Returns (daily frame with nav and sleeve fractions, algorithm).
    account = dict(qty=, cash=, cost=, pending=) from a previous run's algorithm restores the brokerage account."""
    mod = mod or load_qc()
    feed = feed_from_panel(D)
    comp = D["p"]
    base = mod.FearTrancheAccumulator
    if real_signals:
        Algo = type("Algo", (base,), {})
    else:
        class Algo(base):
            def _frame(self): return pd.DataFrame({"composite": [self.p_now]})
            def _seed_composite(self, *a): pass
            def _pct(self, x): return float(self.p_now)

    a = Algo()
    a.params = {k: str(v) for k, v in (params or {}).items()}
    a.feed, a.start, a.sync, a.logs, a.qty, a.pending, a.turnover, a.n_rebalance = feed, pd.Timestamp(start), sync, [], {}, {}, {}, 0
    a.p_now, a.px, a.cash0, a.cost, a.time = float("nan"), {}, 100_000.0, {}, pd.Timestamp(start)
    a.live_mode, a.object_store = live, store if store is not None else Store()
    a.initialize()
    a.cash = a.cash0
    if account:
        a.qty, a.cash, a.cost, a.pending = (dict(account[k]) if isinstance(account[k], dict) else account[k]
                                            for k in ("qty", "cash", "cost", "pending"))
    rows, names = [], [c for c in feed.columns if c not in INDEXES]
    for t, row in feed.loc[start:end].iterrows():
        a.time, a.px, a.p_now = t, {s: row[s] for s in names}, comp.loc[t]
        a.fill()
        if a.nav() <= 0:
            raise RuntimeError("bankrupt")
        bars = {s: NS(close=row[s]) for s in names}
        for s in INDEXES:
            if row[s] == row[s]:
                bars[s] = NS(close=row[s])
        a.on_data(Slice(bars))
        v = a.nav()
        h = {s: q * a.px[s] / v for s, q in a.qty.items()}
        rows.append(dict(nav=v, p=getattr(a, "p_last", float("nan")), qqq=h.get("QQQ", 0), spy=h.get("VOO", 0) + h.get("SPY", 0), qld=h.get("QLD", 0), bil=h.get("BIL", 0),
                         **{"book_" + k: x for k, x in a.book.items() if isinstance(x, (int, float))}))
    return pd.DataFrame(rows, index=feed.loc[start:end].index), a
