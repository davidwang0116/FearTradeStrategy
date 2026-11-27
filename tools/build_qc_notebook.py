"""Generate the QC Research notebooks (clean, output-free): qc/research_new_indicators.ipynb and qc/options_quote_audit.ipynb."""
import nbformat as nbf
from pathlib import Path

cells = []
md = lambda s: cells.append(nbf.v4.new_markdown_cell(s))
code = lambda s: cells.append(nbf.v4.new_code_cell(s))

md("""# Sentiment & valuation indicators on QC data — IC / quintile / event study
Upload this notebook **and `signals.py`** to the same QC project. Run top to bottom.
Every indicator is oriented so **higher = more fear / cheaper**, scored against QQQ forward
returns bought at the **t+1 close**, with a 63-day block bootstrap for the IC (returns overlap).
Section 1 is a data probe: read the printed start/end dates before trusting anything below.""")
code("""from QuantConnect.Research import QuantBook
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from signals import composite_frame, expanding_pct
qb = QuantBook()
START, END = datetime(1999, 1, 1), datetime.now()
HORIZONS = [21, 63, 126, 252]
rng = np.random.default_rng(585)""")
md("## 1. Probe — what data does QC actually have?")
code("""def eq(t, norm=DataNormalizationMode.TOTAL_RETURN):
    s = qb.add_equity(t, Resolution.DAILY, data_normalization_mode=norm).symbol
    h = qb.history(s, START, END, Resolution.DAILY)
    return h.loc[s]["close"] if not h.empty else pd.Series(dtype=float)

def idx(t):
    try:
        s = qb.add_index(t, Resolution.DAILY).symbol
        h = qb.history(s, START, END, Resolution.DAILY)
        return h.loc[s]["close"] if not h.empty else pd.Series(dtype=float)
    except Exception as e:
        print(t, "failed:", e); return pd.Series(dtype=float)

def fred(code_):
    # TODO-1: FRED dropped pre-2023 history for ICE BofA series in Apr 2026 — check the start date!
    try:
        s = qb.add_data(Fred, code_, Resolution.DAILY).symbol
        h = qb.history(s, START, END, Resolution.DAILY)
        return h.loc[s]["value"] if not h.empty else pd.Series(dtype=float)
    except Exception as e:
        print(code_, "failed:", e); return pd.Series(dtype=float)

D = {}
for t in ["QQQ", "SPY", "QLD", "TQQQ", "TLT", "IEF", "GLD", "HYG", "BIL"]:
    D[t] = eq(t)
for t in ["VIX", "VXN", "VIX9D", "VIX3M", "VIX6M", "VVIX", "SKEW"]:
    D["^" + t] = idx(t)
for c in ["BAMLH0A0HYM2", "BAMLC0A0CM", "DFII10", "T10Y2Y", "T10Y3M", "NFCI", "WALCL", "RRPONTSYD", "WTREGEN"]:
    D[c] = fred(c)
for k, v in D.items():
    v.index = pd.to_datetime(v.index).tz_localize(None).normalize() if len(v) else v.index
    print(f"{k:14s} {v.index.min() if len(v) else '-'} -> {v.index.max() if len(v) else '-'}  n={len(v)}")""")
md("""## 2. Object Store uploads (data QC does not have)
Upload from your laptop with `lean cloud object-store set <key> <file>`; columns `date,value`.
* `aaii.csv` — bull−bear spread (AAII members' spreadsheet; **lag by 1 day**: published Thursday)
* `putcall.csv` — CBOE total / equity put-call ratio
* `cnn_fgi.csv` — CNN Fear & Greed (2011+; timestamps are 00:00 UTC — **shift +1 day**, see brief §3)
* `fwd_pe_pit.csv` — point-in-time forward P/E snapshots (TODO-4)""")
code("""def ostore(key):
    if not qb.object_store.contains_key(key):
        print("missing", key); return pd.Series(dtype=float)
    df = pd.read_csv(qb.object_store.get_file_path(key), parse_dates=["date"]).set_index("date")["value"]
    return df.sort_index()
for k in ["aaii.csv", "putcall.csv", "cnn_fgi.csv", "fwd_pe_pit.csv"]:
    D[k] = ostore(k)""")
