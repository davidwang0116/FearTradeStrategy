"""12-month QQQ put hedge on the fear-tranche strategy, judged against holding less equity.

Plan: ~/.claude/plans (Stage 2), README "Options overlay". MODEL-PRICED (research/options_model.py); the
surface is provisional until qc/options_quote_audit.ipynb has fitted it on real 2012-2026 quotes.

Pre-registered, every cell reported (results/options_trials.csv):
  Hedge      one 12-month put struck at 85% of QQQ, units = covered dollars / QQQ price. Bought when the fear
             percentile p <= 0.50 and no hedge is held. Rolled (sell, buy a new one at today's price) when fewer
             than 4 months are left, only while p <= 0.50; otherwise held to expiry and cash-settled. A purchase
             is scaled down to the cash available, and skipped if that is below half of the target; the entry
             step then retries after the day's v2 rules and on later calm days.
  Coverage   all  = all equity dollars (core + trend half when on + 2 x QLD)
             unguarded = core + 2 x QLD only (the trend half already exits below 0.97 x MA200)
  Exit       fear     sell everything when p >= 0.90 and VXN <= 85% of its 10-day max (the QLD trigger)
             rolldown when the put's delta <= -0.60 at the signal close, sell it and buy a new 12-month 85%
                      put on current equity; the difference comes out as cash
             hold     no active exit, only the roll / expiry rule
  Proceeds   tbill    (P1) kept in a separate T-bill bucket that tranche and QLD buys cannot spend (it still
                      counts in NAV, so it enters the 7.5%-of-NAV tranche size and the QLD cap); it pays the
                      next premium first and rejoins the dry powder when the hedge is re-bought in calm
             tranche  (P2) added to the dry powder before the same close's tranche sizing
  Controls   C0 = v2 unhedged.  C1 = v2 with less equity: v2 held at weight k with the rest in T-bills outside
             the strategy (daily rebalanced, financing at T-bill + 60 bp above 1x), k solved (brentq) so that the
             full-window max drawdown equals the hedged cell's; CAGR compared at that point. The plan first used a
             lower core_target, but in v2 that does not lower MaxDD (-37.5% to -38.9% for core_target 0.40-0.95,
             results/options_core_target_frontier.csv): at low targets the tranches spend the extra powder in
             the crash, at high targets the trend guard cuts exposure instead.
  Pricing    central (provisional until the QC fit), pessimistic (put skew x1.5, spreads x2, ATM IV = VXN), and
             flat-term (kappa x2: 12-month IV rises half as much when VXN spikes, which cuts the crash-time value
             of the put; the main thing VXN cannot tell us about a 12-month option).
Timing: signal at close t, trades at close t+1. Order on each close: (1) returns, expiries, marks;
(2) option exits / rolls, proceeds routed; (3) v2 rules (QLD exit, tranche, QLD entry, greed trim, trend
guard); (4) hedge entry, premium from the bucket first, then the powder.
Base: v2 + QLD + trend guard, QQQ+SPY core, $100k, 2007-02-01 -> 2026-09-11 (2007 VXN is VIX x 1.056).

Outputs: results/options_trials.csv, options_monetizations.csv, options_episodes.csv, options_ledger_central.csv
(every option trade, input for qc/options_quote_audit.ipynb), options_core_target_frontier.csv
"""
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd
from scipy.optimize import brentq

import _paths  # noqa: F401  (puts the repo's research/ on sys.path)
from _paths import RESULTS as RES
from common import block_boot_delta, build_signals, load_panel, perf_stats
from options_model import Leg, OptionBook, load_surface, pessimistic
from strategy import Cfg, prepare

A_, B_ = "2007-02-01", "2026-09-11"
MIN_FILL = 0.5                    # skip a put purchase that cash can fund for less than half of its target
CORE = (("qqq", 0.5), ("spy", 0.5))
V2 = Cfg("v2 + QLD + trend guard", core=CORE, tranche=0.075, tranche_step=0.92, lev_cap=0.30,
         trend_guard=True, lev="qld")


