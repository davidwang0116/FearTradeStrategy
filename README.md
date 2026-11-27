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

## Options overlay: a 12-month put on the core (options/protective_put/) — PROVISIONAL
All code, results, figures, the QC audit notebook and tests for this study now live in `options/protective_put/`; see its
[README](options/protective_put/README.md). The next-stage experiments (141 setups) are written up in
[`options/protective_put/results/extensions/REPORT.md`](options/protective_put/results/extensions/REPORT.md).
**Status:** model-priced from VXN with a provisional volatility surface. Nothing here goes into v3 until the QC
steps run:
1. Stage 0: the unhedged QC run matches frozen v2.
2. Stage 1: `options/protective_put/qc/options_quote_audit.ipynb` checks every model trade against real 2012–2026 QQQ quotes and fits the
   surface, which `options/protective_put/research/options_model.py` then loads automatically.

2008 stays a model result, because QC option quotes start in 2012.

**Design.**
- **Base:** v2 + QLD + trend guard, QQQ+SPY core, 2007-02 → 2026-09.
- **Hedge:** one 12-month put struck at 85% of QQQ. It is bought when the fear percentile is ≤ 0.50, and rolled
  with less than 4 months left only while fear stays ≤ 0.50. A purchase is skipped if cash covers less than half
  of the target; the engine retries after the day's v2 rules and on later calm days.
- **Costs:** half bid/ask 2% of the option price, widening in proportion to VXN above 25 (6.4% at VXN 80).
- **Grid (12 cells, all reported):**
  - coverage: all equity, or only the core outside the trend half;
  - exit: sell at the fear peak, roll down at delta −0.6, or hold;
  - proceeds: kept in T-bills, or paid into the tranche powder before same-day sizing.
- **Pricing:** each cell is priced three ways:
  - central;
  - pessimistic (put skew ×1.5, spreads ×2, ATM IV = VXN);
  - flat-term (12-month IV rises half as much in a VXN spike).
- **Cash control:** each cell is compared with v2 scaled with T-bills, with the scale solved so max drawdown matches.
  Lowering `core_target` is *not* a cash control here: v2's MaxDD stays −37.5% to −38.9% for every `core_target`
  from 0.40 to 0.95 (`options/protective_put/results/options_core_target_frontier.csv`). At low targets the tranches spend the extra
  powder in the crash (core 0.40: exposure 0.40 before, 0.98 at the 2009 trough); at high targets the trend guard
  cuts exposure instead (core 0.95: 0.95 before, 0.41 at the trough).

| Cell | Pricing | CAGR | Vol | Sharpe | MaxDD | CAGR vs cash control, same MaxDD | 90% block-bootstrap CI | same, 2012–26 only | min net exposure |
|---|---|---|---|---|---|---|---|---|---|
| v2 unhedged | — | 11.8% | 15.2% | 0.71 | −38.8% | — | — | — | +0.42 |
| **core-only put, hold** | central | 10.3% | 11.0% | **0.80** | **−24.7%** | **+2.3 pp** | [+1.1, +3.7] | +1.7 pp | +0.12 |
| core-only put, hold | pessimistic | 9.9% | 10.8% | 0.78 | −25.0% | +1.8 pp | [+0.6, +3.2] | +1.1 pp | +0.12 |
| core-only put, hold | flat-term | 10.0% | 11.4% | 0.76 | −24.7% | +2.0 pp | [+0.8, +3.5] | +1.4 pp | +0.12 |
| all-equity put, hold | central | 9.8% | 10.2% | 0.82 | −22.2% | +2.5 pp | [+0.8, +4.4] | +1.7 pp | **−0.13** |
| all-equity put, fear exit, T-bills | central | 10.6% | 11.6% | 0.79 | −24.4% | +2.7 pp | [+1.3, +4.5] | −0.3 pp | +0.04 |
| all-equity put, fear exit, tranches | central | 11.1% | 13.0% | 0.76 | −29.6% | +1.8 pp | [+0.4, +3.7] | −0.4 pp | +0.04 |

