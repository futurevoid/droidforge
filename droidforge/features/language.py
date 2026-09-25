"""Language (R-3.1, R-3.2) - rewritten after INCIDENT-2026-09-25.

- The DEVICE language is set by the user in the phone's own Settings, never by droidforge (P9). droidforge reads
  it (`getprop persist.sys.locale`, `settings get system system_locales`, the global configuration line), opens
  Settings > Language with short instructions, and re-reads afterwards.
- PER-APP language only for apps the user picks that are installed user apps and not excluded by P12 (system apps,
  UI infrastructure, the current keyboard and launcher). One `cmd locale set-app-locales` per app; the previous
  value is recorded so undo restores it exactly. There is no "all apps" option.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional

from droidforge.adb import parse
from droidforge.adb.batch import batch_read
from droidforge.engine import guard, steps
from droidforge.engine.plan import Plan
from droidforge.engine.snapshot import CONFIG_CMD

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device

LOCALE_SETTINGS = "android.settings.LOCALE_SETTINGS"
APP_LOCALE_SETTINGS = "android.settings.APP_LOCALE_SETTINGS"
TAGS_RE = re.compile(r"^(?:[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*(?:,[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*)*)?$")
DEFAULT_APP_LOCALES = "en-US"

INSTRUCTIONS = [
    "On the phone: Settings > Language opens now.",
    "Add 'English (United States)' and drag it to the top of the list.",
    "Optional: add Arabic below it (Gboard can then offer both).",
    "droidforge does not change the device language itself - it only reads it again when you are done.",
]


@dataclass
class LanguageStatus:
    persist_locale: str
    system_locales: str
    config_locales: str

    @property
    def first(self) -> str:
        for src in (self.system_locales, self.persist_locale):
            if src and src != "null":
                return src.split(",")[0]
        return self.config_locales.split(",")[0].replace("_", "-") if self.config_locales else ""

    @property
    def chinese_first(self) -> bool:
        return self.first.lower().startswith("zh")

    @property
    def english_first(self) -> bool:
        return self.first.lower().startswith("en")

    def describe(self) -> str:
        shown = self.system_locales if self.system_locales not in ("", "null") else self.persist_locale
        return f"{shown or self.config_locales or '-'}" + (" (Chinese first)" if self.chinese_first else "")


def status(device: "Device") -> LanguageStatus:
    """Read-only (R-3.1)."""
    return LanguageStatus(device.out("getprop persist.sys.locale"),
                          device.out("settings get system system_locales"),
                          parse.global_config(device.read(CONFIG_CMD).out).get("locales", ""))


def open_language_settings(device: "Device") -> Plan:
    """Opens Settings > Language (an allowed read: nothing is written). The user changes the language there."""
    st = status(device)
    plan = Plan(title="Open Settings > Language", steps=[steps.open_screen(LOCALE_SETTINGS, "Open Settings > Language",
                                                                           "language")])
    plan.notes.append(f"Device language now: {st.describe()}")
    plan.notes += INSTRUCTIONS
    return plan


def open_app_languages(device: "Device") -> Plan:
    return Plan(title="Open Settings > App languages",
                steps=[steps.open_screen(APP_LOCALE_SETTINGS, "Open Settings > App languages", "language")])


def recheck(before: LanguageStatus, device: "Device") -> str:
    now = status(device)
    if now.first == before.first:
        return f"Device language unchanged: {now.describe()}"
    return f"Device language is now {now.describe()} (was {before.describe()})"


# ---------------------------------------------------------------------- per-app language (R-3.2)
def app_locales(device: "Device", pkgs: Iterable[str]) -> Dict[str, str]:
    """{pkg: "en-US,ar-EG"} - "" means the app follows the device language."""
    res = batch_read(device, pkgs, "cmd locale get-app-locales $p --user 0", label="app languages")
    return {p: parse.app_locales(o) for p, o in res.items()}


def refusal(device: "Device", pkg: str) -> str:
    """Why `pkg` cannot get a per-app language (P12), or ""."""
    if device.sdk < 33:
        return "per-app language needs Android 13+"
    return guard.language_refusal(pkg, guard.Context(device))


def candidates(device: "Device") -> List[str]:
    """User apps that may be picked (never system apps, UI infrastructure, the keyboard or the launcher)."""
    if device.sdk < 33:
        return []
    ctx = guard.Context(device)
    return sorted(p for p in device.packages("-3") if not guard.language_refusal(p, ctx))


@dataclass
class AppLanguagePick:
    plan: Plan
    refused: Dict[str, str] = field(default_factory=dict)
    kept: Dict[str, str] = field(default_factory=dict)       # apps on a language the user chose themselves
    already: List[str] = field(default_factory=list)


def app_language_plan(device: "Device", picked: Iterable[str], locales: str = DEFAULT_APP_LOCALES,
                      override_custom: bool = False) -> Plan:
    return pick_app_language(device, picked, locales, override_custom).plan


def pick_app_language(device: "Device", picked: Iterable[str], locales: str = DEFAULT_APP_LOCALES,
                      override_custom: bool = False) -> AppLanguagePick:
    """Plan one `set-app-locales` per picked app. Apps refused by P12 are listed with the reason; apps already on
    `locales` are skipped; apps the user set to another language (not English/Chinese) are left alone unless
    `override_custom` (legacy keep_custom)."""
    if not TAGS_RE.match(locales):
        raise ValueError(f"invalid locale list: {locales!r}")
    picked = list(dict.fromkeys(picked))
    title = f"App language -> {locales or 'follow the device'}"
    out = AppLanguagePick(Plan(title=title))
    allowed = []
    for p in picked:
        why = refusal(device, p)
        if why:
            out.refused[p] = why
            out.plan.notes.append(f"Refused {p}: {why}")
        else:
            allowed.append(p)
    current = app_locales(device, allowed)
    for p in allowed:
        cur = current.get(p, "")
        if cur == locales:
            out.already.append(p)
            continue
        if not override_custom and cur and locales and not cur.lower().startswith(("en", "zh")):
            out.kept[p] = cur
            out.plan.notes.append(f"Left {p} on the language you chose for it ({cur}).")
            continue
        out.plan.steps.append(steps.app_locale(p, locales, cur))
    if out.already:
        out.plan.notes.append("Already set: " + ", ".join(out.already))
    if out.plan.steps:
        out.plan.notes.append("Undo puts each app back on exactly the language it had before.")
    return out


def reset_app_language_plan(device: "Device", pkgs: Iterable[str], previous: Optional[Dict[str, str]] = None
                            ) -> Plan:
    """Back to the recorded previous value (profile.app_locale_prev) or to "follow the device"."""
    previous = previous or {}
    plan = Plan(title="Reset app languages")
    allowed = [p for p in pkgs if not refusal(device, p)]
    current = app_locales(device, allowed)
    for p in allowed:
        target = previous.get(p, "")
        if current.get(p, "") != target:
            plan.steps.append(steps.app_locale(p, target, current.get(p, "")))
    return plan
