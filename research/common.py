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


def savefig(fig, name):
    fig.savefig(FIG / name, dpi=200, bbox_inches="tight")
    plt.close(fig)


# ---- paired block bootstrap with family-wise error control ----
def block_boot_sharpes(R, rf, block=63, n=5000, seed=585):
    """Joint moving-block bootstrap of annualised excess-return Sharpe ratios.

    R: DataFrame of daily returns (one column per portfolio), rf: annual T-bill rate.
    Every draw uses the SAME day blocks for all columns, so cross-correlations survive.
    Returns (point estimates, n x K array of bootstrap Sharpes)."""
    X = R.to_numpy(float)
    ex = X - (rf.reindex(R.index).to_numpy(float) / 252)[:, None]
    T, K = X.shape
    nb, last = int(np.ceil(T / block)), T - (int(np.ceil(T / block)) - 1) * block
    pre = [np.vstack([np.zeros(K), np.cumsum(a, axis=0)]) for a in (ex, X, X * X)]
    rng = np.random.default_rng(seed)
    st = rng.integers(0, T - block + 1, (n, nb))
    en = st + block
    en[:, -1] = st[:, -1] + last
    sums = [np.stack([(p[en[b]] - p[st[b]]).sum(axis=0) for b in range(n)]) for p in pre]

    def sharpe(sex, sx, sxx):
        return sex / T / np.sqrt((sxx - sx * sx / T) / (T - 1)) * np.sqrt(252)
    return sharpe(*[p[-1] for p in pre]), sharpe(*sums)


def maxt_family(point, boot, alpha=0.05):
    """Simultaneous one-sided inference for a family of differences (H0: diff <= 0).

    point: length-J differences; boot: n x J bootstrap differences (joint draws).
    Differences are studentised by their bootstrap SE and centred on the bootstrap mean
    (the moving-block mean is not exactly the sample value). Returns a DataFrame with the
    single-step max-t lower bound (decides), the Romano-Wolf step-down p-value (reported)
    and the unadjusted one-sided bound (labelled as such)."""
    point, boot = np.asarray(point, float), np.asarray(boot, float)
    se = boot.std(axis=0, ddof=1)
    ok = se > 1e-12
    z = np.zeros_like(boot)
    z[:, ok] = (boot[:, ok] - boot[:, ok].mean(axis=0)) / se[ok]
    crit = np.quantile(z.max(axis=1), 1 - alpha)
    unadj = np.quantile(z, 1 - alpha, axis=0)
    t = np.where(ok, point / np.where(ok, se, 1), 0.0)
    order, p, run_max = np.argsort(-t), np.ones(len(t)), 0.0
    for r, j in enumerate(order):
        run_max = max(run_max, (z[:, order[r:]].max(axis=1) >= t[j]).mean())
        p[j] = run_max
    return pd.DataFrame({"diff": point, "se": se, "t": t, "lb_simultaneous": point - crit * se,
                         "p_stepdown": p, "lb_unadjusted": point - unadj * se}), crit
