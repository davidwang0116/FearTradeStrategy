"""Report section for the checks ported from the options-put-hedge branch (called at the end of put_report.py)."""
import pandas as pd


def _table(header, rows):
    return "\n".join(["| " + " | ".join(header) + " |", "|" + "---|" * len(header),
                      *["| " + " | ".join(map(str, row)) + " |" for row in rows]])


def ported_section(t, labels, out):
    C = pd.read_csv(out / "decline_checks.csv", parse_dates=["worst_decline"])
    E = pd.read_csv(out / "declines.csv.gz", parse_dates=["peak", "trough", "recovery"])
    spans = E.drop_duplicates("peak").set_index("peak")
    span = lambda p: f"{p:%b %Y}–{spans.loc[p, 'recovery']:%b %Y}" if p in spans.index else f"{p:%b %Y}"
    extra = {"vxn_rank": "VXN-rank gate", "vol_premium": "Volatility-premium gate"}
    lab = lambda cell: labels.get(cell, extra.get(cell, cell))

    cleared = t.query('window in ["full","early","late","quote-era","refresh"] and capital_mode != "fractional"') \
        .groupby("cell").improved.all()
    cleared = list(cleared[cleared].index)
    keeps = C.groupby("cell").apply(lambda g: bool((g.min_left_out > 0).all()))
    keeps = list(keeps[keeps].index)
    c = C[(C.capital == 1000000) & (C.pricing == "central")].set_index("cell")
    pos = c[c.delta_sharpe > 0]
    worst_counts = pos.worst_decline.value_counts()

    lines = ["## Checks ported from the options-put-hedge branch", "",
             "**Does the edge survive without each decline?** For every registered cell, the full-history Sharpe "
             "difference against the frozen hedge is recomputed with each of unhedged v2's seven declines (peak to "
             "recovery) left out in turn, at both whole-contract sizes under all three pricing assumptions "
             "(`research/put_decline_checks.py`, `decline_checks.csv`). The year exclusions above test the Sharpe "
             "level; this tests the edge over the benchmark. Central pricing, $1M:", ""]
    show = [k for k in ["core-0.80-put-0.95", "core-0.80-put-0.90", "core-0.90-put-0.95", "core-0.90-put-0.90",
                        "core-0.80-put", "put-365d-90", "put-365d-95", "rungs-2-phase-0"] if k in c.index]
    rows = [[lab(k), f"{c.loc[k, 'delta_sharpe']:+.3f}", span(c.loc[k, "worst_decline"]),
             f"{c.loc[k, 'min_left_out']:+.3f}", f"{int(c.loc[k, 'edge_kept'])}/{int(c.loc[k, 'declines_tested'])}"]
            for k in show]
    lines += [_table(["Rule", "Full-history ΔSharpe", "Decline whose removal hurts most", "ΔSharpe without it",
                      "Declines left out with the edge intact"], rows), ""]
    names = ", ".join(lab(k) for k in cleared) or "none"
    lines += [f"The cells that cleared the all-window checks above ({names}) lose their edge when the "
              f"{span(pd.Timestamp('2021-12-27'))} decline is left out. "
              f"{len(keeps)} of {C.cell.nunique()} registered cells keep a positive edge with every decline left out "
              "at both account sizes under all three pricings"
              + (f" ({', '.join(lab(k) for k in keeps)})." if keeps else ".") +
              f" Among the {len(pos)} cells with a positive central $1M edge, the decline whose removal hurts most is "
              + ", ".join(f"{span(p)} for {n}" for p, n in worst_counts.items()) + ". "
              "The leading allocation/strike candidates therefore rest on the 2022 bear market. That episode falls "
              "inside the listed-quote era, so the quote audit can test it directly.", ""]

    g = t[(t.family == "gate") & (t.window == "full") & (t.capital_mode == "1000000") & (t.pricing == "central")]
    rows = [[lab(r.cell), str(r.start)[:10], f"{r.Sharpe:.3f}", f"{r.benchmark_sharpe:.3f}", f"{r.delta_sharpe:+.3f}"]
            for r in g.itertuples()]
    lines += ["**Gates against a same-day benchmark.** Feature gates start when their feature first exists. The "
              "VIX/VIX3M row in the portfolio table starts in September 2010, so its Sharpe is not comparable with "
              "rows that start in February 2007. Against a frozen hedge started the same day, central pricing, $1M:", "",
              _table(["Gate", "Start", "Gate Sharpe", "Frozen hedge, same start", "ΔSharpe"], rows), "",
              "**Quote dates in the audit notebook.** QuantConnect stamps a daily bar at its end time, which can be "
              "midnight after the session. `chain_on` now takes the timestamp minus one minute as the session date "
              "before requiring the exact trade session, so a midnight stamp no longer empties every audit.", "",
              "Reproduce this section with `python research/put_decline_checks.py`, then `python research/put_report.py`.", ""]
    return lines
