"""Generate qc/research_new_indicators.ipynb (clean, output-free) for QC Research."""
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
