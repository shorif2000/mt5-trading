"""Offline XAUUSD backtest for the Version 1.0 strategy on a paper ledger. No order execution.

Bar processing, in chronological order, for each M15 bar:
1. A pending entry from the previous bar's signal fills at this bar's open (ask = bid open +
   bar spread for a buy, bid for a sell), after the entry-time checks, the 2 % sizing rule and
   the margin check, each of which can reject it.
2. An open position exits at this bar's open on a forced close (16:45 New York), on a trend
   exit flagged at the previous H1 close, or when the open gaps through its stop or target;
   otherwise within the bar on a stop or target hit, stop first when both are touched.
3. After the bar closes: a trend exit is flagged if a newly completed H1 bar invalidates the
   trend; without a position, the strategy is evaluated on this completed bar.

Every signal ends in one category: filtered (with the reason), rejected by risk, rejected by
margin, or executable. Only executable signals open positions and change the paper ledger.
"""

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from trading.backtest.bars import Bar
from trading.market_data.sessions import MarketCalendar
from trading.models import AccountSnapshot, Direction, InstrumentSpec, MarketSnapshot, Quote
from trading.risk.margin import (
    MarginAccount,
    MarginUnavailable,
    Side,
    check_margin,
    parse_margin_response,
)
from trading.risk.position_sizing import SizingRequest, size_position
from trading.risk.sizing_config import SizingConfig
from trading.strategies.xauusd_m15_pullback import Setup, XauusdM15Pullback, target_price

M15 = timedelta(minutes=15)
SYMBOL = "XAUUSD"
CONVERSION_SYMBOL = "GBPUSD"
MarginProvider = Callable[[Side, Decimal, Decimal], Mapping[str, Any]]


class Outcome(StrEnum):
    FILTERED = "filtered"
    RISK_REJECTED = "rejected_by_risk"
    MARGIN_REJECTED = "rejected_by_margin"
    EXECUTABLE = "executable"


@dataclass(frozen=True)
class SessionRules:
    """Amendment 1 and Appendix A.I, in New York time so US daylight saving is handled."""

    zone: str = "America/New_York"
    force_close: time = time(16, 45)
    no_entry_start: time = time(16, 0)  # 60 minutes before the 17:00 break
    no_entry_end: time = time(19, 0)  # 60 minutes after the 18:00 reopen


@dataclass(frozen=True)
class ExecutionCosts:
    """Adverse slippage per fill type, in points (1 point = the symbol's point, USD 0.01 for
    XAUUSD).

    - ``stop_exit_points``: evidence, a percentile of the account's observed stop-loss slippage.
    - ``entry_points`` and ``market_exit_points``: UNKNOWN (MT5 records no requested price for
      market orders), so each value is a labelled scenario, not an established fact.
    - ``take_profit_points``: evidence, take-profit fills showed median 0.
    Sizing allows ``entry_points`` plus the larger of the stop and market exit allowances, so
    the 2 % check always covers at least the slippage the simulation applies.
    """

    entry_points: Decimal
    stop_exit_points: Decimal
    market_exit_points: Decimal
    take_profit_points: Decimal = Decimal(0)
    sizing_stop_points: Decimal | None = None  # e.g. the p95 stop slippage; >= stop_exit_points
    label: str = ""

    def __post_init__(self) -> None:
        values = (self.entry_points, self.stop_exit_points, self.market_exit_points,
                  self.take_profit_points, self.sizing_stop_points or Decimal(0))  # fmt: skip
        if any(v < 0 for v in values):
            raise ValueError("slippage points must not be negative")
        if self.sizing_stop_points is not None and self.sizing_stop_points < self.stop_exit_points:
            raise ValueError("the sizing stop allowance must cover the simulated stop slippage")

    def sizing_allowance(self) -> Decimal:
        stop = max(self.stop_exit_points, self.sizing_stop_points or Decimal(0))
        return self.entry_points + max(stop, self.market_exit_points)


