"""Bundle the QC files into one main.py for the QuantConnect web editor."""
import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def bundle(parameters):
    sources = [(ROOT / "qc" / name).read_text() for name in ("signals.py", "hedge.py", "main.py")]
    signals, hedge, main = sources
    hedge = hedge.replace("from AlgorithmImports import *\n", "")
    main = main[:main.index("from signals import")] + main[main.index("def _p("):]
    main = main.replace("from AlgorithmImports import *\n", "")
    if parameters:
        marker = "def _p(algo, name, default, cast=float):"
        main = main.replace(marker, f"RUN_PARAMETERS = {parameters!r}\n\n\n{marker}", 1)
        marker = "class FearTrancheAccumulator(QCAlgorithm):\n"
        method = ("\n    def get_parameter(self, name):\n"
                  "        return RUN_PARAMETERS.get(name) or super().get_parameter(name)\n")
        main = main.replace(marker, marker + method, 1)
    return "\n\n".join(["from AlgorithmImports import *", signals, hedge, main]) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="path to the bundled main.py")
    parser.add_argument("--param", action="append", default=[], metavar="KEY=VALUE")
    args = parser.parse_args()
    parameters = {}
    for pair in args.param:
        key, sep, value = pair.partition("=")
        if not key or not sep or not value:
            parser.error("every --param must be KEY=VALUE")
        parameters[key] = value
    args.output.write_text(bundle(parameters), encoding="utf-8")


if __name__ == "__main__":
    main()
