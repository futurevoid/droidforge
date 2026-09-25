"""Hidden activity launcher (R-9.3): curated screens + the activities of any package that have intent filters
(i.e. can be started from outside). Launching is an allowlisted read (`am start`); non-exported ones need root
(v2)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Dict, List, Tuple

from droidforge.engine.plan import Plan, Step

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device

CURATED: Dict[str, Tuple[str, str]] = {
    "developer": ("Developer options (e.g. to turn 'Disable permission monitoring' OFF)",
                  "am start -a android.settings.APPLICATION_DEVELOPMENT_SETTINGS"),
    "app-languages": ("App languages", "am start -a android.settings.APP_LOCALE_SETTINGS"),
    "regional": ("Regional preferences (Android 14+)", "am start -a android.settings.REGIONAL_PREFERENCES_SETTINGS"),
    "battery": ("Battery optimisation", "am start -a android.settings.IGNORE_BATTERY_OPTIMIZATION_SETTINGS"),
    "default-apps": ("Default apps", "am start -a android.settings.MANAGE_DEFAULT_APPS_SETTINGS"),
    "radio-info": ("Radio info (phone / network test screen)", "am start -n com.android.phone/.settings.RadioInfo"),
}
COMP_RE = re.compile(r"\s([A-Za-z0-9_.]+/[A-Za-z0-9_.$]+)\s+filter\b")


def curated_plan(device: "Device", key: str) -> Plan:
    label, cmd = CURATED[key]
    return Plan(title=f"Open {label}", steps=[Step(f"Open {label}", cmd, category="tools", risk="read")])


def activities(device: "Device", pkg: str) -> List[str]:
    """Components of `pkg` that have intent filters (from dumpsys package; read-only)."""
    out = device.out(f"dumpsys package {pkg}")
    return sorted({c for c in COMP_RE.findall(out) if c.split("/")[0] == pkg})


def launch_plan(device: "Device", component: str) -> Plan:
    return Plan(title=f"Start {component}", steps=[Step(f"Start {component}", f"am start -n {component}",
                                                        category="tools", risk="read")])
