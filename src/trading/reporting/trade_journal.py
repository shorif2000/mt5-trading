"""Append-only local research journal. Contains no broker credentials."""


import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def append_event(path: Path, event_type: str, details: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "event_type": event_type,
        "details": details,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
