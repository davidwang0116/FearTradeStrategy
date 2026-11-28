# Allocation study: equity share and QQQ/SPY mix

How much of the portfolio should sit in stocks (70%, 75% or 80%), and how should the core split between QQQ and SPY?
The grid and the decision rule were fixed before any cell was run, and every cell is reported. The same grid supplies the
25 "v3 candidates" that were tested against frozen v2.

## Layout

| Path | Contents |
|---|---|
| `research/allocation_study.py` | The grid, the decision rule and the 45-test family (docstring has the pre-registered rules) |
| `research/allocation_figs.py` | The three figures |
| `research/allocation_paths.py` | This study's folders; puts the repo's shared `research/` code on the import path |
| `results/` | `allocation_*.csv`: static and strategy grids, the 20 mix tests, the 25 v3 tests, the v2 bridge, robustness and diagnostics |
| `figures/` | `fig_allocation_grid.png`, `fig_allocation_risk_return.png`, `fig_allocation_tests.png` |
| `tests/test_allocation.py` | Basket drift/reset timing and costs, v2 regression, reserve accounting, inference helpers |

Shared pieces stay where they were: the panel (`data/panel.csv`), the engine and its new options (`research/strategy.py`),
the bootstrap helpers (`research/common.py`), and the QuantConnect code (`qc/main.py`), whose `core_target`, `ladder`
and `core` parameters run these cells on QuantConnect.

## How to run

Use the Python environment from the repo's `requirements.txt`. The scripts work from any directory; a run takes under a minute.

```sh
python allocation/research/allocation_study.py
python allocation/research/allocation_figs.py
python -m pytest -q allocation/tests
```

## What a v3 candidate changes from v2

The candidates follow what `qc/main.py` actually trades, which differs from frozen v2 in more than the allocation:

| | Frozen v2 | v3 candidates |
|---|---|---|
| Trend-guarded half holds | QQQ only, so a "50/50" core starts near 75/25 | The core basket (`trend_asset="core"`) |
| Core weights | Drift | Reset to target when anything trades (`basket_reset="event"`) |
| Stock share | 70% | 70%, 75% or 80% |
| QQQ share of the core | 50% nominal | 0, 50, 70, 80 or 100% |
| Tranche / QLD buy / QLD cap | Fixed 7.5% / 10% / 30% | Fixed, or scaled to the reserve: ¼ / ⅓ / all of it |

Going from v2 to the like-for-like 70% / 50/50 cell costs 0.026 Sharpe: −0.020 from the basket trend half and −0.005 from
event resets (`results/allocation_bridge.csv`).

## Results
40 cells: equity 70/75/80% × core 100% SPY, 50/50, 70/30, 80/20, 100% QQQ, as static monthly-rebalanced mixes (15),
strategy with a scaled ladder (15) and with v2's fixed ladder (10). 2007-02 → 2026-09, costs in.
**Trial count: 49 more on top of the original log** (40 cells, 1 bridge step, 8 no-guard diagnostics).

| Core (equity 70% / 80%) | Static Sharpe | Static CAGR | Static Max DD | Strategy Sharpe | Strategy CAGR | Strategy Max DD |
|---|---|---|---|---|---|---|
| 100% SPY † | 0.51 / 0.52 | 7.2% / 7.9% | −39% / −44% | 0.57 / 0.58 | 8.4% / 8.7% | −39% / −38% |
| 50/50 † | 0.64 / 0.64 | 9.6% / 10.7% | −39% / −44% | 0.68 / 0.70 | 11.1% / 11.6% | −39% / −38% |
| 70/30 † | 0.67 / 0.68 | 10.6% / 11.8% | −40% / −44% | 0.71 / 0.73 | 12.1% / 12.7% | −39% / −38% |
| 80/20 † | 0.69 / 0.69 | 11.1% / 12.3% | −40% / −44% | 0.72 / 0.75 | 12.6% / 13.3% | −39% / −38% |
| 100% QQQ | 0.71 / 0.72 | 12.0% / 13.4% | −40% / −45% | 0.75 / 0.77 | 13.7% / 14.4% | −40% / −39% |

Strategy columns use the scaled ladder; the core basket also fills the trend half and resets on rebalance events, as in
qc/main.py. Frozen v2 (README headline, different trend half): 0.71, 11.8%, −39%. 75% equity sits between the two.

* **Verdict (rule fixed before the run): nothing qualifies as better.** 45 tests (20 mix vs 50/50 at the same equity and
  ladder, 25 candidates vs frozen v2) form one family; the simultaneous 5% lower bound is below zero for all of them, and
  for every block length tried (21–252 days). 19 of 45 would "pass" unadjusted. Smallest step-down p = 0.11.
* **QQQ mix: provisional at most.** More QQQ had a higher Sharpe in both halves (2007–19, 2020–26), but not significantly,
  in a sample that starts after the dot-com crash. Static 100% QQQ from 1999-03 fell 68% at 70% equity and 74% at 80%.
  † SPY in the panel is not a true total return: 2013–2022 gives 10.76%/yr vs 12.42% in State Street's December 2022 fact
  sheet; 2022 gives −16.02% vs −18.17% at NAV. Mean and volatility are both understated. A flat +1.36%/yr (mean only; it
  makes 2022 worse, −14.9%) adds 0.5–0.6 pp to 50/50 CAGR; it says nothing about drawdown, Sharpe or ranking. **Do not
  choose a QQQ weight until this is re-run on verified SPY daily total returns.**
* **Equity share: a trade-off, no winner.** 70 → 80% at a fixed mix adds 0.7–1.4 pp CAGR and 4.5–4.7 pp of drawdown to
  the static mix; Sharpe does not move (by construction). In the strategy it adds 0.3–0.8 pp (scaled) or 0.3–0.9 pp
  (fixed ladder) and drawdown moves by about 1 pp or less. That flat drawdown is **one episode**: at the trough (2007–09)
  the reserve was already empty in all 25 cells, and a higher target puts more in the trend-guarded half, then in T-bills.
  Without the guard, drawdown deepens with equity (−49.0% → −50.3% for 50/50, results/allocation_drawdown_check.csv).
* **Buying power:** spendable reserve (excluding T-bills parked by the trend guard) is under 1% of NAV on about 527–533 of
  4,934 days at 70%. The scaled ladder keeps that count at 75 and 80%; v2's fixed ladder raises it to 544 and 607.
* **Exposure:** the 100% SPY core still buys QLD and follows QQQ signals; at 70% equity its 2x Nasdaq exposure from QLD
  averages 1.4% of NAV and peaks at 52%.
* **v2 to the 70% 50/50 cell is −0.026 Sharpe** (−0.020 from the basket trend sleeve, −0.005 from event resets), so the
  "same" 50/50 strategy is not v2 (results/allocation_bridge.csv).
* Equal-drawdown CAGR gaps in results/allocation_strategy.csv use the static grid's monthly rebalancing and costs; the
  matched equity share is fitted in hindsight, so they are descriptive.
