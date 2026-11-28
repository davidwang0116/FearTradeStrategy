# QuantConnect execution validation

The unhedged baseline and matched stress tests used LEAN 2.5.0.0.18290 and $1 million of starting capital. The equity and index bars keep their trading-session dates. VIX arrived one hour after QQQ and VXN in the cloud backtest. The algorithm waits for the matching session and uses intraday ETF bars for market-on-open fills. A startup trace exposed an early sleeve reset while opening orders were still working. The final runs retain the trend sleeve and guard the allocation while ETF orders are pending.

## Unhedged baseline

All rows below use adjusted equity prices, BIL, the same brokerage model, and January 3, 2012 through September 11, 2026. The Sharpe and drawdown figures are from QuantConnect.

| Run | Sharpe | CAGR | Max drawdown | End equity |
|---|---:|---:|---:|---:|
| Corrected v2 · Casual Apricot Llama | 0.677 | 14.132% | −28.6% | $6,982,048 |
| VIX · Casual Blue Termite | 0.684 | 13.836% | −28.5% | $6,719,997 |
| Allocation · Jumping Light Brown Bull | 0.714 | 15.648% | −30.1% | $8,476,857 |
| Allocation + VIX · Muscular Violet Kangaroo | 0.717 | 15.314% | −29.7% | $8,124,023 |

The adjusted baseline processed 3,694 QQQ sessions, with all VIX closes present, six missing VXN closes, three unavailable composites and zero pending-equity delays. The composite history began on March 8, 2000 after adding 1,082 early Cboe VIX observations from the pinned repository input to seed the pre-2008 VXN proxy.

Five of six audit dates passed the one-point composite tolerance. September 11, 2026 differed by 4.47 points. The archived input reports VXN of 23.45 on both September 10 and 11, and the cloud run observed 21.02 on September 11. The local same-data test gives daily NAV-return correlation above 0.999. In the cloud, real QLD and BIL replace their local proxies, trades fill at the next open, and the market data, costs and Sharpe conventions differ. The fresh-start local baseline for the same dates had 14.41% CAGR and −25.79% drawdown. [Local metrics](results/qc_local_comparison.csv) · [Local signal observations](results/qc_local_signals.csv)

| QQQ session | Local composite | QC composite | QC minus local |
|---|---:|---:|---:|
| 2012-01-03 | 43.691 | 43.717 | +0.026 |
| 2018-12-24 | 92.515 | 92.548 | +0.033 |
| 2020-03-16 | 91.354 | 91.354 | +0.000 |
| 2022-10-12 | 94.376 | 94.385 | +0.009 |
| 2026-08-14 | 27.289 | 27.666 | +0.377 |
| 2026-09-11 | 46.794 | 42.320 | −4.474 |

## Actual quote and fill checks

The matched December 23, 2019 to April 1, 2020 runs both use raw equity prices, a cash reserve, and the headline allocation.

| Run | End equity | Window return | Max drawdown |
|---|---:|---:|---:|
| Equity only · Crawling Apricot Goshawk | $895,234.34 | −10.48% | −21.5% |
| Hold put · Calculating Apricot Camel | $918,635.68 | −8.14% | −17.9% |

The algorithm bought 16 QQQ December 18, 2020 $180 puts on December 24, 2019. The observed minute quote was $3.66 bid and $7.34 ask. The simulated order filled at $7.34 the next minute, with $10.40 in fees. The account paid $11,754.40 and marked the puts at $31,792 at the end. Each of the 68 held sessions had at least one valid two-sided quote. The entry spread was about 67% of mid, so quoting availability can coexist with expensive execution.

The separate fear-exit run through June 30, 2020 exercised the credit and renewal path. On March 23, the $25.27 bid and $26.56 ask produced a simulated sale at $25.27. Net proceeds of $40,421.60 went to the restricted balance. The May 8 renewal used $28,657.65, including fees, and released the remaining $11,763.95 back to the spendable reserve. The ledger reconciled to $9.55 cumulative cash, a $16,065 open option mark, and a zero restricted balance. The run recorded three orders and zero pending orders at the end. Its 97 held sessions each had a two-sided quote.

A second matched pair from November 1, 2021 to March 31, 2022 tested another selloff.

| Run | End equity | Window return | Max drawdown |
|---|---:|---:|---:|
| Equity only · Logical Brown Dogfish | $932,788.94 | −6.72% | −14.5% |
| Hold put · Crying Fluorescent Orange Armadillo | $932,099.90 | −6.79% | −12.9% |

The November 2 entry paid $15.81 for nine QQQ September 30, 2022 $329 puts against a quote of $11.50 by $15.81. One of the 104 held sessions lacked a valid two-sided quote. The put lowered drawdown by 1.6 percentage points and reduced ending equity by $689.04.

