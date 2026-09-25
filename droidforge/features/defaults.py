"""Default-app swaps (R-6.2). Browser / SMS / Dialer through Android roles (undo re-adds the previous holder);
gallery, files, calendar, contacts, notes have no role: droidforge opens the Google app's Play page and - for
gallery / files only, if asked - disables the ColorOS app. com.android.contacts, com.android.incallui and
com.android.mms are never disabled (they are locked). After an SMS / dialer swap: check calls, SMS and VoLTE."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Mapping, Optional, Tuple

from droidforge.engine.plan import Plan, Step
from droidforge.features import apps, debloat

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device


@dataclass(frozen=True)
class Swap:
    label: str
    target: str                         # Google / Mozilla replacement
    role: Optional[str] = None
    coloros: Tuple[str, ...] = ()       # ColorOS apps that MAY be disabled (only when asked)
    warning: str = ""


SWAPS: Dict[str, Swap] = {
    "browser": Swap("Browser -> Firefox Nightly", "org.mozilla.fenix", "android.app.role.BROWSER",
                    ("com.heytap.browser", "com.nearme.browser")),
    "sms": Swap("SMS -> Google Messages", "com.google.android.apps.messaging", "android.app.role.SMS"),
    "dialer": Swap("Dialer -> Google Phone", "com.google.android.dialer", "android.app.role.DIALER"),
    "gallery": Swap("Gallery -> Google Photos", "com.google.android.apps.photos", None, ("com.coloros.gallery3d",),
                    "Disabling the ColorOS gallery may break the camera's thumbnail shortcut."),
    "files": Swap("Files -> Files by Google", "com.google.android.apps.nbu.files", None, ("com.coloros.filemanager",)),
    "calendar": Swap("Calendar -> Google Calendar", "com.google.android.calendar"),
    "contacts": Swap("Contacts -> Google Contacts", "com.google.android.contacts"),
    "notes": Swap("Notes -> Google Keep", "com.google.android.keep"),
}
TELEPHONY_CHECK = ("After changing the SMS or dialer app: make a test call and send an SMS, and check that VoLTE / "
                   "HD calling still shows in Settings > Mobile network. Undo puts the ColorOS app back.")


def holders(device: "Device", role: str) -> List[str]:
    r = device.read(f"cmd role get-role-holders --user 0 {role}")
    return [x.strip() for x in r.out.splitlines() if x.strip()] if r.ok else []


def role_step(role: str, pkg: str, prev: str) -> Step:
    return Step(f"Default {role.rsplit('.', 1)[-1].lower()} -> {pkg}", f"cmd role add-role-holder --user 0 {role} {pkg}",
                [f"cmd role add-role-holder --user 0 {role} {prev}"], "defaults", pkg, "risky",
                verify=f"cmd role get-role-holders --user 0 {role}", expect=rf"(?m)^{pkg.replace('.', '[.]')}$",
                touches=[f"role:{role}"])


def swap_plan(device: "Device", function: str, disable_coloros: bool = False,
              uad: Optional[Mapping[str, dict]] = None, expert_mode: bool = False) -> Plan:
    sw = SWAPS[function]
    installed = device.packages()
    plan = Plan(title=sw.label)
    if sw.target not in installed:
        plan = apps.play_plan(device, sw.target)
        plan.title = sw.label
        plan.notes.append(f"{sw.target} is not installed: install it, open it once, then run this again.")
        return plan
    if sw.role:
        cur = holders(device, sw.role)
        if cur == [sw.target]:
            plan.notes.append(f"{sw.target} already is the default.")
        elif not cur:
            plan.notes.append("No previous default app to return to, so droidforge cannot offer an undo: set it in "
                              "Settings > Default apps instead.")
            plan.steps.append(Step("Open Settings > Default apps", "am start -a "
                                   "android.settings.MANAGE_DEFAULT_APPS_SETTINGS", category="defaults", risk="read"))
        else:
            plan.steps.append(role_step(sw.role, sw.target, cur[0]))
        if function in ("sms", "dialer"):
            plan.notes.append(TELEPHONY_CHECK)
            plan.reboot_check = True
    else:
        plan.notes.append(f"Android has no default-app role for this: {sw.target} is installed; open it once "
                          "to use it.")
    if disable_coloros and sw.coloros:
        dis = debloat.disable_plan(device, [p for p in sw.coloros if p in installed], uad, expert_mode)
        plan.steps += dis.steps
        plan.typed += [t for t in dis.typed if t not in plan.typed]
        plan.notes += [n for n in dis.notes if n != "Nothing to do."]
        plan.reboot_check = plan.reboot_check or dis.reboot_check
        if sw.warning:
            plan.notes.insert(0, sw.warning)
    return plan
