"""Every backtest run records the code, inputs and parameters behind its result."""

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from trading.backtest.engine import SessionRules
from trading.backtest.provenance import (
    account_terms,
    build_manifest,
    code_state,
    file_sha256,
    plain,
    render_markdown,
    run_id,
    unique_paths,
)
from trading.models import AccountSnapshot

STARTED = datetime(2026, 11, 10, 21, 30, 5, tzinfo=UTC)


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "strategy.py").write_text("RULE = 1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "initial")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_clean_tree_is_reproducible_from_the_commit(repo):
    code = code_state()
    assert code["dirty"] is False and code["uncommitted_files"] == []
    assert code["commit"] and len(code["commit"]) == 40
    assert run_id(STARTED, code) == f"20261110T213005Z_{code['commit'][:10]}"


def test_uncommitted_changes_are_recorded_not_hidden(repo):
    (repo / "strategy.py").write_text("RULE = 2\n")
    (repo / "new_rule.py").write_text("X = 1\n")
    code = code_state()
    assert code["dirty"] is True
    assert code["uncommitted_files"] == ["new_rule.py", "strategy.py"]
    assert code["uncommitted_diff_sha256"]
    assert run_id(STARTED, code).endswith("-dirty")
    manifest = {"run_id": "r", "started_utc": "t", "command": "mt5-trading backtest",
                "code": code, "inputs": {}, "environment": {"python": "3", "platform": "p",
                "packages": {}}, "parameters": {}, "manifest_path": "m.json"}  # fmt: skip
    assert "UNCOMMITTED CHANGES" in render_markdown(manifest)


def test_each_run_gets_new_files(tmp_path):
    first = unique_paths(tmp_path, "run")
    first[0].write_text("report")
    second = unique_paths(tmp_path, "run")
    assert second != first and not second[0].exists()
    assert all(p.suffix in (".md", ".json") and ".local" not in p.name for p in (*first, *second))


def test_input_hashes_identify_the_exact_files(tmp_path):
    path = tmp_path / "history.local.json"
    path.write_bytes(b"bars")
    assert file_sha256(path) == hashlib.sha256(b"bars").hexdigest()


def test_account_terms_exclude_identifiers():
    account = AccountSnapshot(login="12345678", server="Broker-Live 1", currency="GBP",
                              balance=100, credit=0, equity=100, margin=0, free_margin=100,
                              timestamp=STARTED, leverage=500, stop_out_mode=0,
                              margin_call_level=50)  # fmt: skip
    terms = json.dumps(account_terms(account))
    assert "12345678" not in terms and "Broker-Live" not in terms
    assert json.loads(terms)["leverage"] == 500 and "trade_mode" not in json.loads(terms)


def test_manifest_is_json_serialisable_with_parameters(repo, tmp_path):
    config = repo / "risk.yaml"
    config.write_text("x: 1\n")
    manifest = build_manifest(
        code=code_state(), started=STARTED, command=["mt5-trading", "backtest"],
        input_paths={"risk_config": config}, manifest_path=tmp_path / "m.local.json",
        parameters={"sessions": SessionRules(), "risk": Decimal("0.02")}, results={"a": 1},
    )  # fmt: skip
    text = json.dumps(manifest)
    assert manifest["parameters"]["sessions"]["force_close"] == "16:45:00"
    assert manifest["inputs"]["risk_config"]["sha256"] == file_sha256(config)
    assert json.loads(text)["parameters"]["risk"] == "0.02"


def test_plain_handles_nested_values():
    assert plain({"a": (Decimal("1.5"), STARTED)}) == {"a": ["1.5", STARTED.isoformat()]}


def test_durations_serialise_as_seconds():
    from datetime import timedelta

    assert plain({"holding": timedelta(hours=1, minutes=12)}) == {"holding": 4320.0}


def test_no_home_directory_in_the_manifest(repo, tmp_path):
    outside = tmp_path.parent / "elsewhere.json"
    outside.write_text("{}")
    manifest = build_manifest(
        code=code_state(), started=STARTED,
        command=["/Users/someone/project/.venv/bin/mt5-trading", "backtest"],
        input_paths={"export": outside}, manifest_path=repo / "reports" / "r.json",
        parameters={}, results={},
    )  # fmt: skip
    text = json.dumps(manifest)
    assert "/Users/someone" not in text and manifest["command"] == "mt5-trading backtest"
    assert manifest["inputs"]["export"]["path"] == "elsewhere.json"
    assert manifest["manifest_path"] == "reports/r.json"


# --- AI model, tools and data -------------------------------------------------------------


def test_ai_declaration_and_evidence_are_recorded(repo, monkeypatch):
    from trading.backtest.provenance import ai_and_tools

    (repo / "rule.py").write_text("X = 2\n")
    git(repo, "add", ".")
    git(
        repo,
        "commit",
        "-q",
        "-m",
        "change\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>",
    )
    declaration = repo / "provenance.yaml"
    declaration.write_text(
        "ai_assistance: {tool: Claude Code, model: Claude Opus 5.5, model_id: claude-opus-5-5,"
        " skills_used: [], agents_used: []}\nadd_ons: {mcp_servers: []}\n"
    )
    monkeypatch.setenv("CLAUDECODE", "1")
    info = ai_and_tools(declaration, bridge_repo=repo)
    assert info["declared"]["ai_assistance"]["model_id"] == "claude-opus-5-5"
    assert info["evidence"]["git_co_author_commits"] == {"Claude Opus 5.5": 1}
    assert info["evidence"]["run_from_claude_code_session"] is True
    assert info["evidence"]["mt5_bridge_repository"]["commit"]
    rendered = render_markdown(
        {"run_id": "r", "started_utc": "t", "command": "c", "code": code_state(), "inputs": {},
         "environment": {"python": "3", "platform": "p", "packages": {}}, "parameters": {},
         "manifest_path": "m", "ai_and_tools": plain(info)}
    )  # fmt: skip
    assert "Claude Opus 5.5 (`claude-opus-5-5`)" in rendered
    assert "Claude Code skills used: none" in rendered


def test_data_sample_takes_first_and_last_bars():
    from trading.backtest.bars import Bar
    from trading.backtest.provenance import bar_sample

    bars = [Bar(STARTED.replace(minute=i), 1, 2, 0.5, 1.5, 20) for i in range(10)]
    sample = bar_sample(bars, count=2)
    assert [b["open_time"] for b in sample] == [plain(bars[i])["open_time"] for i in (0, 1, 8, 9)]


def test_input_data_description_has_no_account_details():
    from trading.backtest.provenance import describe_series

    terminal = {"path": "C:\\\\Program Files\\\\MetaTrader 5"}
    status = {"broker_offset_seconds": 7200, "version": {"build": 6230}, "terminal": terminal}
    history = {"downloaded_utc": "2026-11-10T21:03:00+00:00", "terminal_status": status}
    described = describe_series(history, {"XAUUSD M15": {"bars": 1}})
    assert described["broker_offset_seconds_at_download"] == 7200
    assert "Program Files" not in json.dumps(described)
