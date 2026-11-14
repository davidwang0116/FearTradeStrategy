"""How much edge does each fear / valuation trigger give?

(1) Trading edge  — buy on every trigger day, hold a fixed horizon (252 trading days,
    also 63): mean forward return on trigger days minus mean forward return on ALL days
    of the same sample. Capital use is ignored (every day is an independent purchase).
(2) DCA edge      — daily DCA of 1 unit, 2 units on trigger days (2x / 1x only), run as
    rolling 5-year DCA plans (a new plan starts every month). Each plan is compared with
    spreading the SAME total money evenly over the same 5 years:
      cost advantage = shares bought / shares bought evenly − 1  (= % lower average cost
      = % more terminal wealth), and the money-weighted return (XIRR) difference.
    Rolling 5-year plans remove the cross-decade drift that a single 27-year plan has
    (moving money into the cheap early 2000s would look like 'edge').

Rules
* signal at close t, buy at close t+1;
* parameter grid per indicator is small and fixed in advance (GRID below); the chosen
  parameter maximises the edge subject to >= MIN_EPISODES separate trigger episodes
  (episodes = runs separated by > 21 trading days without a trigger) — so a single
  "VIX all-time high" day can never win;
* significance: circular-shift test — the trigger series is shifted by a random offset
  (keeps its clustering), 1000 times; p = share of shifts with edge >= observed;
* every indicator uses its longest available history; a second column repeats the
  test on the last five years (2021-11-12 → today, MIN_EPISODES_5Y episodes).
Selecting the best of a grid inflates the edge; the p-value is computed for the chosen
parameter only, so read it as optimistic.  Outputs: results/edge_*.csv, figures/fig_edge_*.png
"""
import numpy as np
import pandas as pd

from common import (BLUE, GRID, INK, INK2, MUTED, ORANGE, RES, SEQ5, build_signals, load_panel, plt, savefig)

rng = np.random.default_rng(2026)
H, H2 = 252, 63
MIN_EPISODES, MIN_EPISODES_5Y = 8, 4
FIVE_Y = "2021-11-12"
N_SHIFT = 1000


def episodes(mask):
    idx = np.flatnonzero(mask)
    if len(idx) == 0:
        return 0
    return int(1 + (np.diff(idx) > 21).sum())


def build_indicators(P):
    S = build_signals(P)
    px = P["qqq"]
    r = px.pct_change()
    I = {}
    vix, vxn = P["vix"], P["vxn"].where(P.index >= "2008-01-03")
    d = px.diff()
    g, l_ = d.clip(lower=0).rolling(14).mean(), -d.clip(upper=0).rolling(14).mean()
    rsi = 100 - 100 / (1 + g / l_)
    dd = px / px.rolling(252, min_periods=60).max() - 1
    ma = px / px.rolling(200).mean() - 1
    rv = r.rolling(21).std() * np.sqrt(252) * 100
    comp_pct = S["Composite (dashboard v4)"].expanding(504).rank(pct=True)
    vrp = (vxn - rv)
    vrp_pct = vrp.expanding(504).rank(pct=True)
    fgi = P["fgi"]
    proxy = 100 - S["Price-sentiment proxy (inv.)"]
    spike = vix / vix.rolling(20).mean()
    # name: (series, op, grid, label-format, start)
    I["VIX level"] = (vix, ">=", [20, 25, 30, 35, 40], "VIX ≥ {}")
    I["VIX spike vs 20d avg"] = (spike, ">=", [1.2, 1.3, 1.4, 1.5], "VIX ≥ {}× its 20d mean")
    I["VXN level"] = (vxn, ">=", [25, 30, 35, 40, 45], "VXN ≥ {}")
    I["CNN Fear & Greed"] = (fgi, "<=", [10, 15, 20, 25, 30], "F&G ≤ {}")
    I["QQQ drawdown from 1y high"] = (dd * 100, "<=", [-10, -15, -20, -25, -30], "drawdown ≤ {}%")
    I["QQQ below 200-day MA"] = (ma * 100, "<=", [0, -5, -10, -15], "≥ {}% vs MA200")
    I["RSI(14) oversold"] = (rsi, "<=", [25, 30, 35, 40], "RSI ≤ {}")
    I["Price-sentiment proxy"] = (proxy, "<=", [15, 20, 30, 40], "proxy ≤ {}")
    I["Variance risk premium (pct)"] = (vrp_pct * 100, ">=", [70, 80, 90, 95], "VRP ≥ {}th pct")
    I["Dashboard composite (pct)"] = (comp_pct * 100, ">=", [70, 80, 90, 95], "composite ≥ {}th pct")
    return I


def mask_of(series, op, thr):
    m = series >= thr if op == ">=" else series <= thr
    return m & series.notna()


def trade_edge(mask, fwd, valid):
    m = mask[valid].values
    f = fwd[valid].values
    if m.sum() == 0:
        return np.nan, np.nan
    return f[m].mean() - f.mean(), f[m].mean()


