"""Composite fear score — QuantConnect-safe port of nasdaq-mood-dashboard v4.

Pure numpy/pandas/scipy so it runs unchanged in LEAN (algorithm or research)
and locally. `tests/test_signals_parity.py` checks it against the dashboard's
own scoring.score_frame to 1e-6.

Scope: VXN + adaptive drawdown + slow price-sentiment proxy. CNN Fear & Greed
and forward-P/E valuation are left as optional inputs (fgi=, val_score=) because
neither has point-in-time history on QC yet — see qc/README.md, TODO-3/TODO-4.
Higher score = more fear / cheaper.
"""
import math
from io import StringIO

import numpy as np
import pandas as pd
from scipy.interpolate import PchipInterpolator

# ---- parameters (copied from nasdaq-mood-dashboard/config.json, score_version 4) ----
W_FEAR, W_DD, W_VAL = 0.30, 0.35, 0.35
SPLIT_VXN, SPLIT_SENT = 0.5, 0.5
MIX_FGI = 0.7
VXN_CENTER, VXN_WIDTH, VXN_PCT_WIN, VXN_PCT_MIN, VXN_PCT_SHARE = 24.0, 4.0, 504, 126, 0.5
DD_LOOKBACK, DD_VOL_DAYS, DD_HORIZON, DD_VOL_FLOOR, DD_K = 252, 60, 63, 10.0, 0.6
PROXY = dict(trend_days=200, rsi_days=21, vol_short=40, vol_long=252,
             w_trend=0.4, w_rsi=0.3, w_vol=0.3,
             trend=[(-20, 0), (-10, 20), (0, 50), (10, 75), (20, 100)],
             rsi=[(20, 0), (30, 15), (50, 50), (70, 85), (80, 100)],
             vol_ratio=[(0.5, 100), (0.75, 80), (1.0, 50), (1.35, 20), (2.0, 0)])
GREED_TO_FEAR = [(0, 100), (25, 80), (40, 60), (55, 40), (75, 20), (100, 0)]
_pchip = PchipInterpolator([a for a, _ in GREED_TO_FEAR], [b for _, b in GREED_TO_FEAR])


def _lin(x, anchors):
    xs, ys = zip(*anchors)
    return pd.Series(np.interp(x, xs, ys), index=x.index).where(x.notna())


def _greed_to_fear(x):
    v = np.clip(np.asarray(x, dtype=float), 0, 100)
    return _pchip(v)


def _pct_rank(s, win, minp):
    return s.rolling(win, min_periods=minp).apply(lambda a: float((a <= a[-1]).mean()), raw=True)


def price_proxy(close):
    """0-100 greed-scale proxy: 40% trend vs MA200, 30% RSI21, 30% vol40/vol252."""
    r = close.pct_change()
    trend = (close / close.rolling(PROXY["trend_days"], min_periods=PROXY["trend_days"]).mean() - 1) * 100
    d = close.diff()
    n = PROXY["rsi_days"]
    g = d.clip(lower=0).rolling(n, min_periods=n).mean()
    l_ = -d.clip(upper=0).rolling(n, min_periods=n).mean()
    rsi = 100 - 100 / (1 + g / l_.replace(0, np.nan))
    rsi = rsi.mask((l_ == 0) & (g > 0), 100.0).mask((l_ == 0) & (g == 0), 50.0)
    vr = r.rolling(PROXY["vol_short"], min_periods=PROXY["vol_short"]).std() / \
        r.rolling(PROXY["vol_long"], min_periods=PROXY["vol_long"]).std().replace(0, np.nan)
    return (PROXY["w_trend"] * _lin(trend, PROXY["trend"]) + PROXY["w_rsi"] * _lin(rsi, PROXY["rsi"])
            + PROXY["w_vol"] * _lin(vr, PROXY["vol_ratio"]))


