"""Protective-put execution on LEAN minute quotes.

An after-close signal selects candidate symbols. A fresh quote during the next
session's opening window is required to submit a limit order. Only order events
move cash between sleeves. LEAN owns positions, fees and portfolio marks.
"""
from AlgorithmImports import *

from collections import Counter
from math import erf, exp, floor, isfinite, log, sqrt
from types import SimpleNamespace


def fresh_quote(bar, now):
    if bar is None or bar.is_fill_forward or bar.end_time != now or bar.bid is None or bar.ask is None:
        return None
    bid, ask = float(bar.bid.close), float(bar.ask.close)
    return (bid, ask) if 0 < bid <= ask and isfinite(ask) else None


def implied_put_delta(spot, strike, days, mid):
    """Approximate delta from a same-session mid for the optional roll-down rule."""
    time = max(days, 1) / 365
    rate = 0.03

    def cdf(x):
        return (1 + erf(x / sqrt(2))) / 2

    def price_delta(vol):
        width = vol * sqrt(time)
        d1 = (log(spot / strike) + (rate + vol * vol / 2) * time) / width
        price = strike * exp(-rate * time) * cdf(width - d1) - spot * cdf(-d1)
        return price, cdf(d1) - 1

    lo, hi = 0.01, 3.0
    if not price_delta(lo)[0] <= mid <= price_delta(hi)[0]:
        return None
    for _ in range(30):
        vol = (lo + hi) / 2
        if price_delta(vol)[0] > mid:
            hi = vol
        else:
            lo = vol
    return price_delta((lo + hi) / 2)[1]