@dataclass(frozen=True)
class Hedge:
    cover: str = "all"            # "all" | "unguarded"
    exit: str = "fear"            # "fear" | "rolldown" | "hold"
    proceeds: str = "tranche"     # "tbill" (P1) | "tranche" (P2)
    moneyness: float = 0.85
    tenor_days: int = 365
    roll_left_days: int = 122     # roll when fewer than ~4 months are left
    entry_p: float = 0.50
    exit_p: float = 0.90
    rolldown_delta: float = -0.60

    cover_ratio: float = 1.0
    budget_pa: float | None = None   # rolling purchase debits as a fraction of trade-date NAV
    gate: str = "p"
    beta: str | None = None
    dynamic: bool = False
    partial: float = 0.0
    partial_trigger: str = "fear"
    lower_m: float | None = None
    call_m: float | None = None
    cover_shares_only: bool = False
    ladder: int = 1
    phase_days: int = 0
    split_spy: bool = False
    whole: bool = False
    fee: float = 0.65               # research assumption, per contract per side in whole mode

    @property
    def label(self):
        return f"{self.cover} · {self.exit} · {self.proceeds}"


def run(D, c: Cfg, start=A_, end=B_, hedge: Hedge | None = None, surface=None, capital=100_000.0, keep_trend_invested=False):
    """strategy.run plus an optional put hedge. With hedge=None this must reproduce strategy.run exactly."""
    D = D.loc[start:end].copy()
    D = D.dropna(subset=["r_qqq"] + [f"r_{k}" for k, _ in c.core])
    n = len(D)
    idx = D.index
    core = {k: capital * c.core_target * w for k, w in c.core}
    trend = 0.0
    if c.trend_guard or keep_trend_invested:
        half = sum(core.values()) / 2
        core = {k: v / 2 for k, v in core.items()}
        trend = half
    trend_on = True
    trend_lev = False
    lev = 0.0
    cash = capital - sum(core.values()) - trend
    lev_entry_val, lev_cost_basis, lev_days = 0.0, 0.0, 0
    last_tranche_i, last_tranche_px, last_trim_i = -999, np.inf, -999
    lev_mult = {"qld": 2, "tqqq": 3}.get(c.lev, 0)
    # ---- option state ----
    surface = surface or (load_surface() if hedge else None)
    symbols = ("qqq", "spy") if hedge and hedge.split_spy else ("qqq",)
    books = [(symbol, rung, OptionBook(surface, fee_per_share=hedge.fee/100 if hedge.whole else 0.0)) for symbol in symbols
             for rung in range(hedge.ladder if hedge else 0)]
    first_entry = None
    purchases = []
    ledger = []
    def market(symbol, row):
        if symbol == "qqq":
            return row["raw_qqq" if hedge.whole else "qqq"], row["vxn"] / 100
        return row["raw_spy" if hedge.whole else "spy"], row["vix"] / 100

    def total(method):
        return sum(getattr(book, method)(market(symbol, row)[0], r, market(symbol, row)[1])
                   for symbol, _, book in books)

    bucket = 0.0                      # P1 proceeds (T-bills, invisible to the v2 rules)
    opt_flows = np.zeros(n)           # option cash flows by day (premiums < 0, sales / settlements > 0)
    opt_mark = np.zeros(n)
    hlog = []
    prior_deltas = {}
    nav = np.empty(n)
    liquidation = np.empty(n)
    rec = {k: np.empty(n) for k in ["core", "lev", "cash", "trend", "expo", "bucket", "opt", "held"]}
    trades = []
    prev = None
    for i, row in enumerate(D.to_dict("records")):
        S, r, vx = row["qqq"], row["rf"], row["vxn"] / 100
        # 1) returns for day i on positions held since close i-1
        if i > 0:
            for k in core:
                core[k] *= 1 + row["r_" + k]
            if trend_on:
                trend *= 1 + (row["r_qld"] if trend_lev else row["r_qqq"])
            else:
                trend *= 1 + row["rf"] / 252
            if lev > 0:
                lev *= 1 + row["r_" + c.lev]
                lev_days += 1
            cash *= 1 + row["rf"] / 252
            if books:
                bucket *= 1 + row["rf"] / 252
                for symbol, rung, book in books:
                    spot, _ = market(symbol, row)
                    book.step((idx[i] - idx[i - 1]).days)
                    x = book.expire(spot, idx[i])
                    if x:
                        opt_flows[i] += x
                        hlog.append(_hlog(idx[i], "expire", spot, x, row, None))
                        if hedge.proceeds == "tbill" and x >= 0:
                            bucket += x
                        else:
                            cash += x
        mark = total("mark")
        V = sum(core.values()) + trend + lev + cash + bucket + mark

        def equity_dollars():
            e = sum(core.values()) + lev_mult * lev
            if hedge.cover == "all" and trend_on:
                e += trend * (2 if trend_lev else 1)
            if hedge.split_spy:
                e = core.get("spy", 0) if symbol == "spy" else e - core.get("spy", 0)
            if hedge.beta:
                e += core.get("spy", 0) * (prev[hedge.beta] - 1)
            if hedge.call_m is not None or hedge.cover_shares_only:
                e = min(e, core.get("qqq", 0))
            ratio = hedge.cover_ratio
            if hedge.dynamic:
                ratio = 1.0 if prev["high_rv"] else 0.5
            return max(0.0, e * ratio / hedge.ladder)

        def route(x, why):
            """Send a hedge cash flow to P1 bucket / P2 powder; costs are paid from the bucket first."""
            nonlocal cash, bucket
            opt_flows[i] += x
            if x >= 0:
                if hedge.proceeds == "tbill":
                    bucket += x
                else:
                    cash += x
            else:
                from_b = min(bucket, -x)
                bucket -= from_b
                cash += x + from_b

        def buy_put(why):
            """Open a new 12-month put on current covered equity, scaled down if cash is short. If cash covers less
            than MIN_FILL of the target, buy nothing: the book stays empty, so step 4 retries after today's v2 rules
            (a QLD exit can free cash later the same close) and on later days, instead of holding a token put."""
            nonlocal first_entry
            if first_entry is not None:
                offset = 243 * rung / hedge.ladder
                if (idx[i] - first_entry).days < offset:
                    return 0.0
            elif rung or (idx[i] - idx[0]).days < hedge.phase_days:
                return 0.0
            T = hedge.tenor_days / 365.25
            legs = [("P", hedge.moneyness, 1)]
            if hedge.lower_m:
                legs.append(("P", hedge.lower_m, -1))
            call = hedge.call_m
            if call == 0:  # Continuous-strike diagnostic, including modeled crossing costs.
                def package_cost(m):
                    cost = book.cost_per_unit("P", hedge.moneyness*S, T, S, r, vx)
                    for right, strike in [("P", hedge.lower_m), ("C", m)]:
                        mid = book.quote(Leg(right, strike*S, T, -1, T), S, r, vx)[0]
                        cost -= book._fill(mid, -1, S, vx)
                    return cost
                if package_cost(1.0) > 0 or package_cost(2.0) < 0:
                    return 0.0
                call = brentq(package_cost, 1.0, 2.0)
            if call is not None:
                legs.append(("C", call, -1))
            want = equity_dollars() / S
            gross = book.cost_per_unit("P", hedge.moneyness * S, T, S, r, vx)
            net = gross
            for right, strike, side in legs[1:]:
                quote = book.quote(Leg(right, strike*S, T, side, T), S, r, vx)[0]
                net -= book._fill(quote, side, S, vx)
            unit_cost = net
            avail = max(cash, 0.0) + bucket
            units = min(want, avail / unit_cost) if unit_cost > 0 else want
            if hedge.budget_pa is not None:
                spent = sum(frac for date, frac in purchases if (idx[i]-date).days < 365)
                units = min(units, max(0, hedge.budget_pa-spent)*V / gross)
            if hedge.whole:
                units = 100 * np.floor(units / 100)
            if units * S < 100 or units < MIN_FILL * want:
                return 0.0
            flow = sum(book.open(right, strike*S, T, units*side, S, r, vx, idx[i], why)
                       for right, strike, side in legs)
            if hedge.budget_pa is not None:
                purchases.append((idx[i], units*gross/V))
            if first_entry is None:
                first_entry = idx[i]
            return flow

        eligible = hedge and prev is not None and (
            hedge.gate == "always" or prev[hedge.gate] <= hedge.entry_p)
        for symbol, rung, book in books:
            S, vx = market(symbol, row)
            if not book.legs or prev is None:
                continue
            prev_delta = prior_deltas[symbol, rung]
            fear_exit = prev["p"] >= hedge.exit_p and prev["vxn_recede"]
            delta_exit = prev_delta <= hedge.rolldown_delta
            long = book.legs[0]
            trigger = fear_exit if hedge.partial_trigger == "fear" else delta_exit
            if hedge.partial and trigger and not long.reduced:
                n = hedge.partial * long.units
                if hedge.whole:
                    n = 100 * np.floor(n / 100)
                if n:
                    route(book.reduce(0, n, S, r, vx, idx[i]), "partial")
                long.reduced = True
            elif hedge.exit == "fear" and fear_exit:
                x = book.close_all(S, r, vx, idx[i], "fear exit")
                route(x, "fear exit")
                hlog.append(_hlog(idx[i], "fear exit", S, x, row, prev_delta))
            elif (hedge.exit == "rolldown" and delta_exit) or (
                    long.T * 365.25 < hedge.roll_left_days and eligible):
                why = "roll-down" if hedge.exit == "rolldown" and delta_exit else "roll"
                x = book.close_all(S, r, vx, idx[i], why + " sell")
                route(x, why + " sell")
                y = buy_put(why + " buy")
                route(y, why + " buy")
                hlog.append(_hlog(idx[i], why, S, x + y, row, prev_delta))
        V = sum(core.values()) + trend + lev + cash + bucket + total("mark")
        # 3) execute orders decided on yesterday's close signal (prev) — identical to strategy.run
        if prev is not None and not c.fear_off:
            p, px, ma, recede = prev["p"], prev["qqq"], prev["ma200"], prev["vxn_recede"]
            core_v = sum(core.values()) + trend

            def buy_core(amt, why):
                nonlocal cash
                amt = min(amt, cash)
                if amt <= 1:
                    return
                tot_w = sum(w for _, w in c.core)
                for k, w in c.core:
                    core[k] += amt * w / tot_w * (1 - c.cost)
                cash -= amt
                trades.append((idx[i], why, amt))

            if lev > 0:
                gain = lev / lev_cost_basis - 1
                if (p <= c.lev_exit_p and px > ma) or gain >= c.lev_tp or lev_days >= c.lev_max_days:
                    cash += lev * (1 - c.lev_cost)
                    trades.append((idx[i], f"sell {c.lev} ({gain:+.0%})", lev))
                    lev, lev_cost_basis, lev_days = 0.0, 0.0, 0
                    excess = cash - (1 - c.core_target) * V
                    if excess > 0:
                        buy_core(excess, "reinvest")
            if not np.isnan(p) and p >= c.tranche_p and i - last_tranche_i >= c.tranche_gap and \
                    (px <= c.tranche_step * last_tranche_px or i - last_tranche_i > 126):
                if cash > 1:
                    buy_core(c.tranche * V, "tranche")
                    last_tranche_i, last_tranche_px = i, px
            if c.lev and not np.isnan(p) and p >= c.lev_p and recede and lev < c.lev_cap * V and cash > 1:
                amt = min(c.lev_size * V, c.lev_cap * V - lev, cash)
                if amt > 1:
                    lev += amt * (1 - c.lev_cost)
                    lev_cost_basis += amt
                    cash -= amt
                    trades.append((idx[i], f"buy {c.lev}", amt))
            if not np.isnan(p) and p <= c.greed_p and px >= c.greed_stretch * ma and i - last_trim_i >= 21:
                core_v = sum(core.values()) + trend
                over = core_v - c.core_target * V
                if over > 0.01 * V:
                    f = over / core_v
                    for k in core:
                        cash += core[k] * f * (1 - c.cost)
                        core[k] *= 1 - f
                    cash += trend * f * (1 - c.cost) if trend_on else trend * f
                    trend *= 1 - f
                    last_trim_i = i
                    last_tranche_px = np.inf
                    trades.append((idx[i], "greed trim", over))
            if c.trend_guard and not np.isnan(ma):
                want = px >= 0.97 * ma
                if want != trend_on:
                    trend *= 1 - c.cost
                    trend_on = want
                    trades.append((idx[i], "trend " + ("on" if want else "off"), trend))
                wl = c.calm_lev and trend_on and not np.isnan(p) and p <= 0.5
                if wl != trend_lev and (wl or p >= 0.7 or not trend_on):
                    trend *= 1 - c.lev_cost
                    trend_lev = wl
                    trades.append((idx[i], "calm-lev " + ("on" if wl else "off"), trend))
        # 4) hedge entry in calm
        for symbol, rung, book in books:
            S, vx = market(symbol, row)
            if hedge.call_m is not None and book.legs:
                # Restore cover after a core trim by closing the entire package.
                calls = sum(-leg.units for leg in book.legs if leg.right == "C")
                if calls*S > core.get("qqq", 0) + 1e-7:
                    route(book.close_all(S, r, vx, idx[i], "coverage close"), "coverage close")
            if eligible and not book.legs:
                y = buy_put("entry")
                if y:
                    route(y, "entry")
                    hlog.append(_hlog(idx[i], "entry", S, y, row, None))
                    if hedge.proceeds == "tbill" and bucket > 0:
                        cash += bucket
                        bucket = 0.0
            prior_deltas[symbol, rung] = book.leg_delta(0, S, r, vx) if book.legs else 0
        mark = total("mark")
        V = sum(core.values()) + trend + lev + cash + bucket + mark
        nav[i] = V
        liquidation[i] = V - mark + total("liquidation")

        opt_mark[i] = mark
        rec["core"][i] = sum(core.values()) / V
        rec["trend"][i] = trend / V if trend_on else 0.0
        rec["lev"][i] = lev / V
        rec["cash"][i] = (cash + (0 if trend_on else trend)) / V
        rec["bucket"][i] = bucket / V
        rec["opt"][i] = mark / V
        rec["held"][i] = any(b.legs for _, _, b in books)
        hd = total("delta") / V
        rec["expo"][i] = rec["core"][i] + rec["trend"][i] * (2 if trend_lev else 1) + lev_mult * rec["lev"][i] + hd
        prev = row
    out = pd.DataFrame(rec, index=idx)
    out["nav"] = nav
    out["liquidation_nav"] = liquidation
    out["opt_flow"] = opt_flows
    out["opt_mark"] = opt_mark
    out["hedge_pnl"] = (opt_flows.cumsum() + opt_mark)        # cumulative $ P&L of the option book
    tr = pd.DataFrame(trades, columns=["date", "action", "amount"])
    hl = pd.DataFrame(hlog)
    for symbol, rung, book in books:
        ledger.extend(dict(event, underlying=symbol, rung=rung) for event in book.ledger)
    return out, tr, hl, sorted(ledger, key=lambda event: event["date"])


