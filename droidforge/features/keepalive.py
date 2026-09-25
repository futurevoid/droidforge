"""Keep-alive for apps the user picks (R-6.3) - stops the system from killing their background work.

Per app (never phone-wide):
    dumpsys deviceidle whitelist +<p>                 (undo -<p>; skipped if already whitelisted)
    cmd appops set <p> RUN_ANY_IN_BACKGROUND allow    (undo: the previous mode)
    am set-standby-bucket <p> active                  (undo: the previous bucket)
then the app's info page opens: ColorOS keeps "Allow background activity" / "Allow auto launch" under Battery usage,
which adb cannot set - the user switches them on there. droidforge never touches developer options for this.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, List, Mapping, Optional

from droidforge.adb import parse
from droidforge.engine import safety, steps
from droidforge.engine.plan import Plan, Step

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device

MANUAL = ("On the phone, for each app: App info > Battery usage > turn on 'Allow background activity' and 'Allow "
          "auto launch'; in Recents, lock the app's card. Do NOT turn on any Developer-options switch for this.")


def status(device: "Device", p: str) -> dict:
    wl = parse.deviceidle_whitelist(device.out("dumpsys deviceidle whitelist"))
    return {"whitelist": wl.get(p, ""),
            "background": parse.appops(device.read(f"cmd appops get {p}").out).get("RUN_ANY_IN_BACKGROUND", "default"),
            "bucket": parse.standby_bucket(device.out(f"am get-standby-bucket {p}"))}


def keepalive_plan(device: "Device", pkgs: Iterable[str], uad: Optional[Mapping[str, dict]] = None,
                   expert_mode: bool = False) -> Plan:
    plan = Plan(title="Keep apps alive in the background")
    installed = device.packages()
    ctx = safety.SafetyContext.from_device(device, uad if uad is not None else {})
    sel = safety.select([p for p in pkgs if p in installed], ctx, expert_mode)
    for p, why in sel.rejected.items():
        plan.notes.append(f"Locked, skipped: {p} ({why})")
    wl = parse.deviceidle_whitelist(device.out("dumpsys deviceidle whitelist"))
    for p in sel.allowed:
        risk = "locked" if p in sel.locked else "normal"
        if not wl.get(p):
            plan.steps.append(Step(f"{p}: exempt from battery optimisation", f"dumpsys deviceidle whitelist +{p}",
                                   [f"dumpsys deviceidle whitelist -{p}"], "keepalive", p, risk,
                                   touches=[f"deviceidle:{p}"]))
        prev = parse.appops(device.read(f"cmd appops get {p}").out).get("RUN_ANY_IN_BACKGROUND")
        if prev != "allow":
            st = steps.appop(p, "RUN_ANY_IN_BACKGROUND", "allow", prev, "keepalive", risk)
            st.label = f"{p}: allow running in the background"
            plan.steps.append(st)
        bucket = parse.standby_bucket(device.out(f"am get-standby-bucket {p}"))
        if bucket and bucket != "active":
            plan.steps.append(Step(f"{p}: standby bucket {bucket} -> active", f"am set-standby-bucket {p} active",
                                   [f"am set-standby-bucket {p} {bucket}"], "keepalive", p, risk,
                                   touches=[f"standby:{p}"]))
        plan.steps.append(Step(f"Open app info of {p} (turn on background activity + auto launch there)",
                               f"am start -a android.settings.APPLICATION_DETAILS_SETTINGS -d package:{p}",
                               category="keepalive", pkg=p, risk="read"))
    if sel.locked:
        safety.make_expert(plan, sel.locked)
    plan.notes.append(MANUAL)
    plan.notes.append("ColorOS may still kill apps it considers idle; the Battery usage switches are the part that "
                      "matters most.")
    return plan


def remove_plan(device: "Device", pkgs: Iterable[str]) -> Plan:
    """Take apps off the battery-optimisation whitelist again (only user entries)."""
    wl = parse.deviceidle_whitelist(device.out("dumpsys deviceidle whitelist"))
    plan = Plan(title="Stop keeping apps alive")
    for p in pkgs:
        if wl.get(p) == "user":
            plan.steps.append(Step(f"{p}: battery optimisation back on", f"dumpsys deviceidle whitelist -{p}",
                                   [f"dumpsys deviceidle whitelist +{p}"], "keepalive", p,
                                   touches=[f"deviceidle:{p}"]))
    return plan


def candidates(device: "Device") -> List[str]:
    return sorted(device.packages("-3"))
