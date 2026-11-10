"""CLI for read-only market snapshot diagnostics."""

from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from trading.market_data.market_snapshot import load_snapshot
from trading.market_data.mcp_collector import CollectorError, collect_to_file
from trading.market_data.mcp_export import ExportRejected, ExportSettings, load_mcp_export
from trading.market_data.sessions import load_market_calendar
from trading.risk.exposure import floating_pnl, open_volume_by_symbol

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