def _hlog(t, event, S, cash, row, delta):
    return dict(date=t, event=event, qqq=S, cash=cash, vxn=row["vxn"], delta=delta)


# ---------------------------------------------------------------------------------------------- analysis
def episodes(nav, thresh=-0.10):
    """(peak, trough, recovery) for drawdowns deeper than thresh."""
    dd = nav / nav.cummax() - 1
    out, inn, pk = [], False, nav.index[0]
    for t, v in dd.items():
        if v == 0:
            if inn:
                if mn < thresh:
                    out.append((pk, tro, t))
                inn = False
            pk = t
        else:
            if not inn:
                inn, mn, tro = True, 0.0, t
            if v < mn:
                mn, tro = v, t
    if inn and mn < thresh:
        out.append((pk, tro, nav.index[-1]))
    return out


def monetizations(res, tr, hl, qqq):
    """One row per hedge sale or settlement that brought cash in."""
    if hl.empty:
        return pd.DataFrame()
    rows = []
    nav = res["nav"]
    q = qqq.reindex(nav.index)
    qpeak = q.cummax()
    buys = tr[tr.action.isin(["tranche", "buy qld"])].set_index("date")["amount"]
    for _, h in hl[hl.event.isin(["fear exit", "roll-down", "expire", "roll"])].iterrows():
        if h["cash"] <= 0:
            continue
        t = h["date"]
        i = nav.index.get_loc(t)
        later = nav.index[i:]
        peak_before = qpeak.loc[t]
        rec = q.loc[t:][q.loc[t:] >= peak_before]
        end = rec.index[0] if len(rec) else nav.index[-1]
        win63 = nav.index[min(i + 63, len(nav) - 1)]
        rows.append(dict(date=t.date(), event=h["event"], qqq_dd_at_sale=q.loc[t] / peak_before - 1,
                         proceeds_pct_nav=h["cash"] / nav.loc[t], vxn=h["vxn"], delta_at_signal=h["delta"],
                         buys_next_63d_pct_nav=buys.loc[t:win63].sum() / nav.loc[t] if len(buys) else 0.0,
                         qqq_further_fall=q.loc[t:end].min() / q.loc[t] - 1,
                         nav_further_fall=nav.loc[t:end].min() / nav.loc[t] - 1,
                         trough_date=q.loc[t:end].idxmin().date()))
    return pd.DataFrame(rows)


