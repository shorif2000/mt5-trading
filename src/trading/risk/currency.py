"""Currency conversion rates derived from quotes in the same validated snapshot.

Used only to *verify* MT5's tick values, which MT5 already reports in the account currency.
No external rate source is used.
"""

from decimal import Decimal

from trading.models import MarketSnapshot


def conversion_rate(snapshot: MarketSnapshot, source: str, target: str) -> Decimal | None:
    """Units of ``target`` per one unit of ``source``, from mid prices of snapshot quotes:
    directly, inverted, or through one intermediate currency. None when not derivable."""
    if source == target:
        return Decimal(1)
    quotes = {q.symbol: q for q in snapshot.quotes}
    edges: dict[tuple[str, str], Decimal] = {}
    for spec in snapshot.instruments:
        quote = quotes.get(spec.symbol)
        if quote is None or not spec.base_currency or not spec.quote_currency:
            continue
        mid = (Decimal(str(quote.bid)) + Decimal(str(quote.ask))) / 2
        edges[(spec.base_currency, spec.quote_currency)] = mid
        edges[(spec.quote_currency, spec.base_currency)] = 1 / mid
    direct = edges.get((source, target))
    if direct is not None:
        return direct
    for (start, middle), first in edges.items():
        if start == source and (middle, target) in edges:
            return first * edges[(middle, target)]
    return None
