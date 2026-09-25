"""Privacy: kill telemetry (R-5.1) and stop the install hijack (R-5.3).

Telemetry: the curated preset from docs/PACKAGES.md, filtered to installed packages, previewed; built on the
debloat preflight (locked / keep / typed confirmations still apply).
Install hijack: disable ColorOS "secure app installation" (com.oplus.appdetail); optionally switch off the adb
install verification (flagged: it lowers protection); silence the HeyTap store's notifications."""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Mapping, Optional

from droidforge.data.packages import TELEMETRY, TELEMETRY_OPT_IN
from droidforge.engine import safety, steps
from droidforge.engine.plan import Plan
from droidforge.features import ads, debloat

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


APPDETAIL = "com.oplus.appdetail"
STORES = ("com.heytap.market", "com.oppo.market")
VERIFIER_KEYS = ("verifier_verify_adb_installs", "package_verifier_enable")
LOWERS_PROTECTION = ("LOWERS PROTECTION: Android will no longer scan apps installed over adb (and the package "
                     "verifier is switched off). Only do this if the install scan blocks apps you trust.")


def install_hijack_plan(device: "Device", uad: Optional[Mapping[str, dict]] = None, lower_verification: bool = False,
                        store_notifications: bool = True, expert_mode: bool = False) -> Plan:
    installed = device.packages()
    plan = debloat.disable_plan(device, [APPDETAIL] if APPDETAIL in installed else [], uad, expert_mode)
    plan.title = "Stop the install hijack"
    if "Nothing to do." in plan.notes:
        plan.notes.remove("Nothing to do.")
    if store_notifications:
        ctx = safety.SafetyContext.from_device(device, uad if uad is not None else {})
        sel = safety.select([p for p in STORES if p in installed], ctx, expert_mode)
        for p in sel.allowed:
            plan.steps += ads.notifications_off_steps(device, p, "privacy")
    if lower_verification:
        for key in VERIFIER_KEYS:
            prev = device.out(f"settings get global {key}")
            prev_v = None if prev in ("", "null") else prev
            if prev_v != "0":
                st = steps.setting_put("global", key, "0", prev_v, f"{key} -> 0 (lowers protection)", "privacy")
                st.risk = "risky"
                plan.steps.append(st)
        plan.notes.insert(0, LOWERS_PROTECTION)
    if not plan.steps:
        plan.notes.append("Nothing to do.")
    return plan