md("## 3. Build indicators (higher = more fear / cheaper)")
code("""px = D["QQQ"]
rv21 = px.pct_change().rolling(21).std() * np.sqrt(252) * 100
X = pd.DataFrame(index=px.index)
X["composite_v4"] = composite_frame(px, D["^VXN"])["composite"]
X["vix"] = D["^VIX"].reindex(X.index)
X["vix_term_inv"] = (D["^VIX"] / D["^VIX3M"]).reindex(X.index)          # >1 = backwardation
X["vix9d_vix"] = (D["^VIX9D"] / D["^VIX"]).reindex(X.index)
X["vvix"] = D["^VVIX"].reindex(X.index)
X["vxn_minus_vix"] = (D["^VXN"] - D["^VIX"]).reindex(X.index)
X["vrp"] = (D["^VXN"].reindex(X.index) ** 2 - rv21 ** 2)
X["hy_oas"] = D["BAMLH0A0HYM2"].reindex(X.index).ffill(limit=5)
X["hy_oas_chg63"] = X["hy_oas"].diff(63)
X["real10y_inv"] = -D["DFII10"].reindex(X.index).ffill(limit=5)        # lower real yield = easier
X["nfci"] = D["NFCI"].reindex(X.index).ffill(limit=10)
X["aaii_bear_minus_bull"] = -D["aaii.csv"].reindex(X.index).ffill(limit=7).shift(1)
X["putcall"] = D["putcall.csv"].reindex(X.index).ffill(limit=3)
X["cnn_fgi_inv"] = 100 - D["cnn_fgi.csv"].shift(1, freq="D").reindex(X.index).ffill(limit=3)
X["breadth_proxy_inv"] = -(eq("QQQE") / px).pct_change(63).reindex(X.index)   # equal- vs cap-weight NDX
X = X.dropna(axis=1, how="all")
X.describe().T""")
md("## 4. IC with block bootstrap + quintiles, by sub-period")
code("""def fwd(px, h): return px.shift(-(h + 1)) / px.shift(-1) - 1
F = {h: fwd(px, h) for h in HORIZONS}

def block_ic(x, y, block=63, n=500):
    d = pd.concat([x, y], axis=1).dropna().values
    T = len(d)
    if T < 300: return np.nan, np.nan, np.nan, T
    ic = spearmanr(d[:, 0], d[:, 1]).statistic
    nb = int(np.ceil(T / block)); bs = []
    for _ in range(n):
        st = rng.integers(0, T - block, nb)
        ii = (st[:, None] + np.arange(block)).ravel()[:T]
        bs.append(spearmanr(d[ii, 0], d[ii, 1]).statistic)
    return ic, *np.percentile(bs, [5, 95]), T

rows = []
for sample, a, b in [("all", "1999", "2026"), ("2008-19", "2008", "2019"), ("2020-26", "2020", "2026")]:
    for c in X.columns:
        for h in HORIZONS:
            ic, lo, hi, T = block_ic(X[c].loc[a:b], F[h])
            rows.append(dict(sample=sample, signal=c, h=h, ic=ic, lo=lo, hi=hi, n=T))
IC = pd.DataFrame(rows)
IC.pivot_table(index=["signal"], columns=["sample", "h"], values="ic").round(3)""")
code("""def quintiles(c, h=63, a="2008"):
    d = pd.concat([X[c], F[h]], axis=1, keys=["x", "y"]).loc[a:].dropna()
    d["q"] = pd.qcut(d.x.rank(method="first"), 5, labels=[1, 2, 3, 4, 5])
    return d.groupby("q", observed=True).y.agg(["mean", "count", lambda v: (v > 0).mean()])
for c in X.columns:
    print(c); print(quintiles(c).round(4))""")
