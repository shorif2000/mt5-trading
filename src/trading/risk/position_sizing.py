"""Position sizing: the largest volume whose worst-case loss stays within the per-trade limit.

The limit is ``current account balance x risk fraction`` (2 % by default and at most), taken
from the validated MT5 snapshot and recalculated for every evaluation. Balance is used, not
equity, free margin or a fixed amount.

Loss per lot, in the account currency:

    adverse distance = |entry - stop| + spread (buy with a bid-based entry) + slippage
    loss per lot     = ceil(adverse distance / tick size) x tick_value_loss + commission

``tick_value_loss`` is MT5's value of one tick for a losing move, already in the account
currency. It is verified against the snapshot's own quotes and never replaced by the generic
``tick_value``. Every input problem rejects the calculation instead of being guessed.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_DOWN, Decimal
from typing import Literal

from trading.models import InstrumentSpec, MarketSnapshot, Quote
from trading.risk.currency import conversion_rate
from trading.risk.exposure import SymbolExposure, symbol_exposure
from trading.risk.sizing_config import SizingConfig

Direction = Literal["buy", "sell"]
# "bid": entry and stop are chart (bid) prices; a buy fills at the ask, so the spread is added.
# "executable": entry is the fill side (ask for a buy, bid for a sell); nothing is added.
EntryBasis = Literal["bid", "executable"]


@dataclass(frozen=True)
class SizingRequest:
    symbol: str
    direction: Direction
    entry: Decimal
    stop_loss: Decimal | None
    entry_basis: EntryBasis


@dataclass(frozen=True)
class LossModel:
    """Per-lot loss inputs, kept so the estimate can be recomputed and reviewed."""

    price_distance: Decimal
    spread: Decimal
    slippage: Decimal
    tick_size: Decimal
    tick_value_loss: Decimal
    commission_per_lot: Decimal

    @property
    def ticks(self) -> Decimal:
        total = self.price_distance + self.spread + self.slippage
        return (total / self.tick_size).to_integral_value(rounding=ROUND_CEILING)

    @property
    def loss_per_lot(self) -> Decimal:
        return self.ticks * self.tick_value_loss + self.commission_per_lot


@dataclass(frozen=True)
class SizingResult:
    accepted: bool
    reasons: tuple[str, ...]
    volume: Decimal | None = None
    estimated_loss: Decimal | None = None
    maximum_risk: Decimal | None = None
    account_currency: str | None = None
    loss_model: LossModel | None = None
    # Reported separately: the per-trade limit is not a portfolio-wide exposure limit.
    existing_exposure: SymbolExposure | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)


def _d(value: float) -> Decimal:
    return Decimal(str(value))


def _on_increment(price: Decimal, increment: Decimal) -> bool:
    return (price % increment) == 0


def estimated_loss(volume: Decimal, model: LossModel) -> Decimal:
    """Worst-case loss of ``volume`` lots, recomputed from the per-lot inputs."""
    adverse = model.price_distance + model.spread + model.slippage
    ticks = (adverse / model.tick_size).to_integral_value(rounding=ROUND_CEILING)
    return volume * (ticks * model.tick_value_loss + model.commission_per_lot)


def _floor_to_step(volume: Decimal, step: Decimal) -> Decimal:
    return (volume / step).to_integral_value(rounding=ROUND_DOWN) * step


def _freshness_problems(
    snapshot: MarketSnapshot, quote: Quote, now: datetime, max_age: timedelta
) -> list[str]:
    problems = []
    for label, moment in (
        ("snapshot", snapshot.generated_at),
        ("account", snapshot.account.timestamp),
        (f"{quote.symbol} quote", quote.timestamp),
    ):
        age = now - moment
        if age > max_age:
            problems.append(f"{label} data is stale ({age.total_seconds():.0f}s old)")
        elif age < -timedelta(seconds=5):
            problems.append(f"{label} data is timestamped in the future")
    return problems


def _tick_value_problem(
    snapshot: MarketSnapshot, spec: InstrumentSpec, tick_value_loss: Decimal, tolerance: Decimal
) -> str | None:
    """MT5's loss tick value must agree with contract size x tick size converted to the
    account currency with the snapshot's own quotes."""
    account_currency = snapshot.account.currency
    if not spec.quote_currency:
        return f"{spec.symbol}: profit currency unknown; tick value cannot be verified"
    rate = conversion_rate(snapshot, spec.quote_currency, account_currency)
    if rate is None:
        return (
            f"{spec.symbol}: no quotes to convert {spec.quote_currency} to {account_currency}; "
            "currency conversion cannot be verified"
        )
    expected = _d(spec.contract_size) * _d(spec.tick_size) * rate
    difference = abs(tick_value_loss - expected) / expected
    if difference > tolerance:
        return (
            f"{spec.symbol}: tick_value_loss {tick_value_loss} {account_currency} disagrees with "
            f"{expected:.6f} derived from contract size, tick size and quotes "
            f"({difference:.2%} > {tolerance:.2%}); conversion is unreliable"
        )
    return None


