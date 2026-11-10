"""Provenance for a backtest run: the code, inputs, parameters and environment behind a result.

Every run gets a new report and a JSON manifest, never overwritten, meant to be committed to
the repository. Account identifiers (login, name, server, company) and the account type are
never recorded; only the margin terms that affect results are.
"""

import dataclasses
import hashlib
import json
import os
import platform
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib import metadata
from pathlib import Path
from typing import Any

import yaml

from trading.models import AccountSnapshot, InstrumentSpec

SPEC_FIELDS = (
    "symbol",
    "contract_size",
    "tick_size",
    "point",
    "digits",
    "volume_min",
    "volume_max",
    "volume_step",
    "stops_level_points",
    "freeze_level_points",
    "calc_mode",
    "margin_currency",
    "swap_mode",
    "swap_long",
    "swap_short",
    "trade_allowed",
)
PACKAGES = ("mt5-trading-research", "pydantic", "pyyaml", "mcp", "truststore", "typer")


def _git(*args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args], capture_output=True, text=True, check=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout


def code_state() -> dict[str, Any]:
    """Commit, branch and any uncommitted changes. A dirty tree is recorded, not hidden."""
    commit = (_git("rev-parse", "HEAD") or "").strip() or None
    status = _git("status", "--porcelain", "--untracked-files=all") or ""
    changed = sorted(line[3:] for line in status.splitlines() if line.strip())
    diff = _git("diff", "HEAD") or ""
    return {
        "commit": commit,
        "short_commit": commit[:10] if commit else None,
        "branch": (_git("rev-parse", "--abbrev-ref", "HEAD") or "").strip() or None,
        "commit_date": (_git("show", "-s", "--format=%cI", "HEAD") or "").strip() or None,
        "dirty": bool(changed),
        "uncommitted_files": changed,
        "uncommitted_diff_sha256": hashlib.sha256(diff.encode()).hexdigest() if diff else None,
    }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _shareable(path: Path) -> str:
    """Repository-relative path, or just the file name: never a home directory."""
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return path.name


def inputs(paths: Mapping[str, Path]) -> dict[str, dict[str, Any]]:
    return {
        name: {"path": _shareable(path), "sha256": file_sha256(path), "bytes": path.stat().st_size}
        for name, path in paths.items()
    }


def environment() -> dict[str, Any]:
    versions: dict[str, str | None] = {}
    for package in PACKAGES:
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = None
    # OS and architecture only: enough to reproduce, without identifying the machine.
    system = f"{platform.system()} {platform.machine()}"
    return {"python": sys.version.split()[0], "platform": system, "packages": versions}


def instrument_terms(spec: InstrumentSpec) -> dict[str, Any]:
    return {name: getattr(spec, name) for name in SPEC_FIELDS}


def account_terms(account: AccountSnapshot) -> dict[str, Any]:
    """Margin terms only; never login, name, server or company."""
    return {
        "currency": account.currency,
        "leverage": account.leverage,
        "stop_out_mode": account.stop_out_mode,
        "margin_call_level": account.margin_call_level,
        "stop_out_level": account.stop_out_level,
    }


