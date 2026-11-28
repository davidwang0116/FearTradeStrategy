# VIX entry indicator: what we tested and what we found

This covers the VIX indicator work only: which VIX conditions have come before higher QQQ returns, how often they occur, and how far the evidence can be trusted. Entry and exit tests built on the trigger are in [section 11](#11-entry-and-exit-tests-on-top-of-the-vix-trigger), and every other VIX signal as the entry is in [section 12](#12-every-vix-signal-as-the-entry-point). The v2 portfolio work is [parked](#10-parked-portfolio-work).

## 1. In short

- **Buying once per episode has earned little more than buying on an average date.** The first VIX ≥24 close of each episode, held 63 sessions after costs, beat the average date by 1.68 pp in training (16 episodes) and 0.32 pp later (12). Without its best episode, later is −1.95 pp. With the study's other episode definition (21 quiet sessions) it is −0.86 and −0.23 pp.

| One purchase per episode at VIX ≥24 | Training excess (return) | Later excess (return) | Better than an average date, training / later |
|---|---:|---:|---:|
| New episode after VIX falls to its median | +1.68 pp (5.50%) | +0.32 pp (5.64%) | 9 of 16 / 6 of 12 |
| New episode after 21 quiet sessions | −0.86 pp (2.96%) | −0.23 pp (5.09%) | 8 of 16 / 6 of 12 |

- **Counting every signal day looks much better.** When VIX closed at 24 or higher, the next 63 sessions (about three months) beat the all-date average by 3.51 pp in training and 3.90 pp later. Long episodes count many times here, and the later figure is −0.51 pp without 2020.
- **Requiring VIX to be easing strengthens the training result.** Our reference rule is **VIX close ≥24 and below its close 20 sessions earlier**: +6.55 pp in training and +5.37 pp later (10.81% mean return, 128 signal days).
- **Most of the later result is one episode.** April to August 2020 supplies 64 of those 128 days. Without it the spread is −2.53 pp. Without any 2020 dates it is −3.59 pp. Counting each of nine episodes once, it is +0.40 pp.
- **Easing over 5 or 10 sessions holds up better later.** Ten-day easing is +6.59 pp later, +0.53 pp without 2020 and +1.33 pp without its largest episode. Training favours 20 days, so we have not settled the lookback.
- **VIX rank and term structure look strong later but not in training.** Rank ≥80% is +0.73 pp in training and +6.84 pp later. VIX above VIX3M beats VIX at or below VIX3M later and loses to it in training.
- **The signal is rare and uneven.** The reference fires in about 1.4 episodes a year later, with gaps from 30 to 635 sessions.
- **Buying rules on top of it added nothing.** No wait, split, ladder or exit passed our rule against buying at the trigger and holding 63 sessions (2008–2019).
- **No other VIX signal is a better entry either.** Of 42 signals (rank lookbacks, easing, floors and combinations), the 11 that passed in training are about what luck gives, and none repeats it later.
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
- **The engine starts at 52.5% QQQ and 17.5% SPY,** because the trend-guarded half of the core is all QQQ. The separate sleeve in section 11 starts at 35% each, so the two are not directly comparable.
- **QLD's take-profit is tested on the close it sells at.** Testing the previous close instead changes no Sharpe in the reference, 10-day, composite and no-tranche runs by more than 0.0002, so shared `strategy.py` is unchanged. Cash earns an approximate annual-average T-bill rate, not the daily rate.
- **Worth a separate look later:** tranche and reinvestment buys go to the half of the core that is not trend-guarded, so the guarded share shrinks over time. Alternative guard rules were tried in this session and removed. They are not in the repo.

## 11. Entry and exit tests on top of the VIX trigger

**Result: nothing passed our rule against buying at the trigger and holding 63 sessions.** Ideas E1 to E6 and X1 to X5 came from the team draft. We added E1v, E7, X6 and X7.

**Method.** The trigger is the first VIX close ≥24 of an episode. A new episode needs VIX to fall back to its expanding median (Cboe history from 1990). That gives 28 episodes since 2008: 16 training and 12 later. Every signal fills at the next close, costs 5 bp a side, and idle cash earns T-bills. Everything is sold 63 sessions after the purchase. The two sensitivity triggers reset on their own gauge: composite at its median, or VIX rank at 50%. We chose on 2008–2019 only, and a rule had to have a positive mean difference, be better in at least 60% of episodes, and stay positive without its best episode. Each stage's rules were coded and tested before its results were read, and the rule definitions did not change afterwards. Exits were written after the entry results were known. Entries and exits were rebuilt with separate code and matched.

### Entry: the first order

Baseline: buy all of one tranche at the trigger. Differences are in points of that order.

| Rule | Training difference | Better in training | Without best episode | Later difference | Mean worst mark (baseline) | Order spent, training |
|---|---:|---:|---:|---:|---:|---:|
| E4 wait for VIX easing 5d | −1.50 | 44% | −2.00 | −1.54 | −3.8% (−6.1%) | 75% |
| E5 half now, half on VIX easing 5d | −0.75 | 44% | −1.00 | −0.77 | −4.7% (−6.1%) | 88% |
| E6 half now, half after 5 sessions unless calm | −0.30 | 50% | −0.80 | −0.11 | −4.8% (−6.1%) | 91% |
| E6u half now, half after 5 sessions always | +0.07 | 50% | −0.40 | −0.48 | −5.3% (−6.1%) | 100% |
| E4 wait for VXN 15% below 10d high | −0.45 | 50% | −1.40 | −1.02 | −3.6% (−6.1%) | 75% |
| E5 half now, half on VXN 15% below 10d high | −0.23 | 50% | −0.70 | −0.51 | −4.6% (−6.1%) | 88% |
| E4 wait for QQQ 5-close breakout | −4.21 | 25% | −4.84 | −4.28 | −3.6% (−6.1%) | 56% |
| E5 half now, half on QQQ 5-close breakout | −2.11 | 25% | −2.42 | −2.14 | −4.7% (−6.1%) | 78% |
| E4 wait for VIX/VIX3M back below 1 | −3.50 | 7% | −4.18 | −4.29 | −4.8% (−5.8%) | 80% |
| E5 half now, half on VIX/VIX3M back below 1 | −1.75 | 7% | −2.09 | −2.14 | −5.2% (−5.8%) | 90% |

- **Waiting for a signal lost in every version tested with this trigger.** The full-order waits (E4) lost more than the halves (E5).
- **Reading VIX did not beat a plain 5-session delay.** E6 follows the draft and cancels its second half when fear calms, which skipped 3 of 16 training and 2 of 12 later buys. E6u always buys it, so the delay is the only difference from E0. E5 (VIX easing) trails E6 by 0.45 and 0.66 points, and E6u by 0.82 and 0.29. A difference of about 1.5 to 1.7 points would be needed to detect it reliably.
- **E6u's +0.07 in training does not pass.** It is better in half the episodes, negative without its best one, and −0.48 later.
- **Splitting lowers pain.** The average worst mark improves, at the cost of return.

### Entry: the four-tranche reserve

Two measures, because they answer different questions. **Profit** is what the investor earns on the whole reserve, with T-bill interest on unspent cash. It rewards buying more, because QQQ rises. **Timing value** is profit beyond buying on an average date and holding as long, and it decides. Baseline: the whole reserve at the trigger, which earned 5.50% in training and 5.64% later.

| Rule | Timing value, training difference | Better in training | Without best episode | Timing value, later difference | Profit on the reserve, training / later | Reserve spent, training / later |
|---|---:|---:|---:|---:|---:|---:|
| R0 whole reserve at the trigger | — | — | — | — | 5.50% / 5.64% | 100% / 100% |
| R1 first tranche only | −1.26 | 44% | −1.94 | −0.24 | 1.53% / 1.93% | 25% / 25% |
| E1 price ladder (8%) | −0.69 | 50% | −1.36 | +0.63 | 2.27% / 3.12% | 34% / 38% |
| E1c the same, cancelled when calm | −0.85 | 50% | −1.53 | +0.21 | 2.06% / 2.59% | 31% / 31% |
| E1v price ladder (VIX-scaled) | −0.81 | 44% | −1.49 | +0.10 | 2.10% / 2.51% | 33% / 33% |
| E1vc the same, cancelled when calm | −0.97 | 44% | −1.66 | −0.23 | 1.90% / 2.08% | 30% / 29% |
| E3 every 10 sessions while VIX is high | −0.65 | 44% | −1.21 | +2.24 | 2.60% / 5.12% | 42% / 48% |
| E3c the same, cancelled when calm | −0.65 | 44% | −1.21 | +1.38 | 2.60% / 4.16% | 42% / 44% |
| E7 late tranche on 20-day easing | −0.79 | 50% | −1.43 | +0.51 | 2.14% / 2.90% | 31% / 33% |

- **None passes on either measure.** Every plan earned less than spending the whole reserve at the trigger, in both periods. E3's later timing value is the best of them and still earned 5.12% against 5.64%.
- **The draft did not say what ends E1 and E3.** As drafted they can buy again after fear has calmed and a new episode has begun. The March 6, 2025 plan bought on April 7, the same close as the April 3 episode's own purchase. The E1c, E1vc and E3c rows cancel what is left at the first calm close, which lowers the later results.
- **Against buying only the first tranche,** the later tranches look good in training: where they acted, E1 was better in 5 of 6 episodes, E1v 5 of 5, E3 5 of 7 and E7 4 of 4. The selection rule counts a tie as not better, so it could not have passed them: they act in fewer than half the episodes. Counting only those episodes they would pass, on 4 to 7 episodes. Spending the whole reserve at the trigger still had more timing value in training.

In the draft, the 20-day easing rule was a possible confirmation. It fires in 8 of the 28 episodes as a late tranche and is too slow for a 10-session confirmation.

### Exit

The whole order is bought at the trigger. Baseline X1 holds to the deadline.

| Rule | Training difference | Better in training | Without best episode | Later difference | Time in QQQ, training | Mean worst mark (baseline) |
|---|---:|---:|---:|---:|---:|---:|
| X2 VIX back to its median | −2.82 | 25% | −3.47 | −0.88 | 40% | −4.6% (−6.1%) |
| X3a price breakdown, armed by a recovery | −3.49 | 38% | −4.19 | +0.16 | 38% | −3.8% (−6.1%) |
| X4a half on normalization, half on breakdown | −3.15 | 31% | −3.77 | −0.36 | 39% | −4.1% (−6.1%) |
| X5a half on normalization, all on breakdown | −4.18 | 31% | −4.93 | −0.71 | 29% | −3.7% (−6.1%) |
| X6 VIX 40% below its episode peak | −3.73 | 12% | −4.35 | −3.48 | 49% | −6.0% (−6.1%) |
| X7 thirds over time | −2.40 | 25% | −2.80 | −1.73 | 67% | −5.2% (−6.1%) |
| X3 price breakdown, as drafted | −6.40 | 25% | −7.30 | −4.49 | 6% | −2.1% (−6.1%) |

- **X3 as drafted sells near the bottom.** QQQ breaks its 10-session low a median of 4 sessions after the trigger, before or at the −8% ladder rung every time that rung was reached (12 of 12). X3a, X4a and X5a require QQQ to close above its prior 5 closes first.
- **Every exit costs return in training.** They also cut time in QQQ and the worst marks.
- **X4a against X5a.** They differ only when price breaks down before fear fades, in 7 training and 3 later episodes. Selling the second half there (X5a) lost 2.36 points in training and 1.38 later, so holding the rest was better. Later is three episodes.
- **At 126 sessions the exits still lose to holding in training.** Later X3a is +0.16 points at 63 sessions and −5.55 at 126.

### Holding 126 sessions against 63

Both sides buy the whole order at the trigger. One sells after 63 sessions and earns T-bills to session 126. Only episodes with 126 sessions of outcome count (15 training, 12 later).

| Measure | Training difference | Better in training | Without best episode | 90% interval, training | Later difference | Later without best |
|---|---:|---:|---:|---:|---:|---:|
| Profit | +0.61 | 73% | −0.32 | −4.12 to +4.94 | +5.91 | +4.13 |
| Timing value | −3.19 | 33% | −4.14 | −7.95 to +1.17 | +0.93 | −0.80 |

- **Holding longer does not pass.** In training the extra profit disappears without the best episode. Mean worst mark goes from −6.5% to −9.4%.
- **Most of the later gain is an extra quarter in stocks.** Timing value, which takes out the average return for the holding length, is +0.93 later and −0.80 without its best episode.
- **The sensitivity triggers differ.** With composite ≥80th and VIX rank ≥80% + VIX ≥20, holding 126 sessions passes on both measures in training (timing value +1.54 and +2.58). Later, timing value is +3.09 on 5 episodes, negative without the best, and −2.31 on 17; profit is +8.01 and +2.63. We did not choose a holding period from this.

### Funded check

A 70% QQQ/SPY buy-and-hold core and 30% T-bills. Each trigger moves a share of the account into QQQ, no more than the cash left. No trend guard, no QLD. `strategy.py` is unchanged. The matched account holds the sleeve's average QQQ weight all the time.

| Account | Share per trigger | Sharpe, training | Sharpe, later | Max drawdown, training / later | Later Sharpe minus exposure-matched static (90% interval) |
|---|---:|---:|---:|---:|---:|
| Static 70/30, no trades | — | 0.671 | 0.712 | −33.7% / −22.8% | — |
| X1 hold to the deadline | 7.5% | 0.673 | 0.703 | −34.3% / −24.1% | −0.011 (−0.046 to +0.027) |
| X1 hold to the deadline | 30.0% | 0.657 | 0.724 | −36.1% / −26.2% | +0.006 (−0.087 to +0.118) |

The sleeve adds nothing measurable: the intervals include zero. A 7.5% tranche averages about 2.5% to 3.4% of the account. Other exits are in the dashboard and were not chosen. The intervals use the same Sharpe formula as the reported Sharpe.

### What we would not repeat

With the composite trigger, spending the whole reserve at the trigger passed the rule against buying only the first tranche. That is the baseline we already use, on a sensitivity trigger.

Tested and rejected here: every wait, split, ladder and exit above, with composite ≥80th and VIX rank ≥80% + VIX ≥20 as alternative triggers. Not tested: 25% of remaining cash (E2), composite ≥90th and VIX ≥30, for lack of episodes.

## 12. Every VIX signal as the entry point

**Result: no signal is reliably better than buying on an average date, and none beats buying at VIX ≥24 under our rule.** Section 11 used VIX ≥24 alone as the entry. Here each earlier signal is the entry: four rank choices (none, 252, 504, 1,260 days at ≥80%) × four easing choices (none, 5, 10, 20 days) × VIX ≥24 or no floor, plus other floors, term structure, a breakout, the intraday high and the intraday spike that fades. That is 42 signals. Easing with no floor and no rank has no fear condition, so it is not an entry.

**Method.** Each episode buys once, at the close after the signal's first close, and holds 63 sessions. A new episode needs the signal's own gauge to calm: VIX at its expanding median when the rule has a floor, otherwise its rank at or below 50%. The dashboard shows which reset each signal uses. That is why VIX ≥20 + 504d rank ≥80% has 28 training episodes here and 13 in section 11, where the same entry condition resets on its rank. Excess is the return beyond the average 63-session return of dates with that signal's data, after costs. This only matters for the two VIX3M signals, whose data start in September 2009. Rules were fixed in code before results. 2008–2019 decides, with the same rule as section 11 (positive mean, better in at least 60% of episodes, positive without the best episode) and at least 8 episodes. We rebuilt seven signals' episodes separately and they matched.

### Luck check

26 signals have at least 8 training episodes and 11 pass the rule. That sounds like a lot. When every signal's dates are slid together by a random amount, which keeps how they overlap and cluster but removes any information, an average of 7.3 pass and 5% of slides give 21 or more. The chance of 11 or more is 27%. The chance that the best of the 26 looks as good as the best we saw is 72%. Dates that slide to before a signal's data exist are left out.

### All signals

Numbers are points of return. "Too few" means fewer than 8 training episodes. The study's other episode definition (21 quiet sessions) is a robustness check, added after the first results.

| Signal | Training excess (episodes) | Passes | Later excess (episodes) | Training excess, 21-quiet-session episodes | Waiting for it vs buying at VIX ≥24, training (fired / episodes) |
|---|---:|---|---:|---:|---:|
| VIX ≥ 24 + 504d rank ≥ 80% + easing 20d | +2.6 (4) | too few | +8.9 (4) | +2.6 (4) | −3.2 (3/15) |
| VIX ≥ 24 + VIX at or below VIX3M | +2.5 (7) | too few | +0.4 (8) | +2.5 (7) | −3.0 (6/14) |
| VIX ≥ 24 + 1260d rank ≥ 80% + easing 20d | +2.1 (5) | too few | +8.1 (3) | +3.4 (6) | −3.0 (4/15) |
| VIX ≥ 24 + easing 20d | +2.1 (5) | too few | +9.2 (4) | +2.1 (5) | −3.0 (4/15) |
| VIX ≥ 24 + 252d rank ≥ 80% + easing 20d | +2.1 (5) | too few | +9.2 (4) | +2.1 (5) | −3.0 (4/15) |
| VIX ≥ 24 + 504d rank ≥ 50% + easing 20d | +2.1 (5) | too few | +9.2 (4) | +3.4 (6) | −3.0 (4/15) |
| VIX ≥ 26 | +1.9 (11) | Yes | +2.0 (10) | −0.3 (14) | −1.0 (11/15) |
| 1260d rank ≥ 80% + easing 20d | +1.9 (8) | Yes | +8.1 (3) | −0.3 (12) | — |
| VIX ≥ 24 | +1.7 (16) | No | +0.3 (12) | −0.9 (16) | — |
| VIX ≥ 24 + 1260d rank ≥ 80% | +1.7 (15) | Yes | +0.8 (12) | −0.3 (16) | −0.4 (14/15) |
| VIX ≥ 24 + VIX above VIX3M | +1.6 (15) | No | +0.0 (10) | +1.7 (14) | −0.7 (13/14) |
| VIX ≥ 24 + easing 1d | +1.6 (12) | Yes | +0.3 (9) | −2.0 (14) | −0.9 (12/15) |
| 504d rank ≥ 90% | +1.5 (12) | Yes | −2.0 (11) | −2.8 (16) | — |
| 252d rank ≥ 80% + easing 20d | +1.5 (10) | Yes | +2.4 (6) | +1.6 (9) | — |
| VIX ≥ 22 | +1.4 (28) | Yes | +0.3 (17) | −0.9 (19) | — |
| VIX high ≥ 24 | +1.2 (20) | Yes | +0.2 (15) | −1.3 (17) | +0.0 (15/15) |
| 504d rank ≥ 80% + easing 5d | +1.0 (10) | Yes | +1.9 (10) | −5.4 (13) | — |
| VIX traded at 24 and closed below | +1.0 (18) | Yes | +0.2 (15) | −0.7 (21) | — |
| 1260d rank ≥ 80% | +1.0 (19) | Yes | +2.0 (12) | +2.1 (16) | — |
| 1260d rank ≥ 80% + easing 10d | +0.8 (7) | too few | +10.3 (5) | −2.3 (9) | — |
| 504d rank ≥ 80% + easing 10d | +0.6 (7) | too few | +5.3 (7) | −4.2 (10) | — |
| VIX ≥ 24 + 252d rank ≥ 80% + easing 10d | +0.6 (7) | too few | +11.5 (4) | +1.5 (8) | −2.7 (6/15) |
| VIX ≥ 24 + 504d rank ≥ 80% | +0.5 (14) | No | −0.4 (10) | −2.4 (14) | −1.9 (13/15) |
| VIX ≥ 20 | +0.3 (52) | No | +1.9 (27) | −0.0 (19) | — |
| VIX ≥ 20 + 504d rank ≥ 80% | +0.2 (28) | No | +0.8 (18) | −3.4 (16) | — |
| 504d rank ≥ 80% + easing 20d | +0.1 (8) | No | +4.2 (10) | −0.6 (11) | — |
| VIX ≥ 30 | +0.0 (6) | too few | +5.6 (6) | +2.2 (9) | −1.5 (5/15) |
| VIX ≥ 24 + easing 5d | −0.4 (8) | No | +12.0 (5) | −3.5 (10) | −3.4 (8/15) |
| 252d rank ≥ 80% | −0.6 (35) | No | −5.1 (21) | −0.3 (32) | — |
| VIX ≥ 24 + easing 3d | −0.8 (9) | No | +0.6 (6) | −3.3 (11) | −3.4 (9/15) |
| VIX ≥ 24 + 252d rank ≥ 80% | −0.8 (14) | No | −0.5 (11) | −1.1 (16) | −3.1 (13/15) |
| 252d rank ≥ 80% + easing 10d | −0.9 (9) | No | +3.1 (7) | +0.0 (10) | — |
| 504d rank ≥ 80% | −1.1 (18) | No | −4.1 (19) | −4.3 (18) | — |
| 1260d rank ≥ 80% + easing 5d | −1.1 (9) | No | +8.7 (6) | −3.7 (10) | — |
| VIX ≥ 24 + 504d rank ≥ 80% + easing 5d | −1.2 (6) | too few | +12.8 (5) | −4.7 (8) | −4.1 (6/15) |
| VIX ≥ 24 + easing 10d | −1.2 (8) | No | +11.5 (4) | −1.6 (11) | −3.8 (8/15) |
| VIX ≥ 24 + 1260d rank ≥ 80% + easing 5d | −2.2 (7) | too few | +13.9 (4) | −4.9 (10) | −4.4 (7/15) |
| VIX ≥ 24 + 252d rank ≥ 80% + easing 5d | −2.3 (7) | too few | +12.0 (5) | −1.7 (8) | −2.4 (6/15) |
| VIX ≥ 24 + 504d rank ≥ 80% + easing 10d | −2.3 (6) | too few | +12.1 (4) | −2.4 (8) | −4.6 (6/15) |
| 252d rank ≥ 80% + easing 5d | −2.4 (14) | No | +2.2 (8) | −2.4 (14) | — |
| VIX ≥ 24 + 1260d rank ≥ 80% + easing 10d | −2.6 (7) | too few | +11.5 (4) | −2.6 (9) | −4.6 (7/15) |
| VIX ≥ 24 + easing 20d + QQQ breakout | −3.7 (4) | too few | +8.8 (3) | +2.0 (5) | −4.9 (3/15) |

- **None of the 11 that pass repeat it later.** Of those, 0 meet all three conditions in 2020–2026.
- **The pass list depends on the episode definition.** With 21 quiet sessions, 2 signals pass. VIX ≥24 itself goes from +1.7 to −0.9 points.
- **Our 20-day easing reference has 5 training and 4 later episodes here**, too few to judge. Its large spread in the earlier sections comes from counting every signal day. Counting each episode's first signal, it is +2.1 points.
- **Easing on VIX ≥24 disagrees across samples.** In training VIX ≥24 + easing 5d is −0.4 and 10d is −1.2. Later they are +12.0 and +11.5, but on 5 and 4 episodes. That pattern is worth watching and is not evidence.
- **Waiting for another signal inside a VIX ≥24 episode cost money in training for every rule that changed the entry.** It often never fires, which leaves the money in T-bills. The comparison uses a common 127-session horizon. Later, easing 5d and 10d rules are about +0.4 to +2.3 points, over 4 or 5 fired episodes of 12.

### Exits and the funded sleeve on each signal

None of the 252 training combinations of signal and exit (X2, X3a, X4a, X5a, X6, X7) beats holding 63 sessions under the rule. 96 of them could not pass, because their signal has fewer than 8 training episodes. X2 uses each signal's own reset. In the funded sleeve with 7.5% per signal, the Sharpe difference from a static account with the same average exposure runs from −0.019 to +0.015 in training and −0.075 to +0.029 later, and the two periods' rankings are unrelated (correlation −0.13). The best later accounts add about 0.02 to 0.03.

## 13. What we checked and changed

**Confirmed correct:** next-close entry and 63-session hold; training and later split; rank, easing, breakout, term-structure and credit-lag formulas; grid selection; ZIP match; and dashboard calculations, which agree with Python on every preset. We rebuilt eight rules from raw data with separate code and matched the results.

**Corrected in the write-up:**

- The term-structure advantage reverses in training.
- The breadth proxy's training spread came from 3 signal days, not comparable with the 246-day reference.
- Concentration in 2020, the late entry and the chance test were missing or underplayed.
- Waiting for a breakout was reported at only one length.
- The funded controls were run and left out. The advantage over no-tranche disappears when holdings carry forward.
- 1,188 configurations are 1,116 distinct rules.

**Corrected after an implementation review ([IMPLEMENTATION_REVIEW.md](IMPLEMENTATION_REVIEW.md)):**

- The VIX3M signals were compared with an average date from before VIX3M existed. Their training excess falls from +2.1 to +1.6 (above VIX3M) and from +3.0 to +2.5 (at or below). No signal changes between passing and not.
- E6 cancels on calm, as drafted. The uncancelled control E6u was added.
- Cancelled versions of E1, E1v and E3 were added, and profit on the reserve is shown next to timing value.
- Holding 126 sessions is compared directly with selling at 63.
- The bootstrap and the reported Sharpe now share a formula. No figure in this file changes.
- `run_tactical.py` and `run_triggers.py` run without the VIX3M file.
- The 21-quiet-session table carries its own reset label, and the dashboard shows the luck check only beside the episode definition it covers.
- The composite first-tranche sentence in section 11 was backwards.

**Added:** episode-weighted, largest-episode and training columns in the outcome table; composite and no-tranche controls; carried-forward runs; signal frequency and gaps; episode entries and 63-session outcomes; a funded trade list; and tests.

## 14. Open questions on the indicator

1. Which easing lookback: 5, 10 or 20 sessions? Training and later disagree.
2. Is rank useful, or is its later result one regime? It needs a test that the training period does not contradict.
3. Does VIX above VIX3M add anything beyond VIX level, given that the sign flips?
4. Constituent breadth needs point-in-time membership data.
5. All results cover 2008 onward, which has no bear market as long as 2000–2002. Earlier data only warms up the indicators. Pre-2008 outcomes were viewed once and are out of scope, so they are not a fresh holdout. Only new data can confirm a rule.

## 15. Files and reproduction

Everything is in the repo's `vix_entry/` folder.

| Path in `vix_entry/` | Role |
|---|---|
| `research/indicators.py` | daily features and the entry gate |
| `research/analyze_vix.py` | grid, experiments, outcome table, funded runs, dashboard export |
| `research/trades.py` | signal frequency, entries and outcomes by episode |
| `research/summary_tables.py` | prints most tables in sections 3 to 9 |
| `research/tactical.py` | entry and exit rules, episode settlement, selection rule |
| `research/tactical_portfolio.py` | funded sleeve outside the v2 engine |
| `research/run_tactical.py` | runs the tests and writes `tactical_*.csv` |
| `research/run_triggers.py` | every signal as the entry, writes `trigger_*.csv` |
| `research/dashboard.html.in` | dashboard template |
| `research/vix_paths.py` | the study's folders; puts the repo's shared `research/` code on the import path |
| `tests/` | `test_vix_entry.py`, `test_vix_tactical.py`, `test_vix_triggers.py` |
| `results/` | the CSVs. The dashboard, `vix_signal_days.csv` and the two tactical ledgers are rebuilt locally and not in Git |
| `data/` | optional QQQE and credit inputs, not in Git |

The study also uses shared files that stay in place: `data/panel.csv`, `data/raw/vix_daily.csv`, `data/raw/VIX3M_History.csv`, `research/common.py` and `research/strategy.py`.

```sh
python vix_entry/research/run_tactical.py
python vix_entry/research/run_triggers.py
python vix_entry/research/analyze_vix.py
python vix_entry/research/summary_tables.py
python -m pytest -q vix_entry/tests
```

The QQQE and credit inputs are not in Git, so a fresh clone shows those experiments as unavailable until they are downloaded as listed in [README.md](README.md). FRED publishes about three years of the credit series, so those rows will stop being reproducible from a new download.
