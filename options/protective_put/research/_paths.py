"""Folders for the protective-put study, and access to the repo's shared research code.

Importing this module puts the repo's research/ (common.py, strategy.py, the signal code) on sys.path, so every
script here runs from any working directory. Outputs stay inside options/protective_put/.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent            # options/protective_put/research
STUDY = HERE.parent                                # options/protective_put
ROOT = STUDY.parents[1]                            # repo root
for p in (HERE, ROOT / "research"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

RESULTS = STUDY / "results"                        # frozen 12-month put study (options_overlay.py)
EXTENSIONS = RESULTS / "extensions"                # next-stage experiments (options_experiments.py and reports)
FIGURES = STUDY / "figures"
RAW = ROOT / "data" / "raw"                        # shared market data (ETF closes, VIX3M, SKEW)
for d in (RESULTS, EXTENSIONS, FIGURES):
    d.mkdir(parents=True, exist_ok=True)


def savefig(fig, name):
    """Same output settings as common.savefig, written to this study's figures/ folder."""
    import matplotlib.pyplot as plt
    fig.savefig(FIGURES / name, dpi=200, bbox_inches="tight")
    plt.close(fig)
