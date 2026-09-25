"""Desktop notifications through notify-send (R-2.7): long job finished, device disconnected, OTA detected.
Silently does nothing when notify-send is not installed. The command is guard-checked like every host command."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device


def _clean(text: str) -> str:
    return re.sub(r"['\n\r\\]", " ", text)[:200]


def command(title: str, body: str) -> str:
    return f"notify-send -a droidforge '{_clean(title)}' '{_clean(body)}'"


def notify(title: str, body: str, device: Optional["Device"] = None) -> bool:
    from droidforge.adb import hostcmd
    from droidforge.engine import guard
    cmd = command(title, body)
    guard.check_command(cmd, host=True)
    return hostcmd.notify(cmd, device)
