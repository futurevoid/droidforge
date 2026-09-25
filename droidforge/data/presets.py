"""Presets (PACKAGES.md "App catalog"): where each app comes from. Official sources only (R-6.1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class App:
    name: str
    package: str
    github: Optional[str] = None       # owner/repo - latest release .apk asset
    fdroid: bool = False               # F-Droid main repo
    url: Optional[str] = None          # fixed official URL (vendor)


# Firefox Nightly: Mozilla's official "latest nightly" link - status V in COMMANDS.md (the dev host could not reach
# it through its proxy on 2026-09-25; confirm in Phase 9). Play is the default source.
FIREFOX_NIGHTLY_URL = "https://download.mozilla.org/?product=fenix-nightly-latest&os=android&lang=multi"

CATALOG: Dict[str, App] = {
    "gboard": App("Gboard", "com.google.android.inputmethod.latin"),
    "firefox-nightly": App("Firefox Nightly", "org.mozilla.fenix", url=FIREFOX_NIGHTLY_URL),
    "photos": App("Google Photos", "com.google.android.apps.photos"),
    "files": App("Files by Google", "com.google.android.apps.nbu.files"),
    "messages": App("Google Messages", "com.google.android.apps.messaging"),
    "phone": App("Google Phone", "com.google.android.dialer"),
    "calendar": App("Google Calendar", "com.google.android.calendar"),
    "contacts": App("Google Contacts", "com.google.android.contacts"),
    "keep": App("Google Keep", "com.google.android.keep"),
    "shizuku": App("Shizuku", "moe.shizuku.privileged.api", github="RikkaApps/Shizuku"),
    "integrity-checker": App("Play Integrity checker", "gr.nikolasspyr.integritycheck"),
    "tasker": App("Tasker", "net.dinglisch.android.taskerm"),
    "systemui-tuner": App("SystemUI Tuner", "com.zacharee1.systemuituner"),
    "automate": App("Automate", "com.llamalab.automate"),
    "macrodroid": App("MacroDroid", "com.arlosoft.macrodroid"),
}
