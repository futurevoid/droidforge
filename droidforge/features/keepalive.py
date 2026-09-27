"""Keep-alive for apps the user picks (R-6.3) - stops the system from killing their background work.

Per app:
    dumpsys deviceidle whitelist +<p>                 (undo -<p>; skipped if already whitelisted)
    cmd appops set <p> RUN_ANY_IN_BACKGROUND allow    (undo: the previous mode; same for RUN_IN_BACKGROUND)
    am set-standby-bucket <p> active                  (undo: the previous bucket)
    am set-bg-restriction-level --user 0 <p> exempted (Android 13+; undo: the previous level)
    cmd appops set <p> SYSTEM_EXEMPT_FROM_POWER_RESTRICTIONS allow   (Android 14+; undo: the previous mode)
    cmd appops set <p> SYSTEM_ALERT_WINDOW allow      (display over other apps; undo: the previous mode)
    cmd appops set <p> AUTO_REVOKE_PERMISSIONS_IF_UNUSED ignore   (Android 11+, "Pause app activity if unused"
                                                      off; undo: the previous mode)
    cmd app_hibernation set-state <p> false           (Android 12+, only when the app is hibernating; undo: true)
    cmd appops set <p> SCHEDULE_EXACT_ALARM allow     (Android 12+, only when the app asks for exact alarms;
                                                      undo: the previous mode)
Read only: why_lines() reports why each app last died (`dumpsys activity exit-info <p>`, Android 11+).
Phone-wide, its own plan so it can be undone on its own (owner opt-in 2026-09-25, never by default):
    child_process_plan - Developer options "Disable child process restrictions" + the phantom-process cap
then the app's info page opens: ColorOS keeps "Allow background activity" / "Allow auto launch" under Battery
usage and "Show pop-ups while running in background" under Permissions, which adb cannot set - the user switches
them on there. droidforge never touches developer options for this.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Dict, Iterable, List, Mapping, Optional

from droidforge.adb import parse
from droidforge.adb.batch import batch_read
from droidforge.engine import safety, steps
from droidforge.engine.plan import Plan, Step

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device

BG_LEVELS = ("unrestricted", "exempted", "adaptive_bucket", "restricted_bucket", "background_restricted",
             "hibernation")
CHILD_SETTING = "settings_enable_monitor_phantom_procs"
PHANTOM_MAX = "2147483647"
EXACT_ALARM = "android.permission.SCHEDULE_EXACT_ALARM"
# (app-op, mode, label, min SDK); SCHEDULE_EXACT_ALARM only for apps that ask for exact alarms
APPOPS = (("RUN_ANY_IN_BACKGROUND", "allow", "allow running in the background", 0),
          ("RUN_IN_BACKGROUND", "allow", "allow background services", 0),
          ("SYSTEM_EXEMPT_FROM_POWER_RESTRICTIONS", "allow", "exempt from power restrictions", 34),
          ("SYSTEM_ALERT_WINDOW", "allow", "allow display over other apps", 0),
          ("AUTO_REVOKE_PERMISSIONS_IF_UNUSED", "ignore", "never pause the app when unused", 30),
          ("SCHEDULE_EXACT_ALARM", "allow", "allow exact alarms", 31))
MANUAL = ("On the phone, for each app: App info > Battery usage > turn on 'Allow background activity' and 'Allow "
          "auto launch'; App info > Permissions > allow 'Show pop-ups while running in background' (ColorOS keeps it "
          "out of adb's reach); in Recents, lock the app's card. Do NOT turn on any Developer-options switch for this.")


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
        ops = parse.appops(device.read(f"cmd appops get {p}").out)
        wants_alarms = device.sdk >= 31 and EXACT_ALARM in parse.granted_perms(device.out(f"dumpsys package {p}"))
        for op, mode, what, min_sdk in APPOPS:
            if op == "SCHEDULE_EXACT_ALARM" and not wants_alarms:
                continue
            if device.sdk >= min_sdk and ops.get(op) != mode:
                st = steps.appop(p, op, mode, ops.get(op), "keepalive", risk)
                st.label = f"{p}: {what}"
                plan.steps.append(st)
        if device.sdk >= 31 and device.out(f"cmd app_hibernation get-state {p}").strip() == "true":
            plan.steps.append(Step(f"{p}: wake from hibernation", f"cmd app_hibernation set-state {p} false",
                                   [f"cmd app_hibernation set-state {p} true"], "keepalive", p, risk,
                                   touches=[f"hibernation:{p}"]))
        bucket = parse.standby_bucket(device.out(f"am get-standby-bucket {p}"))
        if bucket and bucket != "active":
            plan.steps.append(Step(f"{p}: standby bucket {bucket} -> active", f"am set-standby-bucket {p} active",
                                   [f"am set-standby-bucket {p} {bucket}"], "keepalive", p, risk,
                                   touches=[f"standby:{p}"]))
        level = bg_level(device, p)
        if level and level not in ("exempted", "unrestricted"):
            plan.steps.append(Step(f"{p}: background restriction {level} -> exempted",
                                   f"am set-bg-restriction-level --user 0 {p} exempted",
                                   [f"am set-bg-restriction-level --user 0 {p} {level}"], "keepalive", p, risk,
                                   touches=[f"bgrestrict:{p}"]))
        plan.steps.append(Step(f"Open app info of {p} (turn on background activity, auto launch, background pop-ups)",
                               f"am start -a android.settings.APPLICATION_DETAILS_SETTINGS -d package:{p}",
                               category="keepalive", pkg=p, risk="read"))
    if sel.locked:
        safety.make_expert(plan, sel.locked)
    plan.notes.append(MANUAL)
    plan.notes.append("ColorOS may still kill apps it considers idle; the Battery usage switches are the part that "
                      "matters most.")
    return plan


# what each ApplicationExitInfo reason means for a kept-alive app, and what helps
WHY = {
    "USER_REQUESTED": "force-stopped: swiped out of Recents, 'Clear all', a ColorOS cleaner or Force stop",
    "OTHER": "killed by the system - on ColorOS usually its app killer (Athena)",
    "LOW_MEMORY": "Android ran out of memory",
    "FREEZER": "killed while frozen in the background",
    "EXCESSIVE_RESOURCE_USAGE": "used too much CPU or battery in the background",
    "SIGNALED": "killed by a signal (usually a system app killer)",
    "EXIT_SELF": "the app closed itself",
    "CRASH": "the app crashed (not a background kill)",
    "CRASH_NATIVE": "the app crashed (not a background kill)",
    "ANR": "the app stopped responding (not a background kill)",
    "PERMISSION_CHANGE": "a permission was changed, so Android restarted it",
    "PACKAGE_UPDATED": "the app was updated",
    "PACKAGE_STATE_CHANGE": "the app was disabled or changed",
    "DEPENDENCY_DIED": "a process it depends on died",
    "USER_STOPPED": "its user profile was stopped",
    "INITIALIZATION_FAILURE": "the app failed to start",
}
HELP = {
    "USER_REQUESTED": "lock the app's card in Recents; don't use 'Clear all' or ColorOS cleaners on it",
    "OTHER": "App info > Battery usage > turn on 'Allow background activity' and 'Allow auto launch'",
    "SIGNALED": "App info > Battery usage > turn on 'Allow background activity' and 'Allow auto launch'",
    "FREEZER": "App info > Battery usage > turn on 'Allow background activity'",
    "EXCESSIVE_RESOURCE_USAGE": "App info > Battery usage > turn on 'Allow background activity'",
    "LOW_MEMORY": "close heavy apps / games; no setting prevents this",
}


def exits(device: "Device", p: str, limit: int = 5) -> List[Dict[str, str]]:
    """The app's last process exits, newest first (read-only; empty before Android 11)."""
    if device.sdk < 30:
        return []
    return parse.exit_info(device.read(f"dumpsys activity exit-info {p}").out)[:limit]


