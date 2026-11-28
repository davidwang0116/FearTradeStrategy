"""Staged entries after a fear trigger, measured one episode at a time.

Signals use the close and fill at the next close. A rule returns its orders as
(fill session, share of the budget). Every position is closed on the same
deadline, so entry rules differ only in when and how much they buy.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

COST = 0.0005          # per side, as in the repo's ETF cost
TRANCHES = 4           # the reserve is four equal tranches
WAIT = 10              # sessions allowed for a confirmation
GAP = 10               # sessions between ladder buys
STEP = 0.08            # ladder spacing below the last buy signal
ANCHOR_VIX = 24.0      # the volatility-scaled ladder equals STEP at this VIX
DELAY = 5              # sessions between the two halves of the fixed-delay control
SHORT_HOLD = 63        # the shorter holding period when 126 sessions are available


@dataclass
class Market:
    """Daily arrays for one trigger definition, all indexed by QQQ session."""

    close: np.ndarray
    vix: np.ndarray
    rf: np.ndarray                 # annual T-bill rate
    fear: np.ndarray               # trigger condition at the close
    calm: np.ndarray               # normalization condition at the close
    reference: np.ndarray          # VIX >= 24 with 20-day easing
    confirm: dict                  # name -> boolean array; unavailable dates are False
    known: dict                    # name -> boolean array, whether the input exists on that date


def episode_triggers(fear, calm):
    """First fear close of each episode. A new one needs a calm close in between."""
    starts, armed = [], True
    for session in range(len(fear)):
        if armed and fear[session]:
            starts.append(session)
            armed = False
        elif not armed and calm[session]:
            armed = True
    return starts


def first_before_calm(condition, calm, start, window):
    """First session after `start` with the condition, unless a calm close comes first or the window ends."""
    for session in range(start + 1, min(start + window + 1, len(condition))):
        if calm[session]:
            return None
        if condition[session]:
            return session
    return None


def all_now(market, start, deadline, amount=1.0):
    return [(start + 1, amount)]


def wait_for(name):
    def rule(market, start, deadline):
        session = first_before_calm(market.confirm[name], market.calm, start, WAIT)
        return [(session + 1, 1.0)] if session is not None else []
    return rule


def half_then(name):
    def rule(market, start, deadline):
        session = first_before_calm(market.confirm[name], market.calm, start, WAIT)
        return [(start + 1, 0.5)] + ([(session + 1, 0.5)] if session is not None else [])
    return rule


def half_then_delay_always(market, start, deadline):
    """Second half after a fixed delay, whatever fear does."""
    return [(start + 1, 0.5), (start + 1 + DELAY, 0.5)]


def half_then_delay(market, start, deadline):
    """Second half after a fixed delay, cancelled if fear normalizes on or before that close."""
    cancelled = market.calm[start + 1:start + DELAY + 1].any()
    return [(start + 1, 0.5)] + ([] if cancelled else [(start + 1 + DELAY, 0.5)])


def ladder(scaled):
    def rule(market, start, deadline):
        orders, last, price, vix = [(start + 1, 1 / TRANCHES)], start, market.close[start], market.vix[start]
        for session in range(start + GAP, deadline):
            if len(orders) == TRANCHES:
                break
            step = STEP * vix / ANCHOR_VIX if scaled else STEP
            if market.fear[session] and session - last >= GAP and market.close[session] <= (1 - step) * price:
                orders.append((session + 1, 1 / TRANCHES))
                last, price, vix = session, market.close[session], market.vix[session]
        return orders
    return rule


def persistent(market, start, deadline):
    orders = [(start + 1, 1 / TRANCHES)]
    for session in (start + GAP * k for k in range(1, TRANCHES)):
        if session < deadline and market.fear[session]:
            orders.append((session + 1, 1 / TRANCHES))
    return orders


def until_calm(rule):
    """The same plan, but the episode's first calm close cancels every later order."""
    def limited(market, start, deadline):
        return [(fill, amount) for fill, amount in rule(market, start, deadline)
                if not market.calm[start + 1:fill].any()]
    return limited


def late_reference(market, start, deadline):
    """First tranche at the trigger, a second when the 20-day easing rule first fires before fear normalizes."""
    session = first_before_calm(market.reference, market.calm, start, deadline - start - 1)
    return [(start + 1, 1 / TRANCHES)] + ([(session + 1, 1 / TRANCHES)] if session is not None else [])


