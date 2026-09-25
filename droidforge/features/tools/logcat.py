"""Live logcat (R-9.2): `adb -s <serial> logcat -v threadtime [--pid=<pid>] ['*:E']`, filtered on the host by
level, tag and regex; focused app via `pidof`."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from droidforge.adb import hostcmd

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device

LEVELS = "VDIWEF"
LINE_RE = re.compile(r"^\S+\s+\S+\s+(\d+)\s+(\d+)\s+([VDIWEF])\s+([^:]*?)\s*:\s?(.*)$")


def command(serial: str, pid: Optional[int] = None, errors_only: bool = False) -> str:
    cmd = f"adb -s {serial} logcat -v threadtime"
    if pid:
        cmd += f" --pid={pid}"
    if errors_only:
        cmd += " '*:E'"
    return cmd


def pid_of(device: "Device", pkg: str) -> Optional[int]:
    out = device.out(f"pidof {pkg}")
    return int(out.split()[0]) if out.split() and out.split()[0].isdigit() else None


@dataclass
class Filter:
    level: str = "V"          # minimum level
    tag: str = ""             # substring of the tag
    regex: str = ""           # searched in the whole line

    def matches(self, line: str) -> bool:
        m = LINE_RE.match(line)
        if m:
            if LEVELS.index(m.group(3)) < LEVELS.index(self.level):
                return False
            if self.tag and self.tag.lower() not in m.group(4).lower():
                return False
        elif self.level != "V" or self.tag:
            return False
        if self.regex:
            try:
                return re.search(self.regex, line) is not None
            except re.error:
                return self.regex in line
        return True


def open_stream(device: "Device", pid: Optional[int] = None, errors_only: bool = False) -> hostcmd.Stream:
    return hostcmd.stream(command(device.serial or "", pid, errors_only), device)
