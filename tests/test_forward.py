"""Forward observation: forming bars excluded, stored bars merged, forward start respected,
and any change to a frozen file detected."""

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

from candidate_fixtures import h1_from
from test_backtest_engine import Bar
from test_candidates import CAL, at, base, long_breakout_retest

from trading.research.candidates import StrategyA
from trading.research.forward import (
    completed,
    digest,
    forward_signals,
    freeze_mismatches,
    merge_rows,
)

T = datetime(2026, 11, 16, 14, 0, tzinfo=UTC)


def test_the_bar_still_forming_is_never_used():
    bars = [Bar(T + i * timedelta(minutes=15), 1, 1, 1, 1, 20) for i in range(3)]
    now = T + timedelta(minutes=40)  # third bar (14:30-14:45) is still forming
    assert completed(bars, now) == bars[:2]
    assert completed(bars, T + timedelta(minutes=45)) == bars


def test_a_fresh_copy_of_a_stored_bar_replaces_it():
    stored = [{"time": 1, "close": 1.0}, {"time": 2, "close": 2.0}]
    fresh = [{"time": 2, "close": 2.5}, {"time": 3, "close": 3.0}]
    assert merge_rows(stored, fresh) == [{"time": 1, "close": 1.0}, {"time": 2, "close": 2.5},
                                         {"time": 3, "close": 3.0}]  # fmt: skip


def test_only_signals_closing_at_or_after_the_forward_start_are_forward_evidence():
    bars = long_breakout_retest(base())
    a = StrategyA(bars, h1_from(bars), CAL, D("0.01"))
    signal_close = at("02:45")  # the 02:30 signal bar closes at 02:45
    [record] = forward_signals(a, start=signal_close)
    assert record["direction"] == "buy" and record["level"] == "Asian high"
    assert datetime.fromisoformat(record["signal_close_utc"]) == signal_close
    assert record["trading_day"] == date(2026, 10, 21).isoformat()
    assert forward_signals(a, start=signal_close + timedelta(minutes=15)) == []


def test_a_changed_frozen_file_is_reported(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("rule.md").write_text("fixed", encoding="utf-8")
    record = tmp_path / "freeze.json"
    record.write_text(json.dumps({"files": digest(["rule.md"])}), encoding="utf-8")
    assert freeze_mismatches(record) == []
    Path("rule.md").write_text("tuned", encoding="utf-8")
    assert freeze_mismatches(record) == ["rule.md"]


def test_an_arm_is_not_evaluated_before_100_events_and_26_weeks():
    from trading.research.forward import FORWARD_START, readiness

    later = FORWARD_START + timedelta(weeks=30)
    assert readiness(99, later).startswith("NOT READY: 99 of 100 events")
    assert readiness(150, FORWARD_START + timedelta(weeks=10)).startswith("NOT READY")
    assert readiness(100, later) == "READY FOR EVALUATION"
    assert readiness(40, datetime(2028, 11, 15, tzinfo=UTC)).startswith("FINAL: INSUFFICIENT")


def test_support_requires_every_criterion_and_a_few_big_wins_are_not_enough():
    from trading.research.forward import evaluate

    steady = [0.3, -0.2, 0.4, 0.1, -0.1] * 30
    ok = evaluate(steady, steady, steady, {"low": steady, "normal": steady, "high": [-1.0]})
    assert ok["outcome"].startswith("SUPPORTED")
    # Mostly losses with ten huge wins: positive mean, but not without the best 10.
    lucky = [-0.5] * 140 + [20.0] * 10
    result = evaluate(lucky, lucky, lucky, {"low": lucky, "normal": lucky})
    assert not result["checks"]["without_best_10_positive"]
    assert not result["outcome"].startswith("SUPPORTED")
