"""Keep-alive for apps the user picks (R-6.3) - stops the system from killing their background work.

Per app:
    dumpsys deviceidle whitelist +<p>                 (undo -<p>; skipped if already whitelisted)
    cmd appops set <p> RUN_ANY_IN_BACKGROUND allow    (undo: the previous mode; same for RUN_IN_BACKGROUND and
                                                      START_FOREGROUND)
    am set-standby-bucket <p> active                  (undo: the previous bucket)
    am set-bg-restriction-level --user 0 <p> exempted (Android 13+; undo: the previous level)
    cmd appops set <p> SYSTEM_EXEMPT_FROM_POWER_RESTRICTIONS allow   (Android 14+; undo: the previous mode)
    cmd appops set <p> SYSTEM_ALERT_WINDOW allow      (display over other apps; undo: the previous mode)
    cmd appops set <p> AUTO_REVOKE_PERMISSIONS_IF_UNUSED ignore   (Android 11+, "Pause app activity if unused"
                                                      off; undo: the previous mode)
    cmd app_hibernation set-state <p> false           (Android 12+, only when the app is hibernating; undo: true)
    cmd appops set <p> SCHEDULE_EXACT_ALARM allow     (Android 12+, only when the app asks for exact alarms;
                                                      undo: the previous mode)
Read only: why_lines() reports why each app last died (`dumpsys activity exit-info <p>`, Android 11+, and the
`am_kill` lines of `logcat -b events`) and warns when the phone has no Google Play services (no push).
Phone-wide, its own plan so it can be undone on its own (owner opt-in 2026-09-25 / 2026-09-30, never by default):
    child_process_plan - Developer options "Disable child process restrictions" + the phantom-process cap
    phone_wide_plan    - the above + the device_config sync lock, the cached-app cap and the cached-app freezer off
    phone_wide_undo_plan - one-click undo of every phone-wide key still at droidforge's value
then the app's info page opens: ColorOS keeps "Allow background activity" / "Allow auto launch" under Battery
usage and "Show pop-ups while running in background" under Permissions, which adb cannot set - the user switches
them on there. droidforge never touches developer options for this.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Dict, Iterable, List, Mapping, Optional, Tuple

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
CACHED_MAX = "128"
FREEZER = "cached_apps_freezer"
GMS = "com.google.android.gms"
EXACT_ALARM = "android.permission.SCHEDULE_EXACT_ALARM"
# (app-op, mode, label, min SDK); SCHEDULE_EXACT_ALARM only for apps that ask for exact alarms
APPOPS = (("RUN_ANY_IN_BACKGROUND", "allow", "allow running in the background", 0),
          ("RUN_IN_BACKGROUND", "allow", "allow background services", 0),
          ("START_FOREGROUND", "allow", "allow foreground services", 28),
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
    if sel.allowed and GMS not in installed:
        plan.notes.append(NO_GMS)
    return plan


NO_GMS = ("No Google Play services on this phone: apps that rely on push (FCM) get no messages while they are "
          "closed, and no setting fixes that (only the global ROM or microG do).")


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


# am_kill reasons (logcat -b events) -> (what happened, what helps)
KILL_LOG = (
    (("athena",), "killed by ColorOS's app killer (Athena)", HELP["OTHER"]),
    (("hans",), "frozen / killed by ColorOS's freezer (HANS)", "App info > Battery usage > turn on 'Allow "
     "background activity'; lock the app in Recents"),
    (("cached #", "empty #"), "Android's cached-app limit (too many apps in the background)",
     "droidforge keepalive --phone-wide (raises the cached-app limit)"),
    (("excessive",), "used too much CPU in the background", HELP["EXCESSIVE_RESOURCE_USAGE"]),
    (("remove task", "user request", "stop "), "force-stopped (swiped away / Clear all)", HELP["USER_REQUESTED"]),
    (("low mem", "lmk", "min adj"), "Android ran out of memory", HELP["LOW_MEMORY"]),
    (("freez",), "killed while frozen in the background", HELP["FREEZER"]),
)
AM_KILL = re.compile(r"^(\S+ \S+).*\bam_kill\s*:\s*\[\d+,\d+,([^,\]]+),-?\d+,([^,\]]*)")


def kill_log(device: "Device", pkgs: Iterable[str], lines: int = 5000) -> Dict[str, List[Dict[str, str]]]:
    """{pkg: [{ts, reason}]} from the `am_kill` lines of the events log, newest first (read-only)."""
    want = set(pkgs)
    out: Dict[str, List[Dict[str, str]]] = {p: [] for p in want}
    r = device.read(f"logcat -b events -d -t {lines}")
    if not r.ok:
        return out
    for ln in reversed(r.out.splitlines()):
        m = AM_KILL.match(ln.strip())
        if m and m.group(2).split(":")[0] in want:
            out[m.group(2).split(":")[0]].append({"ts": m.group(1), "reason": m.group(3).strip()})
    return out


def _kill_reason(reason: str) -> Tuple[str, str]:
    low = reason.lower()
    for keys, what, fix in KILL_LOG:
        if any(k in low for k in keys):
            return what, fix
    return reason or "no reason given", ""


def why_lines(device: "Device", pkgs: Iterable[str], limit: int = 5) -> List[str]:
    """Why each app last died, with what helps - plain ASCII lines for the CLI and the TUI (read-only)."""
    out: List[str] = []
    pkgs = list(pkgs)
    kills = kill_log(device, pkgs) if pkgs else {}
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
        if kills.get(p):
            out.append("  kill log (am_kill):")
            for k in kills[p][:limit]:
                what, fix = _kill_reason(k["reason"])
                out.append(f"  {k['ts']:<19}  {what} [{k['reason']}]")
                if fix:
                    out.append(f"  {'':<19}  -> {fix}")
    if pkgs and GMS not in device.packages():
        out.append(NO_GMS)
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


def _sync_step(device: "Device") -> Optional[Step]:
    """Keep the ROM's server sync from resetting device_config values (Android 13+, where the modes exist)."""
    if device.sdk < 33:
        return None
    r = device.read("device_config get_sync_disabled_for_tests")
    prev = r.out.strip()
    if not r.ok or prev not in ("none", "until_reboot"):      # already locked, or a build without the command
        return None
    return Step("Stop the ROM resetting these values (device_config sync lock)",
                "device_config set_sync_disabled_for_tests persistent",
                [f"device_config set_sync_disabled_for_tests {prev}"], "keepalive", None, "risky",
                touches=["devcfg:sync:disabled_for_tests"])


