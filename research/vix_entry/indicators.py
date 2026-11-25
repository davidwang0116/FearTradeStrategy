"""Daily features and availability for VIX entry research."""

import json
from pathlib import Path

import pandas as pd


RANK_WINDOWS = (252, 504, 1260)
RANK_CUTOFFS = (0, *range(50, 100, 5))
FLOORS = (0, 20, 22, 24, 26, 30)
EASING_DAYS = (0, 1, 3, 5, 10, 20)
BREAKOUT_DAYS = (3, 5, 10)

FILTERS = {
    "breakout_3": "QQQ above its previous 3 closes",
    "breakout_5": "QQQ above its previous 5 closes",
    "breakout_10": "QQQ above its previous 10 closes",
    "term_inverted": "VIX above VIX3M",
    "term_flat": "VIX at or below VIX3M",
    "breadth_up": "Nasdaq-100 breadth rising over 5 sessions",
    "breadth_proxy_up": "QQQE / QQQ rising over 5 sessions",
    "credit_widening": "High-yield spread widening over 5 sessions",
    "credit_stable": "High-yield spread flat or narrowing over 5 sessions",
    "intraday_fade": "VIX traded at 24 or higher and closed below 24",
}


def read_daily(path, date_column, value_column, *, date_format="%Y-%m-%d"):
    data = pd.read_csv(path, usecols=[date_column, value_column], na_values=["."])
    dates = pd.to_datetime(data[date_column], format=date_format)
    return pd.Series(data[value_column].astype(float).array, index=dates).sort_index()


def read_qqqe(path):
    result = json.loads(path.read_text())["chart"]["result"][0]
    if result["meta"]["symbol"] != "QQQE" or result["meta"]["dataGranularity"] != "1d":
        raise ValueError("QQQE input must be a daily Yahoo Finance chart export.")
    dates = pd.to_datetime(result["timestamp"], unit="s", utc=True)
    dates = dates.tz_convert("America/New_York").tz_localize(None).normalize()
    return pd.Series(result["indicators"]["adjclose"][0]["adjclose"], index=dates, dtype=float)


def constituent_breadth(path, sessions):
    """Fraction above MA20 among members with complete trailing close histories."""
    rows = pd.read_csv(path, dtype={"security": str}, parse_dates=["date"])
    if rows["security"].isna().any() or not rows["member"].isin([0, 1]).all():
        raise ValueError("Constituents need a stable security identifier and member values of 0 or 1.")
    prices = rows.pivot(index="date", columns="security", values="close").reindex(sessions)
    member = rows.pivot(index="date", columns="security", values="member").reindex(sessions).eq(1)
    ma = prices.rolling(20).mean()
    covered = member & ma.notna()
    coverage = covered.sum(axis=1) / member.sum(axis=1)
    fraction = (prices.gt(ma) & covered).sum(axis=1) / covered.sum(axis=1)
    return fraction, coverage


def term_spread(vix, inputs):
    """VIX minus VIX3M. All missing when the optional VIX3M file is absent."""
    path = inputs / "vix3m.csv"
    if not path.exists():
        return pd.Series(float("nan"), index=vix.index)
    return vix - read_daily(path, "DATE", "CLOSE", date_format="%m/%d/%Y").reindex(vix.index)


def build_features(panel, inputs, vix_ohlc, constituents):
    features = panel[["vix"]].rename(columns={"vix": "close"}).copy()
    qqq = panel["qqq"]
    features["high"] = read_daily(vix_ohlc, "DATE", "HIGH").reindex(panel.index)
    for window in RANK_WINDOWS:
        features[f"rank_{window}"] = features["close"].rolling(window).rank(pct=True)
    for days in EASING_DAYS[1:]:
        features[f"ease_{days}"] = features["close"].diff(days)
    for days in BREAKOUT_DAYS:
        prior_high = qqq.shift().rolling(days).max()
        features[f"breakout_{days}"] = qqq.gt(prior_high).where(prior_high.notna()).astype("boolean")

    term = term_spread(features["close"], inputs)
    features["term_inverted"] = term.gt(0).where(term.notna()).astype("boolean")
    features["term_flat"] = term.le(0).where(term.notna()).astype("boolean")

    qqqe_path = inputs / "qqqe.json"
    relative = (read_qqqe(qqqe_path).reindex(panel.index) / qqq).diff(5) if qqqe_path.exists() else (
        pd.Series(float("nan"), index=panel.index))
    features["breadth_proxy_up"] = relative.gt(0).where(relative.notna()).astype("boolean")
    if constituents is not None:
        breadth, coverage = constituent_breadth(constituents, panel.index)
        # Readings based on different coverage during a data gap can create spurious changes.
        breadth = breadth.where(coverage.ge(.95))
        change = breadth.diff(5)
        features["breadth_up"] = change.gt(0).where(change.notna()).astype("boolean")
        print(f"Constituent breadth: {breadth.count():,} sessions with at least 95% MA coverage.")
    else:
        features["breadth_up"] = pd.Series(pd.NA, index=panel.index, dtype="boolean")

    credit_path = inputs / "hy_oas.csv"
    # Daily FRED closing observations are assumed available one QQQ session later.
    # Exact-date join leaves missing observations missing.
    credit = (read_daily(credit_path, "observation_date", "BAMLH0A0HYM2")
              .reindex(panel.index).shift().diff(5)) if credit_path.exists() else (
                  pd.Series(float("nan"), index=panel.index))
    features["credit_widening"] = credit.gt(0).where(credit.notna()).astype("boolean")
    features["credit_stable"] = credit.le(0).where(credit.notna()).astype("boolean")
    features["intraday_fade"] = (features["high"].ge(24) & features["close"].lt(24)).where(
        features[["high", "close"]].notna().all(axis=1)).astype("boolean")
    return features


def entry_mask(features, *, floor=0, rank=0, window=504, easing=0, level="close", confirmation="off"):
    """Return a nullable daily gate so studies can match comparisons on coverage."""
    signal = features[level].ge(floor).where(features[level].notna()).astype("boolean")
    if rank:
        values = features[f"rank_{window}"]
        signal = (signal & values.ge(rank / 100)).where(signal.notna() & values.notna())
    if easing:
        values = features[f"ease_{easing}"]
        signal = (signal & values.lt(0)).where(signal.notna() & values.notna())
    if confirmation != "off":
        values = features[confirmation]
        signal = (signal & values).where(signal.notna() & values.notna())
    return signal
