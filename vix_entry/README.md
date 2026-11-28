# VIX entry research

Which VIX conditions have come before higher QQQ returns, and can staged buying, exits or other VIX signals beat buying at the first VIX ≥24 close? [SUMMARY.md](SUMMARY.md) has every test and result.

## Layout

| Path | Contents |
|---|---|
| [`SUMMARY.md`](SUMMARY.md) | Everything tested, the results, and what they do and do not support |
| [`IMPLEMENTATION_REVIEW.md`](IMPLEMENTATION_REVIEW.md) | An outside review of the code and results, with its follow-up |
| `research/` | The scripts, the dashboard template, and `vix_paths.py`, which puts the repo's shared `research/` code on the import path |
| `results/` | CSVs from the last run. The dashboard, `vix_signal_days.csv` and the two tactical ledgers are rebuilt locally and not in Git |
| `tests/` | Tests for signals, entries, exits, the funded sleeve and the summaries |
| `data/` | Optional QQQE and credit inputs, not in Git |
| `dashboard_template.html` | A link to the rebuilt dashboard |

Shared pieces stay where they were: the QQQ/VIX panel (`data/panel.csv`), the Cboe VIX and VIX3M histories (`data/raw/vix_daily.csv`, `data/raw/VIX3M_History.csv`), and the portfolio engine (`research/strategy.py`, `research/common.py`).

## How to run

Use the Python environment from the repo's `requirements.txt`. The scripts work from any directory, and a full run takes under a minute.

```sh
python vix_entry/research/run_tactical.py   # optional, adds the entry and exit tests
python vix_entry/research/run_triggers.py   # optional, tests every VIX signal as the entry
python vix_entry/research/analyze_vix.py
python -m pytest -q vix_entry/tests
```

Open `vix_entry/results/vix_signal_dashboard.html` in a browser. The outcome table and `vix_outcome_summary.csv` put the preset rules' training spread, later 63-session returns and tails, episode spacing, and funded performance side by side. The same run exports the underlying signals, parameter grid, indicator comparisons, recovery episodes, funded backtests, and input coverage. Use `--skip-portfolio` for the signal studies alone. Use `--output` to save a separate run and `--start` or `--split` to change the sample.

The dashboard also covers signal frequency and gaps, entries and 63-session outcomes by episode, and funded trades. Each has a matching CSV (`vix_signal_frequency`, `vix_episode_entries`, `vix_portfolio_trades`). `trades.py` holds the calculations.

See [SUMMARY.md](SUMMARY.md) for everything tested and what the results do and do not support. `python vix_entry/research/summary_tables.py` prints most of its tables from a finished run.

## Inputs

The repo already supplies the QQQ/VIX panel, VIX OHLC and [Cboe VIX3M](https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX3M_History.csv) (`data/raw/VIX3M_History.csv`, shared with the options study). Keep the observations before training so the rolling features have history. The extra files below are optional and go in `vix_entry/data/` by default. In all three scripts, `--inputs` accepts another directory and `--vix3m` another VIX3M file. Without the VIX3M file, the rules that need it are left out. The study excludes unavailable dates from both sides of a comparison.

| Local file | Input |
|---|---|
| `qqqe.json` | [Yahoo Finance QQQE daily chart export](https://query1.finance.yahoo.com/v8/finance/chart/QQQE?period1=1325376000&period2=1794355200&interval=1d). The script reads adjusted closes and checks that the file is daily. The link covers the checked-in panel's end date. |
| `hy_oas.csv` | [FRED BAMLH0A0HYM2](https://fred.stlouisfed.org/series/BAMLH0A0HYM2). Download the CSV with `observation_date,BAMLH0A0HYM2`. The public series retains about three years. The run on Nov 24, 2026 used observations from Nov 27, 2023 through Nov 23, 2026. |

For actual Nasdaq-100 breadth, pass `--constituents path/to/members_and_closes.csv`. Supply one row per trading date and security with columns `date,security,close,member`. Use a stable security identifier, adjusted closes, and point-in-time membership recorded as 1 for members and 0 for nonmembers. Include securities that later left the index and pre-membership closes so new members can have a complete 20-session moving average. The calculation uses dates when at least 95% of supplied members have complete moving averages. Include every member on each supplied date, even if its close is missing. With no constituent file, that experiment shows unavailable. The QQQE/QQQ relative strength experiment provides a separately labeled breadth proxy.

## Comparisons

- The VIX grid retains the ZIP's 396 configurations at 504 sessions and adds 252- and 1,260-session windows. Rank includes the current close and averages ties. Selected rules maximize mean training return subject to at least 100 signal days and the original 504-day rank baseline's mean drawdown. The default split is Jan 1, 2020. Training exits must precede it. Later signals begin on or after it.
- Signal studies enter QQQ at the next close and exit after 63 trading sessions. Each A/B comparison requires data for both rules. The dashboard can exclude 2020 signal dates and exposes both single-day and episode results. The earlier and later samples are historical research samples and have both been explored.
- The outcome table uses the shared eligible dates within each experiment and split to compute spread relative to the all-date mean. Median episode gaps use only starts in the later sample and are measured in QQQ trading sessions. One-entry-per-episode recovery rules use the spacing between their actual entry signals. The table reports average and worst per-trade drawdowns alongside the separately calculated funded portfolio max drawdown. The episode-weighted spread gives each episode the same weight. The ex-largest spread drops the episode with the most signal days. Both use the same all-date mean as the day-weighted spread. Funded columns show the rule beside the composite and no-tranche controls for training, fresh later, and carried later runs. Coverage dates are shown for both studies. Experiments whose inputs begin later (VIX3M, QQQE, credit) use shorter training samples, so compare their spreads only within the experiment. The original and frozen quintile comparisons have signal results only.
- Recovery episodes begin at the first VIX ≥24 close after 21 quiet sessions. A 3-, 5-, or 10-close QQQ breakout must occur in the next 10 sessions. The paired table shows both 63-session returns and the delayed return at the original exit date. An episode whose possible outcome windows cross the split is excluded from both split samples.
- Breadth, the equal-weight proxy, and credit use a five-session difference. Credit closes are lagged one QQQ session as a release-time assumption. Missing observations and their affected comparisons stay missing. Term structure compares the same day's VIX and VIX3M.
- Funded comparisons reuse the repo's v2 QQQ/SPY core, trend guard, synthetic QLD and costs. Each pair and its controls start fresh on the same dates. Missing indicator days suspend core tranche entry for both sides. The carried runs instead start at the first shared training date and measure only the later period, so they keep the holdings and powder built up before the split. Rank rules by both, because the ordering against the controls can change. The no-tranche control keeps the starting core, reinvestment after sleeve exits, and the QLD sleeve, which follows the composite and spends the same cash as the tranches. The funded simulation ends by the last actual SPY close in the panel.
- Frequency uses each rule's own data coverage. Gaps run between first signals of consecutive episodes. The longest stretch without a signal also counts the start and end of the sample. Spaced entries count back-to-back 63-session trades.
- Entry and exit tests start at a fear trigger, pair every rule with a baseline on the same episodes, and choose on 2008–2019. Run `run_tactical.py` first: `analyze_vix.py` copies its `tactical_*.csv` files into the dashboard when they exist.