def size_position(
    snapshot: MarketSnapshot, request: SizingRequest, config: SizingConfig, *, now: datetime
) -> SizingResult:
    """Largest permitted volume for one proposed trade, or a rejection listing every reason."""

    def reject(*reasons: str) -> SizingResult:
        return SizingResult(False, tuple(reasons))

    account = snapshot.account
    currency = account.currency
    balance = _d(account.balance)
    if balance <= 0:
        return reject(f"account balance {balance} {currency} is not positive")
    maximum_risk = balance * config.risk_fraction

    quote = next((q for q in snapshot.quotes if q.symbol == request.symbol), None)
    spec = next((i for i in snapshot.instruments if i.symbol == request.symbol), None)
    if quote is None or spec is None:
        return reject(f"{request.symbol}: quote or instrument specification missing")

    problems = _freshness_problems(
        snapshot, quote, now, timedelta(seconds=config.maximum_data_age_seconds)
    )

    # Instrument specification
    missing = [
        name
        for name, value in (
            ("tick_value_loss", spec.tick_value_loss),
            ("point", spec.point),
            ("stops_level_points", spec.stops_level_points),
        )
        if value is None
    ]
    if missing:
        # No fallback to the generic tick_value: it values a winning move.
        problems.append(f"{spec.symbol}: specification incomplete, missing {', '.join(missing)}")
    if not spec.trade_allowed:
        problems.append(f"{spec.symbol}: symbol is not open for full trading")

    # Costs that MT5 does not report: must be configured explicitly.
    commission = config.commission_per_lot.get(request.symbol)
    slippage_points = config.slippage_points.get(request.symbol)
    if commission is None:
        problems.append(f"{request.symbol}: commission per lot is not configured")
    elif config.commission_currency != currency:
        problems.append(
            f"commission is configured in {config.commission_currency}, not the account "
            f"currency {currency}; conversion is not supported"
        )
    if slippage_points is None:
        problems.append(f"{request.symbol}: slippage assumption is not configured")

    # Prices
    entry, stop = request.entry, request.stop_loss
    tick_size = _d(spec.tick_size)
    if not entry.is_finite() or entry <= 0:
        problems.append("entry price must be a positive number")
    if stop is None:
        problems.append("stop loss is missing")
    elif not stop.is_finite() or stop <= 0:
        problems.append("stop loss must be a positive number")
    elif request.direction == "buy" and stop >= entry:
        problems.append("a buy stop loss must be below the entry price")
    elif request.direction == "sell" and stop <= entry:
        problems.append("a sell stop loss must be above the entry price")
    else:
        for label, price in (("entry", entry), ("stop loss", stop)):
            if not _on_increment(price, tick_size):
                problems.append(f"{label} {price} is not a multiple of the tick size {tick_size}")
        if spec.point is not None and spec.stops_level_points is not None:
            minimum = spec.stops_level_points * _d(spec.point)
            if abs(entry - stop) < minimum:
                problems.append(
                    f"stop distance {abs(entry - stop)} is below the broker stops level {minimum}"
                )

    if (
        problems
        or stop is None
        or commission is None
        or slippage_points is None
        or spec.tick_value_loss is None
        or spec.point is None
    ):
        return reject(*problems)

    tick_value_loss = _d(spec.tick_value_loss)
    conversion = _tick_value_problem(snapshot, spec, tick_value_loss, config.tick_value_tolerance)
    if conversion:
        return reject(conversion)

    spread = _d(quote.ask) - _d(quote.bid)
    model = LossModel(
        price_distance=abs(entry - stop),
        spread=spread
        if request.direction == "buy" and request.entry_basis == "bid"
        else Decimal(0),
        slippage=slippage_points * _d(spec.point),
        tick_size=tick_size,
        tick_value_loss=tick_value_loss,
        commission_per_lot=commission,
    )
    step, volume_min = _d(spec.volume_step), _d(spec.volume_min)
    volume = min(
        _floor_to_step(maximum_risk / model.loss_per_lot, step),
        _floor_to_step(_d(spec.volume_max), step),
    )
    exposure = symbol_exposure(snapshot, request.symbol)
    if volume < volume_min:
        minimum_loss = estimated_loss(volume_min, model)
        return SizingResult(
            False,
            (
                f"minimum volume {volume_min} would lose {minimum_loss:.2f} {currency}, above "
                f"the {maximum_risk:.2f} {currency} limit",
            ),
            estimated_loss=minimum_loss,
            maximum_risk=maximum_risk,
            account_currency=currency,
            loss_model=model,
            existing_exposure=exposure,
        )
    return check_volume(volume, model, maximum_risk, spec, currency, exposure)


def check_volume(
    volume: Decimal,
    model: LossModel,
    maximum_risk: Decimal,
    spec: InstrumentSpec,
    currency: str,
    exposure: SymbolExposure | None = None,
) -> SizingResult:
    """Independent final check of a volume: valid for the broker and within the risk limit.
    Also used to reject a proposed volume that would exceed the limit."""
    reasons = []
    step, low, high = _d(spec.volume_step), _d(spec.volume_min), _d(spec.volume_max)
    if not volume.is_finite() or volume <= 0:
        reasons.append(f"volume {volume} is not a positive number")
    else:
        if volume < low or volume > high:
            reasons.append(f"volume {volume} is outside the broker range {low} to {high}")
        if (volume % step) != 0:
            reasons.append(f"volume {volume} is not a multiple of the volume step {step}")
    loss = estimated_loss(volume, model) if not reasons else None
    if loss is not None and loss > maximum_risk:
        reasons.append(
            f"estimated loss {loss:.2f} {currency} exceeds the {maximum_risk:.2f} {currency} limit"
        )
    notes = ("per-trade limit only; existing exposure is not netted against it",)
    if reasons:
        return SizingResult(
            False, tuple(reasons), estimated_loss=loss, maximum_risk=maximum_risk,
            account_currency=currency, loss_model=model, existing_exposure=exposure, notes=notes,
        )  # fmt: skip
    return SizingResult(
        True,
        ("volume within the per-trade risk limit; independent review still required",),
        volume=volume,
        estimated_loss=loss,
        maximum_risk=maximum_risk,
        account_currency=currency,
        loss_model=model,
        existing_exposure=exposure,
        notes=notes,
    )