# Group A spends one tranche. Group B plans the four-tranche reserve.
FIRST_ORDER = {
    "E0 all at the trigger": all_now,
    "E4 wait for VIX easing 5d": wait_for("VIX easing 5d"),
    "E5 half now, half on VIX easing 5d": half_then("VIX easing 5d"),
    "E6 half now, half after 5 sessions unless calm": half_then_delay,
    "E6u half now, half after 5 sessions always": half_then_delay_always,
}
CONFIRMATIONS = ("VXN 15% below 10d high", "QQQ 5-close breakout", "VIX/VIX3M back below 1")
FIRST_ORDER_SENSITIVITY = {
    f"{code} {text} {name}": make(name) for name in CONFIRMATIONS
    for code, text, make in (("E4", "wait for", wait_for), ("E5", "half now, half on", half_then))
}
RESERVE = {
    "R0 whole reserve at the trigger": all_now,
    "R1 first tranche only": lambda market, start, deadline: all_now(market, start, deadline, 1 / TRANCHES),
    "E1 price ladder (8%)": ladder(scaled=False),
    "E1v price ladder (VIX-scaled)": ladder(scaled=True),
    "E3 every 10 sessions while VIX is high": persistent,
    "E7 late tranche on 20-day easing": late_reference,
    "E1c price ladder (8%), cancelled when calm": until_calm(ladder(scaled=False)),
    "E1vc price ladder (VIX-scaled), cancelled when calm": until_calm(ladder(scaled=True)),
    "E3c every 10 sessions, cancelled when calm": until_calm(persistent),
}


def settle(orders, market, start, deadline):
    """Value a unit budget at the deadline, with idle cash earning T-bills, and summarize the path."""
    fills = {}
    for session, amount in orders:
        if session < deadline:
            fills[session] = fills.get(session, 0.0) + amount
    cash, holding, worst = 1.0, 0.0, 0.0
    low = start + 1 + int(np.argmin(market.close[start + 1:deadline + 1]))
    cash_at_low = None
    for session in range(start + 1, deadline + 1):
        if session > start + 1:
            cash *= 1 + market.rf[session] / 252
            holding *= market.close[session] / market.close[session - 1]
        if session in fills:
            amount = min(fills[session], cash)
            cash -= amount
            holding += amount * (1 - COST)
        worst = min(worst, cash + holding - 1)
        if session == low:
            cash_at_low = cash
    return dict(pnl=cash + holding * (1 - COST) - 1, deployed=float(sum(fills.values())), worst_mark=worst,
                cash_at_low=cash_at_low, orders=len(fills))


def timing_value(orders, market, deadline, average):
    """Dollars earned beyond an average-date purchase held for the same number of sessions."""
    total = 0.0
    for session, amount in orders:
        if session < deadline:
            total += amount * (market.close[deadline] / market.close[session] - 1 - average(deadline - session))
    return total


def paired(values, baseline):
    """Summary of paired episode differences, with an episode bootstrap and the detectable size."""
    difference = np.asarray(values, float) - np.asarray(baseline, float)
    n = len(difference)
    if not n:
        return dict(n=0)
    deviation = difference.std(ddof=1) if n > 1 else np.nan
    draws = np.random.default_rng(585).integers(0, n, (10_000, n))
    low, high = np.quantile(difference[draws].mean(axis=1), [.05, .95])
    rest = np.delete(difference, difference.argmax()) if n > 1 else np.array([np.nan])
    return dict(n=n, difference=difference.mean(), low90=low, high90=high, win_share=float((difference > 0).mean()),
                ties=int((difference == 0).sum()), without_best=float(rest.mean()),
                detectable=2.8 * deviation / np.sqrt(n))


def passes(row):
    """The selection rule: positive mean, at least 60% of episodes better, positive without the best one."""
    return bool(row["n"] and row["difference"] > 0 and row["win_share"] >= .6 and row["without_best"] > 0)


def average_hold(close, sessions):
    """Average return of buying on any listed session and holding, by holding length, staying inside the list's end."""
    last = sessions[-1]

    def average(length):
        usable = sessions[sessions + length <= last]
        return float((close[usable + length] / close[usable] - 1).mean()) if len(usable) else np.nan
    return average


# ---- exits: the whole order is bought at the trigger, and only the sales differ ----

LOW_WINDOW = 10        # sessions in the breakdown low
PEAK_SHARE = 0.6       # sell when VIX is 40% below its episode peak


