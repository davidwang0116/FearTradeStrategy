# Protective put on the fear-tranche strategy

Can a QQQ put overlay cut v2's drawdowns at an acceptable cost, and can the lower risk be turned into return?

**Status: model-priced.** Option prices come from a VXN-based volatility surface with provisional parameters. No real
option quotes have been checked yet. The QuantConnect quote audit (`qc/options_quote_audit.ipynb`) is ready but not
run, and 2008 can never be checked on real quotes (QC's option data starts in 2012).

## Layout
| Path | Contents |
|---|---|
| `research/options_model.py` | Black-Scholes pricing, VXN-based IV surface (loads a QC fit if present), option book with a cash ledger |
| `research/options_overlay.py` | v2 backtest with a put hedge; the frozen 12-month put study (12 setups × 3 pricings) |
| `research/options_figs.py` | Figures for the frozen study |
| `research/options_experiments.py` | Next-stage experiments: 141 setups × 3 pricings × 3 account sizes × 7 periods |
| `research/put_refresh_checks.py` | Fresh-account and single-year checks for the lead setups |
| `research/put_decline_checks.py` | Leave-one-decline-out check of each setup's edge over the frozen hedge |
| `research/put_report.py`, `put_ported_checks.py` | Write `results/extensions/REPORT.md` |
| `research/_paths.py` | This study's folders; puts the repo's shared `research/` code on the import path |
| `results/` | Frozen study outputs (`options_trials.csv`, episodes, sales, trade ledger) |
| `results/extensions/` | Next-stage outputs and **`REPORT.md`** (full write-up) |
| `figures/` | Frozen study figures |
| `qc/options_quote_audit.ipynb` | QC Research notebook: real quotes for every model trade, surface fit (built by `tools/build_qc_notebook.py`) |
| `tests/` | Engine, pricing, accounting and frozen-result regression tests |

Shared pieces stay where they were: market data in `data/raw/`, the strategy engine in `research/strategy.py` and
`research/common.py`, and the QC algorithm in `qc/main.py` (`overlay=HEDGE12M`), because a QC project needs
`main.py` and `signals.py` together.

## How to run
Every script works from any directory (Python ≥ 3.10, pandas ≥ 2.2):
```
python options/protective_put/research/options_overlay.py      # frozen study, ~1 min
python options/protective_put/research/options_figs.py
python options/protective_put/research/options_experiments.py --jobs 4   # next-stage experiments, long
python options/protective_put/research/put_refresh_checks.py
python options/protective_put/research/put_decline_checks.py   # ~2 min
python options/protective_put/research/put_report.py
python -m pytest options/protective_put/tests
```

## Results so far (model-priced)
Feb 2007 – Sep 2026, $1M start, whole contracts, central pricing (`results/extensions/REPORT.md`):

| Rule | Sharpe | CAGR | Max drawdown |
|---|---|---|---|
| v2, no hedge | 0.707 | 11.78% | −38.79% |
| Frozen hedge: 12-month 85% put on the core, held | 0.805 | 10.24% | −24.73% |
| 80% core + 95% put | 0.865 | 10.04% | −20.21% |
| 90% core + 95% put | 0.855 | 11.16% | −25.12% |

- **The frozen hedge buys lower risk, not higher return.** It beats holding less stock at the same drawdown.
- **No single change to the hedge beats it robustly.** Maturity, strike, coverage, partial sales, beta sizing,
  budgets, ladders, separate SPY puts and entry gates were all tested. Spreads and collars hurt. No gate beats a
  frozen hedge started the same day.
- **The trend guard and the put are not redundant.** Each adds about the same protection with or without the other.
- **The lead is more equity plus a closer strike** (80% core + 95% put). It passes the all-period checks at both
  account sizes under all three pricings. But its edge over the frozen hedge disappears when the Dec 2021 – Nov 2023
  decline is left out (`results/extensions/decline_checks.csv`).
  - The 80% core + 95% put selection was made after seeing the first results, so it is exploratory.
  - 2022 falls inside the QC quote era, so the quote audit can test the episode the lead depends on.

## Next steps
1. Run `qc/options_quote_audit.ipynb` on QuantConnect. Copy the fitted `options_surface_fit.csv` into `results/`, then
   re-run the scripts above (the fit loads automatically).
2. Backtest the frozen hedge and the lead in QC on real quotes (`qc/main.py`, `overlay=HEDGE12M`, `capital=1000000`;
   unhedged control with `price_mode=raw`).
