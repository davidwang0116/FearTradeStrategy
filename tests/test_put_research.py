"""Frozen portfolio parity and accounting boundaries for the research branch."""
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
from common import RES, perf_stats
from options_experiments import BASE, SURFACES, panel
from options_model import OptionBook
from options_overlay import GRID, V2, run


@pytest.fixture(scope="module")
def data():
    return panel()


@pytest.mark.parametrize("pricing", SURFACES)
def test_all_existing_cells(pricing, data):
    frozen = pd.read_csv(RES / "options_trials.csv").set_index(["pricing", "cell"])
    for hedge in GRID:
        portfolio = run(data, V2, hedge=hedge, surface=SURFACES[pricing])[0]
        actual = perf_stats(portfolio.nav, data.rf)
        expected = frozen.loc[(pricing, hedge.label)]
        for field in ["Sharpe", "CAGR", "MaxDD"]:
            assert actual[field] == pytest.approx(expected[field], abs=1e-10)


def test_reduction_and_expiry():
    b = OptionBook()
    initial = b.open("P", 85, 1, 100, 100, .03, .2)
    proceeds = b.reduce(0, 40, 80, .03, .3)
    assert b.legs[0].units == 60
    b.step(366)
    final = b.expire(50)
    assert final == 60*35
    assert sum(e["cash"] for e in b.ledger) == pytest.approx(initial+proceeds+final)


@pytest.mark.parametrize("spot", [45,70,80,85,100,135])
def test_spread_collar_payoff(spot):
    b = OptionBook()
    for right,strike,sign in [("P",85,1),("P",70,-1),("C",110,-1)]:
        b.open(right,strike,1,sign,100,.03,.2)
    b.step(366)
    assert b.expire(spot) == max(85-spot,0)-max(70-spot,0)-max(spot-110,0)


@pytest.mark.parametrize("h", [replace(BASE,ladder=3),replace(BASE,split_spy=True),
                                replace(BASE,partial=.5),replace(BASE,lower_m=.7,call_m=1.1)])
def test_ledger_and_sizing(data,h):
    h = replace(h, whole=True)
    out, _, _, entries = run(data,V2,end="2010-12-31",capital=1e6,hedge=h)
    l=pd.DataFrame(entries)
    assert (l.units.abs()%100==0).all()
    assert np.allclose(l.groupby("date").cash.sum().reindex(out.index,fill_value=0),out.opt_flow)
    if h.split_spy:
        assert set(l.underlying)=={"qqq","spy"}
    if h.ladder>1:
        starts=l[l.event=="entry"].groupby("rung").date.min().sort_index()
        assert len(starts)==3 and starts.is_monotonic_increasing and starts.is_unique
    if h.partial:
        assert "partial" in l.event.values


def test_features_no_future(monkeypatch, data):
    import options_experiments as exp
    original=exp.load_panel()
    cutoff="2016-12-30"
    monkeypatch.setattr(exp,"load_panel",lambda:original.loc[:cutoff].copy())
    cols=["p","beta_126","downside_beta","high_rv","vol_premium","SKEW","VIX3M"]
    pd.testing.assert_frame_equal(data.loc[:cutoff,cols],exp.panel()[cols])