FIN_SPREAD = 0.006                # financing over T-bills above 1x (same spread as the synthetic QLD)


def scaled(nav, rf, k):
    """v2 held at weight k with the rest in T-bills outside the strategy, rebalanced daily (risk_frontier.py)."""
    r = nav.pct_change().fillna(0.0)
    rfd = rf.reindex(nav.index).fillna(0.0) / 252
    fin = rfd + (FIN_SPREAD / 252 if k > 1 else 0.0)
    return nav.iloc[0] * (1 + k * r + (1 - k) * fin).cumprod()


def c1_for(base_nav, target_mdd, rf, lo=0.05, hi=1.5):
    """C1: v2 scaled with outside T-bills so that its max drawdown equals target_mdd.
    (Lowering core_target is NOT a cash control in v2: MaxDD stays at -37.5% to -38.9% for core_target 0.40-0.95;
    see results/options_core_target_frontier.csv.)"""
    mdd = lambda k: (lambda n: (n / n.cummax() - 1).min())(scaled(base_nav, rf, k)) - target_mdd
    k = brentq(mdd, lo, hi, xtol=1e-6)
    return k, scaled(base_nav, rf, k)


def row_stats(nav, rf, pre=""):
    st = perf_stats(nav, rf)
    return {pre + k: v for k, v in st.items()}


