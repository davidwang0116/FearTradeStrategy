"""Shared helpers: data loading, signal construction, chart style, metrics."""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "figures"
RES = ROOT / "results"
FIG.mkdir(exist_ok=True)
RES.mkdir(exist_ok=True)

# Scoring code vendored unchanged from github.com/davidwang0116/nasdaq-mood-dashboard
# (see vendor/mood_dashboard/SOURCE.txt) so research and dashboard share one formula.
DASH = ROOT / "vendor" / "mood_dashboard"
sys.path.insert(0, str(DASH))
import json  # noqa: E402
from features import build_features  # noqa: E402
import scoring  # noqa: E402

CFG = json.loads((DASH / "config.json").read_text(encoding="utf-8"))

# ---- palette (validated reference palette, light mode) ----
INK, INK2, MUTED, GRID, SURF = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e0", "#fcfcfb"
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED = (
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
SEQ5 = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"]   # ordinal Q1..Q5

plt.rcParams.update({
    "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 11,
    "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlecolor": INK,
    "legend.frameon": False, "font.family": "DejaVu Sans",
})


def load_panel():
    P = pd.read_csv(ROOT / "data" / "panel.csv", index_col=0, parse_dates=True)
    return P


def build_signals(P):
    """All fear/cheapness signals, oriented so HIGHER = more fear (contrarian buy)."""
    F = build_features(P["qqq"], P["vxn"].dropna(), CFG, fgi=P["fgi"].dropna())
    F_nofgi = F.copy(); F_nofgi["fgi"] = np.nan
    S = scoring.score_frame(F_nofgi.drop(columns=["fpe_dd"]), CFG)  # composite w/o valuation (no PIT data)
    out = pd.DataFrame(index=P.index)
    out["VIX level"] = P["vix"]
    out["VXN score"] = S["s_vxn"]
    out["Drawdown score"] = S["s_dd"]
    out["Price-sentiment proxy (inv.)"] = 100 - F["proxy"]
    out["CNN Fear&Greed (inv.)"] = 100 - P["fgi"]
    rv = P["qqq"].pct_change().rolling(21).std() * np.sqrt(252) * 100
    out["Variance risk premium"] = P["vxn"] ** 2 - rv ** 2
    out["Composite (dashboard v4)"] = S["composite"]
    out.attrs["scores"] = S
    out.attrs["features"] = F
    return out


def fwd_return(px, h):
    """Return from t+1 close to t+1+h close (signal at t close, trade next close)."""
    return px.shift(-(h + 1)) / px.shift(-1) - 1


def perf_stats(nav, rf=None, freq=252):
    r = nav.pct_change().dropna()
    yrs = (nav.index[-1] - nav.index[0]).days / 365.25
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / yrs) - 1
    vol = r.std() * np.sqrt(freq)
    ex = r - (rf.reindex(r.index) / freq if rf is not None else 0)
    sharpe = ex.mean() / r.std() * np.sqrt(freq)
    dn = r[r < 0].std() * np.sqrt(freq)
    mdd = (nav / nav.cummax() - 1).min()
    return {"CAGR": cagr, "Vol": vol, "Sharpe": sharpe,
            "Sortino": ex.mean() * freq / dn if dn > 0 else np.nan,
            "MaxDD": mdd, "Calmar": cagr / abs(mdd) if mdd < 0 else np.nan}


def block_boot_delta(nav_a, nav_b, rf=None, block=63, n=2000, freq=252, seed=585):
    """Paired moving-block bootstrap of A minus B on the same days (63-day blocks keep crashes together).
    Returns {"dSharpe" | "dCAGR" | "dMaxDD": (point, 5th pct, 95th pct, share of draws <= 0)}."""
    ra = nav_a.pct_change().dropna()
    rb = nav_b.pct_change().reindex(ra.index).fillna(0.0)
    rfd = (rf.reindex(ra.index).fillna(0.0) / freq) if rf is not None else pd.Series(0.0, index=ra.index)
    A, B, R = ra.to_numpy(), rb.to_numpy(), rfd.to_numpy()
    T = len(A)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, T - block, size=(n, int(np.ceil(T / block))))
    ix = (starts[:, :, None] + np.arange(block)).reshape(n, -1)[:, :T]

    def stats(x, r):
        sh = (x - r).mean(axis=-1) / x.std(axis=-1) * np.sqrt(freq)
        g = np.log1p(x).sum(axis=-1)
        cagr = np.exp(g * freq / x.shape[-1]) - 1
        w = np.exp(np.cumsum(np.log1p(x), axis=-1))
        mdd = (w / np.maximum.accumulate(w, axis=-1) - 1).min(axis=-1)
        return sh, cagr, mdd

    pa, pb = stats(A, R), stats(B, R)
    ba, bb = stats(A[ix], R[ix]), stats(B[ix], R[ix])
    out = {}
    for k, j in [("dSharpe", 0), ("dCAGR", 1), ("dMaxDD", 2)]:
        d = ba[j] - bb[j]
        out[k] = (float(pa[j] - pb[j]), float(np.quantile(d, 0.05)), float(np.quantile(d, 0.95)), float((d <= 0).mean()))
    return out


def savefig(fig, name):
    fig.savefig(FIG / name, dpi=200, bbox_inches="tight")
    plt.close(fig)
