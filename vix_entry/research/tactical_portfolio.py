"""Funded check for the tactical sleeve, outside the v2 engine.

The account starts 70% in a buy-and-hold core (half QQQ, half SPY) and 30% in
T-bills. Each trigger buys QQQ from the T-bills at the next close. Every lot has
its own sales and deadline, and its proceeds return to T-bills. There is no
trend guard and no QLD.
"""

import numpy as np
import pandas as pd

from tactical import COST, episode_triggers

CORE = 0.70


def run_sleeve(market, returns, dates, first, last, size, exit_rule, window):
    """Daily account values. `returns` holds QQQ and SPY daily returns on the market's sessions.

    `size` is the share of account value per trigger, capped by available cash.
    A size of 0 gives the static account.
    """
    begin, end = dates.searchsorted(first), dates.searchsorted(last)
    starts = [s for s in episode_triggers(market.fear, market.calm) if begin <= s < end - 1] if size else []
    core = {"qqq": CORE / 2, "spy": CORE / 2}
    cash, lots, values, record = 1 - CORE, [], [], []
    stats = dict(lots=0, short_of_cash=0)
    buys = {s + 1: s for s in starts}
    for t in range(begin, end + 1):
        if t > begin:
            for name in core:
                core[name] *= 1 + returns[name][t]
            cash *= 1 + market.rf[t] / 252
            for lot in lots:
                lot["value"] *= 1 + returns["qqq"][t]
        for lot in lots:
            share = lot["sales"].pop(t, 0.0) if t < lot["deadline"] else 1.0
            if share:
                # Shares are of the original order, so scale by what is still held.
                sold = lot["value"] if t >= lot["deadline"] else lot["value"] * min(1.0, share / lot["left"])
                lot["left"] -= share
                lot["value"] -= sold
                cash += sold * (1 - COST)
        lots = [lot for lot in lots if lot["value"] > 1e-12]
        if t in buys:
            account = sum(core.values()) + cash + sum(lot["value"] for lot in lots)
            wanted = size * account
            amount = min(wanted, cash)
            stats["lots"] += 1
            stats["short_of_cash"] += amount < wanted - 1e-12
            if amount > 1e-12:
                start, deadline = buys[t], min(t + window, len(dates) - 1)
                sales = {}
                for session, share in exit_rule(market, start, deadline):
                    sales[session] = sales.get(session, 0.0) + share
                lots.append(dict(value=amount * (1 - COST), left=1.0, sales=sales, deadline=deadline))
                cash -= amount
        tactical = sum(lot["value"] for lot in lots)
        account = sum(core.values()) + cash + tactical
        values.append(account)
        record.append((tactical / account, cash / account, (sum(core.values()) + tactical) / account))
    frame = pd.DataFrame(record, columns=["tactical", "cash", "equity"], index=dates[begin:end + 1])
    frame["nav"] = values
    return frame, stats


def matched_static(market, returns, dates, first, last, extra):
    """Static account with a constant extra QQQ weight (rebalanced daily) equal to the sleeve's average use."""
    begin, end = dates.searchsorted(first), dates.searchsorted(last)
    core, rest, nav = {"qqq": CORE / 2, "spy": CORE / 2}, 1 - CORE, [1.0]
    for t in range(begin + 1, end + 1):
        for name in core:
            core[name] *= 1 + returns[name][t]
        account = nav[-1]
        stake = extra * account
        rest = (rest - stake) * (1 + market.rf[t] / 252) + stake * (1 + returns["qqq"][t])
        nav.append(sum(core.values()) + rest)
    return pd.Series(nav, index=dates[begin:end + 1])


def sharpe(returns, bills):
    """The repo's Sharpe (`perf_stats`): mean excess return over the deviation of total returns."""
    return (returns - bills).mean() / returns.std(ddof=1) * np.sqrt(252)


def block_bootstrap_sharpe(a, b, rf, block=63, draws=3000):
    """90% interval for the Sharpe difference, resampling the same blocks of days from both accounts."""
    a, b = (x.pct_change().dropna() for x in (a, b))
    bills = (rf.reindex(a.index) / 252).to_numpy()
    a, b = a.to_numpy(), b.to_numpy()
    n, rng, out = len(a), np.random.default_rng(585), []
    difference = lambda days: sharpe(a[days], bills[days]) - sharpe(b[days], bills[days])
    for _ in range(draws):
        out.append(difference((rng.integers(0, n, n // block + 1)[:, None] + np.arange(block)).ravel()[:n] % n))
    low, high = np.quantile(out, [.05, .95])
    return float(difference(np.arange(n))), float(low), float(high)


def episode_low_reserve(frame, market, dates, window):
    """Reserve left, as a share of the account, at each episode's QQQ low in the window after the trigger."""
    position = {date: i for i, date in enumerate(frame.index)}
    values = []
    for start in episode_triggers(market.fear, market.calm):
        if start + 1 >= len(dates) or dates[start + 1] not in position or start + 1 + window >= len(dates):
            continue
        span = market.close[start + 1:start + 2 + window]
        low_date = dates[start + 1 + int(np.argmin(span))]
        if low_date in position:
            values.append(float(frame["cash"].iloc[position[low_date]]))
    return float(np.mean(values)) if values else None
