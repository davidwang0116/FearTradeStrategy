# Fear strategy integration

The published v2 is reproducible at [613318c](https://github.com/davidwang0116/FearTradeStrategy/tree/613318cfd290c757b84b4e8ccbdb2bc0e1e2208b). Running its strategy driver against the pinned panel reproduced the published `results/strategy_variants.csv` byte for byte. The panel's SHA-256 is `494f82e1b87eb7de4aea32fbb195fb51578ba82798827a02b87410f231353198`.

| 2007–2026 QQQ/SPY reference | Sharpe | CAGR | Max drawdown |
|---|---:|---:|---:|
| Published v2 | 0.707479 | 11.7805% | −38.79% |
| Corrected v2 | 0.707395 | 11.7795% | −38.79% |

The correction moves the April 2020 QLD sale from April 29 to April 30 in both published reference portfolios. The engine now evaluates take-profit and holding age at the signal close for every allocation candidate. The frozen v2 configuration still reproduces the historical calculation. [Baseline metrics](results/baseline.csv) · [Sale dates](results/baseline_sell_dates.csv) · [Allocation bridge](../allocation/results/allocation_bridge.csv)

## Local factorial comparison

All eight configurations start with $1 million on February 1, 2007 and run to September 11, 2026. The engine applies the same next-close equity execution, synthetic QLD path, equity fees and approximate T-bill rates to every cell. When allocation is on, it uses the existing 80% equity target with an 80/20 QQQ/SPY basket, a reserve-scaled ladder and event rebalancing. The existing allocation bridge measures the basket changes at the original 70% equity target and 50/50 nominal mix separately.

The VIX switch replaces only the core tranche gate. It requires a VIX close of at least 24 and a lower close than 20 QQQ sessions earlier. Position size, tranche spacing, QLD signals and the trend guard follow their existing rules. The protective put uses an 85% strike and a 365-day target maturity, whole contracts and unguarded exposure. It buys and rolls in calm periods. Sale or settlement proceeds enter a restricted T-bill balance and pay the next premium first. Daily NAV includes the option mark and restricted balance. The debit or credit from each executed trade appears once in the ledger.

| Configuration | Sharpe | CAGR | Max drawdown | Core tranches |
|---|---:|---:|---:|---:|
| Corrected v2 | 0.707 | 11.78% | −38.79% | 24 |
| VIX | 0.724 | 12.21% | −38.55% | 16 |
| Allocation | 0.746 | 13.29% | −38.09% | 24 |
| Allocation + VIX | 0.760 | 13.50% | −38.03% | 16 |
| Put | 0.815 | 10.33% | −24.72% | 24 |
| VIX + put | 0.833 | 10.74% | −24.18% | 16 |
| Allocation + put | 0.849 | 11.80% | −23.99% | 24 |
| Allocation + VIX + put | 0.868 | 11.99% | −23.66% | 16 |

The put drove the largest modeled drawdown reduction. Applied to corrected v2, it cut drawdown by 14.07 percentage points and cost 1.45 points of annual return. The three-switch combination ranged from 0.827 to 0.868 Sharpe across the three pricing surfaces. A 63-session paired block bootstrap with 5,000 draws and simultaneous one-sided 95% bounds found no positive lower bound versus corrected v2 in any pricing scenario. The allocation grid likewise had zero passes after re-running its 45-test family with the timing correction.

The put on corrected v2 delivered 10.33% CAGR against 8.95% for the bills blend calibrated to its daily volatility through 2019. In the later period, the same fixed 70.8% weight in v2 produced 12.94% CAGR against 15.83% for the put. That blend has no modeled implementation charge. The pricing surfaces remain provisional, and both historical periods were examined during strategy development. The panel's SPY series also understates its published long-run total return, so a mix decision needs independently verified daily returns. These results support further testing of the put and keeping v2 as the reference. [All runs and subperiods](results/ablation.csv) · [Paired tests](results/paired_central.csv) · [Cash controls](results/cash_controls.csv) · [Put ledger](results/central_put_ledger.csv)

### Results from 2020 to 2026

The `2020_onward` rows in [ablation.csv](results/ablation.csv) use the December 31, 2019 close as their starting NAV and end on September 11, 2026. Holdings and cash carry over from the February 2007 start. Sharpe is annualized from daily excess returns, and the put rows use central modeled option prices.

| Configuration | Sharpe | CAGR | Max drawdown |
|---|---:|---:|---:|
| Corrected v2 | 0.777 | 16.79% | −26.72% |
| VIX | 0.811 | 17.45% | −26.69% |
| Allocation | 0.799 | 18.32% | −28.81% |
| Allocation + VIX | 0.825 | 18.60% | −28.37% |
| v2 + put | 0.948 | 15.83% | −17.34% |
| VIX + put | 0.973 | 16.72% | −18.12% |
| Allocation + put | 0.971 | 17.46% | −19.00% |
| Allocation + VIX + put | 0.998 | 17.88% | −19.04% |

Adding the put to Allocation + VIX reduced maximum drawdown by 9.33 percentage points and cost 0.72 points of CAGR. Its 2022 calendar-year loss narrowed from 25.79% to 16.69%. The all-switch Sharpe in this slice ranged from 0.962 to 0.998 across the three pricing assumptions.

### Fresh-start replay

These modeled runs open each portfolio with $1 million on January 2, 2020, and end on September 11, 2026. They retain pre-start data for indicator history and measure returns from the new portfolio's first NAV.

| Configuration | Sharpe | CAGR | Max drawdown |
|---|---:|---:|---:|
| Corrected v2 | 0.863 | 17.23% | −23.85% |
| v2 + put | 0.991 | 16.31% | −18.65% |
| Allocation + VIX | 0.880 | 18.54% | −25.55% |
| Allocation + VIX + put | 1.021 | 17.87% | −19.41% |

The table uses central pricing for both hedged rows. The all-switch fresh-start Sharpe was 1.012 under pessimistic pricing and 0.995 under the flat-term surface. Both the continuous slice and the fresh-start replay use dates examined during strategy development.

After installing the requirements below, run this from the repository root. It uses the existing engine, panel, VIX gate and put defaults.

```sh
python - <<'PY'
import pandas as pd

from integration import run_ablation as ablation

panel = ablation.load_panel()
data = ablation.prepare(panel, ablation.build_signals(panel))
raw = ablation.ROOT / "data" / "raw"
spot = pd.read_csv(raw / "options_etf_closes.csv", usecols=["date", "raw_qqq"],
                   index_col="date", parse_dates=True)
data = data.join(spot)
vix = pd.read_csv(raw / "vix_daily.csv", usecols=["DATE", "CLOSE"],
                  index_col="DATE", parse_dates=True)["CLOSE"].reindex(data.index)
vix_gate = vix.ge(24) & vix.lt(vix.shift(20))
allocation = ablation.cell_cfg(0.80, 0.80, "scaled")
cases = (
    ("Corrected v2", ablation.V2_CORRECTED, None, (None,)),
    ("v2 + put", ablation.V2_CORRECTED, None, ("central",)),
    ("Allocation + VIX", allocation, vix_gate, (None,)),
    ("Allocation + VIX + put", allocation, vix_gate, ablation.SURFACES),
)

for name, config, gate, pricing_cases in cases:
    for pricing in pricing_cases:
        overlay = ablation.ModeledPut(ablation.SURFACES[pricing]) if pricing else None
        frame, _ = ablation.run(
            data, config, "2020-01-02", "2026-09-11", ablation.CAPITAL,
            tranche_entry=gate, overlay=overlay,
        )
        stats = ablation.perf_stats(frame["nav"], data["rf"])
        print(f"{name} | {pricing or 'unhedged'} | "
              f"{stats['Sharpe']:.3f} Sharpe | {stats['CAGR']:.2%} CAGR | "
              f"{stats['MaxDD']:.2%} max drawdown")
PY
```

## Reproduction

```sh
python -m pip install -r requirements.txt
python integration/run_ablation.py
python allocation/research/allocation_study.py
python -m pytest -q tests allocation/tests vix_entry/tests options/protective_put/tests
```

The standalone VIX and options studies retain their published configurations. Integration results use the shared portfolio engine. QuantConnect uses the same configurable strategy rules with next-open ETF execution and an opening-window limit order for the put. [QuantConnect validation](QUANTCONNECT.md)
