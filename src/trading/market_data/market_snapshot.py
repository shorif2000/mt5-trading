"""Load and validate a snapshot exported from verified read-only MT5 tools."""

import json
from pathlib import Path

from trading.models import MarketSnapshot


def load_snapshot(path: Path) -> MarketSnapshot:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return MarketSnapshot.model_validate(payload)
