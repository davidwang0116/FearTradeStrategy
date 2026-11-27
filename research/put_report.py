"""Summarize all registered trials and write the local research report and figure."""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from options_experiments import RES, WINDOWS, registry
from put_ported_checks import ported_section

OUT = RES / "put_research"
LABELS = {
    "unhedged":"Unhedged v2", "frozen":"Frozen 12m / 85 put", "claude-benchmark":"Frozen put, tranche proceeds",
    "put-91d-85":"3-month put", "put-182d-85":"6-month put", "put-548d-85":"18-month put",
    "put-730d-85":"24-month put", "put-365d-90":"90% strike", "put-365d-95":"95% strike",
    "guard-off":"Neither guard nor put", "guard-off-put":"Put alone",
    "coverage-0.75":"75% coverage", "budget-0.02":"2% annual gross budget", "dynamic":"Dynamic coverage",
    "fear-0.5":"Sell half on fear", "beta_126":"126-session beta", "split-SPY":"Separate QQQ and SPY puts",
    "package-85-70-0":"85/70 put spread", "package-85-70-110":"85/70 spread + 110 call",
    "covered-size-spread":"Share-matched spread control", "rungs-2-phase-0":"Two staggered puts", "always":"Always eligible",
    "SKEW":"SKEW gate", "VIX3M":"VIX/VIX3M gate", "core-0.80-put":"80% core + frozen put",
    "core-0.90-put":"90% core + frozen put", "core-0.90-unhedged":"90% core, unhedged",
    "core-0.90-put-0.90":"90% core + 90% put", "core-0.90-put-0.95":"90% core + 95% put",
    "core-0.80-put-0.90":"80% core + 90% put", "core-0.80-put-0.95":"80% core + 95% put",
}

def table(header, rows):
    return "\n".join(["| "+" | ".join(header)+" |", "|"+"---|"*len(header),
                      *["| "+" | ".join(map(str,row))+" |" for row in rows]])


def chart(t):
    fig, axs = plt.subplots(1,2, figsize=(11,4.6),layout="constrained")
    for ax, window, title in zip(axs, ["full","refresh"],["February 2007–September 2026","January 2020–September 2026"]):
        x=t[(t.window==window)&(t.family!="control")&(t.start==WINDOWS[window][0])].copy()
        ax.scatter(-100*x.MaxDD,100*x.CAGR,c=x.Sharpe,cmap="viridis",vmin=.65,vmax=1.15,s=19,alpha=.72)
        for cell,marker,label,color in [("frozen","s","Frozen hedge","black"),("unhedged","x","Unhedged v2","#a34d28"),
                                        ("core-0.90-put-0.95","*","90% core / 95% put","#cb3571")]:
            r=t[(t.cell==cell)&(t.window==window)].iloc[0]
            ax.scatter(-100*r.MaxDD,100*r.CAGR,marker=marker,s=95,color=color,label=label,zorder=4)
        ax.set(title=title,xlabel="Maximum drawdown magnitude (%)",ylabel="CAGR (%)")
        ax.grid(alpha=.15)
    axs[0].legend(fontsize=8)
    fig.colorbar(axs[0].collections[0],ax=axs,label="Sharpe")
    fig.suptitle("Modeled return and downside at $1 million • central pricing")
    fig.savefig(OUT/"return_drawdown.png",dpi=165)
    plt.close(fig)


