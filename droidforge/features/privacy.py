"""Kill telemetry (R-5.1): the curated preset from docs/PACKAGES.md, filtered to installed packages, previewed.
Built on the debloat preflight (locked / keep / typed confirmations still apply)."""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Mapping, Optional

from droidforge.data.packages import TELEMETRY, TELEMETRY_OPT_IN
from droidforge.engine.plan import Plan
from droidforge.features import debloat

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device


def telemetry_packages(device: "Device", include_opt_in: bool = False) -> List[str]:
    installed = device.packages()
    wanted = list(TELEMETRY) + (list(TELEMETRY_OPT_IN) if include_opt_in else [])
    return [p for p in wanted if p in installed]


def telemetry_plan(device: "Device", uad: Optional[Mapping[str, dict]] = None, include_opt_in: bool = False,
                   escalate: bool = False, expert_mode: bool = False) -> Plan:
    """Disable (or force-disable with `escalate`) the telemetry preset. `include_opt_in` adds com.oplus.cosa."""
    pkgs = telemetry_packages(device, include_opt_in)
    build = debloat.force_plan if escalate else debloat.disable_plan
    plan = build(device, pkgs, uad, expert_mode)
    plan.title = "Kill telemetry" + (" (force-disable)" if escalate else "")
    plan.notes.insert(0, f"Preset: {len(pkgs)} telemetry package(s) from docs/PACKAGES.md that are installed here.")
    if not include_opt_in:
        plan.notes.append("Not included (opt-in): com.oplus.cosa 'App enhancement' (UAD Advanced).")
    return plan
