# FearTradeStrategy — Buying Blood, Not Knives
A fear-tranche strategy on broad Nasdaq/S&P beta · Math 585 project (midterm Nov 16, 2026; live paper trading after)

## 项目简介（中文）
把"别人恐惧时我贪婪"做成有数据支撑、能在 QuantConnect 上回测和实盘的宽基指数策略。
* **为什么是宽基**：SPIVA 2025 年报告中，20 年期约 93% 的主动大盘基金跑输标普 500；Lecture 9 的分散化 / CAPM 也说明单只股票的夏普低于指数。所以我们不选股，只研究**何时、用多大仓位**持有 QQQM / VOO。
* **为什么情绪有 edge**：2008–2026 年 7 个恐慌指标都显示"越恐慌，之后 63 天 QQQ 收益越高"；在 VIX≥30 的每一天买入，之后一年平均 +33%（任意一天买入为 +13.5%）。但只在恐慌第一天满仓几乎没有优势，所以要**分批**。
* **策略**：70% 底仓 + 30% 国债弹药。（底仓比例与 QQQ/SPY 配比的网格检验见 allocation/：没有任何组合通过预设标准。）恐慌分批加底仓，极度恐慌且开始回落时少量买 QLD（以后换 QQQ LEAPS），恐慌消退卖杠杆、贪婪时减仓重建弹药，资金循环使用。
* **现状**：2007–2026 年夏普 0.71、最大回撤 −39%（50/50 买入持有：每日再平衡 0.64 / −52%，一次买入不再平衡 0.66 / −52%）。夏普 >1 是后半学期的目标。

**Thesis.** Broad index beta (QQQ / VOO) is the Sharpe-efficient core most investors can't beat
(SPIVA: 93% of active large-cap funds trail the S&P 500 over 20 years). Fear and cheapness
signals predict *higher* forward index returns, so we hold dry powder and spend it — partly
through 2x leverage — when fear is extreme, then rebuild the powder when greed returns.
This converts sentiment-weighted DCA (which needs fresh cash every month) into a
fixed-capital strategy whose capital recycles.

## Edge per indicator (research/edge_study.py) — single indicators only
| Indicator (best rule, ≥8 episodes) | Trading: next-1y vs any day | 2x-DCA: extra wealth, rolling 5y plans |
|---|---|---|
| VIX | ≥40: **+37 pp** (p=0.001) | ≥25: **+2.1%**, 75% of plans, XIRR +0.63 pp |
| VXN (2008+) | ≥40: **+31 pp** (p=0.001) | ≥30: +0.9% (n.s.) |
| VIX spike vs 20d mean | ≥1.5×: **+15 pp** (p=0.005) | ≈0 |
| Equity risk premium E/P − 10y (S&P monthly 1881–2022) | ≥70th pct: **+7.8 pp** 12m (p=0.001) | +1.4%, 53% of 60-month plans |
| Trailing P/E (S&P monthly) | ≤40th pct: **+5.2 pp** (p=0.02) | +1.6%, 52% of plans |
| Shiller CAPE (S&P monthly) | ≤30th pct: **+4.8 pp** (p=0.015) | +1.5%, 59% of plans |
| CNN Fear & Greed (2011–23) | ≤10: +3.8 pp (n.s.) | ≤20: +0.4% (n.s.) |
| QQQ drawdown / below MA200 | negative over full history (2000–02) | ≤−20%: **+2.0%**; <MA200: **+1.9%**, 88% of plans |
| RSI, realized vol, 5-day drop, VRP, VXN−VIX | none significant / negative | RSI ≤40 +0.6%, 5-day ≤−4% +0.5%, RV ≥25% +1.4% (n.s.) |

Earnings-based valuation inputs are lagged 3 months. Synthesized scores (dashboard composite, price-sentiment proxy) are excluded from this table.

