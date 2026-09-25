"""Parsers for device output shared by snapshot, health and features."""

from __future__ import annotations

import re
from typing import Dict, List

# ColorOS fields inside mOplusExtraConfiguration that describe how the phone looks (R-11.7 #3).
OEM_CONFIG_FIELDS = ("mMaterialColor", "mUxIconConfig", "mFontVariationSettings", "mFlipFont", "mIconPackName",
                     "mDarkModeBackgroundMaxL", "mDarkModeDialogBgMaxL", "mDarkModeForegroundMinL")


def last_component(out: str) -> str:
    """Last `pkg/activity` line of `cmd package resolve-activity --brief` ("" if nothing resolves)."""
    lines = [x.strip() for x in out.splitlines() if "/" in x and " " not in x.strip()]
    return lines[-1] if lines else ""


def runtime_perms(dumpsys_package: str) -> Dict[str, bool]:
    """`dumpsys package <p>` -> {runtime permission: granted} (legacy granted_runtime_perms, all states)."""
    sec = dumpsys_package.split("runtime permissions:", 1)
    if len(sec) < 2:
        return {}
    perms: Dict[str, bool] = {}
    for line in sec[1].splitlines()[1:]:
        m = re.match(r"\s+([\w.]+): granted=(true|false)", line)
        if not m:
            if line.strip() and not line.startswith(" " * 6):
                break
            continue
        perms.setdefault(m.group(1), m.group(2) == "true")
    return perms


def suspended(dumpsys_package: str) -> bool:
    m = re.search(r"User 0:.*?\bsuspended=(true|false)", dumpsys_package)
    return bool(m and m.group(1) == "true")


def signer_digest(dumpsys_package: str) -> str:
    m = re.search(r"signingCertificateDigest \(sha256\)=([0-9a-fA-F]+)", dumpsys_package) or \
        re.search(r"signatures:\[([0-9a-fA-F, ]+)\]", dumpsys_package)
    return m.group(1).strip().lower() if m else ""


def appops(out: str) -> Dict[str, str]:
    """`cmd appops get <p>` -> {OP: mode}."""
    res = {}
    for line in out.splitlines():
        m = re.match(r"\s*([A-Z][A-Z0-9_]+): ([a-z_]+)", line)
        if m:
            res[m.group(1)] = m.group(2)
    return res


def app_locales(out: str) -> str:
    """`cmd locale get-app-locales <p>` -> "en-US,ar-EG" ("" = follows the system)."""
    m = re.search(r"\[(.*?)\]", out)
    return m.group(1).replace(" ", "") if m else ""


def settings_list(out: str) -> Dict[str, str]:
    res = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            res[k.strip()] = v.strip()
    return res


def ime_ids(out: str) -> List[str]:
    return sorted(i.strip() for i in out.splitlines() if "/" in i)


def global_config(line: str) -> Dict[str, str]:
    """`mGlobalConfig={...}` -> locales, fontScale, density, night + the ColorOS look fields."""
    res: Dict[str, str] = {}
    if not line.strip():
        return res
    m = re.search(r"\{([0-9.]+) ", line)
    res["fontScale"] = m.group(1) if m else ""
    m = re.search(r" (\d+)dpi", line)
    res["density"] = m.group(1) if m else ""
    m = re.search(r"\[([^\]]*)\]", line)
    res["locales"] = m.group(1) if m else ""
    res["night"] = "yes" if re.search(r" night\b", line) else "no"
    for k in OEM_CONFIG_FIELDS:
        m = re.search(rf"\b{k}\s*=\s*([^,}}]*)", line)
        res[k] = m.group(1).strip() if m else ""
    for k, v in re.findall(r"\b(mDarkMode\w+)\s*=\s*([^,}]*)", line):
        res.setdefault(k, v.strip())
    return res


def granted_perms(dumpsys_package: str) -> Dict[str, bool]:
    """Install-time AND runtime permissions from `dumpsys package <p>` (power perms like WRITE_SECURE_SETTINGS
    are listed under `install permissions:`)."""
    out: Dict[str, bool] = {}
    for m in re.finditer(r"^\s+([\w.]+): granted=(true|false)", dumpsys_package, re.M):
        out.setdefault(m.group(1), m.group(2) == "true")
    return out


BUCKET_NAMES = {10: "active", 20: "working_set", 30: "frequent", 40: "rare", 45: "restricted"}


def standby_bucket(out: str) -> str:
    try:
        return BUCKET_NAMES.get(int(out.strip()), "")
    except ValueError:
        return ""


def deviceidle_whitelist(out: str) -> Dict[str, str]:
    """{pkg: "user" | "system" | "system-excidle"} from `dumpsys deviceidle whitelist`."""
    res: Dict[str, str] = {}
    for line in out.splitlines():
        parts = line.strip().split(",")
        if len(parts) >= 2 and parts[0] in ("user", "system", "system-excidle"):
            res.setdefault(parts[1], parts[0])
    return res
