"""Allocation study: equity vs T-bill share (70/75/80%) and QQQ vs SPY core mix (0/50/70/80/100% QQQ).

Grid, fixed before any of it was run; every cell is reported:
  static          15  monthly-rebalanced core mix + T-bills, 5 bp per side
  scaled ladder   15  v2 rules + QLD + trend guard; tranche = reserve/4, leverage buy = reserve/3, cap = reserve
  fixed ladder    10  same with v2's 7.5% / 10% / 30%, at 75% and 80% equity (at 70% the ladder sizes coincide)
Strategy cells hold the core basket in the trend-guarded half and reset the basket on rebalance events
(trend_asset="core", basket_reset="event"), as qc/main.py does. The 70% / 50% QQQ cell is therefore NOT
frozen v2, whose trend half is QQQ and whose weights drift; see the bridge table.

Three questions, three comparisons
  Equity share  mix and ladder fixed; 75 vs 70 and 80 vs 70. DESCRIPTIVE trade-off, no winner: extra CAGR,
                extra drawdown, change in days with spendable reserve < 1% of NAV.
  QQQ mix       equity and ladder fixed; 0/70/80/100% QQQ vs 50%. Sharpe difference, 4 x 5 = 20 tests.
  v3 candidate  25 strategy cells vs frozen v2 (README headline config). Sharpe difference, 25 tests.

Decision rule (written before the grid was run)
  * The 45 tests are ONE family. A joint 63-day moving-block bootstrap gives simultaneous one-sided max-t
    lower bounds at 5% family-wise error. "Better" = simultaneous lower bound > 0. Romano-Wolf step-down
    p-values are reported but do not decide; unadjusted bounds are labelled.
  * Sign agreement 2007-2019 / 2020-2026 is a stability check, not a test; a pass that disagrees is "unstable".
    The whole sample was looked at during the project, so neither half is out-of-sample.
  * Equal-drawdown CAGR gap is descriptive: same core mix + T-bills, same monthly rebalancing and costs as the
    static grid, equity share FITTED IN HINDSIGHT to the strategy's max drawdown.
  * Any preferred QQQ weight is at most PROVISIONAL. The panel's SPY is not a true total-return series:
    2013-2022 10.76%/yr vs 12.42% in State Street's fact sheet, 2022 -16.02% vs -18.17% at NAV, so both the
    mean and the volatility are understated. The flat +1.36%/yr run below bounds the mean only (it moves 2022
    further from the published loss) and is never used for drawdown, Sharpe or ranking claims.

A "100% SPY core" still buys QLD (2x Nasdaq) and still follows QQQ signals; plain QQQ, SPY and QLD-2x
exposure are reported separately.

Two diagnostics were added AFTER the grid was seen; neither changes the rule or the grid:
  drawdown_check   16 runs (8 new, without the trend guard) showing why the strategy's drawdown does not deepen with equity
  test_robustness  the same 45 tests with other block lengths and another seed

Outputs: allocation/results/allocation_{static,strategy,equity_tradeoff,mix_tests,v3_tests,bridge,spy_bound,qqq_long,
         drawdown_check,test_robustness}.csv
"""
from dataclasses import replace

import numpy as np
import pandas as pd
from scipy.optimize import brentq

import allocation_paths  # noqa: F401  (puts the shared research/ on sys.path)
from allocation_paths import RESULTS
from common import block_boot_sharpes, build_signals, load_panel, maxt_family, perf_stats
from strategy import Cfg, bh, prepare, run

A, B = "2007-02-01", "2026-09-11"
EQUITY, MIXES = (0.70, 0.75, 0.80), (0.0, 0.5, 0.7, 0.8, 1.0)
HALVES = (("2007", "2019"), ("2020", "2026"))
COST, UPLIFT, BLOCK, N_BOOT = 0.0005, 0.0136, 63, 5000
V2 = Cfg("frozen v2", core=(("qqq", 0.5), ("spy", 0.5)), tranche=0.075, tranche_step=0.92, lev_cap=0.30,
         lev="qld", trend_guard=True)


def mix_label(q):
    return "100% SPY core" if q == 0 else "100% QQQ core" if q == 1 else f"{q:.0%} QQQ / {1 - q:.0%} SPY"


def core_of(q):
    return tuple((k, w) for k, w in (("qqq", q), ("spy", 1 - q)) if w > 1e-12)