## Selling volatility when fear is high (research/vol_selling.py, model-priced)
* The premium is real but not where you might expect: VXN exceeds next-21-day realized QQQ vol by
  +3.1 pts when fear is below median, **+4.8** at the 50–80th percentile, **−0.4** at the ≥80th
  percentile while fear is still rising (worst 5%: −35 pts) and +2.7 once it starts receding.
* Standalone cash-secured QQQ puts (2008–2026): every month at-the-money Sharpe 0.61 vs 0.72 for QQQ;
  no conditional rule beats "always".
* Writing puts on the 30% dry powder of the fear strategy: Sharpe +0.00 to +0.02, every 90%
  block-bootstrap interval crosses zero, and the gain disappears with cheaper premiums
  (ATM IV 0.85 × VXN). It mostly adds CAGR (+1.3–2 pp) with more negative skew.
* Real-quote check: qc/put_writing.py.

## Top-10 stocks by dollar volume
* Rigorous version: qc/top10_dollar_volume.py (point-in-time universe, rules: equal, invvol,
  dollarvol, reversal, momentum, drawdown, optional trend guard).
* research/top10_local.py is ILLUSTRATIVE ONLY (11 hand-picked tech winners, survivorship-biased):
  within those names no weighting rule clearly beats equal weight.

## Results so far (local, synthetic leveraged ETFs calibrated to real TQQQ)

| | Sharpe (excess, T-bills) | CAGR | Max DD |
|---|---|---|---|
| Buy & hold 50/50 QQQ+SPY, 2007-02 → 2026-09, rebalanced daily | 0.64 | 12.8% | −52% |
| Buy & hold 50/50 QQQ+SPY, bought once (drifts to 77/23 by 2026) | 0.66 | 13.7% | −52% |
| Static 70% beta / 30% T-bills | 0.68 | 11.9% | −37% |
| **v2 fear tranches + QLD sleeve + trend guard** | **0.71** | 11.8% | **−39%** |
| Buy & hold QQQ, 2002-03 → 2026-09 | 0.59 | 13.4% | −53% |
| **v2 … (QQQ core), same period** | **0.64** | 11.8% | **−43%** |

* The signal is real: in 2008–2026 every fear indicator ranks next-63-day QQQ returns in the contrarian
  direction (composite IC 0.18, CI [0.04, 0.33]; VIX 0.20). Buying on *every* VIX≥30 day returned +33%
  over the next year on average vs +13.5% for any day.
* Converting it into a fixed-capital rule set helps drawdowns more than Sharpe. **Sharpe > 1 is not
  reached yet**; the levers to get there are the QC work items below.
* **Compare v2 with the bought-once 50/50.** v2's core also drifts, so that is the like-for-like benchmark: v2 leads it by
  +0.05 Sharpe (+0.06 against the daily-rebalanced 50/50 used before Nov 26).
* v2 reads the QLD sleeve's take-profit gain and age at the close it trades on, one bar later than the stated
  signal-at-t rule. `Cfg(lev_exit_close="signal")` follows the rule, as qc/main.py does: the 2020-04-29 sale moves to
  04-30 and Sharpe goes 0.70748 → 0.70740. v2 stays frozen; v3 candidates use `"signal"`.
* v2's "50/50" core is ~75/25 QQQ/SPY initially, while the trend half is on (that half holds QQQ). Weights
  then drift; the realized average is 65% QQQ of plain equity.
* All 12 variants of the original log are reported (`results/strategy_variants.csv`, `figures/fig_trial_log.png`).

## Allocation study (allocation/)
Equity share 70/75/80% × five QQQ/SPY cores, as static mixes and as v2-style strategies (the 25 "v3 candidates").
**Nothing beat frozen v2** after correcting for all 45 comparisons (smallest step-down p = 0.11). The best cell,
80% equity with a 100% QQQ core (0.77 Sharpe, 14.4% CAGR, −39%), is not proven, and the panel's SPY understates SPY's
return. Full write-up, results and how to run: [allocation/README.md](allocation/README.md).

