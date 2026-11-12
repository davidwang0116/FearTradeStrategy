"""qc/signals.py must reproduce the dashboard's v4 composite (no FGI, no valuation)."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "qc"))
from common import build_signals, load_panel  # noqa: E402
import signals  # noqa: E402


def test_parity():
    P = load_panel()
    S = build_signals(P)
    ref = S.attrs["scores"]
    mine = signals.composite_frame(P["qqq"], P["vxn"].dropna())
    for a, b in [("s_vxn", "s_vxn"), ("s_dd", "s_dd"), ("s_sent", "s_sent"), ("composite", "composite")]:
        d = (ref[a] - mine[b]).abs().dropna()
        assert len(d) > 5000, a
        assert d.max() < 1e-6, (a, d.max())


def test_parity_with_fgi():
    P = load_panel()
    S = build_signals(P)
    F = S.attrs["features"]
    import scoring
    ref = scoring.score_sentiment_blend(F["fgi"].values, F["proxy"].values)
    mine = signals.composite_frame(P["qqq"], P["vxn"].dropna(), fgi=P["fgi"].dropna())["s_sent"]
    d = np.abs(ref - mine.values)
    assert np.nanmax(d) < 1e-6


if __name__ == "__main__":
    test_parity(); test_parity_with_fgi(); print("parity OK")