def shift_p(mask, fwd, valid, obs, fn):
    m = mask[valid].values.astype(bool)
    f = fwd[valid].values
    n = len(m)
    cnt = 0
    for _ in range(N_SHIFT):
        k = rng.integers(21, n - 21)
        cnt += fn(np.roll(m, k), f) >= obs
    return (cnt + 1) / (N_SHIFT + 1)


def dca(mask, price_next, valid):
    """shares-per-dollar advantage and XIRR difference, 2x on trigger days."""
    m = mask[valid].values.astype(bool)
    p = price_next[valid].values
    w = np.where(m, 2.0, 1.0)
    shares = (w / p).sum()
    even = (w.sum() / len(w) / p).sum()
    return shares / even - 1, w, p


def xirr_daily(amounts, prices, dates, end_price, end_date):
    """money-weighted annual return of investing amounts[t] at prices[t]."""
    sh = (amounts / prices).sum()
    V = sh * end_price
    t = (end_date - dates).days.values / 365.25
    lo, hi = -0.9, 2.0
    for _ in range(100):
        mid = (lo + hi) / 2
        fv = (amounts * (1 + mid) ** t).sum()
        if fv > V:
            hi = mid
        else:
            lo = mid
    return mid


WIN, STEP = 1260, 21


def rolling_dca(m, p, win=None):
    """m: bool trigger array, p: purchase prices. Returns per-window cost advantage."""
    win = win or WIN
    w = np.where(m, 2.0, 1.0)
    cw, cwp, cip = [np.concatenate([[0], np.cumsum(a)]) for a in (w, w / p, 1 / p)]
    starts = np.arange(0, len(p) - win + 1, STEP)
    e = starts + win
    W, WP, IP = cw[e] - cw[starts], cwp[e] - cwp[starts], cip[e] - cip[starts]
    return WP / (W / win * IP) - 1, starts


def window_xirr(m, p, dates, starts, end_px, win=None):
    """XIRR difference per window, valued at the price on the window's last day."""
    win = win or WIN
    out = []
    for s0 in starts:
        sl = slice(s0, s0 + win)
        w = np.where(m[sl], 2.0, 1.0); pv = p[sl]; d = dates[sl]
        endp, endd = end_px[s0 + win - 1], d[-1]
        out.append(xirr_daily(w, pv, d, endp, endd) - xirr_daily(np.full(win, w.mean()), pv, d, endp, endd))
    return np.array(out)


