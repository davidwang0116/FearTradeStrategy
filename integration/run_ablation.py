"""Rerun the frozen v2 baseline and the allocation × VIX × put comparison."""
import argparse
from dataclasses import replace
from itertools import product
from pathlib import Path
import sys

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT / path) for path in ("allocation/research", "options/protective_put/research", "research")]

from allocation_study import A, B, V2, V2_CORRECTED, cell_cfg
from common import block_boot_sharpes, build_signals, load_panel, maxt_family, perf_stats
from integrated_put import ModeledPut
from options_model import CENTRAL, pessimistic
from strategy import prepare, run


CAPITAL = 1_000_000.0
SPLIT = "2019-12-31"
QUOTE_ERA = "2012-01-03"
AUDIT_DATES = ["2012-01-03", "2018-12-24", "2020-03-16", "2022-10-12", "2026-08-14", "2026-09-11"]
SURFACES = {"central": CENTRAL, "pessimistic": pessimistic(CENTRAL),
            "flat_term": replace(CENTRAL, kappa=2 * CENTRAL.kappa)}
PERIODS = {"full": (A, B), "through_2019": (A, SPLIT), "2020_onward": (SPLIT, B), "from_2012": (QUOTE_ERA, B)}


def baseline(data, output):
    published = pd.read_csv(ROOT / "results" / "strategy_variants.csv")
    archived = published.loc[published.strategy.eq("v2 + QLD + trend guard")].sort_values("test")
    rows, sale_dates = [], []
    for start, core, ref in zip(("2002-03-08", A), ((("qqq", 1.0),), V2.core), archived.itertuples(), strict=True):
        sells = {}
        for cfg in (V2, V2_CORRECTED):
            frame, trades = run(data, replace(cfg, core=core), start, B)
            stats = perf_stats(frame.nav, data.rf)
            if cfg == V2:
                np.testing.assert_allclose([stats[k] for k in stats], [getattr(ref, k) for k in stats],
                                           rtol=0, atol=1e-12)
                assert len(trades) == ref.trades
            rows.append(dict(test=ref.test, baseline=cfg.name, timing=cfg.lev_exit_close,
                             **stats, trades=len(trades), final_nav=frame.nav.iloc[-1]))
            sells[cfg.lev_exit_close] = set(trades.loc[trades.action.str.startswith("sell "), "date"])
        for timing in ("same", "signal"):
            other = "signal" if timing == "same" else "same"
            sale_dates.extend(dict(test=ref.test, timing=timing, sale_date=day.date())
                              for day in sorted(sells[timing] - sells[other]))
    pd.DataFrame(rows).to_csv(output / "baseline.csv", index=False)
    pd.DataFrame(sale_dates).to_csv(output / "baseline_sell_dates.csv", index=False)


def metrics(frame, trades, ledger, rf, start, end):
    frame = frame.loc[start:end]
    first, last = frame.index[0], frame.index[-1]
    trade_dates = trades.date.between(first, last)
    returns = frame.nav.pct_change().dropna()
    return dict(first=first.date(), last=last.date(), sessions=len(frame), **perf_stats(frame.nav, rf),
                expected_shortfall_5=returns[returns <= returns.quantile(.05)].mean(),
                equity_events=int(trade_dates.sum()),
                tranches=int((trade_dates & trades.action.eq("tranche")).sum()),
                puts_bought=sum(x["units"] > 0 and first <= x["date"] <= last for x in ledger),
                avg_gross_exposure=frame.expo.mean(), avg_reserve=frame.reserve.mean(),
                final_nav=frame.nav.iloc[-1])


def label(allocation, vix, put):
    return " + ".join(name for name, active in zip(("Allocation", "VIX", "Put"), (allocation, vix, put)) if active) or "Corrected v2"


