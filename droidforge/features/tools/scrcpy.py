"""scrcpy launcher (R-9.1): serial-aware, screen off / stay awake / record. Missing -> offer pacman (previewed)."""

from __future__ import annotations

import shlex
import shutil
from typing import TYPE_CHECKING, Optional

from droidforge.adb import hostcmd
from droidforge.engine.plan import Plan, Step

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device


def available() -> bool:
    return shutil.which("scrcpy") is not None


def command(serial: str, screen_off: bool = False, stay_awake: bool = False, record: Optional[str] = None) -> str:
    cmd = f"scrcpy -s {serial}"
    if screen_off:
        cmd += " --turn-screen-off"
    if stay_awake:
        cmd += " --stay-awake"
    if record:
        cmd += f" --record {shlex.quote(record)}"
    return cmd


def launch(device: "Device", screen_off: bool = False, stay_awake: bool = False, record: Optional[str] = None,
           check_installed: bool = True) -> str:
    """Start scrcpy in the background; returns the command. Raises FileNotFoundError when scrcpy is missing."""
    if check_installed and not available() and not hasattr(device.backend, "run_host"):
        raise FileNotFoundError("scrcpy is not installed: sudo pacman -S scrcpy")
    cmd = command(device.serial or "", screen_off, stay_awake, record)
    hostcmd.spawn(cmd, device)
    return cmd


def install_plan(device: "Device") -> Plan:
    """R-2.6: offer the Arch package install (host command, previewed like every plan)."""
    return Plan(title="Install scrcpy (host)", steps=[Step("Install scrcpy with pacman (asks for your password)",
                                                           "sudo pacman -S scrcpy", [], "host", host=True,
                                                           touches=["host:pkg:scrcpy"])])