## QuantConnect code: modes, parameters and fixes (qc/main.py)
QC parameters: `core_target` 0.70/0.75/0.80, `ladder` FIXED (default, v2 sizes) or SCALED, `core` `QQQ:1`,
`QQQ:0.8,VOO:0.2`, `QQQ:0.7,VOO:0.3`, `QQQ:0.5,VOO:0.5` or `VOO:1` (tested locally in the allocation study). Default values are unchanged (the bug fix below does change default-mode output). Not yet run on QC.
QC fills at the next open, local at the next close. **Live v2 is the 50/50 headline** (team answer, Nov 25), the comparator
above. QC's default core is `QQQ:1`, so 50/50 must be set explicitly (`core=QQQ:0.5,VOO:0.5`, or QQQM). Even then
qc/main.py is not the headline: its trend half holds the basket and resets on events, which locally is the 70% / 50/50
cell (Sharpe 0.68, CAGR 11.1%), not 0.71 / 11.8%. Compare a default-mode QC run with that cell.

`sleeves=HEADLINE` (default `BASKET`) makes qc/main.py follow the headline: QQQ trend half, drifting core weights, parked
T-bills kept apart from powder, core `QQQ:0.5,VOO:0.5`. On an offline harness (tests/qc_harness.py, NOT LEAN: fractional
shares, next-close fills, local signals) it gives Sharpe 0.707, CAGR 11.8%, max drawdown −39%, daily correlation 0.9999
with research/strategy.py (local v2: 0.707). Not yet run on QuantConnect.

**Fixed Nov 25: two bugs in the default `BASKET` mode** (both in the original commit e218c91, not in the VIX-entry work).
(1) Opening orders are queued for the next bar, but `_drift_book` re-based the book on the same bar, from empty holdings,
so core and trend became 0. The first fear tranche then *sold* the portfolio down to ~7.5% equity (harness: 2007-08-16,
70% → 7.5%). `on_data` now skips the re-base on the bar that creates the book, as HEADLINE already did. (2) With the trend
guard off, parked T-bills were kept as a fixed fraction of NAV, so part of them became spendable powder as NAV fell. They
now split the T-bill balance with powder by book share. On the harness, fixed BASKET at 50/50 gives Sharpe 0.68, CAGR
11.1% and matches the 70% / 50/50 study cell (test_basket_matches_study_cell); before the fix it showed 0.74 only by
accident of the bug. **Any QC backtest or paper run of `qc/main.py` made before this fix used the buggy code:** discard its
results, and check and reset the holdings of a live run whose first tranche has already fired.

**Fixed Nov 26: live-readiness bugs from an outside review.** All checked on the harness; tests/test_qc_live.py.
* **Fear percentile now matches research.** QC ranked today's composite against ~2.5 years of history; research ranks it
  against every value since 2000-03-08. From a Jan 2026 start the 80th-percentile call disagreed on ~30% of days, always
  as extra "fear". Replayed through local v2 from 2007, that short ranking gives about Sharpe 0.62 and max drawdown −49%
  (vs 0.71 / −39%): powder is spent on mild dips. `initialize` now seeds the full history. QC's VXN starts 2008-01-03,
  so earlier days use VIX × 1.0555, exactly as data/build_dataset.py does (this needs a VIX subscription). The harness
  reproduces research's p to 1e-9, including a 2007 start. A seed that starts after mid-2001 raises an error
  (`allow_short_seed=1` to override).
* **Restarts no longer trade.** QC restores holdings but re-runs `initialize`, so the book was rebuilt at target weights:
  a restart holding 40% QQQ / 20% QLD / 40% BIL ordered 70% / 0% / 29%. In live mode the book, tranche counters, trend
  state and leverage age are now saved to the ObjectStore (`state_key`, default `fear_tranche/state`) every bar and
  restored on restart. Without saved state, the book is rebuilt from what the account holds, tranche spacing restarts that
  day, and a `[WARN]` is logged. Backtests never read or write the store.
