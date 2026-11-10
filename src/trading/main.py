"""CLI for read-only market snapshot diagnostics."""

import dataclasses
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from trading.backtest.cost_model import evidence_from_history, load_cost_model
from trading.backtest.engine import BacktestConfig, BacktestResult, MarginProvider, SessionRules
from trading.backtest.history_bars import coverage, load_history
from trading.backtest.provenance import (
    account_terms,
    ai_and_tools,
    bar_sample,
    build_manifest,
    code_state,
    describe_series,
    instrument_terms,
    render_markdown,
    run_id,
    unique_paths,
)
from trading.backtest.real_yield import RealYieldFilter, RealYieldParameters, load_series
from trading.backtest.runner import PERIODS, compare_versions, run_periods, run_scenarios
from trading.market_data.history import download_history_to_file
from trading.market_data.market_snapshot import load_snapshot
from trading.market_data.mcp_collector import (
    CollectorError,
    MarginSession,
    collect_to_file,
    margin_from_server,
    registered_server,
)
from trading.market_data.mcp_export import ExportRejected, ExportSettings, load_mcp_export
from trading.market_data.sessions import load_market_calendar
from trading.risk.exposure import floating_pnl, open_volume_by_symbol
from trading.risk.margin import (
    MarginUnavailable,
    Side,
    check_margin,
    margin_account_from_snapshot,
    parse_margin_response,
)
from trading.risk.sizing_config import load_sizing_config
from trading.strategies.xauusd_m15_pullback import PullbackParameters

app = typer.Typer(help="Read-only MT5 trading research diagnostics.")
console = Console()


@app.command()
def collect(
    output: Path = typer.Option(Path("data/mcp_export.local.json"), help="Raw export JSON"),
    bars: int = typer.Option(120, min=2, max=5000, help="Bars per timeframe, incl. forming"),
) -> None:
    """Collect a raw export using only read-only tools of the registered mt5 MCP server
    (trading forced off). The server command comes from ~/.claude.json, not from options."""
    settings = ExportSettings()
    try:
        collect_to_file(
            output,
            symbols=settings.symbols,
            timeframes=settings.timeframes,
            bars=bars,
        )
    except CollectorError as exc:
        console.print(f"[red]Collection failed:[/red] {exc}")
        raise typer.Exit(code=2) from exc
    console.print(f"Raw export written to {output}. Validate it with `mt5-trading ingest`.")


@app.command()
def ingest(
    export: Path = typer.Option(..., exists=True, readable=True, help="Raw MCP export JSON"),
    output: Path = typer.Option(Path("data/snapshot.local.json"), help="Validated snapshot"),
    maximum_age_seconds: int = typer.Option(120, min=1),
    minimum_candles: int = typer.Option(50, min=1),
    broker_timezone: str = typer.Option(
        ExportSettings.broker_timezone, help="IANA zone the broker clock follows"
    ),
    broker_shift_hours: int = typer.Option(
        ExportSettings.broker_shift_hours, help="Hours added to that zone's wall time"
    ),
    sessions: Path = typer.Option(
        Path("config/market_sessions.yaml"), exists=True, readable=True, help="Market calendar"
    ),
) -> None:
    """Validate a raw read-only MT5 MCP export and write a validated snapshot."""
    try:
        calendar = load_market_calendar(sessions)
    except ValueError as exc:
        console.print(f"[red]Market calendar rejected:[/red] {exc}")
        raise typer.Exit(code=2) from exc
    settings = ExportSettings(
        calendar=calendar,
        max_export_age_seconds=maximum_age_seconds,
        max_quote_age_seconds=maximum_age_seconds,
        min_completed_candles=minimum_candles,
        broker_timezone=broker_timezone,
        broker_shift_hours=broker_shift_hours,
    )
    try:
        data = load_mcp_export(export, now=datetime.now(UTC), settings=settings)
    except ExportRejected as exc:
        console.print("[red]Export rejected. Analysis is blocked:[/red]")
        for reason in exc.reasons:
            console.print(f"  - {reason}")
        raise typer.Exit(code=2) from exc

    output.write_text(data.model_dump_json(indent=2), encoding="utf-8")
    console.print(f"[green]Export accepted.[/green] Validated snapshot written to {output}")
    for line in calendar.summary():
        console.print(f"  Calendar: {line}")