def _freezer_step(device: "Device") -> Optional[Step]:
    """Developer options "Suspend execution for cached apps" off (Android 11+, takes effect after a reboot)."""
    if device.sdk < 30:
        return None
    cur = device.out(f"settings get global {FREEZER}").strip()
    if cur == "disabled":
        return None
    undo = (f"settings put global {FREEZER} {cur}" if cur in ("enabled", "device_default")
            else f"settings delete global {FREEZER}")
    return Step("Developer option 'Suspend execution for cached apps' -> off (after a reboot)",
                f"settings put global {FREEZER} disabled", [undo], "keepalive", None, "risky",
                touches=[f"setting:global:{FREEZER}"])


def phone_wide_plan(device: "Device") -> Plan:
    """Phone-wide, owner opt-in (2026-09-30): everything adb can loosen for background apps - the device_config
    sync lock first (so the ROM cannot reset what follows), the child-process switch and cap, the cached-app cap
    and the cached-app freezer off. Undo it in one go with phone_wide_undo_plan."""
    plan = Plan(title="Phone-wide keep-alive (all background limits)")
    for st in (_sync_step(device), *child_process_plan(device).steps,
               _devcfg_step(device, "max_cached_processes", CACHED_MAX, f"Cached-app cap -> {CACHED_MAX}"),
               _freezer_step(device)):
        if st:
            plan.steps.append(st)
    plan.notes.append("Phone-wide (owner opt-in). Reboot the phone afterwards: the freezer change needs it.")
    plan.notes.append("If anything goes wrong, undo all of it in one go: droidforge keepalive --phone-wide-undo "
                      "(TUI: Keep-alive > 'Undo phone-wide keep-alive'), then reboot.")
    plan.notes.append("A higher cached-app cap keeps more apps in memory; on a phone short of RAM that can mean more "
                      "low-memory kills - undo it if that happens.")
    return plan


def phone_wide_undo_plan(device: "Device", prev: Optional[Mapping[str, str]] = None) -> Plan:
    """One-click undo of the phone-wide keep-alive: every key still at droidforge's value goes back to what it was
    before (`prev`: touch -> undo command, kept in the profile) or, when that is unknown, to the phone's default.
    Keys the user changed since are left alone."""
    from droidforge.engine.profile import PHONE_WIDE
    prev = prev or {}
    plan = Plan(title="Undo phone-wide keep-alive")
    labels = {"setting:global:cached_apps_freezer": "'Suspend execution for cached apps' back",
              "devcfg:activity_manager:max_cached_processes": "Cached-app cap back",
              "devcfg:activity_manager:max_phantom_processes": "Child-process cap back",
              "setting:global:settings_enable_monitor_phantom_procs": "'Disable child process restrictions' back",
              "devcfg:sync:disabled_for_tests": "device_config sync lock back"}
    for key in reversed(list(PHONE_WIDE)):
        fwd = PHONE_WIDE[key]
        if _current(device, key) != fwd.split()[-1]:
            continue
        kind, ns, name = key.split(":", 2)
        default = (f"settings delete {ns} {name}" if kind == "setting"
                   else "device_config set_sync_disabled_for_tests none" if ns == "sync"
                   else f"device_config delete {ns} {name}")
        plan.steps.append(Step(labels[key], prev.get(key) or default, [fwd], "keepalive", None, "risky",
                               touches=[key]))
    if plan.steps:
        plan.notes.append("Reboot the phone afterwards so the freezer and the process limits reset.")
    else:
        plan.notes.append("Nothing to undo: no phone-wide keep-alive value is set.")
    return plan


def _current(device: "Device", key: str) -> str:
    kind, ns, name = key.split(":", 2)
    if kind == "setting":
        return device.out(f"settings get {ns} {name}").strip()
    if ns == "sync":
        return device.out("device_config get_sync_disabled_for_tests").strip() if device.sdk >= 33 else ""
    return device.out(f"device_config get {ns} {name}").strip()


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