* **QLD take-profit counts from actual fills** (average fill price × quantity), not the planned dollars at the signal
  close. HEADLINE's 2020 exit moves to 2020-04-29, the same day as local v2.
* qc/put_writing.py: same full-history seed, and the composite history now updates every bar, not only on days with no
  put open. qc/top10_dollar_volume.py: the company id is read from `company_reference` (`company_profile` has none).

**Research fixes (Nov 26).** research/leaps_study.py: exposure-matched top-ups are priced with the contract actually held
(Sharpe changes ≤ 0.001; best cell unchanged). research/vol_selling.py: put spreads pay the ask on the protective leg
(always-on at-the-money spread 0.602 → 0.592; spreads still trail plain puts in every row). tests/test_option_costs.py.

**"Trend-guarded half" is only half at the start.** Tranches and reinvested cash go to the other half, so in local headline
v2 the trend sleeve shrinks from 35% of NAV (2007) to 18% (2012), 9% (2020) and 5% (2026). The guard protected 2008 far more
than it would protect a crash today, so the 2007–09 drawdown overstates current protection.

## Layout

```
allocation/                  equity share × QQQ/SPY mix study and its v3 candidates (own README, results, figures, tests)
data/build_dataset.py        one daily panel (QQQ 1999→2026-11, SPY, VIX, VXN, CNN F&G, T-bills, synthetic QLD/TQQQ)
research/common.py           loads the panel, imports the live dashboard's scoring code unchanged
research/evidence.py         IC + bootstrap, quintiles, event study, regimes, CAPE, SPIVA  → figures/, results/
research/strategy.py         fixed-capital engine + all variants (pre-registered rules in the docstring)
research/strategy_figs.py    equity/drawdown, allocation, trial log, leverage-instrument comparison
research/edge_study.py       per-indicator trading edge (1y vs any day) and 2x-DCA edge (rolling 5y plans) → results/edge_*.csv
research/edge_figs.py        fig_edge_trading.png, fig_edge_dca.png
research/vol_selling.py      VRP by fear level; cash-secured puts / spreads, standalone and on the dry powder
research/top10_local.py      illustrative top-10 dollar-volume rules (biased sample)
qc/put_writing.py            QC: put writing on real option quotes
qc/top10_dollar_volume.py    QC: point-in-time top-10 dollar-volume universe with weighting rules
qc/signals.py                QC-safe port of the dashboard composite (parity-tested to 1e-6)
qc/main.py                   QC algorithm: sleeves, tranches, QLD/TQQQ/LEAPS sleeve, trend guard (paper/live-ready)
qc/research_new_indicators.ipynb   QC Research: probe + IC/quintiles for VIX term structure, VVIX, HY OAS, AAII, put/call …
tests/test_qc_params.py      qc/main.py parameter helpers (AlgorithmImports stubbed)
tests/test_qc_headline.py    sleeves=HEADLINE vs local v2 and BASKET vs the study cell on tests/qc_harness.py; bug regressions
tests/test_qc_live.py        QC percentile parity with research, restarts, fill-based take-profit, put_writing, top-10
tests/test_option_costs.py   LEAPS top-up sizing and put-spread pricing
tests/test_signals_parity.py qc/signals.py == nasdaq-mood-dashboard scoring
vendor/mood_dashboard/       scoring code vendored unchanged from nasdaq-mood-dashboard (v4)
tools/build_deck.py          regenerates the midterm slide content; tools/build_qc_notebook.py the QC notebook
```

Reproduce (Python ≥3.10, `pip install -r requirements.txt`, ~1 min):
```
python data/build_dataset.py && python research/evidence.py && python research/strategy.py \
  && python research/strategy_figs.py && python research/edge_study.py \
  && python research/edge_figs.py && python allocation/research/allocation_study.py \
  && python allocation/research/allocation_figs.py && python -m pytest tests allocation/tests
```

## QuantConnect hand-off — TODO list for teammates