def main():
    t=pd.read_csv(OUT/"trials.csv.gz",dtype={"capital_mode":str})
    expected=len(registry())*3*3*len(WINDOWS)
    assert len(t)==expected and not t.duplicated(["cell","pricing","capital_mode","window"]).any()
    assert set(t.cell)==set(registry())
    sizes=["fractional","100000","1000000"]
    t["protects"]=(t.delta_dd>=-.02)&(t.delta_daily_es>=-.001)
    t["joint_target"]=(t.Sharpe>1)&(t.delta_cagr>=-1e-10)&t.protects
    t["improved"]=(t.delta_sharpe>1e-8)&(t.equal_dd_delta>1e-8)&t.protects
    central=t[t.pricing=="central"]
    primary=central[central.capital_mode=="1000000"]
    central[["cell","family","capital_mode","window","start","end","Sharpe","CAGR","MaxDD","delta_sharpe",
             "delta_cagr","delta_dd","ci05","ci95","joint_target"]].to_csv(OUT/"central_scorecard.csv",index=False)
    chart(primary)
    lines=["# Can a protective put deliver Sharpe above 1?", "",
           "Local research on the frozen FearTradeStrategy v2 portfolio through September 11, 2026. The refresh window includes returns from the close of December 31, 2019. All option trades and valuations use a model. Only the ETF closes and volatility-index observations are market data.","",
           "## The threshold in context","",
           "The joint target requires Sharpe above 1, CAGR at least as high as the same-date, same-cost frozen hedge, maximum drawdown within two percentage points, and average daily loss in the worst 5% of sessions within 0.10 percentage points. The threshold for CAGR is a research assumption. Raw CAGR and drawdown are provided so a different threshold can be applied.",""]
    lines[4:4] = [
        "**2020–2026 met the objective in the model.** With $1M at the start of 2007, a 90% v2 core target and a 12-month QQQ put struck at 95% delivered 1.070 Sharpe, 17.50% CAGR, and a 14.85% maximum drawdown in the refresh period. The frozen hedge delivered 0.923, 15.51%, and 18.94%. This was the only tested configuration to meet the return, tail-loss and Sharpe criteria in all three pricing scenarios at both whole-contract sizes on the continuous path.",
        "",
        "**The full history gives a different answer.** The same candidate delivered 0.855 Sharpe, 11.16% CAGR, and a 25.12% drawdown, compared with the frozen hedge’s 0.805, 10.24%, and 24.73%. The 80% core / 95% put delivered the highest full-history Sharpe at $1M (0.865), with a smaller 20.21% drawdown and 10.04% CAGR. No full-period strategy reached 1.",
        "",
        "The 90% target increases the capital allocated to the core. The 95% strike starts protection closer to entry spot. The unhedged 90% core produced 18.12% CAGR in the refresh window, but its drawdown was 27.07% and its Sharpe was 0.799. Adding the 95% put preserved most of that CAGR and cut drawdown by 12.22 points. The extra equity allocation accounts for a meaningful part of the return.",
        ""]
    summary=[]
    for window in ["full","refresh","quote-era","late","early","2026-ytd","data-extension"]:
        g=primary[primary.window==window]
        benchmark=g[g.cell=="frozen"].iloc[0]
        g=g[(g.start==benchmark.start)&(~g.cell.isin(["unhedged","frozen","claude-benchmark"]))&
            (~g.cell.str.endswith("-unhedged"))&(g.cell!="guard-off")]
        all_prices=t[(t.window==window)&t.cell.isin(g.cell)&t.capital_mode.isin(sizes[1:])]
        robust=all_prices.groupby("cell").joint_target.all()
        summary.append([window,f"{benchmark.Sharpe:.3f}",f"{g.Sharpe.max():.3f}",f"{(g.Sharpe>1).sum()}/{len(g)}",
                        f"{g.joint_target.sum()}",str(robust.sum())])
    lines.extend([table(["Window","Frozen Sharpe","Highest modeled Sharpe","Above 1 at $1M","Meet joint target at $1M",
                         "Joint target at both sizes, all prices"],summary),"",
           "Counts include correlated strike/maturity combinations and entry-phase diagnostics. Short 2026 windows have fewer than 12 months of data; their annualized metrics are particularly sensitive to individual days. The trial ledger identifies families and periods.","",
           "## What changed the portfolio","",
           "Central pricing and whole contracts, starting with $1M in 2007. The table reports Sharpe / CAGR / maximum drawdown. An asterisk marks a shorter history for the term-structure gate.",""])
    examples=[]
    for name,label in LABELS.items():
        cols=[]
        for w in ["full","refresh"]:
            r=primary[(primary.cell==name)&(primary.window==w)].iloc[0]
            cols.append(f"{r.Sharpe:.3f} / {r.CAGR:.2%} / {r.MaxDD:.2%}")
        examples.append([label+(" *" if name=="VIX3M" else ""),*cols])
    lines.extend([table(["Rule","Full history","2020–2026"],examples),"",
                  "The VIX/VIX3M rank first becomes available in September 2010. Its deltas use a separately initialized benchmark from that date. The other full-history rows shown start in February 2007.","",
                  "![Return and drawdown across registered tests](return_drawdown.png)","",
                  "## Account size and pricing risk","",
                  "Each range below spans provisional central, higher-skew/wider-spread, and flatter-term pricing. Smaller accounts can skip a trade or be unable to sell half a contract. Whole-contract runs use raw ETF prices and a modeled $0.65 fee per contract per side.",""])
    rows=[]
    for cell in ["frozen","core-0.90-put","core-0.90-put-0.90","core-0.90-put-0.95"]:
        for size in sizes[1:]:
            q=t[(t.cell==cell)&(t.window=="refresh")&(t.capital_mode==size)]
            r=q[q.pricing=="central"].iloc[0]
            rows.append([LABELS[cell],f"${int(size):,}",f"{q.Sharpe.min():.3f}–{q.Sharpe.max():.3f}",
                         f"{r.CAGR:.2%}",f"{r.MaxDD:.2%}",f"[{r.ci05:+.3f}, {r.ci95:+.3f}]"])
    lines.extend([table(["Rule","Starting NAV","Refresh Sharpe range","Central CAGR","Central drawdown","90% paired ΔSharpe interval"],rows),"",
                  "The paired intervals use 2,000 moving-block draws of 63 trading sessions. They describe individual comparisons without a multiple-testing correction. Full-period drawdown matching uses hindsight. The late-window prior-fit cash comparison sets the allocation using data through 2016.","",
                  "## What can be concluded",""])
    checks=pd.read_csv(OUT/"refresh_checks.csv")
    candidate=checks[checks.cell=="core-0.90-put-0.95"]
    lines.extend(["**A new account in January 2020.** The main refresh table carries holdings, gains and the existing hedge into 2020. Starting from fresh capital and no put on December 31, 2019 changes contract counts and the first entry date. The following results isolate that difference.",""])
    rows=[]
    for size in [100000,1000000]:
        g=candidate[(candidate.capital==size)&(candidate.launch=="2019-12-31")&(candidate["sample"]=="refresh")]
        row=g[g.pricing=="central"].iloc[0]
        rows.append([f"${size:,}",f"{row.Sharpe:.3f}",f"{row.CAGR:.2%}",f"{row.MaxDD:.2%}",f"{g.Sharpe.min():.3f}–{g.Sharpe.max():.3f}"])
    lines.extend([table(["Starting NAV","Central Sharpe","CAGR","Max drawdown","Sharpe across pricings"],rows),"",
                  "**Which years mattered.** On the continuous $1M central path, excluding 2020 returns reduced the candidate’s refresh Sharpe to 0.956, and excluding 2023 reduced it to 0.940. Excluding 2022 raised it to 1.313. Each exclusion uses the original portfolio trajectory with one year of returns omitted. This shows how much of the result came from strong years as well as from crash protection.","",
                  "**What the simpler tests established.** In the full $1M central run, the three-month put left a 38.76% drawdown and the 18-month put cost CAGR. A 95% strike at the original allocation reduced drawdown to 20.52% but cut CAGR to 9.00%. Selling half the put on fear widened drawdown to 27.31%. The 85/70 spread improved CAGR to 10.94% while allowing a 32.55% drawdown. The trend guard and the put each added protection: 49.29% drawdown with neither, 38.79% with the guard alone, 35.17% with the put alone and 24.73% with both.","",
                  "**Historical episodes.** Central $1M continuous simulation. The trough comes from unhedged v2. Each reported drawdown is the worst peak-to-trough loss in that episode’s peak-to-recovery interval.",""])
    epi=pd.read_csv(OUT/"declines.csv.gz")
    epi=epi[(epi.capital_mode=="1000000")&(epi.pricing=="central")&epi.cell.isin(["frozen","core-0.90-put-0.95"])]
    pairs=epi.pivot(index="trough",columns="cell",values="drawdown")
    lines.extend([table(["v2 trough","Frozen hedge","90% core / 95% put"],
                        [[date,f"{row['frozen']:.2%}",f"{row['core-0.90-put-0.95']:.2%}"] for date,row in pairs.iterrows()]),"",
                  "**Decision.** Retain the frozen hedge as the benchmark and advance the 90% core / 95% put to listed-quote validation. Under the refresh scenario it delivers more return with a smaller drawdown. Its retrospective selection, the fresh-account test, and the paired uncertainty interval all limit the evidence for treating 1 as its expected Sharpe.",""])
    for name in ["maturity","strike","guard","coverage","budget","exit","basis","structure","ladder","gate","core-weight","allocation-strike"]:
        g=primary[(primary.family==name)&(primary.window=="full")]
        passed=t[t.family==name].query('window in ["full","early","late","quote-era","refresh"] and capital_mode != "fractional"').groupby("cell").improved.all()
        lines.append(f"- **{name}** — {len(g)} registered variants. {passed.sum()} cleared the paired Sharpe, equal-drawdown CAGR and protection checks across both account sizes, all three pricing assumptions and all five long windows.")
    lines.extend(["","The allocation/strike interaction was added after observing the initial single-factor results. The full 80%/90% allocation by 90%/95% strike follow-up is disclosed. The core-weight control rows isolate how much return came from owning more equity. An increase in a retrospectively selected subperiod remains exploratory.","",
        "## Reproduction and limits","",
        "Run `python -m pytest tests`, `python research/options_experiments.py`, `python research/put_refresh_checks.py`, and `python research/put_report.py` from the worktree root. The registry and runner are in `research/options_experiments.py`. All window statistics are in `trials.csv.gz`, all baseline drawdown episodes in `declines.csv.gz`, and every central-price leg trade in `central_ledger.csv.gz`. The plain CSV scorecard supports filtering by cell, family, account size and period.","",
        "The simulation preserves next-close execution, funded purchases, T-bill proceeds and the existing minimum fill rule. Maturity rolls when one third of tenor remains. Budgets constrain trailing 365-day gross purchase spend relative to trade-date NAV. The primary 2×2 guard ablation keeps the QQQ trend sleeve invested with the guard disabled. Ladder phases delay initial entry by zero to eleven months and permit cash during startup. A continuous-strike zero-debit collar is a theoretical diagnostic. Collars limit calls to QQQ shares, model European settlement and omit American early assignment. SPY uses VIX and the same provisional surface parameters. Short-leg offset and net hedge P&L are distinct from gross long premium. Liquidation drawdown includes the modeled cost of closing every leg.","",
        "Prices for the whole-contract sizing experiment come from the public Yahoo Finance daily chart histories for QQQ and SPY, using the Close field. Cboe supplied SKEW and VIX3M. VIX3M is an S&P volatility proxy. The affordability of a particular listed QQQ put requires its actual ask. [Cboe VIX3M history](https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX3M_History.csv) · [Cboe SKEW history](https://cdn.cboe.com/api/global/us_indices/daily_prices/SKEW_History.csv)","",
        "No QuantConnect cloud backtest or real-option fill validation was performed. The quote audit is in `qc/options_quote_audit.ipynb`. It requires QuantBook access to listed option history. The source branch records the US equity-options audit window as starting in 2012; 2008 remains model-only. The branch’s original annualized risk-free series and synthetic QLD returns are retained for comparability. Confirm the executable ask, stress bids, assignment and realized account sizing before adopting an overlay. [QuantConnect option history](https://www.quantconnect.com/docs/v2/writing-algorithms/datasets/algoseek/us-equity-options)",""])
    lines.extend(ported_section(t, LABELS, OUT))
    (OUT/"REPORT.md").write_text("\n".join(lines))


if __name__=="__main__":
    main()
