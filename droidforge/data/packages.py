"""Curated package lists. docs/PACKAGES.md is the human-readable source of truth; keep both in sync."""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Iterable

# R-4.3b / PACKAGES.md "UI infrastructure": hidden from package lists by default, locked when shown, never a
# per-app language target (P12). Matched as fnmatch patterns against the package name.
UI_INFRA_PATTERNS = (
    "android", "oplus",
    "*overlay*", "*.rro*", "*auto_generated_characteristics_rro",
    "android.frameworkres.overlay*", "com.android.internal.display.cutout.*", "com.android.internal.systemui.navbar.*",
    "com.android.theme.*",
    "com.oplus.uxdesign", "com.oplus.uiengine", "com.oplus.systemui.plugins", "com.oplus.framework.*",
    "com.oplus.blur", "com.oplus.wallpapers", "com.heytap.colorfulengine",
    "com.android.settings*", "com.android.permissioncontroller", "com.oplus.securitypermission",
    "com.oplus.keyguard.*", "com.oplus.aod",
)

# P12: names that are never language targets even if a ROM ships them as "user" apps.
LANGUAGE_NEVER_SUBSTRINGS = ("systemui", "inputmethod", "launcher", "permissioncontroller", "packageinstaller",
                             "keyguard", "framework", "overlay")


def matches_any(pkg: str, patterns: Iterable[str]) -> bool:
    return any(fnmatchcase(pkg, pat) for pat in patterns)


def is_ui_infra(pkg: str) -> bool:
    return matches_any(pkg, UI_INFRA_PATTERNS)
