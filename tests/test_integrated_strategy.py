"""Regression checks for the integrated tranche gate and protective-put accounting."""
from datetime import datetime, timedelta
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import numpy as np
import pandas as pd
import pytest

import qc_harness as h

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "options/protective_put/research"), str(ROOT / "research")]
from integrated_put import ModeledPut
from strategy import Cfg, run


def small_market(start, price, fear):
    return pd.DataFrame({"qqq": price, "raw_qqq": price, "rf": 0.0, "vxn": 30.0,
                         "p": fear, "ma200": 100.0, "vxn_recede": True},
                        index=pd.bdate_range(start, periods=len(price))).assign(r_qqq=lambda x: x.qqq.pct_change().fillna(0))


def test_put_sale_cash_and_mark_reconcile_with_core_tranche():
    data = small_market("2020-02-10", [100, 100, 55, 50, 50], [.30, .60, .95, .80, .70])
    config = Cfg("test", tranche=1, tranche_p=2)
    gate = pd.Series(True, index=data.index[[2]])
    outcomes = {}
    for routing in ("tbill", "tranche"):
        put = ModeledPut(exit="fear", proceeds=routing)
        frame, trades = run(data, config, data.index[0], data.index[-1], 100_000, tranche_entry=gate, overlay=put)
        np.testing.assert_allclose(frame[["core", "cash", "lev", "trend", "hedge_mark"]].sum(axis=1), 1)
        assert trades.date.to_list() == [data.index[3]]
        assert frame.hedge_flow.iloc[1] < 0 < frame.hedge_flow.iloc[3]
        assert [row["event"] for row in put.book.ledger] == ["entry", "fear exit"]
        assert frame.hedge_flow.sum() == pytest.approx(sum(row["cash"] for row in put.book.ledger))
        assert frame.hedge_mark.iloc[3] == 0
        outcomes[routing] = frame, trades.amount.iloc[0]
    restricted, spendable = outcomes["tbill"], outcomes["tranche"]
    assert restricted[0].hedge_bucket.iloc[3] > 0
    assert spendable[0].hedge_bucket.iloc[3] == 0
    assert spendable[1] - restricted[1] == pytest.approx(restricted[0].hedge_flow.iloc[3])


def test_modeled_expiry_uses_last_session_before_nominal_weekend():
    data = small_market("2020-02-11", [100, 100, 80, 70, 40], [.30, .70, .80, .80, .80])
    put = ModeledPut(tenor=4, roll_days=0)
    frame, _ = run(data, Cfg("test", fear_off=True), data.index[0], data.index[-1], overlay=put)
    settlement = put.book.ledger[-1]
    assert settlement["event"] == "expire" and settlement["date"] == pd.Timestamp("2020-02-14")
    assert settlement["mid"] == pytest.approx(15)
    assert frame.hedge_mark.iloc[-1] == 0
    assert frame.hedge_bucket.iloc[-1] * frame.nav.iloc[-1] == pytest.approx(settlement["cash"])


def test_vix_gate_waits_for_matching_session_and_excludes_carry_forward():
    algo = h.load_qc().FearTrancheAccumulator()
    algo.qqq, algo.vxn, algo.vix, algo.hedge = "QQQ", "VXN", "VIX", None
    algo.pending_daily = algo.latest_vix = None
    algo.midnight_bars = algo.align_vix = True
    rows = []
    algo._on_daily = lambda *args: rows.append(args)
    session = datetime(2020, 3, 16)
    qqq = NS(time=session, close=170, period=timedelta(days=1))
    vxn = NS(time=session, close=81)
    algo.time = session + timedelta(days=1)
    algo.on_data(h.Slice({"QQQ": qqq, "VXN": vxn}))
    assert not rows
    algo.time += timedelta(hours=1)
    vix = NS(time=session, close=82, is_fill_forward=False)
    algo.on_data(h.Slice({"VIX": vix}))
    assert rows == [(session.date(), 170, vxn, vix)]
    algo.on_data(h.Slice({"VIX": vix}))
    assert len(rows) == 1
    tomorrow = session + timedelta(days=1)
    algo.time = tomorrow + timedelta(days=1, hours=1)
    algo.on_data(h.Slice({"QQQ": NS(time=tomorrow, close=175),
                          "VIX": NS(time=tomorrow, close=82, is_fill_forward=True)}))
    assert rows[-1] == (tomorrow.date(), 175, None, None)


def test_qc_pending_put_fills_and_cancel_use_real_cash_only():
    module = h.load_qc("hedge.py")
    module.OrderStatus = NS(PARTIALLY_FILLED="partial", FILLED="filled", CANCELED="canceled", INVALID="invalid")
    sh = NS(invested=True, holdings_value=1_500)
    algo = NS(get_parameter=lambda k: "tbill" if k == "hedge_proceeds" else None,
              qqq="QQQ", portfolio={"put": sh}, time=datetime(2020, 3, 17, 9, 40), log=lambda _: None)
    put = module.ProtectivePut(algo)
    put.held = "put"

    def event(qty, price, status, fee=0):
        return NS(symbol="put", fill_quantity=qty, fill_price=price, status=status, order_id=4,
                  order_fee=NS(value=NS(amount=fee)))

    put.pending = NS(symbol="put", ticket=NS(order_id=4), entry=False, bought=False)
    assert put.bucket == 0 and put.nonspendable_value() == 1_500
    put.on_order_event(event(-1, 5.25, "partial", 0.65))
    assert put.held == "put" and put.pending is not None
    assert put.bucket == pytest.approx(524.35)
    put.on_order_event(event(0, 0, "canceled"))
    assert put.held == "put" and put.pending is None and put.bucket == pytest.approx(524.35)
    assert put.net_flow == pytest.approx(524.35)

    put.pending = NS(symbol="put", ticket=NS(order_id=4), entry=True, bought=False)
    put.on_order_event(event(1, 2.10, "filled", 0.65))
    assert put.pending is None and put.bucket == 0
    assert put.stats["restricted_cash_released"] == pytest.approx(313.70)
    assert put.net_flow == pytest.approx(313.70)


def test_qc_requires_a_fresh_two_sided_quote():
    hedge = h.load_qc("hedge.py")
    now = datetime(2022, 6, 3, 9, 31)
    bar = NS(end_time=now, bid=NS(close=1), ask=NS(close=2), is_fill_forward=False)
    assert hedge.fresh_quote(bar, now) == (1, 2)
    assert hedge.fresh_quote(bar, now + timedelta(minutes=1)) is None
    bar.is_fill_forward = True
    assert hedge.fresh_quote(bar, now) is None