def composite_frame(close, vxn, fgi=None, val_score=None):
    """Daily frame of sub-scores and the composite on close's calendar."""
    close = close.astype(float).dropna()
    idx = close.index
    v = vxn.astype(float).dropna()
    v = v[~v.index.duplicated(keep="last")]
    vpct = _pct_rank(v, VXN_PCT_WIN, VXN_PCT_MIN).reindex(idx).ffill(limit=3)
    vx = v.reindex(idx).ffill(limit=3)
    level = 100 / (1 + np.exp(-(vx - VXN_CENTER) / VXN_WIDTH))
    s_vxn = level.where(vpct.isna(), (1 - VXN_PCT_SHARE) * level + VXN_PCT_SHARE * 100 * vpct)

    peak = close.rolling(DD_LOOKBACK, min_periods=60).max()
    dd = ((close / peak - 1) * 100).clip(upper=0)
    vol = close.pct_change().rolling(DD_VOL_DAYS, min_periods=DD_VOL_DAYS).std() * math.sqrt(252) * 100
    sig_h = np.maximum(vol, DD_VOL_FLOOR) * math.sqrt(DD_HORIZON / 252)
    s_dd = 100 * (1 - np.exp(-(-dd) / sig_h / DD_K))

    proxy = price_proxy(close)
    s_proxy = pd.Series(_greed_to_fear(proxy.fillna(50)), index=idx).where(proxy.notna())
    if fgi is not None:
        f = fgi.reindex(idx).ffill(limit=5)
        s_fgi = pd.Series(_greed_to_fear(f.fillna(50)), index=idx)
        s_sent = s_proxy.where(f.isna(), MIX_FGI * s_fgi + (1 - MIX_FGI) * s_proxy)
    else:
        s_sent = s_proxy

    fear = SPLIT_VXN * s_vxn + SPLIT_SENT * s_sent
    num = W_FEAR * fear + W_DD * s_dd
    den = W_FEAR + W_DD
    if val_score is not None:
        vs = val_score.reindex(idx).ffill(limit=3)
        num = num + (W_VAL * vs).fillna(0)
        den = den + W_VAL * vs.notna()
    return pd.DataFrame({"close": close, "s_vxn": s_vxn, "s_dd": s_dd, "s_sent": s_sent,
                         "fear": fear, "composite": num / den, "dd": dd, "vol": vol})


def expanding_pct(series, min_periods=504):
    """Causal percentile of each value within its own history (0-1)."""
    return series.expanding(min_periods).rank(pct=True)


# ---- seeding the percentile history in QC (research ranks against every composite value since 2000-03-08) ----
SEED_FROM = "1999-03-10"              # first QQQ date in data/panel.csv
SEED_LATEST_START = "2001-06-30"      # a seed that starts later than this is too short to match research
VIX_SEED_URL = ("https://raw.githubusercontent.com/davidwang0116/FearTradeStrategy/"
                "613318cfd290c757b84b4e8ccbdb2bc0e1e2208b/data/raw/vix_daily.csv")
# QC's VXN starts 2008-01-03. data/build_dataset.py back-fills earlier days as VIX x the 2008-2012 median VXN/VIX
# ratio; QC must do the same or its early composites, and so every percentile, differ from research.
VXN_VIX_RATIO = 1.055526132572263


def backfill_vxn(vxn, vix):
    """VXN closes, with days before the first VXN close filled as VIX x VXN_VIX_RATIO (as in data/build_dataset.py)."""
    vxn, vix = vxn.dropna(), vix.dropna()
    if not len(vix):
        return vxn
    pre = vix if not len(vxn) else vix[vix.index < vxn.index[0]]
    return pd.concat([pre * VXN_VIX_RATIO, vxn]).sort_index()


def extend_vix_history(vix, csv_text, first_price, before):
    """Prepend the pinned panel input only where QC predates its first VIX bar."""
    published = pd.read_csv(StringIO(csv_text), usecols=["DATE", "CLOSE"], parse_dates=["DATE"])
    closes = published.set_index("DATE")["CLOSE"].sort_index()
    cutoff = min(before, vix.index[0]) if len(vix) else before
    earlier = closes.loc[(closes.index >= first_price) & (closes.index < cutoff)]
    return pd.concat([earlier, vix])


def pct_of(hist, x, min_periods=504):
    """expanding_pct for one new value: average rank of x among hist + [x], NaN with fewer than min_periods values."""
    h = np.asarray(hist, dtype=float)
    if len(h) + 1 < min_periods or x != x:
        return float("nan")
    return float(((h < x).sum() + ((h == x).sum() + 2) / 2) / (len(h) + 1))


def close_series(hist, sym, *, midnight=False):
    """Daily close series (normalised dates, no duplicates) from a QC history frame indexed by (symbol, time)."""
    if hist is None or hist.empty:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    s = hist.loc[sym]["close"].astype(float).dropna()
    ends = pd.to_datetime(s.index)
    sessions = ends.normalize()
    if midnight:
        # LEAN History indexes bars by EndTime. At midnight the bar belongs to the prior session.
        sessions = sessions.where(ends.hour >= 8, sessions - pd.Timedelta(days=1))
    s.index = sessions
    return s[~s.index.duplicated(keep="last")].sort_index()


def seed_composite(close, vxn, allow_short=False):
    """Composite history to rank against. Raises if it starts after SEED_LATEST_START (unless allow_short)."""
    comp = composite_frame(close, vxn)["composite"].dropna() if len(close) and len(vxn) else pd.Series(dtype=float)
    first = comp.index[0] if len(comp) else None
    if not allow_short and (first is None or first > pd.Timestamp(SEED_LATEST_START)):
        raise ValueError(f"composite history starts {first}, after {SEED_LATEST_START}: percentiles would not match "
                         "research. Check QQQ/VXN history depth, or set allow_short_seed=1 to run anyway.")
    return comp
