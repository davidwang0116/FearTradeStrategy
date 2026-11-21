"""Figure: (left) volatility risk premium by fear level; (right) Sharpe change from writing puts on the dry powder."""
import numpy as np
import pandas as pd

from common import BLUE, INK, INK2, MUTED, ORANGE, RES, SEQ5, build_signals, load_panel, plt, savefig

P = load_panel(); S = build_signals(P)
d = P.loc["2008-01-03":].copy()
r = np.log(P.qqq).diff()
d["rv_fwd"] = (r.shift(-1).rolling(21).std().shift(-20) * np.sqrt(252) * 100).reindex(d.index)
d["pct"] = S["Composite (dashboard v4)"].expanding(504).rank(pct=True).reindex(d.index)
d["recede"] = (P.vxn <= 0.9 * P.vxn.rolling(10).max()).reindex(d.index)
d = d.dropna(subset=["vxn", "rv_fwd", "pct"])
d["vrp"] = d.vxn - d.rv_fwd
groups = [("< 50th", d.pct < .5), ("50–80th", (d.pct >= .5) & (d.pct < .8)),
          ("≥ 80th, still rising", (d.pct >= .8) & ~d.recede), ("≥ 80th, receding", (d.pct >= .8) & d.recede)]
G = pd.DataFrame([dict(g=g, mean=d.vrp[m].mean(), p5=d.vrp[m].quantile(.05), pos=(d.vrp[m] > 0).mean(), n=m.sum()) for g, m in groups])
G.to_csv(RES / "vrp_by_fear.csv", index=False)

T = pd.read_csv(RES / "vol_selling_sensitivity.csv")
fig, (a1, a2) = plt.subplots(1, 2, figsize=(15, 5.6), gridspec_kw={"width_ratios": [1, 1.25]})
x = np.arange(len(G))
a1.bar(x, G["mean"], color=[SEQ5[2], SEQ5[3], ORANGE, SEQ5[1]], width=0.62)
for i, rw in G.iterrows():
    a1.text(i, rw["mean"] + (0.25 if rw["mean"] >= 0 else -0.25), f"{rw['mean']:+.1f}", ha="center",
            va="bottom" if rw["mean"] >= 0 else "top", fontsize=11, color=INK)
    a1.text(i, -1.9, f"positive {rw['pos']:.0%}\nworst 5%: {rw['p5']:.0f}", ha="center", va="top", fontsize=9.5, color=INK2)
a1.axhline(0, color=INK2, lw=0.8); a1.set_ylim(-4.5, 6.5)
a1.set_xticks(x, ["fear\n< 50th pct", "fear\n50–80th pct", "fear ≥ 80th pct\nstill rising", "fear ≥ 80th pct\nreceding"], fontsize=10)
a1.set_ylabel("VXN minus next-21-day realized vol (vol points)")
a1.set_title("The premium for selling volatility is thickest in moderate fear\nand vanishes at the panic peak (2008–2026)", loc="left", fontsize=12)
a1.grid(axis="x", visible=False)

lab = {"always 0% OTM": "Every month, at-the-money", "fear ≥ 50th & receding 0% OTM": "Fear ≥ 50th pct & receding, at-the-money",
       "fear ≥ 50th & receding 5% OTM": "Fear ≥ 50th pct & receding, 5% below spot"}
assump = T.drop_duplicates(["atm_iv", "haircut"])[["atm_iv", "haircut"]].values.tolist()
cols = [BLUE, SEQ5[3], ORANGE, MUTED]
for k, (ov, name) in enumerate(lab.items()):
    for j, (aiv, hc) in enumerate(assump):
        rw = T[(T.overlay == ov) & (T.atm_iv == aiv) & (T.haircut == hc)].iloc[0]
        y = k * 5 + j
        a2.plot([rw.ci5, rw.ci95], [y, y], color=cols[j], lw=2)
        a2.scatter(rw.dSharpe, y, color=cols[j], s=40, zorder=3)
a2.axvline(0, color=INK2, lw=0.9)
a2.set_yticks([k * 5 + 1.5 for k in range(len(lab))], [n.replace(", ", ",\n") for n in lab.values()], fontsize=10)
a2.set_xlim(-0.09, 0.09); a2.set_ylim(-1, 3 * 5 + 2.5)
a2.set_xlabel("Change in strategy Sharpe vs no puts (dot) with 90% block-bootstrap interval")
from matplotlib.lines import Line2D
a2.legend(handles=[Line2D([], [], color=c, lw=2, label=f"ATM IV {a}, bid/ask {h:.0%}") for c, (a, h) in zip(cols, assump)],
          loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=2, fontsize=9)
a2.set_title("Writing puts on the 30% dry powder:\nSharpe +0.00 to +0.02, every interval crosses zero", loc="left", fontsize=12)
a2.grid(axis="y", visible=False)
fig.tight_layout(w_pad=4)
savefig(fig, "fig_vol_selling.png")
print(G.round(2))