@app.command()
def margin(
    snapshot: Path = typer.Option(
        Path("data/snapshot.local.json"), exists=True, readable=True, help="Validated snapshot"
    ),
    symbol: str = typer.Option(..., help="Broker symbol, e.g. XAUUSD"),
    side: str = typer.Option(..., help="BUY or SELL"),
    volume: str = typer.Option(..., help="Lots, e.g. 0.01"),
    price: float | None = typer.Option(None, help="Default: MT5's current ask (buy) or bid"),
    maximum_age_seconds: int = typer.Option(120, min=1),
) -> None:
    """Broker-calculated margin for one proposed position (read-only calc_margin call).
    Nothing is sent to the market; account figures come from the validated snapshot."""
    side = side.upper()
    if side not in ("BUY", "SELL"):
        console.print("[red]Side must be BUY or SELL.[/red]")
        raise typer.Exit(code=2)
    order_side: Side = "BUY" if side == "BUY" else "SELL"
    try:
        lots = Decimal(volume)
        data = load_snapshot(snapshot)
        account = margin_account_from_snapshot(
            data.account, now=datetime.now(UTC), maximum_age_seconds=maximum_age_seconds
        )
        response = margin_from_server(symbol=symbol, side=side, volume=float(lots), price=price)
        estimate = parse_margin_response(response, symbol=symbol, side=order_side, volume=lots)
    except (InvalidOperation, ValueError, MarginUnavailable, CollectorError) as exc:
        console.print(f"[red]Margin unavailable; proposal rejected:[/red] {exc}")
        raise typer.Exit(code=2) from exc
    result = check_margin(account, estimate)
    table = Table(title=f"Margin: {side} {lots} {symbol} at {estimate.price}")
    table.add_column("Check")
    table.add_column("Result")
    table.add_row("Required margin", f"{result.required} {result.currency}")
    table.add_row("Free margin before", f"{result.free_margin_before} {result.currency}")
    table.add_row("Free margin after", f"{result.free_margin_after} {result.currency}")
    level = result.projected_margin_level
    table.add_row("Projected margin level", "n/a" if level is None else f"{level:.1f}%")
    table.add_row("Decision", "ACCEPTED" if result.accepted else "REJECTED")
    console.print(table)
    for reason in result.reasons:
        console.print(f"  - {reason}")
    if not result.accepted:
        raise typer.Exit(code=3)


@app.command(name="collect-history")
def collect_history(
    output: Path = typer.Option(Path("data/history/xauusd_backtest.local.json")),
    start: str = typer.Option("2022-11-01", help="UTC date; includes indicator warm-up"),
    end: str = typer.Option("2026-11-01", help="UTC date (exclusive)"),
) -> None:
    """Download XAUUSD M15/H1 and GBPUSD M15 history read-only (no orders, no settings)."""
    try:
        result = download_history_to_file(
            output,
            requests=[("XAUUSD", "H1"), ("XAUUSD", "M15"), ("GBPUSD", "M15")],
            start=datetime.fromisoformat(start).replace(tzinfo=UTC),
            end=datetime.fromisoformat(end).replace(tzinfo=UTC),
        )
    except (CollectorError, ValueError) as exc:
        console.print(f"[red]History download failed:[/red] {exc}")
        raise typer.Exit(code=2) from exc
    for series in result["series"]:
        console.print(
            f"{series['symbol']} {series['timeframe']}: {len(series['rates'])} bars, "
            f"{len(series['problems'])} problems"
        )
    console.print(f"History written to {output}")


@app.command(name="slippage-evidence")
def slippage_evidence(
    history: Path = typer.Option(
        Path("data/history/account_xauusd.local.json"), exists=True, readable=True
    ),
) -> None:
    """Recompute XAUUSD stop-loss slippage percentiles from local read-only account history.
    Prints aggregates only; no tickets or account details."""
    summary = evidence_from_history(history)
    for key, value in summary.items():
        console.print(f"{key}: {value}")


