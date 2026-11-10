"""Broker-calculated margin checks for a proposed position (synthetic data only)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from typing import Any

import pytest

from trading.models import AccountSnapshot
from trading.risk.margin import (
    MarginAccount,
    MarginUnavailable,
    check_margin,
    margin_account_from_snapshot,
    parse_margin_response,
)

NOW = datetime(2026, 11, 10, 10, 0, tzinfo=UTC)


def response(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {"symbol": "XAUUSD", "side": "BUY", "volume": 0.01,
                              "price": 2000.2, "margin": 3.2}  # fmt: skip
    values.update(overrides)
    return values


def estimate(**overrides: Any):
    return parse_margin_response(response(**overrides), symbol="XAUUSD", side="BUY",
                                 volume=D("0.01"))  # fmt: skip


def account(**overrides: Any) -> MarginAccount:
    values: dict[str, Any] = {"currency": "GBP", "equity": D("100"), "margin": D("0"),
                              "free_margin": D("100"), "stop_out_mode": 0,
                              "margin_call_level": D("50")}  # fmt: skip
    values.update(overrides)
    return MarginAccount(**values)


def test_margin_free_margin_and_projected_level_are_reported():
    result = check_margin(account(equity=D("100"), margin=D("6.8"), free_margin=D("93.2")),
                          estimate())  # fmt: skip
    assert result.accepted
    assert result.required == D("3.2")
    assert (result.free_margin_before, result.free_margin_after) == (D("93.2"), D("90.0"))
    assert result.projected_margin_level == D("1000")  # 100 / (6.8 + 3.2) x 100


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"tool_error": "MT5 returned an error (code -2): Invalid params"}, "calculation failed"),
        ({"margin": None}, "margin is missing"),
        ({"margin": "3.2"}, "not a number"),
        ({"margin": 0.0}, "not a usable figure"),
        ({"margin": -1.0}, "not a usable figure"),
        ({"margin": float("nan")}, "not finite"),
        ({"price": 0.0}, "price 0.0 is not positive"),
        ({"symbol": "XAUUSD.crp"}, "different symbol or side"),
        ({"side": "SELL"}, "different symbol or side"),
        ({"volume": 0.02}, "different volume"),
    ],
)
def test_unavailable_or_invalid_margin_is_rejected(overrides, message):
    with pytest.raises(MarginUnavailable, match=message):
        estimate(**overrides)


def test_insufficient_free_margin_is_rejected():
    result = check_margin(account(free_margin=D("2")), estimate())
    assert not result.accepted
    assert "exceeds free margin 2 GBP" in " ".join(result.reasons)
    assert result.free_margin_after == D("-1.2")


@pytest.mark.parametrize(("margin_call", "accepted"), [("1000", False), ("999.9", True)])
def test_projected_margin_level_at_the_margin_call_level_is_rejected(margin_call, accepted):
    # Projected level exactly 1000 %: at the level is rejected, just below it is accepted.
    acct = account(equity=D("100"), margin=D("6.8"), free_margin=D("93.2"),
                   margin_call_level=D(margin_call))  # fmt: skip
    assert check_margin(acct, estimate()).accepted is accepted


def test_money_stop_out_mode_compares_free_margin_after_opening():
    acct = account(stop_out_mode=1, margin_call_level=D("97"))
    result = check_margin(acct, estimate())  # 100 - 3.2 = 96.8 free margin after
    assert not result.accepted and "free margin after opening 96.8" in " ".join(result.reasons)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [({"equity": D("0")}, "equity 0 GBP is not positive"),
     ({"stop_out_mode": 7}, "stop-out mode 7 is not supported")],
)  # fmt: skip
def test_unusable_account_figures_are_rejected(overrides, message):
    result = check_margin(account(**overrides), estimate())
    assert not result.accepted and message in " ".join(result.reasons)


def snapshot_account(age: timedelta, **overrides: Any) -> AccountSnapshot:
    values: dict[str, Any] = {"login": "REDACTED", "server": "Example-Demo", "currency": "GBP",
                              "balance": 100, "credit": 0, "equity": 100, "margin": 0,
                              "free_margin": 100, "timestamp": NOW - age, "stop_out_mode": 0,
                              "margin_call_level": 50}  # fmt: skip
    values.update(overrides)
    return AccountSnapshot(**values)


def test_account_figures_come_from_a_fresh_snapshot():
    acct = margin_account_from_snapshot(snapshot_account(timedelta(seconds=10)), now=NOW,
                                        maximum_age_seconds=120)  # fmt: skip
    assert (acct.equity, acct.free_margin, acct.margin_call_level) == (D("100"), D("100"), D("50"))


def test_stale_account_figures_are_rejected():
    with pytest.raises(MarginUnavailable, match="stale"):
        margin_account_from_snapshot(snapshot_account(timedelta(minutes=5)), now=NOW,
                                     maximum_age_seconds=120)  # fmt: skip


def test_missing_margin_call_settings_are_rejected():
    with pytest.raises(MarginUnavailable, match="margin-call settings are missing"):
        margin_account_from_snapshot(
            snapshot_account(timedelta(seconds=10), margin_call_level=None), now=NOW,
            maximum_age_seconds=120,
        )  # fmt: skip
