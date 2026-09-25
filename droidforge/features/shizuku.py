"""Shizuku (R-2.3): install from the official GitHub release, start it over adb, show its status.

Start (non-root, from the host over adb):
    pm path moe.shizuku.privileged.api   ->  .../base.apk  ->  .../lib/arm64/libshizuku.so  (run that path)
    fallback (older versions): sh /storage/emulated/0/Android/data/moe.shizuku.privileged.api/start.sh
On every connect droidforge ASKS to start it when it is installed but stopped (P14 - never on its own).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

from droidforge.engine.plan import Plan, Step
from droidforge.features import apps

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device

PKG = "moe.shizuku.privileged.api"
FALLBACK = f"sh /storage/emulated/0/Android/data/{PKG}/start.sh"


def base_path(device: "Device") -> Optional[str]:
    r = device.read(f"pm path {PKG}")
    for line in r.out.splitlines():
        if line.startswith("package:") and line.endswith("/base.apk"):
            return line[8:]
    return None


def status(device: "Device") -> str:
    """not installed | stopped | running"""
    if base_path(device) is None:
        return "not installed"
    return "running" if device.read("pidof shizuku_server").out.strip() else "stopped"


def start_plan(device: "Device") -> Plan:
    plan = Plan(title="Start Shizuku")
    base = base_path(device)
    if base is None:
        plan.notes.append("Shizuku is not installed - install it first (official GitHub release or Play Store).")
        return plan
    lib = base[: -len("base.apk")] + "lib/arm64/libshizuku.so"
    plan.steps.append(Step("Start the Shizuku server", lib, [], "shizuku", PKG, touches=["shizuku"],
                           verify="pidof shizuku_server", expect=r"\d+",
                           fallbacks=[Step("Start Shizuku (older versions: start.sh)", FALLBACK, [], "shizuku", PKG,
                                           touches=["shizuku"])]))
    plan.notes.append("Shizuku stops when the phone reboots; droidforge offers to start it again when it connects.")
    return plan


def install_plan(device: "Device", apk: Optional[Path] = None, dest: Optional[Path] = None) -> Plan:
    """Install the given APK, or download the latest official release into `dest` first."""
    if apk is None:
        from droidforge import config
        apk = apps.download("shizuku", dest or config.paths().sub("cache"))
    plan = apps.install_plan(device, [apk])
    plan.title = "Install Shizuku"
    return plan
