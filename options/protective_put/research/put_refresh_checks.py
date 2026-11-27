"""Funded cold starts and crisis sensitivity for the exploratory allocation/strike candidates."""
from options_experiments import EXTENSIONS, SURFACES, perf_stats, registry, init, simulate
import options_experiments as exp
import pandas as pd

CELLS = ["unhedged","frozen","core-0.90-unhedged","core-0.90-put",
         "core-0.80-put-0.95","core-0.90-put-0.90","core-0.90-put-0.95"]


def main():
    init()
    rows=[]
    for size in [100000,1000000]:
        for price,surface in SURFACES.items():
            for name in CELLS:
                _, hedge, _ = registry()[name]
                weight = float(name.split("-")[1]) if name.startswith("core-") else .70
                for launch in ["2007-02-01","2019-12-31"]:
                    portfolio,*_ = simulate(hedge,False,surface,size,launch,exp.B_,weight)
                    n=portfolio.nav.loc["2019-12-31":]
                    meta=dict(cell=name,capital=size,pricing=price,launch=launch)
                    rows.append(dict(**meta,sample="refresh",**perf_stats(n,exp.D.rf)))
                    if launch=="2019-12-31":
                        continue
                    r=n.pct_change().dropna()
                    for yr in range(2020,2027):
                        keep=r.index.year!=yr
                        # Omit returns while retaining the original position history.
                        rf=exp.D.rf.reindex(r.index[keep])
                        sharpe=(r[keep]-rf/252).mean()/r[keep].std()*252**.5
                        rows.append(dict(**meta,sample=f"omit-{yr}",Sharpe=sharpe))
                        year=r[r.index.year==yr]
                        rows.append(dict(**meta,sample=str(yr),total_return=(1+year).prod()-1))
    pd.DataFrame(rows).to_csv(EXTENSIONS/"refresh_checks.csv",index=False)


if __name__=="__main__":
    main()
