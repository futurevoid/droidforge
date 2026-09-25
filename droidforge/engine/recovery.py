"""Host-side recovery script (P15): written before the first command of a plan is sent, so the phone can be
restored even if droidforge crashes midway. Plain `adb -s <serial> shell '<undo>'` lines, newest step first.

Every undo command puts a value back to what it was before the plan, so the script is safe to run after a
partial run and safe to run twice.
"""

from __future__ import annotations

import shlex
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from droidforge.engine.health import RESET_ALL_SETTINGS
from droidforge.engine.plan import Plan

HEADER = "#!/bin/sh\n# droidforge recovery script - undo of every step of one plan, newest first.\n"


def lines_for(plan: Plan, serial: str) -> List[str]:
    out = []
    for step in reversed(plan.steps):
        for u in reversed(step.all_undo()):
            out.append(f"adb -s {shlex.quote(serial)} shell {shlex.quote(u)}")
    return out


def write(plan: Plan, serial: str, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{serial}-{plan.id}.sh"
    body = [
        HEADER.rstrip("\n"),
        f"# plan:    {plan.title} ({plan.id})",
        f"# device:  {serial}",
        f"# written: {datetime.now():%Y-%m-%d %H:%M:%S} (before the first command was sent)",
        "# run:     sh " + shlex.quote(str(path)),
        f"# If the phone still looks wrong afterwards: {RESET_ALL_SETTINGS}",
        "",
    ] + lines_for(plan, serial) + [""]
    path.write_text("\n".join(body), encoding="utf-8")
    path.chmod(0o755)
    plan.recovery = str(path)
    return path


def parse(path: Path) -> List[Tuple[str, str]]:
    """[(serial, shell command)] from a recovery script (for replay in tests / the TUI's "run recovery")."""
    res = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("adb "):
            continue
        a = shlex.split(line)
        if a[1] == "-s" and a[3] == "shell" and len(a) == 5:
            res.append((a[2], a[4]))
    return res