md("""## 5. Correlation with the existing composite (is the new signal *incremental*?)
A new indicator is worth adding only if its IC survives after controlling for `composite_v4`.""")
code("""import statsmodels.api as sm
out = []
for c in X.columns.drop("composite_v4"):
    d = pd.concat([X["composite_v4"].rank(pct=True), X[c].rank(pct=True), F[63]], axis=1).dropna()
    d.columns = ["base", "new", "y"]
    m = sm.OLS(d.y, sm.add_constant(d[["base", "new"]])).fit(cov_type="HAC", cov_kwds={"maxlags": 63})
    out.append(dict(signal=c, corr_with_base=d.base.corr(d.new), t_new=m.tvalues["new"], n=len(d)))
pd.DataFrame(out).sort_values("t_new", ascending=False).round(3)""")
md("## 6. Save summary (download the ZIP — raw data cannot leave QC)")
code("""IC.to_csv("ic_new_indicators.csv", index=False)
qb.object_store.save("results/ic_new_indicators.csv", IC.to_csv(index=False))
print("saved")""")

nb = nbf.v4.new_notebook(cells=cells, metadata={"kernelspec": {"name": "python3", "display_name": "Python 3"}})
out = Path(__file__).resolve().parents[1] / "qc" / "research_new_indicators.ipynb"
nbf.write(nb, out)
print("wrote", out)


# =====================================================================================================
# qc/options_quote_audit.ipynb — Stage 1 of the options plan: real 12-month QQQ put quotes (2012+)
# =====================================================================================================
cells = []
md("""# 12-month QQQ put quotes: audit of the local hedge model + surface fit
**Stage 1 gate for the options overlay** (README "Options overlay"). Written offline, not yet run.

Upload to the Object Store first (from your laptop, repo root):
`lean cloud object-store set options_ledger_central.csv results/options_ledger_central.csv`

What this notebook does, all on QC's listed US equity-option quotes (they start in **January 2012**):
1. **Trade audit.** For every option trade the local model made in 2012-2026 (all central cells), find the real QQQ
   put with the same moneyness and ~12 months left, then follow *that contract* to the sale / expiry date.
   Compare the real **ask at entry** and **bid at exit** (as % of spot) with the model's price.
2. **Stress fills.** Show the held contracts around **Mar 2020** and **May 2022**: bid, ask, spread, volume,
   open interest on the sale dates.
3. **Contracts at $1M.** Whole-contract counts and the sizing error vs the model's notional.
4. **Surface fit.** Monthly sample 2012-2026 of puts at 65-100% moneyness and 1-24 months: fit the parameters
   of `research/options_model.Surface` (ATM ratio to VXN, long-run vol, mean reversion, put skew at 12 months,
   half-spread and its stress scaling) → `options_surface_fit.csv`. Copy it to `results/`; the local model loads
   it automatically, then re-run `python research/options_overlay.py`.

**Gate (decided before running):** stop the options track for v3 if the real entry asks are above the model's
*pessimistic* band, or the Mar 2020 / May 2022 exits show no usable bids.""")
code("""from QuantConnect.Research import QuantBook
import numpy as np, pandas as pd
from scipy.optimize import brentq, least_squares
from scipy.special import ndtr
qb = QuantBook()
qqq = qb.add_equity("QQQ", Resolution.DAILY, data_normalization_mode=DataNormalizationMode.RAW).symbol
vxn = qb.add_index("VXN", Resolution.DAILY).symbol
opt = qb.add_option("QQQ", Resolution.DAILY)
opt.set_filter(lambda u: u.include_weeklys().puts_only().strikes(-200, 200).expiration(0, 810))   # wide: held puts go deep ITM in crashes
CAN = opt.symbol
TBILL = {2012: .0009, 2013: .0006, 2014: .0003, 2015: .0005, 2016: .0032, 2017: .0093, 2018: .0194, 2019: .0206,
         2020: .0035, 2021: .0005, 2022: .0202, 2023: .0507, 2024: .0497, 2025: .0410, 2026: .0375}
spot = qb.history(qqq, datetime(2011, 12, 1), datetime(2026, 9, 12), Resolution.DAILY).loc[qqq]["close"]
spot.index = pd.to_datetime(spot.index).normalize()
vx = qb.history(vxn, datetime(2011, 12, 1), datetime(2026, 9, 12), Resolution.DAILY).loc[vxn]["close"] / 100
vx.index = pd.to_datetime(vx.index).normalize()
print("QQQ raw", spot.index.min().date(), "->", spot.index.max().date(), "| VXN", vx.index.min().date(), "->", vx.index.max().date())

def bs_put(S, K, T, r, s):
    v = s * np.sqrt(T); d1 = (np.log(S / K) + (r + .5 * s * s) * T) / v
    return K * np.exp(-r * T) * ndtr(-(d1 - v)) - S * ndtr(-d1)

def iv_put(px, S, K, T, r):
    try:
        return brentq(lambda s: bs_put(S, K, T, r, s) - px, 1e-3, 5.0)
    except Exception:
        return np.nan

def chain_on(day, days=1):
    \"\"\"Daily put quotes on `day` (first trading day on/after it): one row per contract. Trade audits require the exact session.\"\"\"
    h = qb.option_history(qqq, day, day + timedelta(days=days), Resolution.DAILY, fill_forward=False)
    df = h.data_frame
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.reset_index()
    df["time"] = pd.to_datetime(df["time"]).dt.normalize()
    first = df["time"].min()
    if days == 1 and first != pd.Timestamp(day).normalize():
        return pd.DataFrame()
    df = df[df["time"] == first].copy()
    df["expiry"] = pd.to_datetime(df["expiry"])
    df["dte"] = (df["expiry"] - first).dt.days
    df["mid"] = (df["bidclose"] + df["askclose"]) / 2
    return df

def pick(df, S, moneyness, dte):
    d = df[(df["askclose"] > 0) & (df["bidclose"] >= 0) & (df["askclose"] >= df["bidclose"])
           & ((df["strike"]/S - moneyness).abs() <= .025)
           & ((df["dte"]-dte).abs() <= max(20, .15*dte))].copy()
    if d.empty:
        return None
    d["score"] = (d["strike"] / S - moneyness).abs() * 4 + (d["dte"] - dte).abs() / 365
    return d.sort_values("score").iloc[0]""")