def plain(value: Any) -> Any:
    """JSON-safe copy of dataclasses, Decimals, datetimes and nested containers."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, Mapping):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [plain(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "isoformat"):  # time, date
        return value.isoformat()
    return value


def run_id(started: datetime, code: Mapping[str, Any]) -> str:
    stamp = started.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    commit = code.get("short_commit") or "nogit"
    return f"{stamp}_{commit}{'-dirty' if code.get('dirty') else ''}"


def unique_paths(directory: Path, identifier: str) -> tuple[Path, Path]:
    """New report and manifest paths; an existing run is never overwritten."""
    directory.mkdir(parents=True, exist_ok=True)
    for attempt in range(1000):
        suffix = f"_{attempt}" if attempt else ""
        report = directory / f"{identifier}{suffix}.md"
        manifest = directory / f"{identifier}{suffix}.json"
        if not report.exists() and not manifest.exists():
            return report, manifest
    raise RuntimeError(f"too many runs named {identifier} in {directory}")


def render_markdown(manifest: Mapping[str, Any]) -> str:
    code = manifest["code"]
    lines = [
        "## Provenance",
        "",
        f"- Run id: `{manifest['run_id']}` (started {manifest['started_utc']})",
        f"- Command: `{manifest['command']}`",
        f"- Code: commit `{code['commit']}` on `{code['branch']}` ({code['commit_date']})",
    ]
    if code["dirty"]:
        lines += [
            f"- **UNCOMMITTED CHANGES**: this result is not reproducible from the commit alone "
            f"(diff sha256 `{code['uncommitted_diff_sha256']}`). Files: "
            + ", ".join(f"`{f}`" for f in code["uncommitted_files"]),
        ]
    else:
        lines.append("- Working tree clean: reproducible from the commit and the inputs below")
    lines += ["", "| Input | sha256 | Bytes |", "|---|---|---|"]
    lines += [
        f"| `{name}` ({item['path']}) | `{item['sha256'][:16]}…` | {item['bytes']} |"
        for name, item in manifest["inputs"].items()
    ]
    env = manifest["environment"]
    lines += [
        "",
        f"- Environment: Python {env['python']} on {env['platform']}; "
        + ", ".join(f"{k} {v}" for k, v in env["packages"].items()),
        f"- Full parameters, instrument and account terms: `{manifest['manifest_path']}`",
        "",
        *_render_ai(manifest.get("ai_and_tools")),
        *_render_data(manifest.get("input_data"), manifest.get("data_sample")),
        *_render_trades(manifest.get("trade_sample")),
        "### Parameters",
        "",
        "```json",
        json.dumps(manifest["parameters"], indent=2, sort_keys=True),
        "```",
        "",
    ]
    return "\n".join(lines)


def build_manifest(
    *,
    code: Mapping[str, Any],
    started: datetime,
    command: Sequence[str],
    input_paths: Mapping[str, Path],
    parameters: Mapping[str, Any],
    manifest_path: Path,
    results: Mapping[str, Any],
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        **plain(extra or {}),
        "run_id": run_id(started, code),
        "started_utc": started.astimezone(UTC).isoformat(),
        "command": " ".join([Path(command[0]).name, *command[1:]]) if command else "",
        "code": code,
        "inputs": inputs(input_paths),
        "environment": environment(),
        "parameters": plain(parameters),
        "results": plain(results),
        "manifest_path": _shareable(manifest_path),
    }


# --- AI model, tools and data -----------------------------------------------------------


def ai_and_tools(config_path: Path, bridge_repo: Path | None) -> dict[str, Any]:
    """Declared AI assistance and add-ons, plus the evidence this process can read itself."""
    declared = None
    if config_path.exists():
        declared = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    trailers = _git("log", "--format=%(trailers:key=Co-Authored-By,valueonly)") or ""
    co_authors: dict[str, int] = {}
    for line in trailers.splitlines():
        name = line.split("<")[0].strip()
        if name:
            co_authors[name] = co_authors.get(name, 0) + 1
    bridge = None
    if bridge_repo is not None:
        commit = _git("-C", str(bridge_repo), "rev-parse", "HEAD")
        status = _git("-C", str(bridge_repo), "status", "--porcelain")
        bridge = {
            "project": bridge_repo.name,
            "commit": commit.strip() if commit else None,
            "dirty": bool(status and status.strip()),
        }
    return {
        "declared": declared,
        "evidence": {
            "run_from_claude_code_session": os.environ.get("CLAUDECODE") == "1",
            "git_co_author_commits": co_authors,
            "git_commits_total": len((_git("rev-list", "HEAD") or "").split()),
            "mt5_bridge_repository": bridge,
        },
    }


def describe_series(history: Mapping[str, Any], coverage: Mapping[str, Any]) -> dict[str, Any]:
    """Source, retrieval and coverage of the downloaded history, without account details."""
    status = history.get("terminal_status") or {}
    return {
        "source": "MetaTrader 5 terminal via the read-only mt5-mcp bridge (get_rates)",
        "downloaded_utc": history.get("downloaded_utc"),
        "broker_offset_seconds_at_download": status.get("broker_offset_seconds"),
        "terminal_build": (status.get("version") or {}).get("build"),
        "price_basis": "bid OHLC per bar plus the bar's spread in points; ask = bid + spread",
        "series": coverage,
    }


def bar_sample(bars: Sequence[Any], count: int = 3) -> list[dict[str, Any]]:
    """The first and last ``count`` bars exactly as the backtest used them."""
    chosen = [*bars[:count], *bars[-count:]] if len(bars) > 2 * count else list(bars)
    return [plain(bar) for bar in chosen]


def _render_ai(info: Mapping[str, Any] | None) -> list[str]:
    if not info:
        return []
    declared_all = info.get("declared") or {}
    declared = declared_all.get("ai_assistance") or {}
    addons = declared_all.get("add_ons") or {}
    evidence = info.get("evidence") or {}
    bridge = evidence.get("mt5_bridge_repository") or {}
    authors = ", ".join(
        f"{k} ({v} commits)" for k, v in evidence.get("git_co_author_commits", {}).items()
    )
    agents = [f"{a['name']} ({a['use']})" for a in declared.get("agents_used") or []]
    servers = [
        f"{m['name']} ({m['project']}): {str(m['use']).strip()}"
        for m in addons.get("mcp_servers") or []
    ]
    session = "yes" if evidence.get("run_from_claude_code_session") else "no"
    tools = agents + list(declared.get("other_tools") or [])
    dirty = " (uncommitted changes)" if bridge.get("dirty") else ""
    return [
        "### AI model, tools and add-ons",
        "",
        f"- AI assistance (declared in `config/provenance.yaml`): {declared.get('tool')}, "
        f"model {declared.get('model')} (`{declared.get('model_id')}`).",
        f"- Role: {str(declared.get('role', '')).strip()}",
        f"- Claude Code skills used: {', '.join(declared.get('skills_used') or []) or 'none'}",
        f"- Sub-agents and other tools: {'; '.join(tools)}",
        f"- MCP servers: {'; '.join(servers)}",
        f"- Evidence: run from a Claude Code session: {session}; git co-authors: "
        f"{authors or 'none'} of {evidence.get('git_commits_total')} commits; MT5 bridge "
        f"`{bridge.get('project')}` at `{bridge.get('commit')}`{dirty}.",
        "",
    ]


def _render_data(data: Mapping[str, Any] | None, sample: Mapping[str, Any] | None) -> list[str]:
    if not data:
        return []
    lines = [
        "### Input data",
        "",
        f"- Source: {data['source']}; price basis: {data['price_basis']}.",
        f"- Downloaded: {data.get('downloaded_utc') or 'not recorded'} (file last modified "
        f"{data.get('file_modified_utc')}); broker offset at download "
        f"{data.get('broker_offset_seconds_at_download')} s; terminal build "
        f"{data.get('terminal_build')}.",
        "",
        "| Series | Bars | First (UTC) | Last (UTC) | Gaps in scheduled hours |",
        "|---|---|---|---|---|",
    ]
    for name, item in data["series"].items():
        lines.append(
            f"| {name} | {item['bars']} | {item['first']} | {item['last']} | {item['gaps']} |"
        )
    if sample:
        lines += [
            "",
            "Data sample: first and last 3 bars of each series (bid OHLC, spread in points).",
            "",
            "| Series | Open (UTC) | Open | High | Low | Close | Spread |",
            "|---|---|---|---|---|---|---|",
        ]
        for name, bars in sample.items():
            lines += [
                f"| {name} | {b['open_time']} | {b['open']} | {b['high']} | {b['low']} | "
                f"{b['close']} | {b['spread_points']} |"
                for b in bars
            ]
    return [*lines, ""]


def _render_trades(sample: Mapping[str, Any] | None) -> list[str]:
    if not sample:
        return []
    lines = [
        "### Backtest sample",
        "",
        "Base scenario, first 5 trades of each period; every trade is in the JSON manifest.",
        "",
        "| Period | Side | Entry (UTC) | Exit (UTC) | Entry fill | Exit fill | Stop | Target "
        "| Volume | Exit | Net (GBP) |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for period, trades in sample.items():
        lines += [
            f"| {period} | {t['direction']} | {t['entry_time']} | {t['exit_time']} | "
            f"{t['entry_price']} | {t['exit_price']} | {t['stop']} | {t['target']} | "
            f"{t['volume']} | {t['exit_reason']} | {float(t['net_gbp']):.2f} |"
            for t in trades
        ]
    return [*lines, ""]
