# VIX entry indicator: what we tested and what we found

This covers the VIX indicator work only: which VIX conditions have come before higher QQQ returns, how often they occur, and how far the evidence can be trusted. Portfolio buying and selling rules are [parked](#10-parked-portfolio-work).

## 1. In short

- **A high VIX has come before above-average QQQ returns.** When VIX closed at 24 or higher, the next 63 sessions (about three months) beat the all-date average by 3.51 pp in training and 3.90 pp later.
- **Requiring VIX to be easing strengthens the training result.** Our reference rule is **VIX close ≥24 and below its close 20 sessions earlier**: +6.55 pp in training and +5.37 pp later (10.81% mean return, 128 signal days).
- **Most of the later result is one episode.** April to August 2020 supplies 64 of those 128 days. Without it the spread is −2.53 pp. Without any 2020 dates it is −3.59 pp. Counting each of nine episodes once, it is +0.40 pp.
- **Easing over 5 or 10 sessions holds up better later.** Ten-day easing is +6.59 pp later, +0.53 pp without 2020 and +1.33 pp without its largest episode. Training favours 20 days, so we have not settled the lookback.
- **VIX rank and term structure look strong later but not in training.** Rank ≥80% is +0.73 pp in training and +6.84 pp later. VIX above VIX3M beats VIX at or below VIX3M later and loses to it in training.
- **The signal is rare and uneven.** The reference fires in about 1.4 episodes a year later, with gaps from 30 to 635 sessions.
- **Status: a promising pattern, with no independent confirmation.** We looked at both samples while choosing rules, and a handful of episodes dominate both.

## 2. Terms

| Term | Meaning |
|---|---|
| Signal day | A date on which the rule is true at the close |
| Return | QQQ bought at the next close and held 63 sessions |
| Spread | Mean signal-day return minus the mean of all eligible dates in the same sample, in percentage points (pp). All-date means: 3.93% training, 5.44% later |
| Episode | A run of signals. A new one starts after at least 21 sessions without a signal |
| Episode-weighted spread | Each episode counts once, using its average signal-day return |
| Ex 2020 | Drops signal dates in 2020, and compares with other dates outside 2020 |
| Largest episode removed | Drops the episode with the most signal days |
| 10th pct. | The 10th-percentile 63-session return |
| Easing | VIX close below its close N sessions earlier |
| Rank | VIX's percentile within its trailing window, including the signal day |

Spreads count every signal day, so a long episode counts many times, and neighbouring days share most of their 63 sessions. That is why each table also shows the episode-weighted and concentration columns. For rules that are true on most days, episodes merge and those columns say little.

## 3. Data and method

| Input | Dates with data in the study | Used for |
|---|---|---|
| VIX close (Cboe) | Jan 2008 to Aug 2026, history back to 1999 | level, rank, easing |
| VIX intraday high | same | intraday level, spike that fades |
| QQQ adjusted close | same | returns, price breakouts |
| VIX3M | from Sep 18, 2009 | term structure |
| QQQE (Yahoo) | from Mar 28, 2012 | equal-weight breadth proxy |
| High-yield credit spread (FRED) | from Dec 5, 2023 | credit |
| Nasdaq-100 members and prices | none | constituent breadth, not run |

- **Timing:** conditions use the close and QQQ is bought at the next close. Credit is lagged one session for its publication delay. VIX observations have no missing sessions in the sample.
- **Samples:** training is 2,956 signal dates (January 2008 to September 2019). Later is 1,660 dates (January 2020 to August 2026). We drop 64 dates whose outcomes cross into 2020.
- **Rules whose inputs start later use shorter samples.** Their training spreads cover different years, so compare them only within the same pair.
- **Starting point:** we reproduced the ZIP's 396 configurations and all 4,680 signal dates exactly, then added 252- and 1,260-session rank windows.

### The 1,188-cell grid

| Dimension | Values |
|---|---|
| VIX floor | none, 20, 22, 24, 26, 30 |
| Trailing rank | none, or ≥50% to ≥95% in five-point steps |
| Rank window | 252, 504 or 1,260 sessions |
| Easing | none, 1, 3, 5, 10 or 20 sessions |

Of 1,188 cells, 1,116 are distinct rules, because the window does nothing when rank is off. We selected on training only: highest mean return, at least 100 signal days, and mean drawdown no deeper than the 504-day rank ≥80% baseline. The winner is **VIX ≥24, 504-day rank ≥50%, 20-day easing**. It selects the same 128 later dates as the same rule without rank, so we use the simpler rule as the reference. In training the simpler rule keeps 246 days to 196.

Best rules under that screen:

| Window | Floor | Rank | Easing | Training days | Training mean | Later days | Later spread |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 504 | 24 | 50% | 20 | 196 | 10.81% | 128 | +5.37 |
| 504 | 24 | 55% | 20 | 188 | 10.71% | 128 | +5.37 |
| 1260 | 26 | 85% | 20 | 122 | 10.65% | 69 | +10.58 |
| 1260 | 26 | 60% | 20 | 179 | 10.65% | 79 | +8.45 |
| 1260 | 26 | 80% | 20 | 156 | 10.65% | 78 | +8.53 |
| 1260 | 24 | 80% | 20 | 168 | 10.63% | 108 | +6.53 |

Across the grid, 861 distinct rules have at least 100 training days and 50 later days. 765 have a positive training spread, 854 a positive later spread and 761 both. The rules overlap heavily, so this is not 761 pieces of evidence. The rank correlation between their training and later spreads is 0.09, so a rule's place in training says little about its place later. The 434 rules that pass the selection screen look better: the top 50 in training have a median later spread of +8.49 pp, ranging from +2.49 to +15.74 pp. In each of them 51% to 94% of the later signal days fall in 2020.

## 4. VIX level

**The repo's starting observation:** QQQ's 63-session return rises in the top VIX quintile. Quintile cutoffs here use the full history. The training-only cutoff is 23.95, which motivated 24.

| Quintile | VIX range | Training mean (days) | Later mean (days) |
|---|---|---:|---:|
| 1 | 9.14–13.57 | 4.04% (762) | 2.38% (138) |
| 2 | 13.58–16.19 | 2.56% (608) | 2.33% (308) |
| 3 | 16.20–19.12 | 2.64% (505) | 5.54% (425) |
| 4 | 19.13–24.37 | 2.63% (523) | 4.76% (411) |
| 5 | 24.38–82.69 | 7.68% (558) | 9.71% (378) |

The relationship is not monotonic: the lowest quintile beats the middle ones in training. Only the top quintile stands out in both samples.

**Absolute floors, no other condition:**

| Rule | Training spread (days) | Later spread (days) | Later ex 2020 (days) | Later episode-weighted (episodes) | Later, largest episode removed | Later 10th pct. | Later positive |
|---|---:|---:|---:|---:|---:|---:|---:|
| VIX ≥20 | +1.67 (975) | +2.12 (705) | +0.21 (487) | +3.59 (14) | +7.62 | −9.95% | 75% |
| VIX ≥22 | +2.74 (761) | +2.70 (536) | −0.47 (334) | +2.83 (13) | −1.83 | −9.53% | 75% |
| VIX ≥24 | +3.51 (590) | +3.90 (404) | −0.51 (234) | +2.47 (12) | −1.90 | −7.98% | 74% |
| VIX ≥26 | +4.21 (431) | +4.87 (300) | −1.26 (160) | +2.75 (14) | −0.31 | −7.96% | 75% |
| VIX ≥30 | +3.24 (297) | +8.61 (149) | +0.37 (69) | +4.06 (11) | +0.64 | −7.08% | 82% |

The spread grows with the floor up to 26 in training and up to 30 later. Outside 2020, no later floor has a meaningful spread (−1.26 to +0.37 pp).

**Close or intraday high, and spikes that fade:**

| Rule | Training spread (days) | Later spread (days) | Later ex 2020 (days) | Later episode-weighted (episodes) | Later, largest episode removed | Later 10th pct. | Later positive |
|---|---:|---:|---:|---:|---:|---:|---:|
| VIX close ≥ 24 | +3.51 (590) | +3.90 (404) | −0.51 (234) | +2.47 (12) | −1.90 | −7.98% | 74% |
| VIX high ≥ 24 | +2.96 (685) | +2.96 (495) | −0.55 (312) | +3.63 (12) | −1.90 | −9.74% | 74% |
| VIX traded at 24 or higher and closed below 24 | −0.40 (95) | −1.22 (91) | −0.66 (78) | −1.53 (20) | −1.83 | −14.32% | 73% |

Using the intraday high adds days and lowers the spread. A spike to 24 that closes below 24 has a negative spread.

## 5. VIX easing

**Lookback, with VIX ≥24:**

| Rule | Training spread (days) | Later spread (days) | Later ex 2020 (days) | Later episode-weighted (episodes) | Later, largest episode removed | Later 10th pct. | Later positive |
|---|---:|---:|---:|---:|---:|---:|---:|
| none | +3.51 (590) | +3.90 (404) | −0.51 (234) | +2.47 (12) | −1.90 | −7.98% | 74% |
| 1-day | +3.69 (304) | +4.45 (208) | −0.82 (117) | +1.82 (11) | −1.97 | −8.04% | 74% |
| 3-day | +4.06 (281) | +4.80 (192) | −0.61 (106) | +1.87 (10) | −0.06 | −6.71% | 74% |
| 5-day | +4.69 (255) | +5.39 (185) | +0.44 (99) | +4.52 (10) | +0.63 | −6.42% | 76% |
| 10-day | +5.46 (259) | +6.59 (171) | +0.53 (74) | +2.63 (9) | +1.33 | −4.51% | 81% |
| 20-day | +6.55 (246) | +5.37 (128) | −3.59 (52) | +0.40 (9) | −2.53 | −7.77% | 78% |

In training the spread rises with the lookback. Later it peaks at 10 sessions. The 5-session and 10-session rules stay positive without 2020 and without their largest episode. The 1-, 3- and 20-session rules do not.

**Easing alone does nothing:**

| Rule | Training spread (days) | Later spread (days) | Later ex 2020 (days) | Later episode-weighted (episodes) | Later, largest episode removed | Later 10th pct. | Later positive |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1-day | −0.01 (1595) | −0.06 (926) | −0.15 (785) | −0.06 (1) | — | −8.85% | 73% |
| 3-day | +0.02 (1575) | +0.07 (882) | −0.02 (752) | +0.07 (1) | — | −8.93% | 72% |
| 5-day | −0.07 (1579) | −0.03 (899) | −0.04 (763) | −0.03 (1) | — | −8.95% | 72% |
| 10-day | +0.27 (1622) | −0.29 (865) | −0.63 (717) | −1.46 (5) | +0.33 | −8.79% | 71% |
| 20-day | +0.14 (1662) | −0.64 (851) | −0.74 (725) | −5.38 (11) | −2.20 | −8.81% | 71% |

**Floors with 20-day easing:**

| Rule | Training spread (days) | Later spread (days) | Later ex 2020 (days) | Later episode-weighted (episodes) | Later, largest episode removed | Later 10th pct. | Later positive |
|---|---:|---:|---:|---:|---:|---:|---:|
| none | +0.14 (1662) | −0.64 (851) | −0.74 (725) | −5.38 (11) | −2.20 | −8.81% | 71% |
| VIX ≥20 | +3.36 (433) | +0.95 (285) | −2.81 (168) | +1.57 (11) | −4.47 | −11.62% | 75% |
| VIX ≥22 | +5.54 (329) | +2.49 (201) | −3.60 (98) | +4.47 (9) | −5.11 | −10.13% | 78% |
| VIX ≥24 | +6.55 (246) | +5.37 (128) | −3.59 (52) | +0.40 (9) | −2.53 | −7.77% | 78% |
| VIX ≥26 | +6.72 (179) | +8.45 (79) | −5.73 (25) | −0.25 (6) | −3.80 | −6.60% | 84% |
| VIX ≥30 | +5.98 (133) | +15.74 (31) | −18.13 (2) | +2.31 (3) | −10.29 | 18.82% | 94% |

Results at 26 and 30 look larger later, but rest on 25 and 2 days outside 2020.

## 6. VIX rank

**Cutoff, 504-day window:**

| Rule | Training spread (days) | Later spread (days) | Later ex 2020 (days) | Later episode-weighted (episodes) | Later, largest episode removed | Later 10th pct. | Later positive |
|---|---:|---:|---:|---:|---:|---:|---:|
| rank ≥50% | −0.41 (1374) | +1.58 (879) | +0.42 (649) | +5.13 (9) | +1.09 | −7.42% | 76% |
| rank ≥55% | −0.43 (1253) | +1.93 (796) | +0.52 (570) | +3.78 (7) | +1.15 | −7.45% | 77% |
| rank ≥60% | −0.10 (1133) | +2.69 (697) | +1.02 (486) | +1.61 (7) | +1.94 | −6.67% | 78% |
| rank ≥65% | +0.03 (1011) | +3.51 (598) | +1.59 (407) | +0.37 (11) | +0.42 | −6.39% | 79% |
| rank ≥70% | +0.39 (867) | +4.30 (526) | +2.21 (342) | +0.95 (15) | +1.07 | −5.45% | 80% |
| rank ≥75% | +0.69 (746) | +5.30 (443) | +2.70 (282) | +1.13 (15) | +1.55 | −4.28% | 82% |
| rank ≥80% | +0.73 (634) | +6.84 (346) | +3.75 (222) | −0.24 (14) | +3.23 | −3.66% | 85% |
| rank ≥85% | +0.74 (530) | +9.27 (267) | +6.23 (164) | +1.78 (16) | +5.39 | 0.62% | 90% |
| rank ≥90% | +0.08 (373) | +11.20 (182) | +8.18 (114) | +2.80 (13) | +7.32 | 1.48% | 92% |
| rank ≥95% | −0.58 (234) | +13.98 (98) | +10.51 (60) | +3.79 (11) | +9.36 | 5.27% | 94% |

**Window:**

| Rule | Training spread (days) | Later spread (days) | Later ex 2020 (days) | Later episode-weighted (episodes) | Later, largest episode removed | Later 10th pct. | Later positive |
|---|---:|---:|---:|---:|---:|---:|---:|
| 252-day rank ≥80% | +0.54 (534) | +3.49 (335) | +0.92 (261) | +2.79 (14) | +8.86 | −11.43% | 75% |
| 504-day rank ≥80% | +0.73 (634) | +6.84 (346) | +3.75 (222) | −0.24 (14) | +3.23 | −3.66% | 85% |
| 1260-day rank ≥80% | −0.21 (703) | +3.58 (426) | −0.85 (219) | +2.18 (13) | −2.37 | −7.62% | 77% |
| 252-day rank ≥90% | −0.33 (341) | +4.58 (195) | +1.74 (156) | +0.15 (12) | +0.59 | −11.65% | 75% |
| 504-day rank ≥90% | +0.08 (373) | +11.20 (182) | +8.18 (114) | +2.80 (13) | +7.32 | 1.48% | 92% |
| 1260-day rank ≥90% | +0.11 (352) | +7.84 (227) | +0.29 (90) | +2.77 (10) | +1.58 | −6.71% | 84% |

**With a VIX ≥24 floor:**

| Rule | Training spread (days) | Later spread (days) | Later ex 2020 (days) | Later episode-weighted (episodes) | Later, largest episode removed | Later 10th pct. | Later positive |
|---|---:|---:|---:|---:|---:|---:|---:|
| rank ≥50% | +3.09 (507) | +3.90 (404) | −0.51 (234) | +2.47 (12) | −1.90 | −7.98% | 74% |
| rank ≥80% | +0.80 (342) | +7.49 (264) | +2.50 (140) | +0.38 (13) | +2.46 | −4.99% | 82% |
| rank ≥90% | −0.55 (232) | +12.03 (155) | +8.36 (87) | +3.24 (12) | +7.57 | 0.79% | 91% |
| rank ≥95% | −1.47 (173) | +14.69 (90) | +11.04 (52) | +4.11 (10) | +9.89 | 4.76% | 93% |

**With VIX ≥24 and 20-day easing:**

| Rule | Training spread (days) | Later spread (days) | Later ex 2020 (days) | Later episode-weighted (episodes) | Later, largest episode removed | Later 10th pct. | Later positive |
|---|---:|---:|---:|---:|---:|---:|---:|
| none | +6.55 (246) | +5.37 (128) | −3.59 (52) | +0.40 (9) | −2.53 | −7.77% | 78% |
| rank ≥50% | +6.88 (196) | +5.37 (128) | −3.59 (52) | +0.40 (9) | −2.53 | −7.77% | 78% |
| rank ≥80% | +3.12 (100) | +12.90 (66) | −0.55 (12) | +3.93 (8) | +0.74 | 6.47% | 95% |
| rank ≥90% | −0.28 (46) | +18.46 (28) | +15.17 (2) | +15.61 (3) | +14.02 | 19.65% | 100% |

Rank does almost nothing in training at any cutoff or window. Later, higher 504-day cutoffs earned more and held up outside 2020. At 80%, episode-weighted is −0.24 pp and buying each episode's first signal is −4.07 pp, so much of that result comes from long runs of signal days. At 90% and above it is positive by episode. Adding rank to the reference rule changes nothing at 50%, and leaves too few days at 80% and above.

## 7. VIX variants and confirmations

Each table is one experiment and uses the dates both rules share.

### Term structure (VIX against VIX3M, VIX ≥24)

| Rule | Training spread (days) | Later spread (days) | Later ex 2020 (days) | Later episode-weighted (episodes) | Later, largest episode removed | Later 10th pct. | Later positive |
|---|---:|---:|---:|---:|---:|---:|---:|
| VIX close ≥ 24 + VIX at or below VIX3M | +5.30 (161) | +0.85 (300) | −2.83 (181) | +2.47 (9) | −4.52 | −9.15% | 70% |
| VIX close ≥ 24 + VIX above VIX3M | +2.35 (116) | +12.72 (104) | +7.40 (53) | +1.65 (14) | +7.03 | −3.20% | 87% |

**The sign flips between samples.** In training the flat curve earned 9.68% and the inverted one 6.73%. Later the inverted curve earned 18.15% and the flat one 6.28%. Excluding 2020 it is 11.69% to 1.47%. February to April 2020, March to April 2025 and March to April 2026 supply 72 of the 104 later inverted days.

### QQQ price recovery

| Rule | Training spread (days) | Later spread (days) | Later ex 2020 (days) | Later episode-weighted (episodes) | Later, largest episode removed | Later 10th pct. | Later positive |
|---|---:|---:|---:|---:|---:|---:|---:|
| VIX close ≥ 24 + VIX easing 20d | +6.55 (246) | +5.37 (128) | −3.59 (52) | +0.40 (9) | −2.53 | −7.77% | 78% |
| VIX close ≥ 24 + VIX easing 20d + QQQ above its previous 5 closes | +6.20 (81) | +7.64 (41) | −4.26 (12) | +1.17 (6) | −3.42 | −3.42% | 78% |

The breakout cuts 128 later days to 41 and lifts the 10th percentile. It is −4.26 pp without 2020, on 12 days.

We also tested waiting. After the first VIX ≥24 close, wait up to ten sessions for a breakout. This starts from the fear signal, not the reference rule. Twelve later episodes:

| Breakout | Confirmed | Immediate entry | After breakout | After breakout, original exit date | Immediate return of unconfirmed episodes |
|---|---:|---:|---:|---:|---:|
| 3 closes | 12 | 5.20% | 5.53% | 4.30% | none |
| 5 closes | 9 | 4.89% | 4.62% | 3.50% | 6.11% |
| 10 closes | 6 | 7.33% | 4.98% | 3.42% | 3.06% |

The answer changes with the breakout length. Averages for the confirmed group leave out the episodes that never confirmed.

### Breadth

| Rule | Training data from | Training spread (days) | Later spread (days) | Later ex 2020 (days) | Later episode-weighted (episodes) | Later, largest episode removed |
|---|---|---:|---:|---:|---:|---:|
| VIX close ≥ 24 + VIX easing 20d | 2012-03-28 | +4.78 (4) | +5.37 (128) | −3.59 (52) | +0.40 (9) | −2.53 |
| VIX close ≥ 24 + VIX easing 20d + QQQE / QQQ rising over 5 sessions | 2012-03-28 | +3.89 (3) | +5.94 (78) | −2.11 (31) | −1.51 (8) | +0.23 |

QQQE/QQQ rising adds 0.57 pp to the later mean. The matched training comparison has **3 and 4 signal days**, so it tells us nothing. Constituent breadth is coded and untested: the repo lacks point-in-time membership and prices.

### High-yield credit (later only)

| Rule | Training spread (days) | Later spread (days) | Later ex 2020 (days) | Later episode-weighted (episodes) | Later, largest episode removed | Later 10th pct. | Later positive |
|---|---:|---:|---:|---:|---:|---:|---:|
| VIX close ≥ 24 + High-yield spread widening over 5 sessions | — (0) | +10.90 (32) | +10.90 (32) | +3.05 (6) | +8.69 | 1.20% | 94% |
| VIX close ≥ 24 + High-yield spread flat or narrowing over 5 sessions | — (0) | +17.18 (21) | +17.18 (21) | +17.33 (2) | +17.92 | 18.97% | 100% |

Flat or narrowing spreads averaged 22.85% against 16.56% for widening, on 21 days in two episodes. VIX was falling over five sessions on 67% of those days and 25% of the widening days, so this partly repeats easing.

## 8. The reference rule in detail

The first-signal return buys only the first day of each episode. Worst close is measured over the 63 sessions after that entry.

| First signal | Last signal | Days | VIX | First-signal return | Mean of all signal days | Worst close | Sessions after first VIX ≥24 |
|---|---|---:|---:|---:|---:|---:|---:|
| 2008-01-16 | 2008-03-31 | 12 | 24.4 | +2.9% | +11.7% | −9.1% | 49 |
| 2008-11-04 | 2009-11-30 | 156 | 47.7 | −1.8% | +10.8% | −20.1% | 43 |
| 2010-06-07 | 2010-08-18 | 27 | 36.6 | +3.8% | +10.2% | −3.5% | 22 |
| 2011-09-06 | 2011-12-19 | 47 | 37.0 | +4.7% | +9.4% | −6.2% | 26 |
| 2015-09-29 | 2015-09-30 | 2 | 26.8 | +11.7% | +10.7% | 0.0% | 26 |
| 2016-02-08 | 2016-02-16 | 2 | 26.0 | +11.8% | +7.5% | 0.0% | 38 |
| 2020-04-06 | 2020-08-27 | 64 | 45.2 | +32.6% | +18.7% | 0.0% | 30 |
| 2020-09-29 | 2020-11-12 | 12 | 26.3 | +12.8% | +12.5% | −3.0% | 152 |
| 2021-02-02 | 2021-03-02 | 4 | 25.6 | +0.9% | +4.6% | −8.1% | 238 |
| 2022-02-18 | 2022-02-25 | 5 | 27.8 | −13.1% | −12.8% | −14.5% | 21 |
| 2022-04-11 | 2022-04-12 | 2 | 24.4 | −15.4% | −15.5% | −20.1% | 56 |
| 2022-05-24 | 2022-08-23 | 23 | 29.4 | +10.3% | −3.5% | −6.8% | 86 |
| 2022-10-21 | 2022-11-16 | 16 | 29.7 | +3.6% | +9.7% | −6.4% | 190 |
| 2025-05-06 | 2025-05-06 | 1 | 24.8 | +17.9% | +17.9% | 0.0% | 42 |
| 2026-04-06 | 2026-04-06 | 1 | 24.2 | +21.0% | +21.0% | 0.0% | 20 |

By year, mean signal-day return: 2008 +3.6% (41 days), 2009 +13.2% (127), 2010 +10.2% (27), 2011 +9.4% (47), 2015 +10.7% (2), 2016 +7.5% (2), 2020 +17.7% (76), 2021 +4.6% (4), 2022 −0.5% (46), 2025 +17.9% (1), 2026 +21.0% (1).

- **It fires late.** Counting from the first VIX ≥24 close, it fired in 10 of 29 fear episodes, and 9 of the 10 took 20 to 43 sessions. It missed August 2024 entirely. It is a signal for prolonged stress.
- **The first signal is a weaker entry than the average day.** Nine later first entries averaged 7.86% (7 of 9 profitable).

## 9. How often, and how much to trust it

### Frequency

| Rule | Sample | Signal days | Episodes | Episodes a year | Median gap (range) | Gaps ≥63 / ≥90 sessions | Longest stretch with none |
|---|---|---:|---:|---:|---:|---:|---:|
| VIX close ≥ 24 | training | 590 | 17 | 1.4 | 137 (33–604) | 81% / 69% | 585 |
| VIX close ≥ 24 | later | 404 | 12 | 1.8 | 90 (23–352) | 64% / 55% | 345 |
| 504d rank ≥ 80% | training | 634 | 19 | 1.6 | 104 (34–625) | 67% / 67% | 532 |
| 504d rank ≥ 80% | later | 346 | 14 | 2.1 | 96 (38–474) | 77% / 62% | 443 |
| VIX close ≥ 24 + VIX easing 20d | training | 246 | 6 | 0.5 | 316 (90–1,022) | 100% / 100% | 948 |
| VIX close ≥ 24 + VIX easing 20d | later | 128 | 9 | 1.4 | 113 (30–635) | 75% / 62% | 616 |
| VIX close ≥ 24 + VIX easing 10d | training | 259 | 11 | 0.9 | 106 (46–1,016) | 80% / 60% | 932 |
| VIX close ≥ 24 + VIX easing 10d | later | 171 | 9 | 1.4 | 103 (26–624) | 88% / 50% | 604 |
| VIX close ≥ 24 + VIX at or below VIX3M | training | 161 | 7 | 0.7 | 134 (69–828) | 100% / 50% | 912 |
| VIX close ≥ 24 + VIX at or below VIX3M | later | 300 | 9 | 1.4 | 154 (37–448) | 75% / 62% | 441 |
| VIX close ≥ 24 + VIX above VIX3M | training | 116 | 14 | 1.4 | 134 (33–806) | 77% / 62% | 733 |
| VIX close ≥ 24 + VIX above VIX3M | later | 104 | 14 | 2.1 | 76 (23–466) | 69% / 46% | 452 |

Gaps run from one episode's first signal to the next, in trading sessions. 63 is about three months and 252 is a year. The reference's 113-session median hides droughts: nothing between November 2022 and May 2025, and nothing from February 2016 to the end of training. Two of seven later calendar years had no signal.

### Could this be chance?

We slide each rule's signal dates along the sample, keeping their clustering, and count how often the shifted dates do at least as well. Smaller numbers are stronger evidence. These numbers do **not** correct for the rules we searched.

| Rule | Training | Later |
|---|---:|---:|
| VIX close ≥ 24 | 0.023 | 0.005 |
| 504d rank ≥ 80% | 0.437 | <0.001 |
| VIX close ≥ 24 + VIX easing 10d | 0.025 | 0.011 |
| VIX close ≥ 24 + VIX easing 20d | 0.020 | 0.054 |
| VIX close ≥ 24 + VIX easing 20d + QQQ above its previous 5 closes | 0.027 | 0.027 |
| VIX close ≥ 24 + VIX above VIX3M | 0.144 | <0.001 |
| VIX close ≥ 24 + VIX at or below VIX3M | 0.015 | 0.417 |

VIX ≥24, VIX ≥24 with 10-day easing, and the reference plus a breakout are below 0.03 in both samples. The breakout rule has 41 later days. The reference is 0.020 in training and 0.054 later. Rank and VIX above VIX3M are strong later and ordinary in training.

### What limits the conclusions

1. Both samples were explored, so the later one is not an independent test.
2. A few episodes dominate: 2008–2009, 2010–2011, and 2020.
3. Overlapping 63-session windows make the number of independent observations closer to the episode count than the day count.
4. We tried many rules. The best results overstate what to expect.
5. Training and later disagree for rank and term structure.

## 10. Parked: portfolio work

Outside the current focus. These results come from using a VIX rule as the gate for core purchases in the repo's v2 portfolio. The gate is the only setting that changes between rows.

| Gate | Sharpe, training | Sharpe, later (fresh start) | Sharpe, later (carried from training) |
|---|---:|---:|---:|
| VIX ≥24 | 0.718 | 0.828 | 0.739 |
| VIX ≥24 + 10-day easing | 0.723 | 0.884 | 0.802 |
| VIX ≥24 + 20-day easing (reference) | 0.699 | 0.882 | 0.807 |
| Existing composite (control) | 0.693 | 0.863 | 0.773 |
| No tranche purchases (control) | 0.699 | 0.845 | 0.823 |

- **The VIX gate is not clearly better than no tranche purchases.** The reference wins on a fresh start, ties in training and loses when holdings carry forward.
- **The comparison is not isolated.** The QLD sleeve still follows the composite and spends the same cash.
- **Worth a separate look later:** tranche and reinvestment buys go to the half of the core that is not trend-guarded, so the guarded share shrinks over time. Alternative exit and guard rules were tried in this session and removed. They are not in the repo.

## 11. What we checked and changed

**Confirmed correct:** next-close entry and 63-session hold; training and later split; rank, easing, breakout, term-structure and credit-lag formulas; grid selection; ZIP match; and dashboard calculations, which agree with Python on every preset. We rebuilt eight rules from raw data with separate code and matched the results.

**Corrected in the write-up:**

- The term-structure advantage reverses in training.
- The breadth proxy's training spread came from 3 signal days, not comparable with the 246-day reference.
- Concentration in 2020, the late entry and the chance test were missing or underplayed.
- Waiting for a breakout was reported at only one length.
- The funded controls were run and left out. The advantage over no-tranche disappears when holdings carry forward.
- 1,188 configurations are 1,116 distinct rules.

**Added:** episode-weighted, largest-episode and training columns in the outcome table; composite and no-tranche controls; carried-forward runs; signal frequency and gaps; episode entries and 63-session outcomes; a funded trade list; and tests.

## 12. Open questions on the indicator

1. Which easing lookback: 5, 10 or 20 sessions? Training and later disagree.
2. Is rank useful, or is its later result one regime? It needs a test that the training period does not contradict.
3. Does VIX above VIX3M add anything beyond VIX level, given that the sign flips?
4. Constituent breadth needs point-in-time membership data.
5. Nothing here has been tested on data we had not already seen.

## 13. Files and reproduction

| File | Role |
|---|---|
| `research/vix_entry/indicators.py` | daily features and the entry gate |
| `research/vix_entry/analyze_vix.py` | grid, experiments, outcome table, funded runs, dashboard export |
| `research/vix_entry/trades.py` | signal frequency, entries and outcomes by episode |
| `research/vix_entry/summary_tables.py` | prints most tables in this document |
| `research/vix_entry/dashboard.html.in` | dashboard template |
| `tests/test_vix_entry.py` | tests |
| `results/vix_entry/` | CSVs and dashboard (gitignored) |

```sh
python research/vix_entry/analyze_vix.py
python research/vix_entry/summary_tables.py
```

`data/raw/vix_entry/` and `results/vix_entry/` are gitignored, so a fresh clone must download the inputs listed in [README.md](README.md). FRED publishes about three years of the credit series, so those rows will stop being reproducible from a new download.
