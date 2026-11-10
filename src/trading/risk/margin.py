"""Broker-calculated margin for a proposed position, kept separate from the 2 % loss rule.

The required margin comes only from MT5's ``order_calc_margin`` (the read-only ``calc_margin``
tool) for the exact symbol, side, volume and price. Nothing here estimates margin itself: an
unavailable, mismatched or invalid broker answer rejects the proposal.

Reported for a proposal:
- required margin (account currency, as MT5 returns it),
- free margin before and after opening,
- projected margin level = equity / (current margin + required margin) x 100.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from trading.models import AccountSnapshot

Side = Literal["BUY", "SELL"]
STOP_OUT_PERCENT = 0  # ACCOUNT_STOPOUT_MODE_PERCENT
STOP_OUT_MONEY = 1  # ACCOUNT_STOPOUT_MODE_MONEY


class MarginUnavailable(Exception):
    """MT5 did not return a usable margin figure for the proposal."""


@dataclass(frozen=True)
class MarginAccount:
    """Account figures margin is checked against: from a fresh MT5 snapshot or a paper ledger."""

    currency: str
    equity: Decimal
    margin: Decimal
    free_margin: Decimal
    stop_out_mode: int
    margin_call_level: Decimal


@dataclass(frozen=True)
class MarginEstimate:
    symbol: str
    side: Side
    volume: Decimal
    price: Decimal
    required: Decimal


@dataclass(frozen=True)
class MarginResult:
    accepted: bool
    reasons: tuple[str, ...]
    required: Decimal | None = None
    free_margin_before: Decimal | None = None
    free_margin_after: Decimal | None = None
    projected_margin_level: Decimal | None = None
    currency: str | None = None


def _number(value: object, where: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise MarginUnavailable(f"{where} is missing or not a number: {value!r}")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise MarginUnavailable(f"{where} is not a number: {value!r}") from exc
    if not number.is_finite():
        raise MarginUnavailable(f"{where} is not finite")
    return number


def parse_margin_response(
    response: Mapping[str, Any], *, symbol: str, side: Side, volume: Decimal
) -> MarginEstimate:
    """Validate a ``calc_margin`` response against the proposal it was requested for."""
    if "tool_error" in response:
        raise MarginUnavailable(f"MT5 margin calculation failed: {response['tool_error']}")
    if response.get("symbol") != symbol or response.get("side") != side:
        raise MarginUnavailable("margin response is for a different symbol or side")
    if _number(response.get("volume"), "margin response volume") != volume:
        raise MarginUnavailable("margin response is for a different volume")
    price = _number(response.get("price"), "margin response price")
    required = _number(response.get("margin"), "margin")
    if price <= 0:
        raise MarginUnavailable(f"margin response price {price} is not positive")
    if required <= 0:
        raise MarginUnavailable(f"MT5 returned margin {required}, which is not a usable figure")
    return MarginEstimate(symbol, side, volume, price, required)


def margin_account_from_snapshot(
    account: AccountSnapshot, *, now: datetime, maximum_age_seconds: int
) -> MarginAccount:
    age = now - account.timestamp
    if age > timedelta(seconds=maximum_age_seconds) or age < -timedelta(seconds=5):
        raise MarginUnavailable(f"account data is stale ({age.total_seconds():.0f}s old)")
    if account.stop_out_mode is None or account.margin_call_level is None:
        raise MarginUnavailable("account margin-call settings are missing")
    return MarginAccount(
        currency=account.currency,
        equity=Decimal(str(account.equity)),
        margin=Decimal(str(account.margin)),
        free_margin=Decimal(str(account.free_margin)),
        stop_out_mode=account.stop_out_mode,
        margin_call_level=Decimal(str(account.margin_call_level)),
    )


def check_margin(account: MarginAccount, estimate: MarginEstimate) -> MarginResult:
    """Accept only if the position fits the free margin and keeps the account above its
    margin-call level after opening."""
    reasons = []
    if account.equity <= 0:
        reasons.append(f"equity {account.equity} {account.currency} is not positive")
    if account.margin < 0:
        reasons.append(f"current margin {account.margin} is negative")
    if reasons:
        return MarginResult(False, tuple(reasons), currency=account.currency)

    after = account.free_margin - estimate.required
    total_margin = account.margin + estimate.required
    level = account.equity / total_margin * 100
    if after < 0:
        reasons.append(
            f"required margin {estimate.required} exceeds free margin {account.free_margin} "
            f"{account.currency}"
        )
    if account.stop_out_mode == STOP_OUT_PERCENT:
        if level <= account.margin_call_level:
            reasons.append(
                f"projected margin level {level:.1f}% is at or below the margin-call level "
                f"{account.margin_call_level}%"
            )
    elif account.stop_out_mode == STOP_OUT_MONEY:
        if after <= account.margin_call_level:
            reasons.append(
                f"free margin after opening {after} is at or below the margin-call level "
                f"{account.margin_call_level} {account.currency}"
            )
    else:
        reasons.append(f"stop-out mode {account.stop_out_mode} is not supported")
    return MarginResult(
        accepted=not reasons,
        reasons=tuple(reasons) or ("margin available; independent review still required",),
        required=estimate.required,
        free_margin_before=account.free_margin,
        free_margin_after=after,
        projected_margin_level=level,
        currency=account.currency,
    )
