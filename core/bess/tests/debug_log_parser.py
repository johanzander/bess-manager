"""Parse BESS debug log markdown files to extract optimization inputs.

The debug log is a markdown file with JSON embedded in fenced code blocks
inside <details> sections. This parser uses a simple single-pass state
machine — no markdown library required.

Usage:
    from core.bess.tests.debug_log_parser import parse_debug_log

    log = parse_debug_log("docs/bess-debug-2026-03-24-225535.md")
    d = log.input_data          # buy_price, sell_price, horizon, ...
    s = log.battery_settings    # total_capacity, min_soc, ...
"""

import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Section header strings as they appear in the debug log markdown
_SECTION_BATTERY = "### Battery Settings"
_SECTION_PRICE = "### Price Settings"
_SECTION_PRICE_DATA = "### Price Data"
_SECTION_HOME = "### Home Settings"
_SECTION_BESS_CONFIG = "## BESS Configuration"
_SECTION_INVERTER_TOU = "## Inverter TOU Segments"
_SECTION_HISTORICAL = "## Historical Sensor Data"
_SECTION_SCHEDULES = "## Optimization Schedules"


@dataclass
class DebugLogData:
    """Structured data extracted from a BESS debug log file."""

    battery_settings: dict = field(default_factory=dict)
    price_settings: dict = field(default_factory=dict)
    price_data: dict = field(default_factory=dict)
    home_settings: dict = field(default_factory=dict)
    addon_options: dict = field(default_factory=dict)
    inverter_tou_segments: list[dict] = field(default_factory=list)
    historical_periods: list[dict] = field(default_factory=list)
    last_schedule: dict = field(default_factory=dict)

    @property
    def input_data(self) -> dict:
        """Shortcut to the input_data dict from the last optimization schedule.

        Contains: buy_price, sell_price, full_home_consumption,
        full_solar_production, initial_soe, initial_cost_basis, horizon.
        """
        return self.last_schedule.get("optimization_result", {}).get("input_data", {})

    @property
    def optimization_period(self) -> int:
        """Period index at which the last optimization was run."""
        return self.last_schedule.get("optimization_period", 0)


def parse_debug_log(path: str) -> DebugLogData:
    """Parse a BESS debug log markdown file.

    Extracts battery/price/home settings, historical period data, and the
    most recent optimization schedule (including its input_data).

    Args:
        path: Path to the debug log .md file.

    Returns:
        DebugLogData with all extracted fields populated.

    Raises:
        FileNotFoundError: If path does not exist.
        ValueError: If the file has no recognisable sections.
    """
    result = DebugLogData()

    with open(path, encoding="utf-8") as f:
        lines = f.readlines()

    current_section = ""
    in_json_fence = False
    buffer: list[str] = []

    def _flush(section: str, raw_json: str) -> None:
        """Parse buffered JSON and assign to the matching section."""
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            logger.debug("JSON parse error in section '%s': %s", section, exc)
            return

        if section == _SECTION_BATTERY:
            result.battery_settings = parsed
        elif section == _SECTION_PRICE:
            result.price_settings = parsed
        elif section == _SECTION_PRICE_DATA:
            result.price_data = parsed
        elif section == _SECTION_HOME:
            result.home_settings = parsed
        elif section == _SECTION_BESS_CONFIG:
            if isinstance(parsed, dict):
                result.addon_options = parsed
        elif section == _SECTION_INVERTER_TOU:
            if isinstance(parsed, list):
                result.inverter_tou_segments = parsed
        elif section == _SECTION_HISTORICAL:
            if isinstance(parsed, list):
                result.historical_periods = parsed
            elif isinstance(parsed, dict):
                # Some versions wrap the list in a dict
                result.historical_periods = list(parsed.values())
        elif section == _SECTION_SCHEDULES and not result.last_schedule:
            if isinstance(parsed, list) and parsed:
                result.last_schedule = parsed[0]
            elif isinstance(parsed, dict):
                result.last_schedule = parsed

    for line in lines:
        stripped = line.rstrip()

        # Detect section header transitions
        for header in (
            _SECTION_BATTERY,
            _SECTION_PRICE,
            _SECTION_PRICE_DATA,
            _SECTION_HOME,
            _SECTION_BESS_CONFIG,
            _SECTION_INVERTER_TOU,
            _SECTION_HISTORICAL,
            _SECTION_SCHEDULES,
        ):
            if stripped == header:
                current_section = header
                break

        # JSON fence handling
        if stripped.startswith("```json") and not in_json_fence:
            in_json_fence = True
            buffer = []
        elif stripped == "```" and in_json_fence:
            in_json_fence = False
            if current_section and buffer:
                _flush(current_section, "\n".join(buffer))
            buffer = []
        elif in_json_fence:
            buffer.append(stripped)

    if not result.battery_settings and not result.last_schedule:
        raise ValueError(
            f"No recognisable BESS sections found in: {path}\n"
            "Expected headers: '### Battery Settings', '## Optimization Schedules'"
        )

    logger.info(
        "Parsed debug log: battery_settings=%s, historical_periods=%d, has_schedule=%s",
        bool(result.battery_settings),
        len(result.historical_periods),
        bool(result.last_schedule),
    )
    return result
