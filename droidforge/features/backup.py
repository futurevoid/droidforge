"""Backups (R-11.3): a full snapshot at every session start - settings (system/secure/global), package states,
every app locale, IMEs, launcher and the global configuration line. They are evidence and diff baselines.

"Restore" only reverts keys droidforge itself changed, through the history (undo of those entries). There is no
blanket settings restore: writing hundreds of keys back is its own risk (COMMANDS.md Forbidden). Changes that
droidforge did not make are listed with the advice to use Settings > Reset all settings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from droidforge.engine import snapshot
from droidforge.engine.health import RESET_ALL_SETTINGS
from droidforge.engine.plan import Plan
from droidforge.engine.snapshot import Change, Snapshot

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device
    from droidforge.engine.history import History


def backup_dir(serial: str, base: Optional[Path] = None) -> Path:
    if base is None:
        from droidforge import config
        base = config.paths().sub("backups")
    d = Path(base) / re.sub(r"[^A-Za-z0-9_.-]", "_", serial or "device")
    d.mkdir(parents=True, exist_ok=True)
    return d


def session_backup(device: "Device", base: Optional[Path] = None, kind: str = "session") -> Path:
    """Read-only: take the full snapshot and save it."""
    snap = snapshot.take(device, full=True)
    path = backup_dir(device.serial or "device", base) / f"{snap.ts.replace(':', '')}-{kind}.json"
    snap.save(path)
    device.log.trace(f"backup saved: {path}")
    return path


def list_backups(serial: str, base: Optional[Path] = None) -> List[Path]:
    return sorted(backup_dir(serial, base).glob("*.json"))


def changes_since(device: "Device", path: Path) -> List[Change]:
    """What differs between a saved backup and the phone now (read-only)."""
    before = Snapshot.load(path)
    return snapshot.diff(before, snapshot.take(device, full=True, scope=before.details))


@dataclass
class RestoreAnalysis:
    changes: List[Change] = field(default_factory=list)
    by_droidforge: List[Change] = field(default_factory=list)
    foreign: List[Change] = field(default_factory=list)
    entry_ids: List[str] = field(default_factory=list)


def analyse(device: "Device", history: "History", path: Path) -> RestoreAnalysis:
    before = Snapshot.load(path)
    a = RestoreAnalysis(changes=snapshot.diff(before, snapshot.take(device, full=True, scope=before.details)))
    live = [e for e in history.entries() if e.ts >= before.ts and e.undoable]
    for ch in a.changes:
        hits = [e for e in live if snapshot.covered(ch.key, e.touches)]
        if hits:
            a.by_droidforge.append(ch)
            a.entry_ids += [e.id for e in hits if e.id not in a.entry_ids]
        else:
            a.foreign.append(ch)
    return a


def restore_plan(device: "Device", history: "History", path: Path) -> Plan:
    """Undo the droidforge history entries that changed something since the backup - nothing else."""
    a = analyse(device, history, path)
    plan = history.undo(a.entry_ids, title=f"Restore droidforge's changes since {Path(path).name}")
    if a.foreign:
        plan.notes.append("Changed since the backup, but not by droidforge (droidforge will not touch these): "
                          + ", ".join(str(c) for c in a.foreign[:20])
                          + (f" ... and {len(a.foreign) - 20} more" if len(a.foreign) > 20 else ""))
        plan.notes.append(f"If the phone misbehaves because of them: {RESET_ALL_SETTINGS}")
    if not a.changes:
        plan.notes.append("Nothing changed since this backup.")
    return plan