What the provisional numbers say (`options/protective_put/figures/fig_options_frontier.png`, `fig_options_episodes.png`, `fig_options_sales.png`):
* **Insurance beats holding less equity, most clearly when the put is held.** Over the full window, 12 of 12 cells
  beat their cash control under central and flat-term pricing, and 10 of 12 under pessimistic pricing (the two
  core-only roll-down cells lose 0.1–0.2 pp). On 2012–2026 alone, the window QC can check, the four *hold* cells win
  by 0.9–1.7 pp under every pricing; the other eight range from −1.4 to +0.2 pp (2 of 8 slightly positive under
  central pricing, none under the other two). Net hedge cost is roughly 1.0–2.7% of NAV a year (cumulative option P&L over
  average NAV).
* **It buys lower risk, not higher CAGR.** Sharpe rises from 0.71 to 0.71–0.82 and max drawdown falls from −39% to
  −22% to −33%. Raw CAGR falls by 0.6–2.7 pp.
* **Recycling the proceeds into tranches does not pay at equal risk.** Proceeds into tranches minus proceeds into
  T-bills (central pricing): −0.9 pp (fear exit), −0.5 pp (roll-down), +0.05 pp (hold) with the put on all equity;
  −0.4, −0.2 and +0.05 pp with the put on the core only. The fear-peak exit sells too early in big
  declines (Oct 2008: QQQ fell another 19%; May 2022: another 16%), so the redeployed cash takes the rest of the fall.
  In 4 of v2's 7 declines the exit never fires before the trough.
* **Held puts on all equity overlap with the trend guard.** The put bought on Jun 6, 2008 covered 83% of NAV,
  including the trend half; the guard moved that half to cash on Jun 27. In the all-equity *hold* cells the
  portfolio was then net short on 111 days between Nov 12, 2008 and Apr 24, 2009 (min −0.13) and lagged the 2009
  rebound. The fear-exit and roll-down cells sold before that and never went net short. Putting the hedge on the
  core only avoids this.
* Positions are marked at mid; a sale gets the bid, so NAV at a crash trough is slightly overstated when the put is
  large (up to ~28% of NAV in Mar 2009 for the all-equity hold cells).
* Trial count for the Deflated Sharpe: 12 new strategy cells (each priced 3 ways).

QC: `qc/main.py` has `overlay=HEDGE12M` with `hedge_cover`, `hedge_exit` and `hedge_proceeds` parameters, run at
`capital=1000000`. One QQQ contract is about $68k of stock, so $100k can't be sized to the model. Default
`overlay=NONE` leaves v2 unchanged. The overlay switches prices to RAW (needed for strikes), which also shifts the
signal slightly; run the unhedged control with `price_mode=raw` so both runs see the same signal.

## Top-10 stocks by dollar volume
* Rigorous version: qc/top10_dollar_volume.py (point-in-time universe, rules: equal, invvol,
  dollarvol, reversal, momentum, drawdown, optional trend guard).
* research/top10_local.py is ILLUSTRATIVE ONLY (11 hand-picked tech winners, survivorship-biased):
  within those names no weighting rule clearly beats equal weight.

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
research/vol_selling.py      VRP by fear level; cash-secured puts / spreads, standalone and on the dry powder
research/top10_local.py      illustrative top-10 dollar-volume rules (biased sample)
options/                     option studies; protective_put/ holds the put-hedge code (research/), results/,
                             figures/, the QC quote-audit notebook (qc/) and tests/ — see options/README.md
qc/put_writing.py            QC: put writing on real option quotes
qc/top10_dollar_volume.py    QC: point-in-time top-10 dollar-volume universe with weighting rules
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
python options/protective_put/research/options_overlay.py && python options/protective_put/research/options_figs.py && python -m pytest
```
pandas ≥ 2.2 is needed (the code uses the "ME"/"YE" frequency aliases).

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
