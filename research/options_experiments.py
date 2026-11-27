"""Run the registered protective-put study locally. All portfolio options are model-priced."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from common import RES, build_signals, load_panel, perf_stats
from options_model import CENTRAL, pessimistic
from options_overlay import A_, B_, Hedge, V2, c1_for, episodes, run, scaled
from strategy import prepare

BASE = Hedge(cover="unguarded", exit="hold", proceeds="tbill")
SURFACES = {"central": CENTRAL, "pessimistic": pessimistic(CENTRAL),
            "flat-term": replace(CENTRAL, kappa=2 * CENTRAL.kappa)}
WINDOWS = {"full": (A_, B_), "early": (A_, "2016-12-31"),
           "late": ("2017-01-01", B_), "refresh": ("2019-12-31", B_), "2026-ytd": ("2025-12-31", B_),
           "data-extension": ("2026-04-17", B_), "quote-era": ("2012-01-03", B_)}
RAW = RES.parent / "data" / "raw"


def panel():
    p = load_panel()
    d = prepare(p, build_signals(p)).join(p[["spy", "vix"]])
    d = d.join(pd.read_csv(RAW / "options_etf_closes.csv", index_col=0, parse_dates=True))
    q, s = d.r_qqq, d.r_spy
    d["beta_126"] = s.rolling(126).cov(q) / q.rolling(126).var()
    d["beta_252"] = s.rolling(252).cov(q) / q.rolling(252).var()
    down = pd.concat([q, s], axis=1).loc[q < -.02].dropna()
    beta = down.r_spy.expanding(20).cov(down.r_qqq) / down.r_qqq.expanding(20).var()
    d["downside_beta"] = beta.reindex(d.index).ffill()
    rv = q.rolling(63).std()
    d["high_rv"] = rv > rv.shift().rolling(756).median()
    features = {"vxn_rank": d.vxn, "vol_premium": d.vxn - 100*q.rolling(21).std()*np.sqrt(252)}
    for name, column in [("VIX3M", "CLOSE"), ("SKEW", "SKEW")]:
        series = pd.read_csv(RAW / f"{name}_History.csv", index_col="DATE", parse_dates=True)[column]
        features[name] = d.vix / series if name == "VIX3M" else series
    for name, values in features.items():
        d[name] = values.reindex(d.index).expanding(252).rank(pct=True)
    study = d.loc[A_:B_].dropna(subset=["r_qqq", "r_spy"])
    if study[["raw_qqq", "raw_spy"]].isna().any().any():
        raise ValueError("Incomplete raw ETF prices in whole-contract study")
    return d


def registry():
    cells = {}
    def add(family, name, **changes):
        cells[name] = (family, replace(BASE, **changes), False)

    cells["unhedged"] = ("control", None, False)
    add("control", "frozen")
    add("control", "claude-benchmark", proceeds="tranche")
    for days in [91, 182, 365, 548, 730]:
        for strike in [70, 75, 80, 85, 90, 95, 100]:
            if (days, strike) == (365, 85):
                continue
            family = "maturity" if strike == 85 else "strike" if days == 365 else "map"
            add(family, f"put-{days}d-{strike}", tenor_days=days,
                roll_left_days=round(days/3), moneyness=strike/100)
    for days in [61, 183]:
        add("maturity", f"roll-{days}", roll_left_days=days)
    cells["guard-off"] = ("guard", None, True)
    cells["guard-off-put"] = ("guard", BASE, True)
    for ratio in [.25, .5, .75, 1.25]:
        add("coverage", f"coverage-{ratio}", cover_ratio=ratio)
    add("coverage", "dynamic", dynamic=True)
    for cap in [.01, .02, .03]:
        add("budget", f"budget-{cap}", budget_pa=cap)
    for gate in ["always", "vxn_rank", "vol_premium", "VIX3M", "SKEW"]:
        add("gate", gate, gate=gate)
    for frac in [.25, .5, .75, 1.]:
        for trigger in ["fear", "delta"]:
            add("exit", f"{trigger}-{frac}", partial=frac, partial_trigger=trigger)
    add("exit", "fear-0.5-tranche", partial=.5, proceeds="tranche")
    for beta in ["beta_126", "beta_252", "downside_beta"]:
        add("basis", beta, beta=beta)
    add("basis", "split-SPY", split_spy=True)
    for long, lower, call in [(85,70,0),(90,75,0),(85,70,110),(85,70,120),(85,0,115)]:
        add("structure", f"package-{long}-{lower}-{call}", moneyness=long/100,
            lower_m=lower/100 or None, call_m=call/100 or None)
    add("structure", "continuous-zero-debit", lower_m=.7, call_m=0.)
    add("structure", "covered-size-put", cover_shares_only=True)
    add("structure", "covered-size-spread", lower_m=.7, cover_shares_only=True)
    for days in [91,182,365,548,730]:
        add("matched-budget", f"cap2-tenor-{days}", tenor_days=days,
            roll_left_days=round(days/3), budget_pa=.02)
    for strike in [70,75,80,90,95,100]:
        add("matched-budget", f"cap2-strike-{strike}", moneyness=strike/100,budget_pa=.02)
    for weight in [.80,.90]:
        for hedged in [False,True]:
            cells[f"core-{weight:.2f}-" + ("put" if hedged else "unhedged")] = (
                "core-weight", BASE if hedged else None, False)
    # Follow-up factorial requested for the refresh-period return/Sharpe objective.
    # Both allocation levels and both nearer strikes are disclosed as exploratory.
    for weight in [.80, .90]:
        for strike in [.90, .95]:
            add("allocation-strike", f"core-{weight:.2f}-put-{strike:.2f}", moneyness=strike)
    for count in [1,2,3,4]:
        for phase in range(12):
            if count > 1 or phase:
                add("ladder", f"rungs-{count}-phase-{phase}", ladder=count,
                    phase_days=round(phase*365.25/12))
    return cells


def paired_interval(a, b, rf):
    """63-session paired block bootstrap, using block sums for bounded memory."""
    x = pd.concat([a.pct_change(), b.pct_change(), rf/252], axis=1).dropna().to_numpy()
    n = len(x)
    block = 63
    cols = np.column_stack((x, x[:,0]**2, x[:,1]**2))
    prefix = np.vstack([np.zeros(5), np.cumsum(cols, axis=0)])
    rng = np.random.default_rng(585)
    draws = rng.integers(0, n-block+1, (2000, int(np.ceil(n/block))))
    lengths = np.full(draws.shape[1], block)
    lengths[-1] = n - block*(len(lengths)-1)
    av = (prefix[draws+lengths]-prefix[draws]).sum(axis=1)/n
    vol = np.sqrt(av[:,3:5] - av[:,:2]**2)
    sharpe = (av[:,:2]-av[:,2:3])/vol*np.sqrt(252)
    return np.quantile(sharpe[:,0]-sharpe[:,1], [.05,.95])


def init():
    global D, CACHE
    D, CACHE = panel(), {}


def simulate(h, guard_off, surface, size, start, end, core_target=V2.core_target):
    if size and h:
        h = replace(h, whole=True)
    return run(D, replace(V2, trend_guard=not guard_off, core_target=core_target), start, end, hedge=h,
               surface=surface, capital=size or 100000, keep_trend_invested=guard_off)


def score(task):
    name, family, h, guard_off, pricing, size = task
    surface = SURFACES[pricing]
    start, end = A_, B_
    # Compare signal gates only where that gate has a historical observation.
    if h and h.gate not in ("always", "p"):
        start = max(pd.Timestamp(A_), D[h.gate].first_valid_index())
    key = (pricing, size, start)
    if key not in CACHE:
        base = simulate(BASE, False, surface, size, start, end)[0].nav
        unhedged = simulate(None, False, surface, size, start, end)[0].nav
        CACHE[key] = base, unhedged
    base, control = CACHE[key]
    weight = float(name.split("-")[1]) if family in ("core-weight","allocation-strike") else V2.core_target
    portfolio, trades, _, ledger = simulate(h, guard_off, surface, size, start, end, weight)
    nav = portfolio.nav
    meta = dict(cell=name, family=family, pricing=pricing, capital_mode=size or "fractional")
    records, declines, flows = [], [], []
    ledger = pd.DataFrame(ledger)
    if len(ledger):
        ledger["nav"] = nav.reindex(ledger.date).to_numpy()
        flows = ledger.assign(**meta).to_dict("records")
    train = nav.loc[:"2016-12-31"]
    train_k, _ = c1_for(control.reindex(train.index), perf_stats(train)["MaxDD"], D.rf, .001, 4)
    for label, (left, right) in WINDOWS.items():
        n = nav.loc[left:right]
        if len(n)<64:
            continue
        rf = D.rf.reindex(n.index)
        b, u = base.reindex(n.index), control.reindex(n.index)
        stats = perf_stats(n, rf)
        ref = perf_stats(b, rf)
        _, scaled_u = c1_for(u, stats["MaxDD"], rf, .001, 4)
        _, scaled_n = c1_for(n, ref["MaxDD"], rf, .001, 4)
        lo, hi = paired_interval(n, b, rf)
        monthly = n.resample("ME").last().pct_change().dropna()
        daily = n.pct_change().dropna()
        tail = lambda x: x[x <= x.quantile(.05)].mean()
        stress = D.p.reindex(n.index) >= .8
        years = (n.index[-1]-n.index[0]).days/365.25
        prem = 0.
        if len(ledger):
            buys = ledger[ledger.date.between(n.index[0], n.index[-1]) &
                          ledger.event.isin(["entry","roll buy","roll-down buy"]) & (ledger.units>0)]
            prem = -buys.cash.sum()/n.mean()/years
        hp = portfolio.hedge_pnl
        prev = hp.loc[hp.index<n.index[0]]
        records.append(dict(**meta,window=label,start=n.index[0],end=n.index[-1],**stats,
            total_return=n.iloc[-1]/n.iloc[0]-1,
            delta_cagr=stats["CAGR"]-ref["CAGR"], benchmark_sharpe=ref["Sharpe"],
            delta_sharpe=stats["Sharpe"]-ref["Sharpe"],ci05=lo,ci95=hi,
            equal_dd_delta=perf_stats(scaled_n,rf)["CAGR"]-ref["CAGR"],
            prior_fit_cash_delta=(stats["CAGR"]-perf_stats(scaled(u,rf,train_k),rf)["CAGR"]
                                 if label=="late" else np.nan),
            liquidation_maxdd=perf_stats(portfolio.liquidation_nav.reindex(n.index),rf)["MaxDD"],
            vs_cash=stats["CAGR"]-perf_stats(scaled_u,rf)["CAGR"],
            delta_dd=stats["MaxDD"]-ref["MaxDD"],delta_daily_es=tail(daily)-tail(b.pct_change().dropna()),
            ulcer=np.sqrt(((n/n.cummax()-1)**2).mean()),monthly_es=tail(monthly),
            gross_premium=prem,net_option_pnl=(hp[n.index[-1]]-(prev.iloc[-1] if len(prev) else 0))/n.mean()/years,
            high_fear_held=portfolio.held.reindex(n.index)[stress].mean(),min_exposure=portfolio.expo.reindex(n.index).min()))
    for peak,trough,recovery in episodes(control):
        w = nav.loc[peak:recovery]
        hp = portfolio.hedge_pnl
        declines.append(dict(**meta,peak=peak,trough=trough,recovery=recovery,
            drawdown=(w/w.cummax()-1).min(),hedge_at_trough=(hp[trough]-hp[peak])/w.iloc[0],
            hedge_at_recovery=(hp[recovery]-hp[peak])/w.iloc[0]))
    return records, declines, flows if pricing=="central" else []


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--family", default="all", choices=["all",*sorted({v[0] for v in registry().values()})])
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out", type=Path, default=RES/"put_research")
    args=ap.parse_args()
    cells=registry()
    tasks=[(name,group,h,guard,price,size) for name,(group,h,guard) in cells.items()
           if args.family in ("all",group) or group=="control"
           for price in SURFACES for size in (0,100000,1000000)]
    tables=[[],[],[]]
    with ProcessPoolExecutor(args.jobs, initializer=init) as pool:
        for result in pool.map(score,tasks,chunksize=3):
            for table,rows in zip(tables,result):
                table.extend(rows)
    out=args.out if args.family=="all" else args.out/args.family
    out.mkdir(parents=True,exist_ok=True)
    for rows,filename in zip(tables,["trials","declines","central_ledger"]):
        pd.DataFrame(rows).to_csv(out/f"{filename}.csv.gz", index=False,float_format="%.10g")
    print(f"{len(tasks)} runs, {len(tables[0])} window results in {out}")


if __name__=="__main__":
    main()
