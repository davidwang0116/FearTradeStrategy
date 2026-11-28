"""Folders for the VIX entry study, and access to the repo's shared research code.

Importing this module puts the repo's research/ (common.py, strategy.py) on sys.path, so every script here
runs from any working directory. Outputs stay inside vix_entry/. The name differs from other studies'
path modules so that their tests can run in one pytest session.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent              # vix_entry/research
STUDY = HERE.parent                                  # vix_entry
ROOT = STUDY.parent                                  # repo root
for path in (ROOT / "research", HERE):
    if str(path) not in sys.path:
        sys.path.insert(1, str(path))

RESULTS = STUDY / "results"                          # CSVs and the dashboard
INPUTS = STUDY / "data"                              # optional QQQE and high-yield credit files, not in Git
PANEL = ROOT / "data" / "panel.csv"                  # shared QQQ/VIX panel
VIX_OHLC = ROOT / "data" / "raw" / "vix_daily.csv"   # shared Cboe VIX OHLC
VIX3M = ROOT / "data" / "raw" / "VIX3M_History.csv"  # shared Cboe VIX3M, also used by the options study
