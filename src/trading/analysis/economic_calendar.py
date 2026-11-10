"""Economic calendar boundary.

No calendar provider is configured. The application must not assume that there are no
high-impact events merely because no calendar data has been supplied.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CalendarStatus:
    available: bool
    events_checked: int
    restricted: bool
    explanation: str


def unavailable_calendar_status() -> CalendarStatus:
    return CalendarStatus(
        available=False,
        events_checked=0,
        restricted=True,
        explanation="Economic calendar data unavailable; new setup assessment is blocked.",
    )