@app.command()
def backtest(
    history: Path = typer.Option(
        Path("data/history/xauusd_backtest.local.json"), exists=True, readable=True
    ),
    export: Path = typer.Option(
        Path("data/mcp_export.local.json"),
        exists=True,
        readable=True,
        help="Raw export supplying the current XAUUSD/GBPUSD specifications and margin terms",
    ),
    sessions: Path = typer.Option(Path("config/market_sessions.yaml"), exists=True),
    risk_config: Path = typer.Option(Path("config/risk.yaml"), exists=True),
    cost_config: Path = typer.Option(Path("config/backtest.yaml"), exists=True),
    no_margin: bool = typer.Option(False, help="Do not request broker margin (all fail margin)"),
    reports_dir: Path = typer.Option(
        Path("reports/backtests"), help="Each run writes a new report and manifest here"
    ),
    require_clean: bool = typer.Option(
        False, help="Refuse to run with uncommitted changes, so the commit reproduces it"
    ),
    real_yield: Path | None = typer.Option(
        None,
        exists=True,
        readable=True,
        help="FRED DFII10 download (JSON): runs Version 1.1 with the real-yield filter and "
        "compares it with Version 1.0",
    ),
) -> None:
    """Offline backtest of the approved XAUUSD M15 strategy on a paper ledger, for every
    configured cost scenario. Read-only: margin comes from MT5 calc_margin; nothing is sent.
    Every run writes a new report plus a JSON manifest of the code, inputs and parameters."""
    started = datetime.now(UTC)
    code = code_state()
    if require_clean and code["dirty"]:
        console.print("[red]Uncommitted changes; refusing to run (--require-clean):[/red]")
        for name in code["uncommitted_files"]:
            console.print(f"  - {name}")
        raise typer.Exit(code=2)
    report, manifest_path = unique_paths(reports_dir, run_id(started, code))
    calendar = load_market_calendar(sessions)
    raw = json.loads(export.read_text(encoding="utf-8"))
    snapshot = load_mcp_export(
        export,
        now=datetime.fromisoformat(raw["exported_at_utc"]),
        settings=ExportSettings(
            calendar=calendar,
            max_export_age_seconds=10**9,
            max_quote_age_seconds=10**9,
            min_completed_candles=1,
        ),
    )
    spec = next(i for i in snapshot.instruments if i.symbol == "XAUUSD")
    conversion_spec = next(i for i in snapshot.instruments if i.symbol == "GBPUSD")
    account = snapshot.account
    if account.stop_out_mode is None or account.margin_call_level is None:
        console.print("[red]Export lacks the account margin-call settings.[/red]")
        raise typer.Exit(code=2)
    model = load_cost_model(cost_config)
    gate = RealYieldFilter(load_series(real_yield)) if real_yield is not None else None
    version = "1.0" if gate is None else "1.1"
    base_config = BacktestConfig(
        starting_balance=model.starting_balance,
        account_currency=account.currency,
        stop_out_mode=account.stop_out_mode,
        margin_call_level=Decimal(str(account.margin_call_level)),
        sizing=load_sizing_config(risk_config),
        costs=model.base(),
        real_yield_filter=gate,
    )
    scenarios = [(c.label, dataclasses.replace(base_config, costs=c)) for c in model.grid()]
    notes = [
        "Commission: £0 round turn per lot, verified (Standard swap-free account; 18,466 "
        "historical XAUUSD deals all with commission 0).",
    ]
    bars = load_history(history)

    def run(
        provider: MarginProvider | None,
    ) -> tuple[str, dict[str, Any], list[tuple[str, BacktestResult]]]:
        return run_scenarios(
            scenarios=scenarios,
            base=model.base().label,
            m15=bars[("XAUUSD", "M15")],
            h1=bars[("XAUUSD", "H1")],
            conversion_m15=bars[("GBPUSD", "M15")],
            spec=spec,
            conversion_spec=conversion_spec,
            calendar=calendar,
            margin_provider=provider,
            cost_notes=notes,
            version=version,
        )

    def compare(provider: MarginProvider | None, filtered: list[tuple[str, BacktestResult]]) -> str:
        if gate is None:
            return ""
        _, baseline = run_periods(
            m15=bars[("XAUUSD", "M15")],
            h1=bars[("XAUUSD", "H1")],
            conversion_m15=bars[("GBPUSD", "M15")],
            spec=spec,
            conversion_spec=conversion_spec,
            calendar=calendar,
            config=dataclasses.replace(base_config, real_yield_filter=None),
            margin_provider=provider,
            cost_notes=notes,
        )
        return compare_versions(baseline, filtered, gate)

    if no_margin:
        notes.append("Margin: NOT requested (--no-margin); every sized signal fails margin.")
        text, results, base_results = run(None)
        comparison = compare(None, base_results)
    else:
        notes.append("Margin: MT5 calc_margin over one read-only session.")
        with MarginSession() as session:

            def provider(side: Side, volume: Decimal, price: Decimal) -> dict[str, Any]:
                return session.margin(
                    symbol="XAUUSD", side=side, volume=float(volume), price=float(price)
                )

            text, results, base_results = run(provider)
            comparison = compare(provider, base_results)
    if comparison:
        text = text.replace("## Data coverage", comparison + "\n## Data coverage", 1)
    exchange_calendar = sessions.parent / "exchange_holidays.yaml"
    parameters = {
        "strategy": {
            "name": "XAUUSD M15 trend pullback",
            "version": version,
            "specification": "docs/strategy-xauusd-trend-pullback.md",
            "values": PullbackParameters(),
            **(
                {
                    "amendment": "docs/strategy-xauusd-v1.1-real-yield-filter.md",
                    "real_yield_filter": RealYieldParameters(),
                    "real_yield_series": {
                        "series_id": gate.series.series_id,
                        "source": "FRED via the read-only FRED MCP server (download link)",
                        "fred_last_updated": gate.series.last_updated,
                        "vintage": "current only; revisions cannot be checked",
                        "observations": len(gate.series.values),
                        "first": gate.series.values[0][0],
                        "last": gate.series.values[-1][0],
                        "missing_marked_by_fred": len(gate.series.holidays),
                    },
                }
                if gate is not None
                else {}
            ),
        },
        "sessions": SessionRules(),
        "periods": [{"name": n, "from": a, "until": b} for n, a, b in PERIODS],
        "starting_balance_gbp": model.starting_balance,
        "sizing": {
            "risk_fraction": base_config.sizing.risk_fraction,
            "tick_value_tolerance": base_config.sizing.tick_value_tolerance,
            "maximum_data_age_seconds": base_config.sizing.maximum_data_age_seconds,
            "commission_currency": base_config.sizing.commission_currency,
            "commission_per_lot_xauusd": base_config.sizing.commission_per_lot.get("XAUUSD"),
        },
        "cost_model": model,
        "scenarios": [config.costs for _, config in scenarios],
        "base_scenario": model.base().label,
        "margin_source": "none (--no-margin)" if no_margin else "MT5 calc_margin, read-only",
        "news_filter": "unavailable (Version 1.0)",
        "broker_clock": {"timezone": "America/New_York", "shift_hours": 7},
        "instruments": {
            "XAUUSD": instrument_terms(spec),
            "GBPUSD": instrument_terms(conversion_spec),
        },
        "account_terms": account_terms(account),
        "specification_snapshot_utc": raw.get("exported_at_utc"),
        "history": {
            f"{s} {tf}": {"bars": len(b), "first": b[0].open_time, "last": b[-1].open_time}
            for (s, tf), b in bars.items()
        },
    }
    inputs = {
        "history": history,
        "specification_export": export,
        "risk_config": risk_config,
        "cost_config": cost_config,
        "sessions": sessions,
        "exchange_calendar": exchange_calendar,
        **({"real_yield": real_yield} if real_yield is not None else {}),
        "uv.lock": Path("uv.lock"),
        "pyproject.toml": Path("pyproject.toml"),
    }
    try:
        bridge_repo: Path | None = registered_server().bridge_repo
    except CollectorError:
        bridge_repo = None
    history_raw = json.loads(history.read_text(encoding="utf-8"))
    series_coverage = {}
    for (symbol, timeframe), series_bars in bars.items():
        c = coverage(symbol, timeframe, series_bars, calendar)
        series_coverage[f"{symbol} {timeframe}"] = {
            "bars": c.bars,
            "first": c.first,
            "last": c.last,
            "gaps": len(c.gaps),
        }
    input_data = describe_series(history_raw, series_coverage)
    input_data["file_modified_utc"] = datetime.fromtimestamp(
        history.stat().st_mtime, tz=UTC
    ).isoformat()
    extra = {
        "ai_and_tools": ai_and_tools(Path("config/provenance.yaml"), bridge_repo),
        "input_data": input_data,
        "data_sample": {f"{s} {tf}": bar_sample(b) for (s, tf), b in bars.items()},
        "trade_sample": {period: result.trades[:5] for period, result in base_results},
        "base_scenario_trades": {period: result.trades for period, result in base_results},
    }
    manifest = build_manifest(
        code=code,
        started=started,
        command=sys.argv,
        input_paths=inputs,
        parameters=parameters,
        manifest_path=manifest_path,
        results=results,
        extra=extra,
    )
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    report.write_text(
        f"<!-- run {manifest['run_id']} -->\n"
        + text.replace(
            "## Status and assumptions",
            render_markdown(manifest) + "\n## Status and assumptions",
            1,
        ),
        encoding="utf-8",
    )
    if code["dirty"]:
        console.print(
            "[yellow]Uncommitted changes recorded in the manifest; this result is "
            "not reproducible from the commit alone.[/yellow]"
        )
    console.print(f"Backtest report: {report}")
    console.print(f"Run manifest:    {manifest_path}")


