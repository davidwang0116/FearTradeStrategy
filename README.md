# FearTradeStrategy — Buying Blood, Not Knives
A fear-tranche strategy on broad Nasdaq/S&P beta · Math 585 project (midterm Nov 16, 2026; live paper trading after)

## 项目简介（中文）
把"别人恐惧时我贪婪"做成有数据支撑、能在 QuantConnect 上回测和实盘的宽基指数策略。
* **为什么是宽基**：SPIVA 2025 年报告中，20 年期约 93% 的主动大盘基金跑输标普 500；Lecture 9 的分散化 / CAPM 也说明单只股票的夏普低于指数。所以我们不选股，只研究**何时、用多大仓位**持有 QQQM / VOO。
* **为什么情绪有 edge**：2008–2026 年 7 个恐慌指标都显示"越恐慌，之后 63 天 QQQ 收益越高"；在 VIX≥30 的每一天买入，之后一年平均 +33%（任意一天买入为 +13.5%）。但只在恐慌第一天满仓几乎没有优势，所以要**分批**。
* **策略**：70% 底仓 + 30% 国债弹药。恐慌分批加底仓，极度恐慌且开始回落时少量买 QLD（以后换 QQQ LEAPS），恐慌消退卖杠杆、贪婪时减仓重建弹药，资金循环使用。
* **现状**：2007–2026 年夏普 0.71、最大回撤 −39%（50/50 买入持有为 0.64 / −52%）。夏普 >1 是后半学期的目标。

**Thesis.** Broad index beta (QQQ / VOO) is the Sharpe-efficient core most investors can't beat
(SPIVA: 93% of active large-cap funds trail the S&P 500 over 20 years). Fear and cheapness
signals predict *higher* forward index returns, so we hold dry powder and spend it — partly
through 2x leverage — when fear is extreme, then rebuild the powder when greed returns.
This converts sentiment-weighted DCA (which needs fresh cash every month) into a
fixed-capital strategy whose capital recycles.

## Edge per indicator (research/edge_study.py)
| Indicator (best rule, ≥8 episodes) | Trading: next-1y vs any day | 2x-DCA: extra wealth, rolling 5y plans |
|---|---|---|
| VIX | ≥40: **+37 pp** (p=0.001) | ≥25: **+2.1%**, 75% of plans, XIRR +0.63 pp |
| VXN (2008+) | ≥40: **+31 pp** (p=0.001) | ≥30: +0.9% (n.s.) |
| VIX spike vs 20d mean | ≥1.5×: **+15 pp** (p=0.005) | ≈0 |
| QQQ drawdown / below MA200 | negative over full history (2000–02) | ≤−20%: **+2.0%**; <MA200: **+1.9%**, 88% of plans |
| Dashboard composite | ≥95th pct: +14 pp (n.s.) | ≥70th pct: **+1.5%** |
| CNN Fear & Greed (2011–23) | ≤10: +4 pp (n.s.) | ≤20: +0.4% |
| Shiller CAPE (S&P, monthly) | ≤40th pct: **+4.3 pp** 12m (p=0.015) | ≤40th pct: +1.7% (60-month plans) |

## Results so far (local, synthetic leveraged ETFs calibrated to real TQQQ)

| | Sharpe (excess, T-bills) | CAGR | Max DD |
|---|---|---|---|
| Buy & hold 50/50 QQQ+SPY, 2007-02 → 2026-09 | 0.64 | 12.8% | −52% |
| Static 70% beta / 30% T-bills | 0.68 | 11.9% | −37% |
| **v2 fear tranches + QLD sleeve + trend guard** | **0.71** | 11.8% | **−39%** |
| Buy & hold QQQ, 2002-03 → 2026-09 | 0.59 | 13.4% | −53% |
| **v2 … (QQQ core), same period** | **0.64** | 11.8% | **−43%** |

* The signal is real: in 2008–2026 every fear indicator ranks next-63-day QQQ returns in the contrarian
  direction (composite IC 0.18, CI [0.04, 0.33]; VIX 0.20). Buying on *every* VIX≥30 day returned +33%
  over the next year on average vs +13.5% for any day.
* Converting it into a fixed-capital rule set helps drawdowns more than Sharpe. **Sharpe > 1 is not
  reached yet**; the levers to get there are the QC work items below.
