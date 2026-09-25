"""Regional formats and time (R-3.3): droidforge only OPENS Regional preferences (API 34+) and Date & time.
It writes no time, date or format setting (owner decision; COMMANDS.md Forbidden)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from droidforge.engine import steps
from droidforge.engine.plan import Plan

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device

REGIONAL = "android.settings.REGIONAL_PREFERENCES_SETTINGS"
DATE = "android.settings.DATE_SETTINGS"


def regional_plan(device: "Device") -> Plan:
    plan = Plan(title="Open Regional preferences")
    if device.sdk < 34:
        plan.notes.append("Regional preferences need Android 14+. Use Settings > System > Language & region.")
        return plan
    plan.steps.append(steps.open_screen(REGIONAL, "Open Settings > Regional preferences", "region"))
    plan.notes.append("Set temperature, first day of week and number format there - droidforge writes none of them.")
    return plan


def datetime_plan(device: "Device") -> Plan:
    plan = Plan(title="Open Date & time", steps=[steps.open_screen(DATE, "Open Settings > Date & time", "region")])
    plan.notes.append("Set time zone and 12/24-hour format there - droidforge writes no time settings.")
    return plan
