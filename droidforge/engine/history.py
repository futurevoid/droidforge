"""History timeline (R-11.2): one JSONL file per device, one entry per executed step.

    {"type": "step", id, ts, serial, fingerprint, plan_id, plan_title, category, label, pkg, cmd, host, ok,
     exit, out_tail, undo[], touches[], risk, undoes, dry_run}
    {"type": "undone", id, by, ts}          (appended when an undo plan reverted entry `id`)

`undo(ids)` / `rollback_to(id)` return Plans that run through the normal guard + confirm + health-gated executor.
"""

from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional

from droidforge.engine.plan import Plan, Step, StepResult
from droidforge.engine.undo import undo_steps

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device

OUT_TAIL_LINES = 20


@dataclass
class Entry:
    id: str
    ts: str
    serial: str
    fingerprint: str
    plan_id: str
    plan_title: str
    category: str
    label: str
    cmd: str
    ok: bool
    exit: int = 0
    out_tail: str = ""
    undo: List[str] = field(default_factory=list)
    touches: List[str] = field(default_factory=list)
    pkg: Optional[str] = None
    host: bool = False
    risk: str = "normal"
    undoes: Optional[str] = None
    dry_run: bool = False
    undone: bool = False
    undone_by: Optional[str] = None

    @property
    def undoable(self) -> bool:
        return self.ok and not self.dry_run and not self.undone and bool(self.undo)

    def as_step(self) -> Step:
        return Step(label=self.label, cmd=self.cmd, undo=list(self.undo), category=self.category, pkg=self.pkg,
                    risk=self.risk, host=self.host, touches=list(self.touches))


def _safe(serial: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", serial) or "device"


class History:
    def __init__(self, serial: str, directory: Optional[Path] = None) -> None:
        if directory is None:
            from droidforge import config
            directory = config.paths().sub("history")
        self.serial = serial
        self.path = Path(directory) / f"{_safe(serial)}.jsonl"

    # ------------------------------------------------------------------ storage
    def _append(self, obj: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, sort_keys=True) + "\n")

    def entries(self) -> List[Entry]:
        if not self.path.exists():
            return []
        steps: Dict[str, Entry] = {}
        order: List[str] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn last line after a crash must not lose the rest
            t = obj.pop("type", "step")
            if t == "step":
                e = Entry(**{k: v for k, v in obj.items() if k in Entry.__dataclass_fields__})
                steps[e.id] = e
                order.append(e.id)
            elif t == "undone" and obj.get("id") in steps:
                steps[obj["id"]].undone = True
                steps[obj["id"]].undone_by = obj.get("by")
        return [steps[i] for i in order]

    def get(self, entry_id: str) -> Entry:
        for e in self.entries():
            if e.id == entry_id:
                return e
        raise KeyError(entry_id)

    # ------------------------------------------------------------------ executor hook
    def record(self, plan: Plan, result: StepResult, device: "Device") -> str:
        applied = result.applied
        stage = applied[-1] if applied else result.step
        undo_cmds = [u for st in applied for u in st.undo]
        tail = "\n".join(f"{result.out}\n{result.err}".strip().splitlines()[-OUT_TAIL_LINES:])
        e = Entry(id=f"{datetime.now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}",
                  ts=datetime.now().isoformat(timespec="seconds"), serial=self.serial,
                  fingerprint=_fingerprint(device), plan_id=plan.id, plan_title=plan.title,
                  category=result.requested.category, label=stage.label, cmd=stage.cmd, ok=result.ok,
                  exit=result.exit, out_tail=tail, undo=undo_cmds, touches=[t for st in applied for t in st.touches]
                  or list(result.requested.touches), pkg=result.requested.pkg, host=stage.host,
                  risk=result.requested.risk, undoes=result.requested.undoes, dry_run=result.dry_run)
        d = asdict(e)
        d.pop("undone")
        d.pop("undone_by")
        self._append({"type": "step", **d})
        if e.undoes and e.ok and not e.dry_run:
            self._maybe_mark_undone(e.undoes, e.id)
        return e.id

    def _maybe_mark_undone(self, original_id: str, by: str) -> None:
        entries = self.entries()
        orig = next((x for x in entries if x.id == original_id), None)
        if orig is None or orig.undone:
            return
        done = Counter(x.cmd for x in entries if x.undoes == original_id and x.ok and not x.dry_run)
        need = Counter(orig.undo)
        if all(done[c] >= n for c, n in need.items()):
            self._append({"type": "undone", "id": original_id, "by": by,
                          "ts": datetime.now().isoformat(timespec="seconds")})

    # ------------------------------------------------------------------ undo plans
    def undo(self, ids: Iterable[str], title: Optional[str] = None) -> Plan:
        wanted = set(ids)
        chosen = [e for e in self.entries() if e.id in wanted]
        return self._plan(chosen, title or f"Undo {len(chosen)} change(s)")

    def rollback_to(self, entry_id: str) -> Plan:
        """Undo `entry_id` and every newer entry, newest first."""
        entries = self.entries()
        idx = next(i for i, e in enumerate(entries) if e.id == entry_id)
        return self._plan(entries[idx:], f"Roll back to before {entries[idx].label} ({entries[idx].ts})")

    def _plan(self, chosen: List[Entry], title: str) -> Plan:
        plan = Plan(title=title)
        skipped = []
        ids = {e.id for e in chosen}
        for e in reversed(chosen):  # newest first
            if e.undoes in ids:
                continue  # it reverted an entry in this range: the pair cancels out (never "redo" it here)
            if not e.undoable:
                if not (e.dry_run or e.undone or not e.ok):
                    skipped.append(e.label)
                continue
            for st in undo_steps(e.as_step()):
                st.undoes = e.id
                plan.steps.append(st)
            if e.risk == "locked" and e.pkg:
                plan.expert = True
                if e.pkg not in plan.typed:
                    plan.typed.append(e.pkg)
        if skipped:
            plan.notes.append("No automatic undo recorded for: " + ", ".join(skipped))
        return plan


def _fingerprint(device: "Device") -> str:
    try:
        return device.fingerprint
    except Exception:  # never let history recording break a running plan
        return ""