* All 12 variants run are reported (`results/strategy_variants.csv`, `figures/fig_trial_log.png`).

## Layout

```
data/build_dataset.py        one daily panel (QQQ 1999→2026-11, SPY, VIX, VXN, CNN F&G, T-bills, synthetic QLD/TQQQ)
research/common.py           loads the panel, imports the live dashboard's scoring code unchanged
research/evidence.py         IC + bootstrap, quintiles, event study, regimes, CAPE, SPIVA  → figures/, results/
research/strategy.py         fixed-capital engine + all variants (pre-registered rules in the docstring)
research/strategy_figs.py    equity/drawdown, allocation, trial log, leverage-instrument comparison
research/edge_study.py       per-indicator trading edge (1y vs any day) and 2x-DCA edge (rolling 5y plans) → results/edge_*.csv
research/edge_figs.py        fig_edge_trading.png, fig_edge_dca.png
qc/signals.py                QC-safe port of the dashboard composite (parity-tested to 1e-6)
qc/main.py                   QC algorithm: sleeves, tranches, QLD/TQQQ/LEAPS sleeve, trend guard (paper/live-ready)
qc/research_new_indicators.ipynb   QC Research: probe + IC/quintiles for VIX term structure, VVIX, HY OAS, AAII, put/call …
tests/test_signals_parity.py qc/signals.py == nasdaq-mood-dashboard scoring
vendor/mood_dashboard/       scoring code vendored unchanged from nasdaq-mood-dashboard (v4)
tools/build_deck.py          regenerates the midterm slide content; tools/build_qc_notebook.py the QC notebook
```

Reproduce (Python ≥3.10, `pip install -r requirements.txt`, ~1 min):
```
python data/build_dataset.py && python research/evidence.py && python research/strategy.py \
  && python research/strategy_figs.py && python research/edge_study.py \
  && python research/edge_figs.py && python tests/test_signals_parity.py
```

## QuantConnect hand-off — TODO list for teammates

Upload `qc/main.py` + `qc/signals.py` as one project. Parameters (`core`, `lev`, `tranche_p`, …) are QC parameters.

| # | Task | Why | Done when |
|---|---|---|---|
| 0 | **Probe + parity.** Run `main.py` 2011→now; compare `[SIGNAL]` log lines to `results/signal_reference.csv` | local data ≠ QC data | composite within ±1 point on spot dates |
| 1 | **Credit & macro signals**: HY OAS (`BAMLH0A0HYM2`), real 10y (`DFII10`), NFCI via QC FRED | brief §4.3 ★★★ | IC table; *check start date* — FRED cut ICE series to 3 years in Apr 2026 |
| 2 | **VIX term structure** (VIX/VIX3M, VIX9D), VVIX, SKEW, VXN−VIX | best short-horizon fear gauges | IC + incremental t-stat vs composite (notebook §5) |
| 3 | **AAII, put/call, CNN F&G** via Object Store | survey / positioning fear | same; mind publication lags |
| 4 | **Point-in-time valuation** (forward P/E snapshots or Morningstar fundamentals) | local forward-P/E used realised EPS = look-ahead | valuation sub-score re-enters composite (35% weight) |
| 5 | **LEAPS sleeve** on the real QQQ chain (`lev=LEAPS`) | defined-risk leverage, no daily-reset decay | daily marks from bid/ask mid, stale-mark audit, ledger reconciles (see QC-realdata repo notes) |
| 6 | **Sharpe levers**: vol-targeted core; powder in IEF/TLT/GLD instead of BIL; credit filter on the leverage entry | Sharpe needs lower vol, not more return | walk-forward 2008–2019 train / 2020–2026 test |
| 7 | **Multiple-testing**: Deflated Sharpe, PBO on the full trial log | 12+ variants already | DSR reported with the final number |

## Known limitations (say these out loud)
* VXN before 2008 is VIX × 1.056 (back-fill). In 2000–02 real VXN was far above VIX, so pre-2008 fear is understated.
* QLD/TQQQ before inception are synthetic (2x/3x daily QQQ − financing − fees); calibrated: synthetic TQQQ 42.14% CAGR vs real 42.15% (2010–2026), daily corr 0.9986.
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