Upload `qc/main.py` + `qc/signals.py` as one project. Parameters (`core`, `lev`, `tranche_p`, …) are QC parameters.

**First QC run checklist** (none of this is verifiable offline):
1. `[PROBE]`: QQQ history from 1999-03-10, VXN from 2008-01-03, VIX from 1999, composite values from 2000-03-08. If
   `initialize` raises "composite history starts …", QC's VIX or QQQ history is shorter than assumed.
2. `[SIGNAL]` composite and p on a few dates against results/signal_reference.csv and research's p.
3. Paper restart drill: stop and redeploy while holding QLD. Expect `[RESTART] state … restored` and no orders that bar.

| # | Task | Why | Done when |
|---|---|---|---|
| 0 | **Probe + parity.** Run `main.py` 2011→now; compare `[SIGNAL]` log lines to `results/signal_reference.csv` | local data ≠ QC data | composite within ±1 point on spot dates |
| 1 | **Credit & macro signals**: HY OAS (`BAMLH0A0HYM2`), real 10y (`DFII10`), NFCI via QC FRED | brief §4.3 ★★★ | IC table; *check start date* — FRED cut ICE series to 3 years in Apr 2026 |
| 2 | **VIX term structure** (VIX/VIX3M, VIX9D), VVIX, SKEW, VXN−VIX | best short-horizon fear gauges | IC + incremental t-stat vs composite (notebook §5) |
| 3 | **AAII, put/call, CNN F&G** via Object Store | survey / positioning fear | same; mind publication lags |
| 4 | **Point-in-time valuation** (forward P/E snapshots or Morningstar fundamentals) | local forward-P/E used realised EPS = look-ahead | valuation sub-score re-enters composite (35% weight) |
| 5 | **LEAPS sleeve** on the real QQQ chain (`lev=LEAPS`) | defined-risk leverage, no daily-reset decay | daily marks from bid/ask mid, stale-mark audit, ledger reconciles (see QC-realdata repo notes) |
| 6 | **Sharpe levers**: vol-targeted core; powder in IEF/TLT/GLD instead of BIL; credit filter on the leverage entry | Sharpe needs lower vol, not more return | walk-forward 2008–2019 train / 2020–2026 test |
| 7 | **Multiple-testing**: Deflated Sharpe, PBO on the full trial log | 12+ variants, plus 49 in the allocation study | DSR reported with the final number |

## Known limitations (say these out loud)
* VXN before 2008 is VIX × 1.056 (back-fill). In 2000–02 real VXN was far above VIX, so pre-2008 fear is understated.
* QLD/TQQQ before inception are synthetic (2x/3x daily QQQ − financing − fees); calibrated: synthetic TQQQ 42.14% CAGR vs real 42.15% (2010–2026), daily corr 0.9986.
* SPY in data/panel.csv is not a true total-return series (about 1.4–1.7 pp/yr too low, volatility too low) and starts in
  2005. Every result with SPY in it, including the 50/50 headline rows, inherits this; see the allocation study.
* T-bill rates are annual averages (approx.). Costs: 5 bp/side ETFs, 15 bp/side leveraged ETFs.
* CNN Fear & Greed history is a community archive (2011–2023), not an official CNN series.
* The 2026 hold-out from the dashboard project was looked at during exploration → not a clean out-of-sample test. Live trading is.

Not investment advice. Personal research for a course project.

## Team & timeline
| Who | Owns | Midterm slides |
|---|---|---|
| [Member 1] | thesis, signal design, Sharpe levers, project lead | 1–4, 18–19 |
| [Member 2] | evidence & statistics, new indicators on QC, trial log / Deflated Sharpe | 5–9, 15–16, 20 |
| [Member 3] | strategy rules, QC implementation, leverage & LEAPS, risk, live paper trading | 10–14, 17 |

Nov 16 midterm · Nov 17 → mid-Dec live paper trading of v2 (frozen) · v3 frozen Dec 3 and run in parallel · final report mid-December.