QC_A = "2012-01-03"                # QC's listed-option quotes start in Jan 2012


def window_vs_c1(nav, base_nav, rf, a, b, sfx):
    """Hedged vs its MaxDD-matched cash control on a sub-window (C1 re-solved on that window)."""
    n, bn = nav.loc[a:b], base_nav.loc[a:b]
    st, s0 = perf_stats(n, rf), perf_stats(bn, rf)
    k, c1 = c1_for(bn, st["MaxDD"], rf)
    s1 = perf_stats(c1, rf)
    return {"CAGR" + sfx: st["CAGR"], "Sharpe" + sfx: st["Sharpe"], "MaxDD" + sfx: st["MaxDD"],
            "v2_CAGR" + sfx: s0["CAGR"], "v2_Sharpe" + sfx: s0["Sharpe"], "v2_MaxDD" + sfx: s0["MaxDD"],
            "dCAGR_vs_C1" + sfx: st["CAGR"] - s1["CAGR"]}


GRID = [Hedge(cover=cv, exit=ex, proceeds=pr) for cv in ["all", "unguarded"] for ex in ["fear", "rolldown", "hold"]
        for pr in ["tbill", "tranche"]]


def main():
    P = load_panel()
    D = prepare(P, build_signals(P))
    rf = P["rf"]
    central = load_surface()
    surfaces = {"central": central, "pessimistic": pessimistic(central),
                "flat-term": replace(central, kappa=2 * central.kappa, source=central.source + " / flat-term")}
    print("surface:", central.source)
    base, base_tr, *_ = run(D, V2)
    eps = episodes(base["nav"])
    rows, monet, epi, ledgers = [], [], [], []
    st0 = perf_stats(base["nav"], rf)
    s12 = perf_stats(base["nav"].loc[QC_A:B_], rf)
    rows.append(dict(cell="C0 v2 unhedged", pricing="—", cover="", exit="", proceeds="", **st0, c1_k=np.nan,
                     n_sales=0, min_expo=base["expo"].min(), share_days_net_short=(base["expo"] < 0).mean(),
                     CAGR_1226=s12["CAGR"], Sharpe_1226=s12["Sharpe"], MaxDD_1226=s12["MaxDD"]))
    for pname, surf in surfaces.items():
        for h in GRID:
            res, tr, hl, led = run(D, V2, hedge=h, surface=surf)
            nav = res["nav"]
            st = perf_stats(nav, rf)
            ct, c1 = c1_for(base["nav"], st["MaxDD"], rf)
            s1 = perf_stats(c1, rf)
            b0 = block_boot_delta(nav, base["nav"], rf)
            b1 = block_boot_delta(nav, c1, rf)
            yrs = (nav.index[-1] - nav.index[0]).days / 365.25
            prem = -sum(x["cash"] for x in led if x["cash"] < 0)
            rows.append(dict(cell=h.label, pricing=pname, cover=h.cover, exit=h.exit, proceeds=h.proceeds, **st,
                             c1_k=ct, c1_CAGR=s1["CAGR"], c1_Sharpe=s1["Sharpe"], c1_Vol=s1["Vol"],
                             dCAGR_vs_C1=st["CAGR"] - s1["CAGR"], dSharpe_vs_C1=st["Sharpe"] - s1["Sharpe"],
                             dCAGR_vs_C0=st["CAGR"] - st0["CAGR"], dSharpe_vs_C0=st["Sharpe"] - st0["Sharpe"],
                             dMaxDD_vs_C0=st["MaxDD"] - st0["MaxDD"],
                             dSharpe_C0_ci5=b0["dSharpe"][1], dSharpe_C0_ci95=b0["dSharpe"][2],
                             dCAGR_C1_ci5=b1["dCAGR"][1], dCAGR_C1_ci95=b1["dCAGR"][2],
                             premium_paid_pct_nav_pa=prem / nav.mean() / yrs,
                             hedge_pnl_pct_start=res["hedge_pnl"].iloc[-1] / nav.iloc[0],
                             hedge_net_pct_nav_pa=res["hedge_pnl"].iloc[-1] / nav.mean() / yrs,
                             n_sales=int((hl.event.isin(["fear exit", "roll-down"])).sum()) if len(hl) else 0,
                             avg_bucket=res["bucket"].mean(), avg_opt=res["opt"].mean(),
                             min_expo=res["expo"].min(), share_days_net_short=(res["expo"] < 0).mean(),
                             **window_vs_c1(nav, base["nav"], rf, QC_A, B_, "_1226")))
            if pname == "central":
                L = pd.DataFrame(led)
                L["nav"] = res["nav"].reindex(pd.to_datetime(L["date"])).to_numpy()
                ledgers.append(L.assign(cell=h.label, moneyness=L.K / L.S, notional_pct_nav=(L.units.abs() * L.S) / L.nav,
                                        cash_pct_nav=L.cash / L.nav, mid_pct_spot=L.mid / L.S))
            m = monetizations(res, tr, hl, D["qqq"])
            if len(m):
                monet.append(m.assign(cell=h.label, pricing=pname))
            for pk, tro, rc in eps:
                w = nav.loc[pk:rc]
                hp = res["hedge_pnl"]
                epi.append(dict(cell=h.label, pricing=pname, peak=pk.date(), trough=tro.date(),
                                dd_v2=(base["nav"].loc[pk:rc] / base["nav"].loc[pk:rc].cummax() - 1).min(),
                                dd_cell=(w / w.cummax() - 1).min(),
                                hedge_pnl_pct=(hp.loc[tro] - hp.loc[pk]) / nav.loc[pk],
                                hedge_pnl_to_recovery_pct=(hp.loc[rc] - hp.loc[pk]) / nav.loc[pk]))
            print(f"{pname:11s} {h.label:28s} CAGR {st['CAGR']:.2%} vol {st['Vol']:.1%} Sh {st['Sharpe']:.3f} "
                  f"MDD {st['MaxDD']:.1%} minExpo {res['expo'].min():+.2f} | C1 k {ct:.3f} CAGR {s1['CAGR']:.2%} -> dCAGR {st['CAGR'] - s1['CAGR']:+.2%}",
                  flush=True)
    T = pd.DataFrame(rows)
    T.to_csv(RES / "options_trials.csv", index=False)
    pd.concat(monet).to_csv(RES / "options_monetizations.csv", index=False)
    pd.DataFrame(epi).to_csv(RES / "options_episodes.csv", index=False)
    # every option trade of the central cells: input for qc/options_quote_audit.ipynb (upload to the Object Store)
    pd.concat(ledgers)[["cell", "date", "event", "right", "moneyness", "T", "units", "notional_pct_nav", "mid_pct_spot",
                        "cash_pct_nav", "vxn", "S", "K", "mid", "cash", "nav"]].to_csv(RES / "options_ledger_central.csv",
                                                                                      index=False)
    # why core_target is not a cash control: v2's MaxDD barely moves with it
    fr = []
    for ct in np.arange(0.40, 0.951, 0.05):
        res, *_ = run(D, replace(V2, core_target=float(ct)))
        fr.append(dict(core_target=ct, **perf_stats(res["nav"], rf)))
    pd.DataFrame(fr).to_csv(RES / "options_core_target_frontier.csv", index=False)


if __name__ == "__main__":
    main()
