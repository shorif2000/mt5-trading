"""Position sizing using verified instrument tick specifications."""

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal


@dataclass(frozen=True)
class SizingResult:
    volume: Decimal | None
    estimated_loss: Decimal | None
    accepted: bool
    reason: str


def calculate_volume(
    *,
    risk_cash: Decimal,
    entry: Decimal,
    stop: Decimal,
    tick_size: Decimal,
    tick_value_per_lot: Decimal,
    volume_min: Decimal,
    volume_max: Decimal,
    volume_step: Decimal,
    direction: str,
) -> SizingResult:
    if risk_cash <= 0:
        return SizingResult(None, None, False, "Risk cash must be positive.")
    if min(entry, stop, tick_size, tick_value_per_lot, volume_min, volume_max, volume_step) <= 0:
        return SizingResult(None, None, False, "All price and contract inputs must be positive.")
    if direction not in {"buy", "sell"}:
        return SizingResult(None, None, False, "Direction must be buy or sell.")
    if direction == "buy" and stop >= entry:
        return SizingResult(None, None, False, "A buy stop loss must be below entry.")
    if direction == "sell" and stop <= entry:
        return SizingResult(None, None, False, "A sell stop loss must be above entry.")

    distance = abs(entry - stop)
    ticks = distance / tick_size
    loss_per_lot = ticks * tick_value_per_lot
    raw_volume = risk_cash / loss_per_lot
    steps = (raw_volume / volume_step).to_integral_value(rounding=ROUND_DOWN)
    volume = steps * volume_step

    if volume < volume_min:
        minimum_loss = volume_min * loss_per_lot
        return SizingResult(
            None, minimum_loss, False,
            "Minimum broker volume exceeds the permitted monetary risk.",
        )
    if volume > volume_max:
        volume = (volume_max / volume_step).to_integral_value(rounding=ROUND_DOWN) * volume_step

    estimated_loss = volume * loss_per_lot
    if estimated_loss > risk_cash:
        return SizingResult(None, estimated_loss, False, "Calculated loss exceeds risk cash.")
    return SizingResult(volume, estimated_loss, True, "Volume calculated; independent review required.")
