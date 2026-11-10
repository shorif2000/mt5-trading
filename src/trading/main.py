"""CLI for read-only market snapshot diagnostics."""

from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from trading.market_data.market_snapshot import load_snapshot
from trading.risk.exposure import floating_pnl, open_volume_by_symbol

app = typer.Typer(help="Read-only MT5 trading research diagnostics.")
console = Console()


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
    table.add_row("Snapshot freshness", "FRESH" if 0 <= age <= maximum_age_seconds else "STALE / FUTURE")
    table.add_row("Positions", str(len(data.positions)))
    table.add_row("Pending orders", str(data.pending_orders_count))
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

    if age < 0 or age > maximum_age_seconds:
        console.print("[red]Analysis blocked: snapshot is not fresh.[/red]")
        raise typer.Exit(code=3)

    console.print(
        "\n[green]Diagnostic completed.[/green] This application is read-only; "
        "no order tools are available."
    )


if __name__ == "__main__":
    app()
