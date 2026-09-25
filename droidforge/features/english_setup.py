"""Guided "English setup" (replaces the legacy menu `e`). Three steps, each its own confirmed, health-gated plan:

1. Open Settings > Language - the USER adds English and drags it to the top; droidforge waits, then re-reads.
2. Keyboard: Gboard as default (R-3.4), then - only once Gboard is current - the Chinese keyboards off.
3. Apps still showing Chinese: the focused-app watcher records what the user opens; per-app language is offered
   for the caught apps that are installed user apps only (P12 - system apps follow the device language).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional

from droidforge.engine.plan import Plan
from droidforge.features import keyboard, language

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device

FOCUS_CMD = "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'"
FOCUS_RE = re.compile(r"u\d+\s+([A-Za-z]\w*(?:\.\w+)+)")

STEP_TITLES = ("1. Device language (you set it in Settings)", "2. Keyboard: Gboard, Chinese keyboards off",
               "3. Apps that still show Chinese")


def focused_package(device: "Device") -> Optional[str]:
    """The app in the foreground (legacy focused_pkg). Read-only."""
    for line in device.out(FOCUS_CMD).splitlines():
        m = FOCUS_RE.search(line)
        if m:
            return m.group(1)
    return None


@dataclass
class Watcher:
    """Records every app that comes to the foreground while the user browses the screens that show Chinese."""
    device: "Device"
    caught: List[str] = field(default_factory=list)
    last: Optional[str] = None

    def poll(self) -> Optional[str]:
        """One poll; returns the package if a new app came to the front."""
        p = focused_package(self.device)
        if p and p != self.last:
            self.last = p
            if p not in self.caught:
                self.caught.append(p)
            return p
        return None


@dataclass
class EnglishSetup:
    device: "Device"
    start_status: Optional[language.LanguageStatus] = None
    watcher: Optional[Watcher] = None

    # step 1
    def language_plan(self) -> Plan:
        self.start_status = language.status(self.device)
        plan = language.open_language_settings(self.device)
        plan.title = STEP_TITLES[0]
        return plan

    def language_result(self) -> str:
        before = self.start_status or language.status(self.device)
        return language.recheck(before, self.device)

    # step 2
    def keyboard_plan(self) -> Plan:
        plan = keyboard.gboard_plan(self.device)
        plan.title = f"{STEP_TITLES[1]} - Gboard"
        return plan

    def chinese_keyboards_plan(self) -> Plan:
        plan = keyboard.chinese_imes_plan(self.device)
        plan.title = f"{STEP_TITLES[1]} - Chinese keyboards off"
        return plan

    # step 3
    def start_watch(self) -> Watcher:
        self.watcher = Watcher(self.device)
        return self.watcher

    def caught_summary(self) -> Dict[str, str]:
        """{caught package: "" if it can get a per-app language, else why not}."""
        caught = self.watcher.caught if self.watcher else []
        return {p: language.refusal(self.device, p) for p in caught}

    def apps_plan(self, locales: str = language.DEFAULT_APP_LOCALES) -> Plan:
        caught = self.watcher.caught if self.watcher else []
        pick = language.pick_app_language(self.device, caught, locales)
        pick.plan.title = STEP_TITLES[2]
        if not caught:
            pick.plan.notes.append("No apps caught yet - start the watcher and open the screens that show Chinese.")
        return pick.plan