The option run submits against a current, two-sided quote and books premium, fees and sale proceeds from order events. LEAN supplies the portfolio mark. The test uses cash for the buffer and restricted proceeds. The local model credits T-bill interest and can cash-settle at expiry, while the cloud tries to close ahead of expiry and flags any delivery of QQQ shares. The opening-window check validates the observed quote and the simulated fill. It leaves fill capacity and market impact unmeasured. QuantConnect's listed US equity-option data start in January 2012. [US Equity Options dataset](https://www.quantconnect.com/data/algoseek-us-equity-options) · [LEAN time slices](https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/time-modeling/timeslices)

## Long-window hedged quote audit

The companion `FearTradeStrategy_QuantConnect_Quote_Audit.csv` contains 84 completed simulated fills from two hedged runs. The first and last audited quote dates are January 5, 2012 and April 14, 2026. The first audited quote from 2020 onward is May 21, 2020.

| Hedged portfolio | QuantConnect run | Total fills (buys / sells) | Fills since 2020 (buys / sells) |
|---|---|---:|---:|
| Corrected v2 + put | Logical Magenta Jellyfish | 42 (22 / 20) | 16 (8 / 8) |
| Allocation + VIX + put | Creative Yellow Green Lemur | 42 (22 / 20) | 16 (8 / 8) |

The audit compares each purchase's historical ask with the central model ask for the same QQQ put strike and expiry. The model uses QQQ spot from the quote minute and the previous VXN observation. The percentage gap is `100 × (historical ask / model ask − 1)`. Every audited buy filled at the recorded ask and every audited sell at the recorded bid in the simulations.

| Sample | Buys above model ask | Median ask gap | Ask gap range | Median bid–ask spread / midpoint |
|---|---:|---:|---:|---:|
| All audited fills | 44 / 44 | +25.4% | +2.2% to +56.6% | 9.0% |
| From 2020 onward | 16 / 16 | +31.2% | +8.9% to +56.6% | 7.0% |

Spreads use all audited fills in each sample. Some trades in the two portfolios used the same contract on the same date. The counts cover completed fills. Attempted orders, quote coverage between fills, and daily marks are needed to assess execution and net hedge cost. The CSV SHA-256 is `6009b512fc8398115bbf1db00c766c868dbd3b614ce6ab4825e2b1c21a3c47d5`.

The full run parameter exports and matched daily equity are pending. The dates above describe the audit records.

## Reproduction

Upload `qc/main.py`, `qc/signals.py`, and `qc/hedge.py` as one Python project. The bundler also generates a single file for the web editor.

```sh
python tools/build_qc_algorithm.py /tmp/fear_qc_main.py \
  --param start_date=2012-01-03 --param end_date=2026-09-12 \
  --param capital=1000000 --param sleeves=HEADLINE --param core=QQQ:0.5,SPY:0.5 \
  --param price_mode=adjusted --param trace_signals=0 \
  --param audit_dates=2012-01-03,2018-12-24,2020-03-16,2022-10-12,2026-08-14,2026-09-11
```

| Experiment | Change from the baseline parameters |
|---|---|
| Allocation | `sleeves=BASKET`, `core=QQQ:0.8,SPY:0.2`, `core_target=0.80`, `ladder=SCALED` |
| VIX | `tranche_signal=VIX_EASING` |
| 2020 raw control | `start_date=2019-12-23`, `end_date=2020-04-01`, `price_mode=raw`, `powder=CASH` |
| 2020 put | Raw control settings plus `overlay=HEDGE12M`, `hedge_proceeds=tbill` |
| Fear-exit audit | 2020 put settings plus `hedge_exit=fear`, `end_date=2020-06-30` |
| 2022 matched pair | Raw control and put settings with `start_date=2021-11-01` and `end_date=2022-03-31` |

Compare `[DATA SUMMARY]`, `[AUDIT]`, `[OPT ORDER]`, `[OPT FILL]` and `[OPT SUMMARY]` in the backtest log. The comparative 2007–2026 put results in this branch use modeled prices.

### Matched full-window comparison

Use the same dates, starting capital, brokerage, fees, leverage and reserve within each pair. For a new pair that follows the matched stress-test settings, set `price_mode=raw` and `powder=CASH` in both arms. Use `overlay=NONE` for the control and `overlay=HEDGE12M`, `hedge_exit=hold` and `hedge_proceeds=tbill` for the put arm. Run one pair with the Corrected v2 equity settings and one with both the Allocation and VIX settings above. With a cash reserve, `hedge_proceeds=tbill` keeps sale proceeds in the restricted cash balance.

Record the run IDs, engine version and parameter exports with the results. Export session-level equity for each arm, including the December 31, 2019 value to calculate the continuous 2020–2026 slice. Also export attempted orders, fill logs, unavailable or stale quotes and daily marks for held contracts. This produces a comparison on common data and assumptions. The earlier adjusted-price BIL runs used a different setup.