def why_lines(device: "Device", pkgs: Iterable[str], limit: int = 5) -> List[str]:
    """Why each app last died, with what helps - plain ASCII lines for the CLI and the TUI (read-only)."""
    out: List[str] = []
    for p in pkgs:
        ex = exits(device, p, limit)
        out.append(f"{p}:" if ex else f"{p}: no exits recorded (not killed since boot, or Android < 11)")
        for e in ex:
            reason = e["reason"]
            what = WHY.get(reason, reason.lower().replace("_", " "))
            if "athena" in e["description"].lower():
                what = "killed by ColorOS's app killer (Athena)"
            detail = "; ".join(x for x in (e["subreason"], e["description"]) if x)
            out.append(f"  {e['ts'] or '?':<19}  {reason}: {what}" + (f" [{detail}]" if detail else ""))
            fix = HELP.get("OTHER" if "athena" in e["description"].lower() else reason)
            if fix:
                out.append(f"  {'':<19}  -> {fix}")
    return out


def bg_level(device: "Device", p: str) -> str:
    """Android 13+ background restriction level ("" when the build has no such command)."""
    if device.sdk < 33:
        return ""
    r = device.read(f"am get-bg-restriction-level --user 0 {p}")
    v = r.out.strip()
    return v if r.ok and v in BG_LEVELS else ""