@dataclass(frozen=True)
class BacktestConfig:
    starting_balance: Decimal
    account_currency: str
    stop_out_mode: int
    margin_call_level: Decimal
    sizing: SizingConfig
    costs: ExecutionCosts
    sessions: SessionRules = field(default_factory=SessionRules)
    news_filter_available: bool = False  # Version 1.0 runs without an economic calendar
    # Signals are evaluated only for bars closing in [trade_from, trade_until); earlier bars
    # serve as indicator warm-up. A position open at trade_until is closed at its forced close.
    trade_from: datetime | None = None
    trade_until: datetime | None = None


@dataclass(frozen=True)
class SignalRecord:
    signal_time: datetime  # close of the signal bar
    direction: Direction
    outcome: Outcome
    reasons: tuple[str, ...]
    volume: Decimal | None = None
    estimated_loss: Decimal | None = None
    maximum_risk: Decimal | None = None
    minimum_volume_loss: Decimal | None = None  # when the 0.01 minimum exceeded the limit
    required_margin: Decimal | None = None
    pullback_event: datetime | None = None  # open of the pullback run this candle belongs to


@dataclass(frozen=True)
class TradeRecord:
    direction: Direction
    entry_time: datetime
    exit_time: datetime
    quoted_entry: Decimal  # ask (buy) or bid (sell) at the entry bar open
    entry_price: Decimal  # actual fill, including entry slippage
    exit_price: Decimal  # actual fill, including exit slippage
    stop: Decimal
    target: Decimal  # 2R from the quoted entry (Appendix A.F)
    volume: Decimal
    exit_reason: str
    exit_kind: str  # "stop", "target" or "market"
    # All amounts in GBP at the exit GBPUSD rate. Reconciliation (checked for every trade):
    # net = gross - spread - entry slippage - exit slippage - commission.
    gross_gbp: Decimal  # bid-to-bid move, before every cost
    spread_cost_gbp: Decimal  # long: entry bar spread; short: exit bar spread
    entry_slippage_gbp: Decimal
    exit_slippage_gbp: Decimal
    commission_gbp: Decimal
    net_gbp: Decimal
    planned_reward_to_risk: Decimal  # |target - entry fill| / |entry fill - stop|
    realised_r: Decimal | None  # net / estimated loss at sizing
    balance_after: Decimal
    maximum_risk: Decimal | None = None
    estimated_loss: Decimal | None = None

    @property
    def slippage_cost_gbp(self) -> Decimal:
        return self.entry_slippage_gbp + self.exit_slippage_gbp


@dataclass
class _Position:
    setup: Setup
    entry_time: datetime
    quoted_entry: Decimal
    entry_bid: Decimal
    entry_spread: Decimal  # price units
    entry_price: Decimal  # fill
    target: Decimal
    volume: Decimal
    force_close_at: datetime
    maximum_risk: Decimal | None = None
    estimated_loss: Decimal | None = None
    exit_next_open: str | None = None


@dataclass
class BacktestResult:
    signals: list[SignalRecord] = field(default_factory=list)
    trades: list[TradeRecord] = field(default_factory=list)
    starting_balance: Decimal = Decimal(0)
    final_balance: Decimal = Decimal(0)
    notes: list[str] = field(default_factory=list)


def _d(value: float) -> Decimal:
    return Decimal(str(value))


