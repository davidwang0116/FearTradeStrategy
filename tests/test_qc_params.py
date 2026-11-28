"""qc/main.py parameter helpers (AlgorithmImports is stubbed: this does NOT run the algorithm on QuantConnect)."""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def qc():
    stub = types.ModuleType("AlgorithmImports")
    stub.QCAlgorithm, stub.Slice = object, object
    saved = sys.modules.get("AlgorithmImports")
    sys.modules["AlgorithmImports"] = stub
    sys.path.insert(0, str(ROOT / "qc"))
    spec = importlib.util.spec_from_file_location("qc_main", ROOT / "qc" / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    yield mod
    sys.path.remove(str(ROOT / "qc"))
    sys.modules.pop("AlgorithmImports") if saved is None else sys.modules.update(AlgorithmImports=saved)


def test_defaults_are_frozen_v2(qc):
    assert qc.ladder_defaults("FIXED", 0.70) == dict(tranche=0.075, lev_size=0.10, lev_cap=0.30)
    assert qc.ladder_defaults("FIXED", 0.80) == qc.ladder_defaults("FIXED", 0.70)
    assert qc.parse_core("QQQ:1") == {"QQQ": 1.0}


def test_scaled_matches_local_study(qc):
    # allocation/research/allocation_study.py ladder_sizes(e, "scaled"): tranche = reserve/4, QLD buy = reserve/3, cap = reserve
    for e in (0.70, 0.75, 0.80):
        r = 1 - e
        assert qc.ladder_defaults("SCALED", e) == pytest.approx(dict(tranche=r / 4, lev_size=r / 3, lev_cap=r))
    with pytest.raises(ValueError):
        qc.ladder_defaults("OTHER", 0.7)


def test_core_parsing(qc):
    assert qc.parse_core("QQQ:0.8, voo:0.2") == pytest.approx({"QQQ": 0.8, "VOO": 0.2})
    assert qc.parse_core("QQQ:4,VOO:1") == pytest.approx({"QQQ": 0.8, "VOO": 0.2})
    for bad in ("QQQ", "QQQ:0", "QQQ:-1,VOO:2", "QQQ:.5,QQQ:.5", "QQQ:nan", "QQQ:inf", ""):
        with pytest.raises(ValueError):
            qc.parse_core(bad)