def ladder_sizes(equity, ladder):
    r = round(1 - equity, 10)
    return (dict(tranche=r / 4, lev_size=r / 3, lev_cap=r) if ladder == "scaled"
            else dict(tranche=0.075, lev_size=0.10, lev_cap=0.30))


def cell_cfg(equity, q, ladder):
    return Cfg(f"{equity:.0%} equity, {mix_label(q)}, {ladder}", core=core_of(q), core_target=equity,
               tranche_step=0.92, lev="qld", trend_guard=True, trend_asset="core", basket_reset="event",
               **ladder_sizes(equity, ladder))


def static_mix(D, q, equity, start, end, rebal="M", cost=COST, capital=100_000.0):
    """Core mix + T-bills. rebal: "M" month-end close | "D" daily | None (drift). Costs on QQQ/SPY turnover.
    Invested at the first close, like strategy.run()."""
    d = D.loc[start:end].dropna(subset=["r_" + k for k, _ in core_of(q)])
    rq, rs, rf = d["r_qqq"].fillna(0).to_numpy(), d["r_spy"].fillna(0).to_numpy(), d["rf"].to_numpy() / 252
    m = d.index.to_period("M")
    month_end = np.append(m[1:] != m[:-1], False)
    tq, ts = equity * q, equity * (1 - q)
    Q, S, C = capital * tq, capital * ts, capital * (1 - equity)
    nav = np.empty(len(d)); nav[0] = capital
    for i in range(1, len(d)):
        Q *= 1 + rq[i]; S *= 1 + rs[i]; C *= 1 + rf[i]
        V = Q + S + C
        if rebal == "D" or (rebal == "M" and month_end[i]):
            V -= cost * (abs(tq * V - Q) + abs(ts * V - S))
            Q, S, C = V * tq, V * ts, V * (1 - equity)
        nav[i] = V
    return pd.Series(nav, d.index)


def mdd(nav):
    return (nav / nav.cummax() - 1).min()


def equal_drawdown_share(D, q, target, start, end):
    """Equity share (fitted in hindsight) at which the monthly static mix has max drawdown = target; nan if none <= 100%."""
    f = lambda k: mdd(static_mix(D, q, k, start, end)) - target
    if f(1.0) > 0:                      # fully invested still falls less than the strategy
        return np.nan
    return brentq(f, 0.05, 1.0, xtol=1e-5)


def underwater_days(nav):
    under = (nav < nav.cummax()).to_numpy()
    best = cur = 0
    for u in under:
        cur = cur + 1 if u else 0
        best = max(best, cur)
    return best


def metrics(nav, rf):
    st = perf_stats(nav, rf)
    dd = nav / nav.cummax() - 1
    m = nav.resample("ME").last().pct_change().dropna()
    out = dict(**st, Ulcer=np.sqrt((dd ** 2).mean()), CVaR5_monthly=m[m <= m.quantile(.05)].mean(),
               underwater_days=underwater_days(nav), end_value=nav.iloc[-1])
    for a, b in HALVES:
        s = perf_stats(nav.loc[a:b], rf)
        out[f"Sharpe {a}-{b}"], out[f"CAGR {a}-{b}"], out[f"MaxDD {a}-{b}"] = s["Sharpe"], s["CAGR"], s["MaxDD"]
    ye = nav.resample("YE").last()
    for y in (2008, 2020, 2022):
        if y - 1 in ye.index.year:
            out[f"ret_{y}"] = ye[ye.index.year == y].iloc[0] / ye[ye.index.year == y - 1].iloc[0] - 1
    return out


def strategy_metrics(res, tr, rf):
    want, got = res["tranche_want"], res["tranche_got"]
    nasdaq = res["qqq_w"] + res["lev_2x"]
    return dict(**metrics(res["nav"], rf), days_reserve_lt1=int((res["reserve"] < 0.01).sum()),
                pct_days_reserve_lt1=(res["reserve"] < 0.01).mean(), avg_reserve=res["reserve"].mean(),
                avg_trend_parked=res["trend_parked"].mean(), avg_qqq=res["qqq_w"].mean(), avg_spy=res["spy_w"].mean(),
                avg_qld_2x=res["lev_2x"].mean(), max_qld_2x=res["lev_2x"].max(), avg_nasdaq_total=nasdaq.mean(),
                max_nasdaq_total=nasdaq.max(), avg_expo=res["expo"].mean(),
                realized_qqq_share=(res["qqq_w"] / (res["qqq_w"] + res["spy_w"])).mean(), trades=len(tr),
                tranches_full=int(((got > 0) & (got >= want - 1e-9)).sum()),
                tranches_partial=int(((got > 0) & (got < want - 1e-9)).sum()),
                days_tranche_blocked=int(((want > 0) & (got == 0)).sum()))


