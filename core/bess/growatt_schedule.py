"""Backward compatibility re-export.

GrowattScheduleManager has moved to min_schedule.py.
This module re-exports it for backward compatibility with existing imports.
"""

from .min_schedule import GrowattScheduleManager

__all__ = ["GrowattScheduleManager"]