def factorial(data, vix_gate, output):
    cases = tuple(product((False, True), repeat=3))
    selected = cell_cfg(.80, .80, "scaled")
    rows, flows, full, risk_checks = [], [], {}, []
    for pricing, surface in SURFACES.items():
        navs = {}
        for a, v, h in cases:
            key = label(a, v, h)
            if pricing == "central" or h:
                overlay = ModeledPut(surface) if h else None
                frame, trades = run(data, selected if a else V2_CORRECTED, A, B, CAPITAL,
                                    tranche_entry=vix_gate if v else None, overlay=overlay)
                ledger = overlay.book.ledger if overlay is not None else []
                if h:
                    np.testing.assert_allclose(frame[["core", "lev", "cash", "trend", "hedge_mark"]].sum(axis=1),
                                               1, atol=1e-12, rtol=0)
                    np.testing.assert_allclose(frame.hedge_flow.sum(), sum(x["cash"] for x in ledger),
                                               atol=1e-8, rtol=0)
                    assert (frame.reserve >= -1e-12).all() and (frame.hedge_bucket >= -1e-12).all()
                if pricing == "central":
                    full[key] = frame, trades, ledger
                    flows.extend(dict(strategy=key, **x) for x in ledger)
            else:
                frame, trades, ledger = full[key]
            navs[key] = frame.nav
            for period, dates in PERIODS.items():
                rows.append(dict(pricing=pricing, strategy=key, period=period, allocation=a, vix=v, put=h,
                                 **metrics(frame, trades, ledger, data.rf, *dates)))
        if pricing == "central":
            for a, v in product((False, True), repeat=2):
                unhedged, hedged = navs[label(a, v, False)], navs[label(a, v, True)]
                base_returns = unhedged.pct_change()
                ratio = hedged.pct_change().loc[:SPLIT].std() / base_returns.loc[:SPLIT].std()
                weight = min(1, ratio)
                scaled = CAPITAL * (1 + (weight * base_returns + (1 - weight) * data.rf / 252).fillna(0)).cumprod()
                for period, dates in PERIODS.items():
                    for comparator, nav in (("unhedged", unhedged), ("put", hedged), ("vol-matched bills blend", scaled)):
                        risk_checks.append(dict(put_strategy=label(a, v, True), comparator=comparator, period=period,
                                                equity_strategy_weight=weight if comparator.startswith("vol-matched") else 1,
                                                **perf_stats(nav.loc[dates[0]:dates[1]], data.rf)))
        returns = pd.DataFrame(navs).pct_change().dropna()
        point, boot = block_boot_sharpes(returns, data.rf)
        tests = maxt_family(point[1:] - point[0], boot[:, 1:] - boot[:, [0]])[0]
        tests.insert(0, "strategy", returns.columns[1:])
        tests.insert(0, "pricing", pricing)
        tests.to_csv(output / f"paired_{pricing}.csv", index=False)

    pd.DataFrame(rows).to_csv(output / "ablation.csv", index=False)
    pd.DataFrame(flows).to_csv(output / "central_put_ledger.csv", index=False)
    pd.DataFrame(risk_checks).to_csv(output / "cash_controls.csv", index=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "results")
    output = parser.parse_args().output
    output.mkdir(parents=True, exist_ok=True)

    panel = load_panel()
    signals = build_signals(panel)
    data = prepare(panel, signals)
    raw = ROOT / "data" / "raw"
    data = data.join(pd.read_csv(raw / "options_etf_closes.csv", usecols=["date", "raw_qqq"],
                                 index_col="date", parse_dates=True))
    vix = pd.read_csv(raw / "vix_daily.csv", usecols=["DATE", "CLOSE"], index_col="DATE",
                      parse_dates=True)["CLOSE"].reindex(data.index)
    gate = vix.ge(24) & vix.lt(vix.shift(20))
    baseline(data, output)
    factorial(data, gate, output)

    comparison = []
    for cfg in (V2_CORRECTED, cell_cfg(.70, .50, "scaled"), cell_cfg(.80, .80, "scaled")):
        frame, trades = run(data, cfg, QUOTE_ERA, B, CAPITAL)
        comparison.append(dict(strategy=cfg.name, **metrics(frame, trades, [], data.rf, QUOTE_ERA, B)))
    pd.DataFrame(comparison).to_csv(output / "qc_local_comparison.csv", index=False)
    audits = data.assign(vix=vix, composite=signals["Composite (dashboard v4)"])
    audits.loc[AUDIT_DATES, ["qqq", "vxn", "vix", "composite", "p"]].to_csv(output / "qc_local_signals.csv")


if __name__ == "__main__":
    main()