def evaluate(name, spec, P, px, sample_start, min_ep, fixed_thr=None):
    series, op, grid, fmt = spec
    fwd = px.shift(-(H + 1)) / px.shift(-1) - 1
    fwd2 = px.shift(-(H2 + 1)) / px.shift(-1) - 1
    pnext = px.shift(-1)
    base_valid = series.notna() & (series.index >= sample_start)
    rows = []
    for thr in (grid if fixed_thr is None else [fixed_thr]):
        m = mask_of(series, op, thr)
        v1 = base_valid & fwd.notna()
        ep = episodes(m[v1].values)
        e, mt = trade_edge(m, fwd, v1)
        e2, _ = trade_edge(m, fwd2, base_valid & fwd2.notna())
        vd = base_valid & pnext.notna()
        win = WIN if (fixed_thr is None or vd.sum() >= WIN) else (int(vd.sum()) if vd.sum() >= 750 else 10 ** 9)
        if vd.sum() >= win:
            adv, _ = rolling_dca(m[vd].values, pnext[vd].values, win)
            dmean, dwin = adv.mean(), (adv > 0).mean()
        else:
            dmean = dwin = np.nan
        rows.append(dict(indicator=name, param=fmt.format(thr), thr=thr, episodes=ep,
                         trig_days=int(m[v1].sum()), trig_share=float(m[vd].mean()),
                         edge_252=e, mean_trig_252=mt, edge_63=e2, dca_adv=dmean, dca_win=dwin,
                         n_windows=int((vd.sum() - win) // STEP + 1) if vd.sum() >= win else 0, win=win))
    G = pd.DataFrame(rows)
    ok = G[G.episodes >= min_ep] if fixed_thr is None else G
    if ok.empty or ok.edge_252.isna().all():
        return G, None, None
    bt = ok.loc[ok.edge_252.idxmax()].copy()
    v1 = base_valid & fwd.notna()
    mt = mask_of(series, op, bt.thr)
    bt["mean_all_252"] = fwd[v1].mean()
    bt["p_shift"] = shift_p(mt, fwd, v1, bt.edge_252, lambda m, f: f[m].mean() - f.mean() if m.any() else -9) \
        if bt.trig_days > 0 else np.nan
    bt["start"] = series[base_valid].index[0].date()
    bt["end"] = fwd[v1].index[-1].date()
    bd = None
    okd = ok.dropna(subset=["dca_adv"])
    if not okd.empty:
        bd = okd.loc[okd.dca_adv.idxmax()].copy()
        vd = base_valid & pnext.notna()
        md = mask_of(series, op, bd.thr)[vd].values
        pv = pnext[vd].values
        win = int(bd.win)
        adv, starts = rolling_dca(md, pv, win)

        def stat(mm, f_unused):
            a_, _ = rolling_dca(mm, pv, win)
            return a_.mean()
        bd["p_shift"] = shift_p(pd.Series(md, index=pnext[vd].index), pnext, vd, bd.dca_adv, stat)
        xd = window_xirr(md, pv, pnext[vd].index, starts, px[vd].values, win)
        bd["xirr_diff"], bd["xirr_win"] = xd.mean(), (xd > 0).mean()
        bd["start"] = pnext[vd].index[0].date()
        bd["end"] = pnext[vd].index[-1].date()
    return G, bt, bd


def cape_study():
    """Monthly S&P 500 (Shiller, real total return 1881-2023): CAPE expanding-percentile trigger.
    Trading edge = next-12-month return; DCA = rolling 60-month plans, 2x when triggered."""
    from common import ROOT
    sh = pd.read_csv(ROOT / "data/raw/shiller_sp500_monthly.csv", parse_dates=["Date"]).set_index("Date")
    sh = sh[sh["PE10"] > 0]
    rp = sh["Real Price"]
    tr = (1 + (rp.pct_change() + sh["Real Dividend"] / 12 / rp.shift())).cumprod()
    pct = sh["PE10"].expanding(120).rank(pct=True) * 100
    fwd = tr.shift(-13) / tr.shift(-1) - 1
    pnext = tr.shift(-1)
    rows = []
    for thr in [10, 20, 30, 40]:
        m = (pct <= thr) & pct.notna()
        v = pct.notna() & fwd.notna()
        idx = np.flatnonzero(m[v].values)
        ep = 0 if len(idx) == 0 else int(1 + (np.diff(idx) > 1).sum())
        e = fwd[v][m[v]].mean() - fwd[v].mean()
        vd = pct.notna() & pnext.notna()
        mm, pv = m[vd].values, pnext[vd].values
        w = np.where(mm, 2.0, 1.0)
        cw, cwp, cip = [np.concatenate([[0], np.cumsum(a)]) for a in (w, w / pv, 1 / pv)]
        st = np.arange(0, len(pv) - 60 + 1); en = st + 60
        adv = (cwp[en] - cwp[st]) / ((cw[en] - cw[st]) / 60 * (cip[en] - cip[st])) - 1
        # shift test for trading edge
        f = fwd[v].values; mv = m[v].values; cnt = 0
        for _ in range(N_SHIFT):
            k = rng.integers(12, len(mv) - 12); r_ = np.roll(mv, k)
            cnt += (f[r_].mean() - f.mean()) >= e
        rows.append(dict(indicator="Shiller CAPE (S&P 500, monthly)", param=f"CAPE ≤ {thr}th pct", thr=thr,
                         episodes=ep, trig_share=float(m[vd].mean()), edge_12m=e, p_shift=(cnt + 1) / (N_SHIFT + 1),
                         dca_adv=adv.mean(), dca_win=(adv > 0).mean(), start=pct[v].index[0].date(),
                         end=fwd[v].index[-1].date()))
    return pd.DataFrame(rows)


def main():
    P = load_panel()
    px = P["qqq"]
    I = build_indicators(P)
    allg, T, D = [], [], []
    for name, spec in I.items():
        G, bt, bd = evaluate(name, spec, P, px, "1999-01-01", MIN_EPISODES)
        G["sample"] = "full"; allg.append(G)
        T.append(dict(bt, sample="full")); D.append(dict(bd, sample="full"))
        # last five years with the SAME parameter (no re-optimisation)
        _, bt5, _ = evaluate(name, spec, P, px, FIVE_Y, 0, fixed_thr=bt.thr)
        T.append(dict(bt5, sample="5y") if bt5 is not None else dict(indicator=name, sample="5y"))
        _, _, bd5 = evaluate(name, spec, P, px, "2021-11-09", 0, fixed_thr=bd.thr)   # exactly one 5y plan
        D.append(dict(bd5, sample="5y") if bd5 is not None else dict(indicator=name, sample="5y"))
    pd.concat(allg).to_csv(RES / "edge_grid.csv", index=False)
    T, D = pd.DataFrame(T), pd.DataFrame(D)
    T.to_csv(RES / "edge_trading.csv", index=False)
    D.to_csv(RES / "edge_dca.csv", index=False)
    cape = cape_study()
    cape.to_csv(RES / "edge_cape.csv", index=False)
    pd.set_option("display.width", 250)
    cols = ["indicator", "sample", "param", "episodes", "trig_days", "edge_252", "mean_trig_252", "mean_all_252", "edge_63", "p_shift", "start", "end"]
    print(T[cols].round(3).to_string())
    cols = ["indicator", "sample", "param", "episodes", "trig_share", "n_windows", "dca_adv", "dca_win", "xirr_diff", "xirr_win", "p_shift", "start", "end"]
    print(D[cols].round(4).to_string())
    print(cape.round(4).to_string())


if __name__ == "__main__":
    main()