class ProtectivePut:
    def __init__(self, algo):
        self.algo = algo

        def parameter(key, default):
            value = algo.get_parameter("hedge_" + key)
            return type(default)(value) if value not in (None, "") else default

        self.cover = parameter("cover", "unguarded").strip().lower()
        self.exit = parameter("exit", "hold").strip().lower()
        self.proceeds = parameter("proceeds", "tranche").strip().lower()
        self.moneyness = parameter("moneyness", 0.85)
        self.dte = parameter("dte", 365)
        self.roll_dte = parameter("roll_dte", 122)
        self.entry_p = parameter("entry_p", 0.50)
        self.exit_p = parameter("exit_p", 0.90)
        self.roll_delta = parameter("rolldown_delta", -0.60)
        if self.cover not in ("all", "unguarded") or self.proceeds not in ("tbill", "tranche"):
            raise ValueError("hedge_cover must be all or unguarded and hedge_proceeds must be tbill or tranche")
        if self.exit not in ("hold", "fear", "rolldown"):
            raise ValueError("hedge_exit must be hold, fear or rolldown")
        if not (0 < self.moneyness <= 1 and 7 < self.roll_dte < self.dte
                and 0 <= self.entry_p < self.exit_p <= 1 and -1 <= self.roll_delta < 0):
            raise ValueError("invalid hedge moneyness, tenor, roll timing or signal thresholds")

        self.bucket = 0.0
        self.held = None
        self.intent = None
        self.pending = None
        self.subscriptions = set()
        self.last_mark_quote = None
        self.stats = Counter()
        self.net_flow = 0.0

    def nonspendable_value(self):
        mark = float(self.algo.portfolio[self.held].holdings_value) if self.held is not None else 0.0
        return mark + self.bucket

    def plan(self, session, close, p, recede):
        """Create one intent once the equity decisions for this close are known."""
        a = self.algo
        self._finish_window()
        if self.pending is not None:
            return
        if self.held is not None and not a.portfolio[self.held].invested:
            self.held, self.last_mark_quote = None, None
        calm = p <= self.entry_p
        reason, replace_put = None, False
        if self.held is None:
            if calm:
                reason, replace_put = "entry", True
        else:
            days = (self.held.id.date.date() - session).days
            marked_today = self.last_mark_quote is not None and self.last_mark_quote[0].date() == session
            self.stats["held_sessions"] += 1
            self.stats["held_sessions_without_quote"] += not marked_today
            if days <= 7:
                reason = "expiry sale"
            elif self.exit == "fear" and p >= self.exit_p and recede:
                reason = "fear exit"
            elif self.exit == "rolldown" and marked_today:
                _, bid, ask = self.last_mark_quote
                delta = implied_put_delta(close, float(self.held.id.strike_price), days, (bid + ask) / 2)
                if delta is not None and delta <= self.roll_delta:
                    reason, replace_put = "roll-down", True
            if reason is None and days < self.roll_dte and calm:
                reason, replace_put = "roll", True

        nav = float(a.portfolio.total_portfolio_value)
        exposure = a.book["core"] + {"QLD": 2, "TQQQ": 3}.get(a.lev_mode, 0) * a.book["lev"]
        if self.cover == "all" and a.trend_on:
            exposure += a.book["trend"]
        target = max(0, floor(exposure * nav / (100 * close)))
        if reason == "entry" and target == 0:
            self.stats["zero_contract_target"] += 1
            reason = None
        candidates = self._subscribe(session, close) if replace_put and reason is not None else []
        active = set(candidates)
        if self.held is not None:
            active.add(self.held)
        for symbol in self.subscriptions - active:
            a.remove_security(symbol)
        self.subscriptions = active
        if reason is None:
            return
        self.intent = SimpleNamespace(session=session, reason=reason, buy=replace_put, candidates=candidates,
                                      target=target, powder=a.book["powder"] * nav,
                                      parked=0 if a.trend_on or a.powder is not None else a.book["trend"] * nav,
                                      submitted_buy=False, submitted_sell=False, cash_blocked=False)
        self.stats["intents"] += 1
        if replace_put and not candidates:
            self.stats["intents_without_candidates"] += 1

    def _subscribe(self, session, close):
        a = self.algo
        candidates = []
        for symbol in a.option_chain_provider.get_option_contract_list(a.qqq, a.time):
            if symbol == self.held or symbol.id.option_right != OptionRight.PUT:
                continue
            days = (symbol.id.date.date() - session).days
            if abs(days - self.dte) > min(120, self.dte - 8):
                continue
            score = 4 * abs(float(symbol.id.strike_price) / close - self.moneyness) + abs(days - self.dte) / 365
            candidates.append((score, str(symbol), symbol))
        shortlist = []
        for _, _, symbol in sorted(candidates)[:8]:
            if symbol not in self.subscriptions:
                a.add_option_contract(symbol, Resolution.MINUTE, fill_forward=False)
            shortlist.append(symbol)
        return shortlist

    def on_data(self, data):
        a = self.algo
        now = a.time
        held_quote = fresh_quote(data.quote_bars.get(self.held), now) if self.held is not None else None
        if held_quote is not None:
            self.last_mark_quote = (now, *held_quote)
        minute = now.hour * 60 + now.minute
        if minute > 600 and self.intent is not None and now.date() > self.intent.session:
            self._finish_window()
        intent = self.intent
        if (intent is None or now.date() <= intent.session or not 571 <= minute <= 600
                or self.pending is not None):
            return
        # The stock and bill orders from the same close have priority at the open.
        if a.transactions.get_open_orders():
            return
        if self.held is not None and a.portfolio[self.held].invested:
            if held_quote is not None and not intent.submitted_sell:
                intent.submitted_sell = True
                self._submit(self.held, -int(a.portfolio[self.held].quantity), held_quote)
        elif intent.buy and not intent.submitted_buy and intent.target > 0:
            # No use of unfilled proceeds or the trend sleeve's earmarked cash.
            capacity = max(0, min(intent.powder + self.bucket, float(a.portfolio.cash) - intent.parked))
            for symbol in intent.candidates:
                quote = fresh_quote(data.quote_bars.get(symbol), now)
                if quote is None or a.securities[symbol].symbol_properties.contract_multiplier != 100:
                    continue
                # Budget reserve allows for commissions. The actual broker fee comes from the fill.
                quantity = min(intent.target, floor(capacity / (100 * quote[1] + 2)))
                if quantity <= 0 or 2 * quantity < intent.target:
                    intent.cash_blocked = True
                    continue
                intent.submitted_buy = True
                self._submit(symbol, quantity, quote)
                break

    def _submit(self, symbol, quantity, quote):
        bid, ask = quote
        limit = ask if quantity > 0 else bid
        a = self.algo
        self.pending = SimpleNamespace(symbol=symbol, ticket=None, cancel_requested=False,
                                       entry=self.intent.reason == "entry", bought=False)
        ticket = a.limit_order(symbol, quantity, limit, tag=f"HEDGE {self.intent.reason}")
        self.stats["orders"] += 1
        a.log(f"[OPT ORDER] {a.time} {self.intent.reason} qty={quantity} {symbol} bid={bid:.2f} ask={ask:.2f}")
        if self.pending is not None:
            self.pending.ticket = ticket
            if ticket.status == OrderStatus.INVALID:
                self.stats["invalid_orders"] += 1
                self.pending = None

    def _finish_window(self):
        if self.pending is not None and not self.pending.cancel_requested:
            self.pending.cancel_requested = True
            self.pending.ticket.cancel("hedge opening window closed")
        if self.intent is not None:
            if not (self.intent.submitted_buy or self.intent.submitted_sell):
                key = "cash_blocked_intents" if self.intent.cash_blocked else "intents_without_order"
                self.stats[key] += 1
            self.intent = None

    def on_order_event(self, event):
        a = self.algo
        quantity = int(event.fill_quantity)
        if quantity and event.symbol == a.qqq:
            order = a.transactions.get_order_by_id(event.order_id)
            if order.type == OrderType.OPTION_EXERCISE:
                raise RuntimeError("A protective put delivered QQQ shares. Review expiry fills before using the run.")
        active = self.pending
        if active is None or event.symbol != active.symbol:
            return
        if active.ticket is not None and event.order_id != active.ticket.order_id:
            return
        if quantity:
            fee = float(event.order_fee.value.amount)
            cash = -quantity * 100 * float(event.fill_price) - fee
            self.net_flow += cash
            self.stats["buy_fills" if quantity > 0 else "sell_fills"] += 1
            self.stats["contracts_bought" if quantity > 0 else "contracts_sold"] += abs(quantity)
            if quantity > 0:
                active.bought = True
                self.held = event.symbol
                from_bucket = min(self.bucket, -cash)
                self.bucket -= from_bucket
                if self.intent is not None:
                    self.intent.powder = max(0, self.intent.powder + cash + from_bucket)
            else:
                if self.proceeds == "tbill":
                    self.bucket += max(0, cash)
                elif self.intent is not None:
                    self.intent.powder += cash
                if not a.portfolio[event.symbol].invested:
                    self.held, self.last_mark_quote = None, None
            a.log(f"[OPT FILL] {a.time} qty={quantity} {event.symbol} price={float(event.fill_price):.2f} "
                  f"fee={fee:.2f} cash={cash:.2f} restricted={self.bucket:.2f}")
        if event.status in (OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.INVALID):
            if active.entry and active.bought:
                # After premium is paid, unused P1 proceeds rejoin the powder.
                self.stats["restricted_cash_released"] += self.bucket
                self.bucket = 0.0
            if event.status != OrderStatus.FILLED:
                self.stats["invalid_orders" if event.status == OrderStatus.INVALID else "canceled_orders"] += 1
            self.pending = None

    def report(self):
        a = self.algo
        mark = self.nonspendable_value() - self.bucket
        a.log(f"[OPT SUMMARY] {dict(sorted(self.stats.items()))} net_cash={self.net_flow:.2f} "
              f"mark={mark:.2f} restricted={self.bucket:.2f} order_pending={self.pending is not None}")
