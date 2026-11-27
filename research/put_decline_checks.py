"""Leave-one-decline-out check, ported from the options-put-hedge branch.

Question: does a rule's full-history Sharpe edge over the frozen hedge survive when each of unhedged v2's seven
declines (peak to recovery, -10% or worse) is left out in turn? A rule whose edge comes from one decline is a bet on
that episode repeating. The year exclusions in put_refresh_checks.py test the Sharpe level; this tests the edge over
the benchmark.

Every registered cell, full window, whole contracts at $100k and $1M, all three pricing assumptions. Gate cells start
where their feature starts and are compared with a frozen hedge started the same day (as in options_experiments.score);
declines outside a cell's window are skipped. Model-priced.

Output: results/put_research/decline_checks.csv
"""
import numpy as np
import pandas as pd

import options_experiments as exp
from options_experiments import A_, B_, BASE, RES, SURFACES, episodes, registry, simulate


def sharpe(r, rf):
    return (r - rf / 252).mean() / r.std() * np.sqrt(252)


def main():
    exp.init()
    D = exp.D
    unhedged = simulate(None, False, SURFACES["central"], 0, A_, B_)[0].nav
    declines = episodes(unhedged)
    rows, bases = [], {}
    for size in (100000, 1000000):
        for pricing, surface in SURFACES.items():
            for name, (family, h, guard_off) in registry().items():
                if family == "control":
                    continue
                start = A_
                if h and h.gate not in ("always", "p"):
                    start = max(pd.Timestamp(A_), D[h.gate].first_valid_index())
                key = (size, pricing, start)
                if key not in bases:
                    bases[key] = simulate(BASE, False, surface, size, start, B_)[0].nav
                weight = float(name.split("-")[1]) if family in ("core-weight", "allocation-strike") else exp.V2.core_target
                nav = simulate(h, guard_off, surface, size, start, B_, weight)[0].nav
                ra = nav.pct_change().dropna()
                rb = bases[key].pct_change().reindex(ra.index)
                rf = D.rf.reindex(ra.index)
                edge = sharpe(ra, rf) - sharpe(rb, rf)
                left_out = {}
                for peak, _, recovery in declines:
                    keep = ~((ra.index >= peak) & (ra.index <= recovery))
                    if keep.all():
                        continue
                    left_out[peak] = sharpe(ra[keep], rf[keep]) - sharpe(rb[keep], rf[keep])
                worst = min(left_out, key=left_out.get)
                rows.append(dict(cell=name, family=family, pricing=pricing, capital=size, start=pd.Timestamp(start).date(),
                                 delta_sharpe=edge, min_left_out=left_out[worst], worst_decline=worst.date(),
                                 declines_tested=len(left_out), edge_kept=sum(v > 0 for v in left_out.values()),
                                 **{f"without_{p:%Y-%m}": v for p, v in left_out.items()}))
        print(f"${size:,} done", flush=True)
    out = pd.DataFrame(rows)
    out.to_csv(RES / "put_research" / "decline_checks.csv", index=False, float_format="%.10g")
    print(f"{len(out)} rows")


if __name__ == "__main__":
    main()
