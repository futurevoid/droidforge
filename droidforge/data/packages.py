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


# R-4.3 / PACKAGES.md "Locked": legacy HARD_PROTECTED substrings. Never touched outside expert mode.
HARD_PROTECTED = ("systemui", "com.android.phone", "telephony", ".ims", "com.android.settings",
                  "permissioncontroller", "packageinstaller", "com.android.shell", "keyguard",
                  "com.google.android.gms", "com.google.android.gsf", "com.android.vending",
                  "webview", "networkstack", "framework")

# PACKAGES.md "Telephony - never disabled by swaps; locked in debloat".
TELEPHONY = ("com.android.phone", "com.android.contacts", "com.android.incallui", "com.android.mms",
             "com.android.providers.telephony", "com.android.server.telecom")

# UAD-NG "Unsafe" packages named in PACKAGES.md - locked even when the UAD list is not downloaded.
KNOWN_UNSAFE = ("com.coloros.safecenter", "com.oplus.safecenter", "com.coloros.pictorial",
                "com.heytap.appplatform", "com.oplus.appplatform")

# Legacy FALLBACK_PROTECTED: packages UAD does not rate whose names look critical -> "I UNDERSTAND".
FALLBACK_PROTECTED = ("launcher", "securitypermission", "safecenter", "phonemanager", "providers",
                      "com.qualcomm", "com.qti", "wifi", "bluetooth", "nfc", "carrier", "simsettings",
                      "cellbroadcast", "documentsui", "extservices", "appplatform", "battery", "thermal",
                      "biometric", "fingerprint", "faceunlock", "camera", "dialer", "incallui", "contacts",
                      "setupwizard", "mediaprovider", "externalstorage")

# R-4.4 keep-list: warn, excluded from bulk selections unless explicitly added.
KEEP_GAME_SPACE = ("com.coloros.gamespace", "com.coloros.gamespaceui", "com.oplus.games", "com.oplus.stdid")
KEEP_SMART_SIDEBAR = ("com.coloros.smartsidebar",)

# PACKAGES.md "OTA path": updates are allowed - never in presets; warn if selected manually.
OTA_PATH = ("com.oplus.ota", "com.oppo.ota", "com.oplus.sau", "com.coloros.sau", "com.oplus.romupdate",
            "com.nearme.romupdate", "com.oplus.cota", "com.heytap.appplatform", "com.oplus.appplatform",
            "com.coloros.simsettings")


def is_keep(pkg: str) -> bool:
    return pkg in KEEP_GAME_SPACE or pkg in KEEP_SMART_SIDEBAR or "smartsidebar" in pkg


def is_ota(pkg: str) -> bool:
    return pkg in OTA_PATH


# R-3.4 keyboards
GBOARD = "com.google.android.inputmethod.latin"
GBOARD_IME = f"{GBOARD}/com.android.inputmethod.latin.LatinIME"
GBOARD_SETTINGS = f"{GBOARD}/com.google.android.apps.inputmethod.latin.preference.SettingsActivity"
CHINESE_IME_PATTERNS = ("sogou", "sohu", "baidu", "iflytek", "qqpinyin", "tencent", "pinyin", "oplus.inputmethod",
                        "coloros.inputmethod", "heytap")
SECURE_KEYBOARDS = ("com.oplus.securitykeyboard", "com.coloros.securitykeyboard")
SECURE_KEYBOARD_FRAMEWORK = "com.oplus.onet"
