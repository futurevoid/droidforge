"""Install sources (R-6.1): open the Play page on the phone; download an APK from an OFFICIAL source (GitHub
releases, F-Droid, Mozilla) and `adb install`; install a local folder (splits via install-multiple).

The package an install creates is read from the APK before anything runs, so the step declares it (P10) and its
undo is `pm uninstall <p>` (user app). Apps that are already installed are left to the Play Store to update.
"""

from __future__ import annotations

import json
import shlex
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, List, Sequence

from droidforge.adb.apk import ApkError, package_name, split_name
from droidforge.data.presets import CATALOG
from droidforge.engine.plan import Plan, Step

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device

Opener = Callable[..., object]


def play_plan(device: "Device", pkg: str) -> Plan:
    """Open the app's Play Store page on the phone (an allowed read)."""
    return Plan(title=f"Open {pkg} in the Play Store", steps=[Step(
        f"Open {pkg} in the Play Store", f"am start -a android.intent.action.VIEW -d 'market://details?id={pkg}'",
        category="apps", risk="read")])


def _install_step(serial: str, apks: Sequence[Path], pkg: str) -> Step:
    multi = len(apks) > 1
    paths = " ".join(shlex.quote(str(a)) for a in apks)
    return Step(f"Install {pkg}" + (f" ({len(apks)} split APKs)" if multi else ""),
                f"adb -s {serial} install{'-multiple' if multi else ''} -r {paths}", [f"pm uninstall {pkg}"],
                "apps", pkg, host=True, touches=[f"pkg:{pkg}:installed", f"pkg:{pkg}:*"])


def install_plan(device: "Device", apks: Sequence[Path]) -> Plan:
    """One app: a base APK, optionally with its split APKs."""
    apks = [Path(a) for a in apks]
    base = next((a for a in apks if not split_name(a)), apks[0])
    plan = Plan(title=f"Install {base.name}")
    try:
        pkg = package_name(base)
    except ApkError as e:
        plan.notes.append(str(e))
        return plan
    if pkg in device.packages("-u"):
        plan.notes.append(f"{pkg} is already on the phone - update it from the Play Store (Android does not "
                          "downgrade, so droidforge cannot undo an update).")
        return plan
    plan.title = f"Install {pkg}"
    plan.steps.append(_install_step(device.serial or "device", [base] + [a for a in apks if a != base], pkg))
    plan.notes.append(f"Undo: pm uninstall {pkg}")
    return plan


def folder_plan(device: "Device", folder: Path) -> Plan:
    """Every app in a folder; APKs of the same package are installed together (splits)."""
    groups: Dict[str, List[Path]] = {}
    plan = Plan(title=f"Install APKs from {folder}")
    for apk in sorted(Path(folder).glob("*.apk")):
        try:
            groups.setdefault(package_name(apk), []).append(apk)
        except ApkError as e:
            plan.notes.append(f"Skipped: {e}")
    present = device.packages("-u")
    for pkg, files in groups.items():
        if pkg in present:
            plan.notes.append(f"Already on the phone: {pkg}")
            continue
        base = next((a for a in files if not split_name(a)), files[0])
        plan.steps.append(_install_step(device.serial or "device", [base] + [a for a in files if a != base], pkg))
    if not groups:
        plan.notes.append("No readable .apk files in this folder.")
    return plan


# ---------------------------------------------------------------------- official downloads (host, on request)
def _get(url: str, opener: Opener, timeout: float = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "droidforge"})
    with opener(req, timeout=timeout) as r:  # type: ignore[attr-defined]
        return r.read()


def download(app_key: str, dest: Path, opener: Opener = urllib.request.urlopen) -> Path:
    """Fetch the latest official APK of a catalog app into `dest`. Raises ValueError with a clear reason."""
    app = CATALOG[app_key]
    dest.mkdir(parents=True, exist_ok=True)
    if app.github:
        rel = json.loads(_get(f"https://api.github.com/repos/{app.github}/releases/latest", opener))
        assets = [a for a in rel.get("assets", []) if str(a.get("name", "")).endswith(".apk")]
        if not assets:
            raise ValueError(f"{app.github}: the latest release has no .apk")
        url, name = assets[0]["browser_download_url"], assets[0]["name"]
    elif app.fdroid:
        idx = json.loads(_get("https://f-droid.org/repo/index-v1.json", opener))
        versions = idx.get("packages", {}).get(app.package) or []
        if not versions:
            raise ValueError(f"{app.package} is not in F-Droid")
        name = versions[0]["apkName"]
        url = f"https://f-droid.org/repo/{name}"
    elif app.url:
        url, name = app.url, f"{app.package}.apk"
    else:
        raise ValueError(f"{app.name} has no official APK download - use its Play Store page")
    out = dest / Path(name).name
    out.write_bytes(_get(url, opener, timeout=600))
    got = package_name(out)
    if got != app.package:
        out.unlink()
        raise ValueError(f"downloaded APK is {got}, expected {app.package} - discarded")
    return out
