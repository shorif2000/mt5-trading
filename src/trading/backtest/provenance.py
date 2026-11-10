"""Provenance for a backtest run: the code, inputs, parameters and environment behind a result.

Every run gets a new report and a JSON manifest, never overwritten, meant to be committed to
the repository. Account identifiers (login, name, server, company) and the account type are
never recorded; only the margin terms that affect results are.
"""

import dataclasses
import hashlib
import json
import platform
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib import metadata
from pathlib import Path
from typing import Any

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
) -> dict[str, Any]:
    return {
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
