"""Keyboard (R-3.4): Gboard as default, Chinese IMEs off, ColorOS secure keyboard removed, Gboard languages.

- Undo restores the previous default IME - only ever an IME that was the default before (never a remote or
  accessory IME picked by us).
- Chinese IMEs are switched off (`ime disable`, the app stays installed) only once Gboard is the current IME.
- The secure keyboard: its IME ids are disabled first, then it is stopped and removed for user 0 (`pm uninstall
  --user 0`, falling back to disable-user). Refused while it is the current IME.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

from droidforge.adb import parse
from droidforge.data.packages import (
    CHINESE_IME_PATTERNS,
    GBOARD,
    GBOARD_IME,
    GBOARD_SETTINGS,
    SECURE_KEYBOARD_FRAMEWORK,
    SECURE_KEYBOARDS,
)
from droidforge.engine import steps
from droidforge.engine.plan import Plan, Step

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device


def current_ime(device: "Device") -> str:
    v = device.out("settings get secure default_input_method")
    return "" if v in ("", "null") else v


def enabled_imes(device: "Device") -> List[str]:
    return parse.ime_ids(device.read("ime list -s").out)


def is_chinese_ime(ime: str) -> bool:
    pkg = ime.split("/")[0].lower()
    return any(x in pkg for x in CHINESE_IME_PATTERNS) and not ime.startswith(GBOARD)


# ---------------------------------------------------------------------- Gboard
def gboard_plan(device: "Device") -> Plan:
    """Make Gboard the default keyboard (or open its Play page when it is not installed)."""
    if GBOARD not in device.packages():
        return Plan(title="Install Gboard", steps=[
            Step("Open Gboard in the Play Store", f"am start -a android.intent.action.VIEW -d "
                 f"'market://details?id={GBOARD}'", category="keyboard", risk="read")],
            notes=["Gboard is not installed. Install it on the phone, open it once, then run this again."])
    cur = current_ime(device)
    plan = Plan(title="Switch the keyboard to Gboard", reboot_check=True)
    if cur == GBOARD_IME:
        plan.notes.append("Gboard is already the default keyboard.")
        return plan
    if GBOARD_IME not in enabled_imes(device):
        plan.steps.append(steps.ime_enable(GBOARD_IME))
    plan.steps.append(steps.ime_set(GBOARD_IME, cur))
    plan.notes.append(f"Undo sets the keyboard back to {cur or '(none)'} - the one you had before.")
    plan.notes.append("Gboard's languages follow the languages you set in Settings; use 'Gboard languages' to add "
                      "more (e.g. Arabic).")
    return plan


def gboard_languages_plan(device: "Device") -> Plan:
    """Opens Gboard's settings, where the user adds languages (read-only for droidforge)."""
    plan = Plan(title="Open Gboard languages")
    if GBOARD not in device.packages():
        plan.notes.append("Gboard is not installed.")
        return plan
    plan.steps.append(Step("Open Gboard settings > Languages", f"am start -n {GBOARD_SETTINGS}", category="keyboard",
                           risk="read"))
    plan.notes.append("In Gboard: Languages > Add keyboard (e.g. English (US), Arabic).")
    return plan


# ---------------------------------------------------------------------- Chinese IMEs
def chinese_imes_plan(device: "Device") -> Plan:
    plan = Plan(title="Switch off the Chinese keyboards", reboot_check=True)
    cur = current_ime(device)
    if cur != GBOARD_IME:
        plan.notes.append("Make Gboard the default keyboard first - otherwise you could be left without a keyboard.")
        return plan
    targets = [i for i in enabled_imes(device) if i != cur and is_chinese_ime(i)]
    plan.steps += [steps.ime_disable(i) for i in targets]
    if not targets:
        plan.notes.append("No Chinese keyboards are enabled.")
    else:
        plan.notes.append("The apps stay installed; undo switches the keyboards back on.")
    return plan


# ---------------------------------------------------------------------- secure keyboard
def secure_keyboard_plan(device: "Device", include_framework: bool = False) -> Plan:
    """Remove the ColorOS secure keyboard for user 0 (owner request; PACKAGES.md)."""
    plan = Plan(title="Remove the ColorOS secure keyboard", reboot_check=True)
    installed = device.packages()
    cur = current_ime(device)
    enabled = enabled_imes(device)
    for p in SECURE_KEYBOARDS:
        if p not in installed:
            continue
        if cur.split("/")[0] == p:
            plan.notes.append(f"Refused {p}: it is the current keyboard - switch to Gboard first.")
            continue
        plan.steps += [steps.ime_disable(i) for i in enabled if i.split("/")[0] == p]
        plan.steps.append(steps.force_stop(p, "keyboard"))
        rm = Step(f"Remove {p} for user 0 (undo: restore)", f"pm uninstall --user 0 {p}",
                  [f"cmd package install-existing {p}"], "keyboard", p, touches=[f"pkg:{p}:installed"],
                  fallbacks=[steps.disable(p, "keyboard")])
        plan.steps.append(rm)
    if include_framework and SECURE_KEYBOARD_FRAMEWORK in installed and plan.steps:
        plan.steps.append(steps.remove_user0(SECURE_KEYBOARD_FRAMEWORK, "keyboard"))
    if not plan.steps and not plan.notes:
        plan.notes.append("The secure keyboard is not installed for user 0.")
    return plan
