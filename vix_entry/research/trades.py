"""Signal frequency, and entries and 63-session outcomes by episode.

Every trade enters at the next QQQ close after a signal. All lengths are trading sessions.
"""

import numpy as np
import pandas as pd

QUIET = 21
HOLD = 63
PERIODS = ("training", "later", "all")

def in_period(rows, period):
    return rows if period == "all" else rows[rows["period"].eq(period)]


def episode_table(hits):
    """One row per episode in sorted session numbers: first and last signal, and signal count."""
    hits = np.asarray(hits)
    if not len(hits):
        return pd.DataFrame(columns=["start", "end", "days"], dtype=int)
    number = np.r_[True, np.diff(hits) > QUIET].cumsum()
    groups = pd.Series(hits).groupby(number)
    return pd.DataFrame({"start": groups.first(), "end": groups.last(), "days": groups.size()}).reset_index(drop=True)


def spaced_entries(hits, hold=HOLD):
    """Count signals that could be bought if each holding period must finish first."""
    count, free_at = 0, -np.inf
    for session in hits:
        if session >= free_at:
            count, free_at = count + 1, session + hold
    return count


def frequency(signals, eligible):
    """How often a rule fires inside one sample, and how long the quiet stretches are."""
    if not len(eligible):
        return None
    years = len(eligible) / 252
    hits = signals["session"].to_numpy()
    episodes = episode_table(hits)
    gaps = episodes["start"].diff().dropna().to_numpy()
    edges = np.r_[eligible["session"].iloc[0] - 1, hits, eligible["session"].iloc[-1] + 1]
    calendar = set(eligible.index.year)
    stat = lambda values, function: float(function(values)) if len(values) else None
    return dict(
        years=years, signal_days=len(hits), share_of_days=len(hits) / len(eligible),
        signal_days_per_year=len(hits) / years, episodes=len(episodes), episodes_per_year=len(episodes) / years,
        spaced_63_session_entries=spaced_entries(hits),
        median_signal_days_per_episode=stat(episodes["days"], np.median),
        largest_episode_signal_days=stat(episodes["days"], np.max),
        median_episode_span=stat(episodes["end"] - episodes["start"] + 1, np.median),
        median_gap=stat(gaps, np.median), shortest_gap=stat(gaps, np.min), longest_gap=stat(gaps, np.max),
        gaps_of_63_or_more=stat(gaps >= 63, np.mean), gaps_of_90_or_more=stat(gaps >= 90, np.mean),
        longest_stretch_without_signal=int(np.diff(edges).max() - 1),
        calendar_years_with_signal=len(set(signals.index.year)), calendar_years=len(calendar),
        last_signal=signals.index[-1].strftime("%Y-%m-%d") if len(signals) else None,
    )


def trade_path(close, entry, leave):
    """Return the trade's return, worst and best close versus entry, and when the low occurred."""
    path = close[entry:leave + 1] / close[entry] - 1
    low = int(path.argmin())
    recovered = np.flatnonzero(path[low:] >= 0)
    return dict(
        trade_return=float(path[-1]), worst=float(path.min()), best=float(path.max()), sessions_to_low=low,
        sessions_to_recover=low + int(recovered[0]) if len(recovered) else None,
    )


def rule_signals(gate, frame):
    """Eligible dates and signals for one rule on the frame's dates, using the rule's own data coverage."""
    gate = gate.reindex(frame.index)
    eligible = frame.loc[gate.notna()]
    return eligible, eligible.loc[gate.loc[eligible.index].astype(bool)]


def signal_frequency(rules, frame):
    rows = []
    for rule, gate in rules.items():
        eligible, signals = rule_signals(gate, frame)
        for period in PERIODS:
            stats = frequency(in_period(signals, period), in_period(eligible, period))
            if stats:
                rows.append(dict(rule=rule, period=period, **stats))
    return rows


def episode_entries(rules, panel, frame):
    """Each episode's first entry, its 63-session exit, and what happened in between."""
    close, vix = panel["qqq"].to_numpy(), panel["vix"]
    high = panel["qqq"].rolling(252).max()
    fear = np.flatnonzero(panel["vix"].ge(24).to_numpy())
    fear_starts = episode_table(fear)["start"].to_numpy()
    rows = []
    for rule, gate in rules.items():
        _, signals = rule_signals(gate, frame)
        previous = None
        # Sessions index the full panel, so they also locate prices.
        for start, end, days in episode_table(signals["session"].to_numpy()).itertuples(index=False):
            signal = panel.index[start]
            row = frame.loc[signal]
            began = fear_starts[fear_starts <= start]
            inside = signals.loc[panel.index[start]:panel.index[end], "qqq_return"]
            entry, leave = start + 1, start + 1 + HOLD
            rows.append(dict(
                rule=rule, period=row["period"], signal_date=signal.strftime("%Y-%m-%d"),
                last_signal_date=panel.index[end].strftime("%Y-%m-%d"), signal_days=int(days),
                sessions_since_previous_start=None if previous is None else int(start - previous),
                sessions_after_first_vix_24=int(start - began[-1]) if len(began) and vix.iloc[start] >= 24 else None,
                vix_at_signal=float(vix.iloc[start]), qqq_below_252_high=float(close[start] / high.iloc[start] - 1),
                entry_date=panel.index[entry].strftime("%Y-%m-%d"), entry_price=float(close[entry]),
                exit_date=panel.index[leave].strftime("%Y-%m-%d"), exit_price=float(close[leave]),
                vix_at_exit=float(vix.iloc[leave]) if pd.notna(vix.iloc[leave]) else None,
                **trade_path(close, entry, leave), mean_return_all_signal_days=float(inside.mean()),
            ))
            previous = start
    return rows