md("## 1-3. Trade audit: follow each model trade's real contract")
code("""L = pd.read_csv(qb.object_store.get_file_path("options_ledger_central.csv"), parse_dates=["date"])
L = L[L["date"] >= "2012-01-03"].reset_index(drop=True)
OPENS = {"entry", "roll buy", "roll-down buy"}
rows, held = [], {}
for _, t in L.iterrows():
    day = t["date"].to_pydatetime()
    S = float(spot.asof(t["date"]))
    if t["event"] in OPENS:
        held.pop(t.cell, None)
    if t["event"] == "expire":
        rows.append(dict(cell=t.cell,date=t.date.date(),event=t.event,note="model settlement; no sale quote"))
        continue
    df = chain_on(day)
    if df.empty:
        rows.append(dict(cell=t.cell, date=t.date.date(), event=t.event, note="no chain")); continue
    if t["event"] in OPENS:
        c = pick(df, S, t["moneyness"], t["T"] * 365.25)
        held[t.cell] = c["symbol"] if c is not None else None
        q = c
    else:
        sym = held.get(t.cell)
        q = df[df["symbol"] == sym].iloc[0] if sym is not None and (df["symbol"] == sym).any() else None
    if q is None:
        rows.append(dict(cell=t.cell, date=t.date.date(), event=t.event, note="contract not quoted")); continue
    real = q["askclose"] if t["event"] in OPENS else q["bidclose"]
    model_fill = abs(t["cash"]) / abs(t["units"]) / t["S"] if t["units"] else np.nan    # model fill as % of spot
    n_1m = round(t["notional_pct_nav"] * 1_000_000 / (100 * S)) if t["event"] in OPENS else np.nan
    rows.append(dict(cell=t.cell, date=t.date.date(), event=t.event, vxn=t.vxn, strike=q["strike"], spot=S,
                     moneyness_real=q["strike"] / S, moneyness_model=t["moneyness"], dte=q["dte"],
                     real_fill_pct=real / S, model_fill_pct=model_fill, real_mid_pct=q["mid"] / S,
                     model_mid_pct=t["mid_pct_spot"], spread_pct_mid=(q["askclose"] - q["bidclose"]) / q["mid"] if q["mid"] > 0 else np.nan,
                     volume=q.get("volume", np.nan), open_interest=q.get("openinterest", np.nan), contracts_at_1M=n_1m,
                     sizing_error=(n_1m * 100 * S / 1_000_000 - t["notional_pct_nav"]) if t["event"] in OPENS else np.nan))
A = pd.DataFrame(rows)
A["real_over_model"] = A["real_fill_pct"] / A["model_fill_pct"]
qb.object_store.save("results/options_quotes_12m.csv", A.to_csv(index=False))
print(A.groupby("event")[["real_over_model", "spread_pct_mid"]].describe().round(3).T)
A.head(20)""")
md("""**Gate check.** Entry asks: compare `real_over_model` for opening trades with the model's pessimistic band
(the local pessimistic case pays about 1.26× the central price for a 12-month 85% put at VXN 14-25; recompute it
with `research/options_model.py` if the surface changes).""")
code("""opens = A[A["event"].isin(OPENS)]
print("entry ask / model fill: median %.2f, 90th pct %.2f, n=%d" % (opens.real_over_model.median(),
      opens.real_over_model.quantile(.9), len(opens)))
for a, b in [("2020-02-20", "2020-04-15"), ("2022-04-20", "2022-06-30")]:
    print(f"\\n--- {a} -> {b}")
    print(A[(pd.to_datetime(A.date) >= a) & (pd.to_datetime(A.date) <= b)]
          [["cell", "date", "event", "strike", "dte", "real_fill_pct", "model_fill_pct", "spread_pct_mid", "volume", "open_interest"]]
          .round(4).to_string())""")
