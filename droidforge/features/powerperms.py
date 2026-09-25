"""Power permissions (R-6.4): presets for Tasker / SystemUI Tuner / Automate / MacroDroid (only if installed) and a
custom app + permission choice. If ColorOS refuses a grant, droidforge reports it - there is no developer-option
workaround in droidforge (INCIDENT-2026-09-25)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Iterable, List, Mapping, Optional, Tuple

from droidforge.adb import parse
from droidforge.data.presets import CATALOG
from droidforge.engine import safety, steps
from droidforge.engine.plan import Plan

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device

PERMS: Dict[str, str] = {
    "WRITE_SECURE_SETTINGS": "android.permission.WRITE_SECURE_SETTINGS",
    "READ_LOGS": "android.permission.READ_LOGS",
    "DUMP": "android.permission.DUMP",
    "PACKAGE_USAGE_STATS": "appop:GET_USAGE_STATS",
}
# presets: the one permission all four document as required (the rest via "custom")
PRESETS: Dict[str, Tuple[str, ...]] = {k: ("WRITE_SECURE_SETTINGS",) for k in
                                       ("tasker", "systemui-tuner", "automate", "macrodroid")}
REFUSAL_NOTE = ("If ColorOS refuses a grant, the step fails and is reported. droidforge will not suggest any "
                "developer-option workaround.")


def installed_presets(device: "Device") -> List[str]:
    installed = device.packages()
    return [k for k in PRESETS if CATALOG[k].package in installed]


def grant_plan(device: "Device", wanted: Mapping[str, Iterable[str]], uad: Optional[Mapping[str, dict]] = None,
               expert_mode: bool = False) -> Plan:
    """`wanted` = {package: [WRITE_SECURE_SETTINGS | READ_LOGS | DUMP | PACKAGE_USAGE_STATS]}."""
    plan = Plan(title="Grant power permissions")
    installed = device.packages()
    ctx = safety.SafetyContext.from_device(device, uad if uad is not None else {})
    sel = safety.select([p for p in wanted if p in installed], ctx, expert_mode)
    for p, why in sel.rejected.items():
        plan.notes.append(f"Locked, skipped: {p} ({why})")
    for p in sel.allowed:
        dump = device.read(f"dumpsys package {p}").out
        have = parse.granted_perms(dump)
        risk = "locked" if p in sel.locked else "normal"
        for name in wanted[p]:
            perm = PERMS[name]
            if perm.startswith("appop:"):
                op = perm[6:]
                prev = parse.appops(device.read(f"cmd appops get {p}").out).get(op)
                if prev != "allow":
                    plan.steps.append(steps.appop(p, op, "allow", prev, "powerperms", risk))
            elif perm not in have:
                plan.notes.append(f"{p} does not request {name} - it cannot be granted.")
            elif not have[perm]:
                plan.steps.append(steps.grant(p, perm, "powerperms", risk))
    if sel.locked:
        safety.make_expert(plan, sel.locked)
    plan.notes.append(REFUSAL_NOTE)
    return plan


def preset_plan(device: "Device", keys: Iterable[str]) -> Plan:
    wanted = {CATALOG[k].package: PRESETS[k] for k in keys if k in PRESETS}
    plan = grant_plan(device, wanted)
    plan.title = "Power permissions: " + ", ".join(CATALOG[k].name for k in keys if k in PRESETS)
    return plan