class Backtest:
    def __init__(
        self,
        *,
        m15: Sequence[Bar],
        h1: Sequence[Bar],
        conversion_m15: Sequence[Bar],
        spec: InstrumentSpec,
        conversion_spec: InstrumentSpec,
        calendar: MarketCalendar,
        config: BacktestConfig,
        margin_provider: MarginProvider | None,
        strategy: XauusdM15Pullback | None = None,
    ) -> None:
        self.m15, self.h1, self.spec, self.calendar, self.config = m15, h1, spec, calendar, config
        self.conversion_spec = conversion_spec
        self.conversion = {bar.open_time: bar for bar in conversion_m15}
        self.margin_provider = margin_provider
        self.point = _d(spec.point or spec.tick_size)
        self.tick = _d(spec.tick_size)
        self.contract = _d(spec.contract_size)
        self.zone = ZoneInfo(config.sessions.zone)
        self.strategy = strategy or XauusdM15Pullback(m15, h1, self.tick)
        commission = config.sizing.commission_per_lot.get(SYMBOL)
        if commission is None:
            raise ValueError("XAUUSD commission must be configured before a backtest")
        self.commission = commission
        self.costs = config.costs
        self.entry_slippage = config.costs.entry_points * self.point
        # Sizing uses the combined allowance of this cost scenario, never less than simulated.
        self.sizing = dataclasses.replace(
            config.sizing,
            slippage_points={
                **config.sizing.slippage_points,
                SYMBOL: config.costs.sizing_allowance(),
            },
        )
        self.balance = config.starting_balance

    # --- time rules ---------------------------------------------------------------------

    def _ny(self, moment: datetime) -> datetime:
        return moment.astimezone(self.zone)

    def _force_close_for(self, entry: datetime) -> datetime:
        local = self._ny(entry)
        day = (
            local.date()
            if local.time() < self.config.sessions.no_entry_end
            else (local.date() + timedelta(days=1))
        )
        return datetime.combine(day, self.config.sessions.force_close, tzinfo=self.zone)

    def _entry_time_problem(self, moment: datetime) -> str | None:
        rules, local = self.config.sessions, self._ny(moment).time()
        if rules.no_entry_start <= local < rules.no_entry_end:
            return "within 60 minutes of the daily break"
        if self.calendar.open_time(SYMBOL, moment, moment + M15) < M15:
            return "outside the verified trading session"
        if any(
            n.startswith("unconfirmed") for n in self.calendar.notes(SYMBOL, moment, moment + M15)
        ):
            return "date has an unconfirmed broker holiday schedule"
        if self._force_close_for(moment) <= moment + M15:
            return "too close to the forced close"
        return None

    def _window_is_complete(self, first: int, last: int) -> bool:
        for previous, current in zip(
            self.m15[first:last], self.m15[first + 1 : last + 1], strict=False
        ):
            missing = self.calendar.open_time(SYMBOL, previous.open_time + M15, current.open_time)
            if missing > self.calendar.max_unexplained_gap:
                return False
        return True

    # --- money ----------------------------------------------------------------------------

    def _usd_to_gbp_rate(self, moment: datetime) -> Decimal | None:
        """GBP per USD from the GBPUSD bar open at ``moment`` (or within the previous hour)."""
        for back in range(5):
            bar = self.conversion.get(moment - back * M15)
            if bar is not None:
                spread = bar.spread_points * _d(self.conversion_spec.point or 0.00001)
                mid = _d(bar.open) + spread / 2
                # 12 decimal places: exactly representable as a float, so the sizing snapshot
                # and the P/L conversion use the identical rate.
                return (1 / mid).quantize(Decimal("1E-12"))
        return None

    def _snapshot(self, fill: Bar, rate: Decimal) -> MarketSnapshot | None:
        """Decision-time market state for the sizing rules: the paper balance, the fill bar's
        quotes, and loss tick values converted with GBPUSD at that moment."""
        conversion = self.conversion.get(fill.open_time)
        if conversion is None:
            return None
        bid = _d(fill.open)
        ask = bid + fill.spread_points * self.point
        tick_value = float(self.contract * self.tick * rate)
        spec = self.spec.model_copy(
            update={
                "tick_value": tick_value,
                "tick_value_loss": tick_value,
                "tick_value_profit": tick_value,
            }
        )
        c_point = _d(self.conversion_spec.point or 0.00001)
        quotes = [
            Quote(
                symbol=SYMBOL,
                bid=float(bid),
                ask=float(ask),
                timestamp=fill.open_time,
                point=float(self.point),
                digits=self.spec.digits or 2,
            ),
            Quote(
                symbol=CONVERSION_SYMBOL,
                bid=conversion.open,
                ask=float(_d(conversion.open) + conversion.spread_points * c_point),
                timestamp=fill.open_time,
                point=float(c_point),
                digits=self.conversion_spec.digits or 5,
            ),
        ]
        balance = float(self.balance)
        account = AccountSnapshot(
            login="PAPER",
            server="paper",
            currency=self.config.account_currency,
            balance=balance,
            credit=0,
            equity=balance,
            margin=0,
            free_margin=balance,
            timestamp=fill.open_time,
            stop_out_mode=self.config.stop_out_mode,
            margin_call_level=float(self.config.margin_call_level),
        )
        return MarketSnapshot(
            account=account,
            quotes=quotes,
            instruments=[spec, self.conversion_spec],
            generated_at=fill.open_time,
        )

    # --- entries ----------------------------------------------------------------------------

    def _try_entry(
        self, setup: Setup, signal_time: datetime, fill: Bar
    ) -> tuple[SignalRecord, _Position | None]:
        direction = setup.direction

        def record(outcome: Outcome, *reasons: str, **extra: Any) -> tuple[SignalRecord, None]:
            return SignalRecord(signal_time, direction, outcome, reasons, **extra), None

        p = self.strategy.params
        if fill.spread_points > p.max_spread_points:
            return record(
                Outcome.FILTERED, f"entry spread {fill.spread_points} points above maximum"
            )
        bid = _d(fill.open)
        ask = bid + fill.spread_points * self.point
        entry = ask if direction == Direction.BUY else bid
        if abs(entry - setup.stop) > _d(p.max_stop_atr) * _d(setup.atr):
            return record(Outcome.FILTERED, "stop wider than 3 x ATR(14)")
        rate = self._usd_to_gbp_rate(fill.open_time)
        snapshot = self._snapshot(fill, rate) if rate is not None else None
        if snapshot is None or rate is None:
            return record(Outcome.RISK_REJECTED, "GBPUSD quote unavailable for currency conversion")
        request = SizingRequest(
            SYMBOL,
            "buy" if direction == Direction.BUY else "sell",
            entry,
            setup.stop,
            "executable",
            holding_nights=0,
        )
        sizing = size_position(snapshot, request, self.sizing, now=fill.open_time)
        if not sizing.accepted or sizing.volume is None:
            minimum = (
                sizing.estimated_loss
                if any(r.startswith("minimum volume") for r in sizing.reasons)
                else None
            )
            return record(
                Outcome.RISK_REJECTED,
                *sizing.reasons,
                maximum_risk=sizing.maximum_risk,
                minimum_volume_loss=minimum,
            )
        side: Side = "BUY" if direction == Direction.BUY else "SELL"
        if self.margin_provider is None:
            return record(
                Outcome.MARGIN_REJECTED,
                "broker margin unavailable (no margin source)",
                volume=sizing.volume,
                estimated_loss=sizing.estimated_loss,
            )
        try:
            response = self.margin_provider(side, sizing.volume, entry)
            estimate = parse_margin_response(
                response, symbol=SYMBOL, side=side, volume=sizing.volume
            )
        except MarginUnavailable as exc:
            return record(
                Outcome.MARGIN_REJECTED,
                str(exc),
                volume=sizing.volume,
                estimated_loss=sizing.estimated_loss,
            )
        account = MarginAccount(
            self.config.account_currency,
            self.balance,
            Decimal(0),
            self.balance,
            self.config.stop_out_mode,
            self.config.margin_call_level,
        )
        margin = check_margin(account, estimate)
        if not margin.accepted:
            return record(
                Outcome.MARGIN_REJECTED,
                *margin.reasons,
                volume=sizing.volume,
                estimated_loss=sizing.estimated_loss,
                required_margin=margin.required,
            )
        slip = self.entry_slippage if direction == Direction.BUY else -self.entry_slippage
        position = _Position(
            setup=setup,
            entry_time=fill.open_time,
            quoted_entry=entry,
            entry_bid=bid,
            entry_spread=ask - bid,
            entry_price=entry + slip,
            # Appendix A.F: 2R from the quoted entry, as an order's take profit would be set.
            target=target_price(entry, setup.stop, p.target_r, self.tick),
            volume=sizing.volume,
            force_close_at=self._force_close_for(fill.open_time),
            maximum_risk=sizing.maximum_risk,
            estimated_loss=sizing.estimated_loss,
        )
        signal = SignalRecord(
            signal_time,
            direction,
            Outcome.EXECUTABLE,
            sizing.reasons,
            volume=sizing.volume,
            estimated_loss=sizing.estimated_loss,
            maximum_risk=sizing.maximum_risk,
            required_margin=margin.required,
        )
        return signal, position

    # --- exits ------------------------------------------------------------------------------

    def _exit_level(self, position: _Position, bar: Bar) -> tuple[Decimal, str] | None:
        """Stop or target on this bar. Longs exit on the bid, shorts on the ask."""
        stop, target = position.setup.stop, position.target
        spread = bar.spread_points * self.point
        if position.setup.direction == Direction.BUY:
            o, h, lo = _d(bar.open), _d(bar.high), _d(bar.low)
            if o <= stop:
                return o, "stop (gap)"
            if o >= target:
                return o, "target (gap)"
            if lo <= stop:  # stop first when both are touched (conservative)
                return stop, "stop"
            if h >= target:
                return target, "target"
            return None
        o, h, lo = _d(bar.open) + spread, _d(bar.high) + spread, _d(bar.low) + spread
        if o >= stop:
            return o, "stop (gap)"
        if o <= target:
            return o, "target (gap)"
        if h >= stop:
            return stop, "stop"
        if lo <= target:
            return target, "target"
        return None

    def _close(
        self, position: _Position, bar: Bar, price: Decimal, reason: str, at: datetime
    ) -> TradeRecord | None:
        """Close at ``price``: the bid (long) or ask (short) level before exit slippage."""
        buy = position.setup.direction == Direction.BUY
        kind = "stop" if reason.startswith("stop") else (
            "target" if reason.startswith("target") else "market"
        )  # fmt: skip
        points = {"stop": self.costs.stop_exit_points, "target": self.costs.take_profit_points,
                  "market": self.costs.market_exit_points}[kind]  # fmt: skip
        exit_slip = points * self.point
        fill = price - exit_slip if buy else price + exit_slip
        rate = self._usd_to_gbp_rate(bar.open_time)
        if rate is None:
            return None
        exit_spread = bar.spread_points * self.point
        # Bid-to-bid move, then the costs on top of it, all in price units per ounce.
        if buy:
            gross_px = price - position.entry_bid
            spread_px = position.entry_spread  # bought at the ask, sold at the bid
            net_px = fill - position.entry_price
        else:
            gross_px = position.entry_bid - (price - exit_spread)
            spread_px = exit_spread  # sold at the bid, bought back at the ask
            net_px = position.entry_price - fill
        if net_px != gross_px - spread_px - self.entry_slippage - exit_slip:
            raise AssertionError(
                f"cost reconciliation failed for the trade at {position.entry_time}"
            )
        ounces = position.volume * self.contract
        commission = self.commission * position.volume
        net = net_px * ounces * rate - commission
        self.balance += net
        stop = position.setup.stop
        return TradeRecord(
            direction=position.setup.direction,
            entry_time=position.entry_time,
            exit_time=at,
            quoted_entry=position.quoted_entry,
            entry_price=position.entry_price,
            exit_price=fill,
            stop=stop,
            target=position.target,
            volume=position.volume,
            exit_reason=reason,
            exit_kind=kind,
            gross_gbp=gross_px * ounces * rate,
            spread_cost_gbp=spread_px * ounces * rate,
            entry_slippage_gbp=self.entry_slippage * ounces * rate,
            exit_slippage_gbp=exit_slip * ounces * rate,
            commission_gbp=commission,
            net_gbp=net,
            planned_reward_to_risk=abs(position.target - position.entry_price)
            / abs(position.entry_price - stop),
            realised_r=net / position.estimated_loss if position.estimated_loss else None,
            balance_after=self.balance,
            maximum_risk=position.maximum_risk,
            estimated_loss=position.estimated_loss,
        )

    def _with_event(self, record: SignalRecord, setup: Setup) -> SignalRecord:
        if setup.pullback_event_start < 0:
            return record
        event = self.m15[setup.pullback_event_start].open_time
        return dataclasses.replace(record, pullback_event=event)

    # --- run --------------------------------------------------------------------------------

    def run(self) -> BacktestResult:
        result = BacktestResult(starting_balance=self.balance)
        if not self.config.news_filter_available:
            result.notes.append("Not news-filtered: no economic calendar source (Version 1.0).")
        position: _Position | None = None
        pending: tuple[Setup, datetime] | None = None
        for index, bar in enumerate(self.m15):
            if pending is not None:
                setup, signal_time = pending
                pending = None
                if bar.open_time != signal_time:
                    record = SignalRecord(
                        signal_time,
                        setup.direction,
                        Outcome.FILTERED,
                        ("missing candle before entry",),
                    )
                else:
                    record, position = self._try_entry(setup, signal_time, bar)
                result.signals.append(self._with_event(record, setup))
            if position is not None:
                exit_at_open = None
                if bar.open_time >= position.force_close_at:
                    exit_at_open = "forced close 16:45 New York"
                elif position.exit_next_open:
                    exit_at_open = position.exit_next_open
                if exit_at_open:
                    price = (
                        _d(bar.open)
                        if position.setup.direction == Direction.BUY
                        else (_d(bar.open) + bar.spread_points * self.point)
                    )
                    hit: tuple[Decimal, str] | None = (price, exit_at_open)
                else:
                    hit = self._exit_level(position, bar)
                if hit is not None:
                    trade = self._close(position, bar, hit[0], hit[1], bar.open_time)
                    if trade is None:
                        result.notes.append(
                            f"trade at {position.entry_time} closed without a GBPUSD rate"
                        )
                    else:
                        result.trades.append(trade)
                    position = None
            close_time = bar.open_time + M15
            if position is not None:
                if (
                    close_time.minute == 0
                    and self.strategy.trend_at(close_time) != position.setup.direction
                ):
                    position.exit_next_open = "H1 trend invalidated"
                continue
            if pending is not None:
                continue
            if (self.config.trade_from and close_time < self.config.trade_from) or (
                self.config.trade_until and close_time >= self.config.trade_until
            ):
                continue
            candidate = self.strategy.evaluate(index)
            if candidate is None:
                continue
            h1_index = self.strategy.last_completed_h1(close_time)
            h1_fresh = h1_index is not None and (
                self.h1[h1_index].open_time + timedelta(hours=2) > close_time
            )
            first = max(0, index - self.strategy.params.pullback_max_bars)
            reason = self._entry_time_problem(close_time)
            if reason is None and not h1_fresh:
                reason = "missing H1 candles for the trend"
            elif reason is None and not self._window_is_complete(first, index):
                reason = "missing candles in the decision window"
            elif reason is None and bar.spread_points > self.strategy.params.max_spread_points:
                reason = f"signal spread {bar.spread_points} points above maximum"
            if reason:
                filtered = SignalRecord(
                    close_time, candidate.direction, Outcome.FILTERED, (reason,)
                )
                result.signals.append(self._with_event(filtered, candidate))
            else:
                pending = (candidate, close_time)
        if position is not None:
            last = self.m15[-1]
            price = (
                _d(last.close)
                if position.setup.direction == Direction.BUY
                else (_d(last.close) + last.spread_points * self.point)
            )
            trade = self._close(position, last, price, "end of data", last.open_time + M15)
            if trade is not None:
                result.trades.append(trade)
        result.final_balance = self.balance
        return result