md("## 4. Surface fit (monthly sample 2012-2026)")
code("""grid_m = [0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00]
grid_d = [30, 91, 182, 273, 365, 450, 548, 730]
obs = []
for day in pd.date_range("2012-01-01", datetime(2026, 9, 12), freq="MS"):
    df = chain_on(day.to_pydatetime(), days=6)
    if df.empty:
        continue
    t0 = df["time"].iloc[0]
    S, v, r = float(spot.asof(t0)), float(vx.asof(t0)), TBILL.get(t0.year, .02)
    for m in grid_m:
        for d in grid_d:
            c = pick(df[(df["dte"] - d).abs() <= max(20, d * .2)], S, m, d)
            if c is None or c["bidclose"] <= 0 or abs(c["strike"] / S - m) > 0.02:
                continue
            T = c["dte"] / 365
            obs.append(dict(date=t0, S=S, vxn=v, m_target=m, d_target=d, K=c["strike"], T=T,
                            iv=iv_put(c["mid"], S, c["strike"], T, r), h=(c["askclose"] - c["bidclose"]) / (2 * c["mid"])))
O = pd.DataFrame(obs).dropna(subset=["iv"])
print(len(O), "quotes;", O.date.min().date(), "->", O.date.max().date())
O.groupby(["m_target", "d_target"]).iv.median().unstack().round(3)""")
code("""T_REF = 30 / 365
atm = O[O.m_target == 1.00]
def atm_model(p, T, v):
    ratio, lr, kappa = p
    x = kappa * T
    return lr + (ratio * v - lr) * (1 - np.exp(-x)) / x
fit = least_squares(lambda p: atm_model(p, atm["T"].values, atm["vxn"].values) - atm["iv"].values,
                    x0=[0.92, 0.23, 2.0], bounds=([0.5, 0.05, 0.05], [1.5, 0.6, 20]))
ratio, lr, kappa = fit.x
print("ATM fit: ratio %.3f  lr %.3f  kappa %.2f  rmse %.4f" % (ratio, lr, kappa, np.sqrt(np.mean(fit.fun ** 2))))
# put skew: IV(K)/ATM - 1 = skew * sqrt(T_REF/T) * ln(S/K), solved per quote against the fitted ATM of that day
otm = O[O.m_target < 1.00].copy()
otm["atm_fit"] = atm_model(fit.x, otm["T"].values, otm["vxn"].values)
otm["skew"] = (otm["iv"] / otm["atm_fit"] - 1) / (np.sqrt(T_REF / otm["T"]) * np.log(otm["S"] / otm["K"]))
print(otm.groupby(["m_target", "d_target"]).skew.median().unstack().round(2))
skew_12m = otm[(otm.m_target == 0.85) & (otm.d_target == 365)].skew.median()
# spreads: h = half_spread x max(1, VXN / stress_vxn) for 12-month ~85% puts
p12 = O[(O.m_target == 0.85) & (O.d_target == 365)]
h0 = p12[p12.vxn < 0.25].h.median()
hi = p12[p12.vxn >= 0.25]
stress = np.median(h0 * hi.vxn * 100 / hi.h) if len(hi) else 25.0
F = pd.DataFrame([("ratio", ratio), ("lr", lr), ("kappa", kappa), ("skew_put", skew_12m), ("half_spread", h0),
                  ("stress_vxn", stress)], columns=["param", "value"])
F["note"] = "fit on QC QQQ put quotes 2012-2026 (skew_put at 12 months, 85% strike)"
qb.object_store.save("results/options_surface_fit.csv", F.to_csv(index=False))
qb.object_store.save("results/options_surface_obs.csv", O.to_csv(index=False))
F""")
md("""## Additional QQQ and SPY surface observations
Collect two-sided listed puts and calls by underlying for the extensions. Write each year separately.
The full-window fitted surface above is descriptive. Fit each evaluation year only with earlier observations.""")
code("""for ticker in ["QQQ", "SPY"]:
    asset = qb.add_equity(ticker, Resolution.DAILY, data_normalization_mode=DataNormalizationMode.RAW).symbol
    chain = qb.add_option(ticker, Resolution.DAILY)
    chain.set_filter(lambda u: u.include_weeklys().strikes(-250, 250).expiration(5, 810))
    closes = qb.history(asset, datetime(2012,1,1), datetime(2026,9,12), Resolution.DAILY).loc[asset]["close"]
    closes.index = pd.to_datetime(closes.index).normalize()
    for year in range(2012,2027):
        observations = []
        for date, S in closes[closes.index.year == year].groupby(closes[closes.index.year == year].index.month):
            session, spot_value = S.index[0], float(S.iloc[0])
            h = qb.option_history(asset, session.to_pydatetime(), (session+pd.Timedelta(days=1)).to_pydatetime(),
                                  Resolution.DAILY, fill_forward=False).data_frame
            if h is None or h.empty:
                continue
            quotes = h.reset_index()
            quotes = quotes[pd.to_datetime(quotes.time).dt.normalize() == session].copy()
            quotes["dte"] = (pd.to_datetime(quotes.expiry)-session).dt.days
            quotes = quotes[(quotes.bidclose > 0) & (quotes.askclose >= quotes.bidclose)]
            for right, targets in [("put",grid_m),("call",[1.0,1.05,1.10,1.15,1.20,1.25,1.30])]:
                side = quotes[quotes.right.astype(str).str.lower().str.endswith(right)]
                for tenor in grid_d:
                    for strike in targets:
                        q = pick(side,spot_value,strike,tenor)
                        if q is not None:
                            observations.append(dict(date=session,ticker=ticker,right=right,target_dte=tenor,
                                target_m=strike,contract=str(q.symbol),spot=spot_value,expiry=q.expiry,
                                strike=q.strike,bid=q.bidclose,ask=q.askclose))
        qb.object_store.save(f"results/put_surface_{ticker}_{year}.csv",pd.DataFrame(observations).to_csv(index=False))""")
md("""## 5. Download and re-run locally
Download `results/options_quotes_12m.csv`, `results/options_surface_fit.csv` (and `options_surface_obs.csv`) from the
Object Store into the repo's `results/`, then `python research/options_overlay.py && python research/options_figs.py`.
The trials table then says `surface: fit: options_surface_fit.csv`.""")

nb = nbf.v4.new_notebook(cells=cells, metadata={"kernelspec": {"name": "python3", "display_name": "Python 3"}})
out = Path(__file__).resolve().parents[1] / "qc" / "options_quote_audit.ipynb"
nbf.write(nb, out)
print("wrote", out)