def cells():
    out = [(e, q, "scaled") for e in EQUITY for q in MIXES]
    return out + [(e, q, "fixed") for e in EQUITY[1:] for q in MIXES]


def main():
    P = load_panel(); D = prepare(P, build_signals(P)); D["r_cash"] = 0.0; rf = P["rf"]
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)

    # ---- portfolios ----
    static, navs, strat_rows, static_rows = {}, {}, [], []
    for e in EQUITY:
        for q in MIXES:
            n = static_mix(D, q, e, A, B); static[(e, q)] = n
            static_rows.append(dict(kind="static monthly", equity=e, qqq_share=q, mix=mix_label(q), has_spy=q < 1, **metrics(n, rf)))
    refs = {"Buy & hold QQQ": bh(D, {"qqq": 1.0}, A, B), "Buy & hold SPY": bh(D, {"spy": 1.0}, A, B),
            "Buy & hold 50/50 QQQ+SPY": bh(D, {"qqq": .5, "spy": .5}, A, B),
            "Buy & hold 50/50 QQQ+SPY, bought once": bh(D, {"qqq": .5, "spy": .5}, A, B, rebalance="never"),
            "Drifting static 70/30 (50/50 core, never rebalanced)": run(D, Cfg("s", fear_off=True, core=core_of(.5)), A, B)[0]["nav"]}
    for k, n in refs.items():
        static_rows.append(dict(kind="reference", mix=k, has_spy=k != "Buy & hold QQQ", **metrics(n, rf)))
    pd.DataFrame(static_rows).to_csv(RESULTS / "allocation_static.csv", index=False)

    def add(name, cfg, e, q, ladder, bench_q):
        res, tr = run(D, cfg, A, B); nav = res["nav"]; navs[name] = nav
        k = equal_drawdown_share(D, bench_q, mdd(nav), A, B)
        gap = perf_stats(nav, rf)["CAGR"] - perf_stats(static_mix(D, bench_q, k, A, B), rf)["CAGR"] if k == k else np.nan
        strat_rows.append(dict(name=name, equity=e, qqq_share=q, mix=mix_label(q) if q is not None else "v2: initial trend-on 75/25",
                               ladder=ladder, has_spy=q != 1.0, **strategy_metrics(res, tr, rf), bench_qqq_share=bench_q,
                               hindsight_equal_dd_equity=k, cagr_gap_equal_dd=gap))
    add("frozen v2", V2, 0.70, None, "v2", 0.75)
    for e, q, lad in cells():
        add((e, q, lad), cell_cfg(e, q, lad), e, q, lad, q)
    S = pd.DataFrame(strat_rows)
    S.assign(name=[n if isinstance(n, str) else cell_cfg(*n).name for n in S.name]).to_csv(RESULTS / "allocation_strategy.csv", index=False)
    row = {n: r for n, (_, r) in zip(navs, S.iterrows())}

    # ---- equity share: descriptive trade-off ----
    eq = []
    get = lambda e, q, lad: row[(e, q, "scaled" if e == 0.70 else lad)]     # at 70% the two ladders are the same cell
    for lad in ("scaled", "fixed"):
        for q in MIXES:
            for e in EQUITY[1:]:
                a, b = get(e, q, lad), get(0.70, q, lad)
                eq.append(dict(portfolio=f"strategy, {lad} ladder", mix=mix_label(q), qqq_share=q, change=f"{e:.0%} vs 70%",
                               d_CAGR=a.CAGR - b.CAGR, d_MaxDD=a.MaxDD - b.MaxDD, d_Sharpe=a.Sharpe - b.Sharpe,
                               d_days_reserve_lt1=a.days_reserve_lt1 - b.days_reserve_lt1,
                               days_reserve_lt1_from=b.days_reserve_lt1, days_reserve_lt1_to=a.days_reserve_lt1, has_spy=q < 1))
    for q in MIXES:
        for e in EQUITY[1:]:
            a, b = metrics(static[(e, q)], rf), metrics(static[(0.70, q)], rf)
            eq.append(dict(portfolio="static monthly", mix=mix_label(q), qqq_share=q, change=f"{e:.0%} vs 70%", d_CAGR=a["CAGR"] - b["CAGR"],
                           d_MaxDD=a["MaxDD"] - b["MaxDD"], d_Sharpe=a["Sharpe"] - b["Sharpe"], has_spy=q < 1))
    E = pd.DataFrame(eq); E.to_csv(RESULTS / "allocation_equity_tradeoff.csv", index=False)

    # ---- the 45 tests ----
    names = list(navs)
    R = pd.DataFrame({i: navs[n].pct_change() for i, n in enumerate(names)}).dropna()
    pt, bt = block_boot_sharpes(R, rf, BLOCK, N_BOOT)
    ix = {n: i for i, n in enumerate(names)}
    pairs = [("mix", (e, q, lad), (e, 0.5, lad)) for e, lad in [(e, "scaled") for e in EQUITY] + [(e, "fixed") for e in EQUITY[1:]]
             for q in MIXES if q != 0.5]
    pairs += [("v3", c, "frozen v2") for c in cells()]
    point = np.array([pt[ix[a]] - pt[ix[b]] for _, a, b in pairs])
    boot = np.column_stack([bt[:, ix[a]] - bt[:, ix[b]] for _, a, b in pairs])
    T, crit = maxt_family(point, boot)
    T.insert(0, "test", [p[0] for p in pairs])
    for j, k in enumerate(("equity", "qqq_share", "ladder")):
        T.insert(1 + j, k, [p[1][j] for p in pairs])
    T.insert(4, "versus", ["50% QQQ / 50% SPY, same equity and ladder" if p[0] == "mix" else "frozen v2" for p in pairs])
    for a, b in HALVES:
        T[f"diff {a}-{b}"] = [row[x][f"Sharpe {a}-{b}"] - row[y][f"Sharpe {a}-{b}"] for _, x, y in pairs]
    for met in ("CAGR", "MaxDD"):
        T["d_" + met] = [row[x][met] - row[y][met] for _, x, y in pairs]
    signs = [np.sign(T[f"diff {a}-{b}"]) for a, b in HALVES]
    T["halves_agree"] = (signs[0] == signs[1]) & (signs[0] == np.sign(T["diff"]))
    T["passes"] = T.lb_simultaneous > 0
    T["status"] = np.where(~T.passes, "not distinguishable", np.where(T.halves_agree, "provisional (SPY data)", "provisional, unstable"))
    T["family_size"], T["maxt_critical"] = len(T), crit
    T[T.test == "mix"].to_csv(RESULTS / "allocation_mix_tests.csv", index=False)
    T[T.test == "v3"].to_csv(RESULTS / "allocation_v3_tests.csv", index=False)

    rob = []
    for block, seed in ((21, 585), (BLOCK, 585), (BLOCK, 1), (126, 585), (252, 585)):
        p_, b_ = block_boot_sharpes(R, rf, block, N_BOOT, seed)
        t_, c_ = maxt_family([p_[ix[a]] - p_[ix[b]] for _, a, b in pairs],
                             np.column_stack([b_[:, ix[a]] - b_[:, ix[b]] for _, a, b in pairs]))
        rob.append(dict(block=block, seed=seed, maxt_critical=c_, passes=int((t_.lb_simultaneous > 0).sum()),
                        best_lower_bound=t_.lb_simultaneous.max(), min_p_stepdown=t_.p_stepdown.min(),
                        unadjusted_passes=int((t_.lb_unadjusted > 0).sum())))
    pd.DataFrame(rob).to_csv(RESULTS / "allocation_test_robustness.csv", index=False)

    # ---- why the strategy's drawdown does not deepen with equity (post-grid diagnostic) ----
    dc = []
    for q in (0.5, 1.0):
        for e, lad in [(e, "scaled") for e in EQUITY] + [(0.80, "fixed")]:
            for guard in (True, False):
                c = cell_cfg(e, q, lad)
                if not guard:
                    c = replace(c, trend_guard=False, trend_asset="qqq", basket_reset="none")
                r_, _ = run(D, c, A, B)
                n_ = r_["nav"]; tr_ = (n_ / n_.cummax() - 1).idxmin(); x = r_.loc[tr_]
                dc.append(dict(qqq_share=q, equity=e, ladder=lad, trend_guard=guard, MaxDD=mdd(n_), trough=tr_.date(),
                               equity_at_trough=x.core + x.trend, parked_at_trough=x.trend_parked, reserve_at_trough=x.reserve))
    pd.DataFrame(dc).to_csv(RESULTS / "allocation_drawdown_check.csv", index=False)

    # ---- bridge: frozen v2 -> each cell, one change at a time ----
    basket = Cfg(**{**V2.__dict__, "name": "v2 + basket trend sleeve", "trend_asset": "core"})
    mb = perf_stats(run(D, basket, A, B)[0]["nav"], rf)
    chain, br = ["frozen v2", "basket trend sleeve", "event reset", "QQQ mix", "equity share", "ladder"], []
    for e, q, lad in cells():
        seq = [row["frozen v2"], mb, row[(0.70, 0.5, "scaled")], row[(0.70, q, "scaled")], row[(e, q, "scaled")], row[(e, q, lad)]]
        for met in ("Sharpe", "CAGR", "MaxDD"):
            br.append(dict(equity=e, qqq_share=q, ladder=lad, metric=met, v2=seq[0][met],
                           **{f"step: {c}": seq[i + 1][met] - seq[i][met] for i, c in enumerate(chain[1:])}, cell=seq[-1][met]))
    pd.DataFrame(br).to_csv(RESULTS / "allocation_bridge.csv", index=False)

    # ---- SPY mean-return bound (CAGR only, no ranking) ----
    DU = D.copy(); DU["r_spy"] = DU["r_spy"] + UPLIFT / 252
    sb = []
    for e in EQUITY:
        for q in MIXES:
            sb.append(dict(portfolio="static monthly", equity=e, qqq_share=q, ladder="", CAGR_panel=metrics(static[(e, q)], rf)["CAGR"],
                           CAGR_spy_plus_1_36=perf_stats(static_mix(DU, q, e, A, B), rf)["CAGR"]))
    for e, q, lad in cells():
        sb.append(dict(portfolio="strategy", equity=e, qqq_share=q, ladder=lad, CAGR_panel=row[(e, q, lad)].CAGR,
                       CAGR_spy_plus_1_36=perf_stats(run(DU, cell_cfg(e, q, lad), A, B)[0]["nav"], rf)["CAGR"]))
    sb = pd.DataFrame(sb); sb["effect"] = sb.CAGR_spy_plus_1_36 - sb.CAGR_panel
    sb.to_csv(RESULTS / "allocation_spy_bound.csv", index=False)

    # ---- QQQ-only, longer windows (no SPY data before 2005) ----
    lg = []
    for e in EQUITY + (1.0,):
        lg.append(dict(window="1999-03 → 2026-09", portfolio="static monthly", equity=e, ladder="", **perf_stats(static_mix(D, 1.0, e, "1999-03-10", B), rf)))
        lg.append(dict(window="2002-03 → 2026-09", portfolio="static monthly", equity=e, ladder="", **perf_stats(static_mix(D, 1.0, e, "2002-03-08", B), rf)))
    for e, q, lad in cells():
        if q == 1.0:
            lg.append(dict(window="2002-03 → 2026-09", portfolio="strategy", equity=e, ladder=lad,
                           **perf_stats(run(D, cell_cfg(e, q, lad), "2002-03-08", B)[0]["nav"], rf)))
    pd.DataFrame(lg).to_csv(RESULTS / "allocation_qqq_long.csv", index=False)

    c = ["equity", "mix", "ladder", "Sharpe", "CAGR", "Vol", "MaxDD", "Calmar", "underwater_days", "days_reserve_lt1", "avg_qqq",
         "avg_spy", "avg_qld_2x", "avg_expo", "tranches_partial", "days_tranche_blocked", "hindsight_equal_dd_equity", "cagr_gap_equal_dd"]
    print(S[c].round(3).to_string())
    print(pd.DataFrame(static_rows)[["kind", "equity", "mix", "Sharpe", "CAGR", "Vol", "MaxDD", "Calmar", "underwater_days"]].round(3).to_string())
    print(E.round(4).to_string())
    print(f"max-t critical value {crit:.2f}, family {len(T)}")
    print(T[["test", "equity", "qqq_share", "ladder", "diff", "se", "lb_simultaneous", "p_stepdown", "lb_unadjusted", "halves_agree", "d_CAGR", "d_MaxDD", "status"]].round(3).to_string())
    print(sb.round(4).to_string()); print(pd.DataFrame(lg).round(3).to_string())
    print(pd.DataFrame(br).query("ladder=='scaled' and equity==0.7").round(4).to_string())


if __name__ == "__main__":
    main()
