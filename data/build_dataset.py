"""Build one daily panel for the midterm research.

Sources (all copied into data/raw, see data/README.md):
  qqq   Yahoo Adj Close 1999-03-10 -> 2026-04-17 (QQQ-LEAPS repo), extended to
        2026-11-10 with the daily adjusted returns embedded in QQQ-vacation
  spy   QuantConnect TOTAL_RETURN closes 2005-01-31 -> 2026-09-11 (QC realdata repo, project 01)
  vxn   QuantConnect ^VXN closes 2008-01-03 -> 2026-09-11 (QC realdata repo, project 02);
        before 2008 it is back-filled as VIX x (median VXN/VIX ratio 2008-2012) and flagged
  vix   CBOE VIX via github.com/datasets/finance-vix, 1990 -> 2026-09-22
  fgi   CNN Fear & Greed 2011-01-03 -> 2023-12-29 (github.com/Benny2000/fear-greed-data)
  rf    3-month T-bill, annual averages (approximate, hard-coded; QC uses the real series)
  tqqq_real  QC TOTAL_RETURN TQQQ 2010-02-11 -> 2026-09-11, used only to validate
        the synthetic leveraged series

Run:  python data/build_dataset.py   ->  data/panel.csv
"""
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path(__file__).parent / "raw"
OUT = Path(__file__).parent / "panel.csv"

# Approximate annual-average 3M T-bill yield (%), used for cash yield, leverage
# financing and Sharpe. Replace with QC's US Treasury / FRED DTB3 series on QC.
TBILL = {1999: 4.64, 2000: 5.82, 2001: 3.39, 2002: 1.60, 2003: 1.01, 2004: 1.37,
         2005: 3.15, 2006: 4.73, 2007: 4.36, 2008: 1.37, 2009: 0.15, 2010: 0.14,
         2011: 0.05, 2012: 0.09, 2013: 0.06, 2014: 0.03, 2015: 0.05, 2016: 0.32,
         2017: 0.93, 2018: 1.94, 2019: 2.06, 2020: 0.35, 2021: 0.05, 2022: 2.02,
         2023: 5.07, 2024: 4.97, 2025: 4.10, 2026: 3.75}

# Leveraged-ETF synthesis: r_L = L*r - (L-1)*(rf + SPREAD) - FEE   (daily)
FEE = {2: 0.0095, 3: 0.0086}
SPREAD = 0.0060   # swap financing spread over T-bills; calibrated against real TQQQ below


def load_qqq():
    y = pd.read_csv(RAW / "qqq_yahoo_1999_2026-04.csv", parse_dates=["Date"]).set_index("Date")["Adj Close"]
    v = pd.read_csv(RAW / "qqq_vacation_rets.csv", parse_dates=["date"]).set_index("date")["ret"]
    ext = v[v.index > y.index[-1]]
    tail = y.iloc[-1] * (1 + ext).cumprod()
    # overlap check: vacation returns should match Yahoo adj returns
    ov = pd.concat([y.pct_change(), v], axis=1, join="inner").dropna()
    corr = ov.corr().iloc[0, 1]
    return pd.concat([y, tail]).rename("qqq"), corr


def load_qc():
    m = pd.read_csv(RAW / "qc_mood_dca_daily.csv", encoding="utf-8-sig", parse_dates=["time"]).set_index("time")
    b = pd.read_csv(RAW / "qc_bollinger_daily.csv", header=[0, 1], index_col=0, encoding="utf-8-sig")
    b.index = pd.to_datetime(b.index)
    spy = b[("标普500代理_SPY", "close")].rename("spy")
    t = pd.read_csv(RAW / "qc_tqqq_real_daily.csv", encoding="utf-8-sig", parse_dates=["date"]).set_index("date")
    return m["vxn"].rename("vxn_qc"), m["qqq"].rename("qqq_qc"), spy, t["tqqq_buy_hold"].rename("tqqq_real")


def load_vix():
    v = pd.read_csv(RAW / "vix_daily.csv", parse_dates=["DATE"]).set_index("DATE")["CLOSE"]
    return v.rename("vix")


def load_fgi():
    g = pd.read_csv(RAW / "cnn_fgi_2011_2023.csv")
    g.columns = ["date", "fgi"]
    g["date"] = pd.to_datetime(g["date"], format="mixed")
    return g.set_index("date")["fgi"].astype(float)


def synth(r, rf_d, L):
    return L * r - (L - 1) * (rf_d + SPREAD / 252) - FEE[L] / 252


def main():
    qqq, corr = load_qqq()
    vxn_qc, qqq_qc, spy, tqqq_real = load_qc()
    vix, fgi = load_vix(), load_fgi()

    P = pd.DataFrame(index=qqq.index)
    P["qqq"] = qqq
    P["spy"] = spy.reindex(P.index)
    P["vix"] = vix.reindex(P.index).ffill(limit=3)
    ratio = (vxn_qc / vix.reindex(vxn_qc.index)).loc["2008":"2012"].median()
    vxn = vxn_qc.reindex(P.index)
    P["vxn_backfilled"] = vxn.isna() & (P.index < vxn_qc.index[0])
    P["vxn"] = vxn.where(~P["vxn_backfilled"], P["vix"] * ratio)
    P["vxn"] = P["vxn"].ffill(limit=3)
    P["fgi"] = fgi.reindex(P.index)
    P["rf"] = [TBILL[d.year] / 100 for d in P.index]
    rf_d = P["rf"] / 252
    r = P["qqq"].pct_change()
    P["ret_qqq"] = r
    P["ret_spy"] = P["spy"].pct_change()
    P["ret_qld"] = synth(r, rf_d, 2)
    P["ret_tqqq"] = synth(r, rf_d, 3)
    P["tqqq_real"] = tqqq_real.reindex(P.index)
    P = P.loc["1999-03-10":]
    P.to_csv(OUT)

    # --- validation of synthetic TQQQ vs real (QC) ---
    tr = P["tqqq_real"].dropna()
    s = (1 + P["ret_tqqq"].reindex(tr.index).fillna(0)).cumprod()
    yrs = (tr.index[-1] - tr.index[0]).days / 365.25
    cagr_real = (tr.iloc[-1] / tr.iloc[0]) ** (1 / yrs) - 1
    cagr_syn = (s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1
    dc = pd.concat([tr.pct_change(), P["ret_tqqq"]], axis=1, join="inner").dropna().corr().iloc[0, 1]
    print(f"QQQ splice: Yahoo vs vacation daily-return corr = {corr:.6f}")
    print(f"VXN/VIX back-fill ratio (2008-12 median) = {ratio:.3f}")
    print(f"TQQQ {tr.index[0].date()}->{tr.index[-1].date()}: real CAGR {cagr_real:.2%}, synthetic {cagr_syn:.2%}, daily corr {dc:.4f}")
    print(f"panel {P.index[0].date()} -> {P.index[-1].date()}, rows {len(P)}")
    print(P[["qqq", "spy", "vix", "vxn", "fgi"]].apply(lambda c: f"{c.first_valid_index().date()}..{c.last_valid_index().date()}"))


if __name__ == "__main__":
    main()