@app.command(name="calendar")
def calendar_status(
    sessions: Path = typer.Option(
        Path("config/market_sessions.yaml"), exists=True, readable=True, help="Market calendar"
    ),
) -> None:
    """Show the local market calendar's last update and coverage (no network access)."""
    try:
        calendar = load_market_calendar(sessions)
    except ValueError as exc:
        console.print(f"[red]Market calendar rejected:[/red] {exc}")
        raise typer.Exit(code=2) from exc
    for line in calendar.summary():
        console.print(line)


@app.command()
def diagnose(
    snapshot: Path = typer.Option(..., exists=True, readable=True, help="Snapshot JSON file"),
    maximum_age_seconds: int = typer.Option(120, min=1),
) -> None:
    """Validate a market snapshot and print account and market diagnostics."""
    try:
        data = load_snapshot(snapshot)
    except Exception as exc:
        console.print(f"[red]Snapshot rejected:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    now = datetime.now(UTC)
    age = (now - data.generated_at.astimezone(UTC)).total_seconds()
    table = Table(title="Read-only MT5 diagnostic")
    table.add_column("Check")
    table.add_column("Result")
    table.add_row("Snapshot source", data.source)
    table.add_row("Account server", data.account.server)
    table.add_row("Account currency", data.account.currency)
    table.add_row("Snapshot age (seconds)", f"{age:.1f}")
    table.add_row(
        "Snapshot freshness", "FRESH" if 0 <= age <= maximum_age_seconds else "STALE / FUTURE"
    )
    table.add_row("Positions", str(len(data.positions)))
    table.add_row("Account type", data.account.trade_mode or "not reported")
    offset = data.broker_utc_offset_seconds
    table.add_row("Broker UTC offset", "unknown" if offset is None else f"{offset / 3600:+g} h")
    table.add_row("Pending orders", str(len(data.pending_orders)))
    table.add_row("Floating P/L", f"{floating_pnl(data.positions):.2f} {data.account.currency}")
    console.print(table)

    exposure = open_volume_by_symbol(data.positions)
    if exposure:
        console.print("\nOpen volume by symbol:")
        for symbol, volume in sorted(exposure.items()):
            console.print(f"  {symbol}: {volume:g}")

    quote_table = Table(title="Quotes")
    quote_table.add_column("Symbol")
    quote_table.add_column("Bid")
    quote_table.add_column("Ask")
    quote_table.add_column("Spread (points)")
    for quote in data.quotes:
        quote_table.add_row(
            quote.symbol, str(quote.bid), str(quote.ask), f"{quote.spread_points:.1f}"
        )
    console.print(quote_table)

    if data.candles:
        candle_table = Table(title="Completed candles")
        candle_table.add_column("Symbol")
        candle_table.add_column("Timeframe")
        candle_table.add_column("Count")
        candle_table.add_column("Last bar open (UTC)")
        candle_table.add_column("Last bar open (broker)")
        for series in data.candles:
            last = series.candles[-1]
            broker = last.broker_time.isoformat() if last.broker_time else "not reported"
            candle_table.add_row(
                series.symbol,
                series.timeframe,
                str(len(series.candles)),
                last.timestamp.astimezone(UTC).isoformat(),
                broker,
            )
        console.print(candle_table)

    if age < 0 or age > maximum_age_seconds:
        console.print("[red]Analysis blocked: snapshot is not fresh.[/red]")
        raise typer.Exit(code=3)

    console.print(
        "\n[green]Diagnostic completed.[/green] This application is read-only; "
        "no order tools are available."
    )


if __name__ == "__main__":
    app()