def _devcfg_step(device: "Device", key: str, value: str, label: str) -> Optional[Step]:
    prev = device.out(f"device_config get activity_manager {key}").strip()
    if prev == value:
        return None
    undo = (f"device_config put activity_manager {key} {prev}" if prev.isdigit()
            else f"device_config delete activity_manager {key}")
    return Step(label, f"device_config put activity_manager {key} {value}", [undo], "keepalive", None, "risky",
                touches=[f"devcfg:activity_manager:{key}"])


def child_process_plan(device: "Device") -> Plan:
    """Phone-wide, owner opt-in: Developer options > "Disable child process restrictions" (Android 12L+) and the
    phantom-process cap. Matters for apps that start their own processes (Termux, some sync tools)."""
    plan = Plan(title="Allow unlimited child processes (phone-wide)")
    cur = device.out(f"settings get global {CHILD_SETTING}").strip()
    if cur != "false":
        undo = (f"settings put global {CHILD_SETTING} {cur}" if cur == "true"
                else f"settings delete global {CHILD_SETTING}")
        plan.steps.append(Step("Developer option 'Disable child process restrictions' -> on",
                               f"settings put global {CHILD_SETTING} false", [undo], "keepalive", None, "risky",
                               touches=[f"setting:global:{CHILD_SETTING}"]))
    st = _devcfg_step(device, "max_phantom_processes", PHANTOM_MAX, "Child-process cap -> unlimited")
    if st:
        plan.steps.append(st)
    plan.notes.append("Phone-wide (owner opt-in). Undo just this plan with the command printed after it runs, or "
                      "turn 'Disable child process restrictions' off in Developer options.")
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


def statuses(device: "Device", pkgs: Iterable[str]) -> Dict[str, str]:
    """{pkg: "kept alive" | "partly" | ""} for many apps in a few batched reads (read-only)."""
    pkgs = list(pkgs)
    wl = parse.deviceidle_whitelist(device.out("dumpsys deviceidle whitelist"))
    ops = batch_read(device, pkgs, "cmd appops get $p", label="background mode")
    buckets = batch_read(device, pkgs, "am get-standby-bucket $p", label="standby bucket")
    out = {}
    for p in pkgs:
        checks = [bool(wl.get(p)), parse.appops(ops.get(p, "")).get("RUN_ANY_IN_BACKGROUND") == "allow",
                  parse.standby_bucket(buckets.get(p, "").strip()) == "active"]
        out[p] = "kept alive" if all(checks) else "partly" if any(checks) else ""
    return out


def parse_selection(text: str, items: List[str]) -> List[str]:
    """Legacy picker syntax: `3`, `1,4,7`, `2-9`, `all`, or package names; unknown tokens are ignored."""
    picked: List[str] = []
    for tok in re.split(r"[,\s]+", text.strip()):
        if not tok:
            continue
        m = re.fullmatch(r"(\d+)-(\d+)", tok)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            picked += [items[i - 1] for i in range(a, b + 1) if 1 <= i <= len(items)]
        elif tok.isdigit():
            if 1 <= int(tok) <= len(items):
                picked.append(items[int(tok) - 1])
        elif tok.lower() == "all":
            picked += items
        elif "." in tok:
            picked.append(tok)
    return list(dict.fromkeys(picked))