def normalization(market, entry, deadline):
    """First close at or after the purchase on which the trigger's indicator is back at its median."""
    return next((t for t in range(entry, deadline) if market.calm[t]), None)


def breakdown(market, entry, deadline, armed):
    """First close below the prior ten closes. When armed, QQQ must first close above its prior five closes."""
    ready = not armed
    for t in range(entry, deadline):
        if ready and t >= LOW_WINDOW and market.close[t] < market.close[t - LOW_WINDOW:t].min():
            return t
        if market.confirm["QQQ 5-close breakout"][t]:
            ready = True
    return None


def vix_off_peak(market, entry, deadline, start):
    peak = market.vix[start]
    for t in range(entry, deadline):
        peak = max(peak, market.vix[t])
        if market.vix[t] <= PEAK_SHARE * peak:
            return t
    return None


def sale(session, share):
    """A close-time signal sells at the next close."""
    return [(session + 1, share)] if session is not None else []


def hold_to_deadline(market, start, deadline):
    return []


def on_normalization(market, start, deadline):
    return sale(normalization(market, start + 1, deadline), 1.0)


def on_breakdown(armed):
    return lambda market, start, deadline: sale(breakdown(market, start + 1, deadline, armed), 1.0)


def independent_halves(market, start, deadline):
    return (sale(normalization(market, start + 1, deadline), .5)
            + sale(breakdown(market, start + 1, deadline, True), .5))


def half_then_all_on_breakdown(market, start, deadline):
    calm = normalization(market, start + 1, deadline)
    broken = breakdown(market, start + 1, deadline, True)
    if broken is not None and (calm is None or broken <= calm):
        return sale(broken, 1.0)
    return sale(calm, .5) + sale(broken, .5)


def on_vix_off_peak(market, start, deadline):
    return sale(vix_off_peak(market, start + 1, deadline, start), 1.0)


def staged_time(market, start, deadline):
    """Thirds at equal intervals, the last at the deadline."""
    entry, span = start + 1, deadline - start - 1
    return [(entry + span // 3, 1 / 3), (entry + 2 * span // 3, 1 / 3)]


EXITS = {
    "X1 hold to the deadline": hold_to_deadline,
    "X2 VIX back to its median": on_normalization,
    "X3a price breakdown, armed by a recovery": on_breakdown(True),
    "X4a half on normalization, half on breakdown": independent_halves,
    "X5a half on normalization, all on breakdown": half_then_all_on_breakdown,
    "X6 VIX 40% below its episode peak": on_vix_off_peak,
    "X7 thirds over time": staged_time,
}
EXIT_REFERENCE = {"X3 price breakdown, as drafted": on_breakdown(False)}


def sell_at_short_hold(market, start, deadline):
    return [(start + 1 + SHORT_HOLD, 1.0)]


HOLD_LENGTHS = {"Sell after 63 sessions, then T-bills": sell_at_short_hold, "Hold 126 sessions": hold_to_deadline}


def settle_exit(sales, market, start, deadline):
    """Buy one unit at the trigger's next close, sell shares of it, and value it at the deadline."""
    entry = start + 1
    shares, left, cash, worst, exposure = (1 - COST) / market.close[entry], 1.0, 0.0, -COST, 0.0
    planned = {}
    for session, share in sales:
        if session < deadline:
            planned[session] = planned.get(session, 0.0) + share
    for session in range(entry, deadline + 1):
        if session > entry:
            cash *= 1 + market.rf[session] / 252
            exposure += left
        if session in planned:
            sold = min(planned[session], left)
            cash += sold * shares * market.close[session] * (1 - COST)
            left -= sold
        worst = min(worst, cash + left * shares * market.close[session] - 1)
    return dict(pnl=cash + left * shares * market.close[deadline] * (1 - COST) - 1, worst_mark=worst,
                exposure=exposure / (deadline - entry), sold_early=1 - left)


def exit_timing_value(sales, market, start, deadline, average):
    """Profit on each piece beyond holding QQQ from an average date for the same number of sessions."""
    entry, left, total = start + 1, 1.0, 0.0
    for session, share in sales:
        if session < deadline:
            total += share * (market.close[session] / market.close[entry] - 1 - average(session - entry))
            left -= share
    return total + left * (market.close[deadline] / market.close[entry] - 1 - average(deadline - entry))
