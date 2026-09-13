"""Time windows read from a Home Assistant calendar entity.

The Octoplus integration publishes the account's joined Power Up sessions and
Weekend Happy Hours on a calendar entity. HA's ``/api/calendars/{entity}``
endpoint answers a time-range query directly, which is why the calendar -- not
the companion event entity, whose attributes are empty after an integration
reload -- is the source of truth.
"""

from dataclasses import dataclass
from datetime import datetime

from .exceptions import CalendarWindowError


@dataclass(frozen=True)
class CalendarWindow:
    """One bounded calendar event.

    Attributes:
        start: When the window begins (timezone-aware).
        end: When the window ends (timezone-aware, after ``start``).

    """

    start: datetime
    end: datetime


def parse_calendar_events(raw: object) -> list[CalendarWindow]:
    """Parse an HA calendar REST response into windows.

    Args:
        raw: The JSON body of ``GET /api/calendars/{entity}``.

    Returns:
        One window per event, in the order given.

    Raises:
        CalendarWindowError: If the body is not a list of events with
            timezone-aware ``start.dateTime`` / ``end.dateTime`` and a
            positive duration. All-day events (``date`` instead of
            ``dateTime``) are rejected: a free window is always a bounded span.

    """
    if not isinstance(raw, list):
        raise CalendarWindowError(
            f"calendar events must be a list, got {type(raw).__name__}"
        )

    windows = []
    for position, event in enumerate(raw):
        if not isinstance(event, dict):
            raise CalendarWindowError(
                f"calendar event {position} must be a mapping, "
                f"got {type(event).__name__}"
            )
        start = _parse_event_time(event, "start", position)
        end = _parse_event_time(event, "end", position)
        if end <= start:
            raise CalendarWindowError(
                f"calendar event {position}: end ({end.isoformat()}) must be "
                f"after start ({start.isoformat()})"
            )
        windows.append(CalendarWindow(start=start, end=end))
    return windows


def _parse_event_time(event: dict, field: str, position: int) -> datetime:
    """Parse ``event[field].dateTime``, requiring an explicit UTC offset."""
    bound = event.get(field)
    if not isinstance(bound, dict) or "dateTime" not in bound:
        raise CalendarWindowError(
            f"calendar event {position} has no '{field}.dateTime' "
            f"(all-day events are not supported): {event!r}"
        )
    value = bound["dateTime"]
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as e:
        raise CalendarWindowError(
            f"calendar event {position}: '{field}.dateTime' is not ISO-8601 "
            f"({value!r})"
        ) from e
    if parsed.tzinfo is None:
        raise CalendarWindowError(
            f"calendar event {position}: '{field}.dateTime' has no UTC offset "
            f"({value!r})"
        )
    return parsed
