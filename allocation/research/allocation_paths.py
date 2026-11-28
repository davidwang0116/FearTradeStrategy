"""Folders for the allocation study, and access to the repo's shared research code.

Importing this module puts the repo's research/ (common.py, strategy.py) on sys.path, so every script here
runs from any working directory. Outputs stay inside allocation/. The name differs from other studies'
path modules so that their tests can run in one pytest session.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent              # allocation/research
STUDY = HERE.parent                                  # allocation
ROOT = STUDY.parent                                  # repo root
for path in (ROOT / "research", HERE):
    if str(path) not in sys.path:
        sys.path.insert(1, str(path))

RESULTS = STUDY / "results"                          # allocation_*.csv
FIGURES = STUDY / "figures"                          # fig_allocation_*.png
RESULTS.mkdir(exist_ok=True)
FIGURES.mkdir(exist_ok=True)
