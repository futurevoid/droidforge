"""Permission audit (R-8.1): every app's granted runtime ("dangerous") permissions + notable app-ops, from one
`dumpsys package packages` call (+ batched `cmd appops get` for user apps). Revoking from the table is a normal
previewed, undoable plan."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Dict, Iterable, List, Mapping, Optional, Tuple

from droidforge.adb import parse
from droidforge.adb.batch import batch_read
from droidforge.engine import safety, steps
from droidforge.engine.plan import Plan

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device

# app-ops worth showing when an app has them allowed
NOTABLE_OPS = ("SYSTEM_ALERT_WINDOW", "GET_USAGE_STATS", "REQUEST_INSTALL_PACKAGES", "MANAGE_EXTERNAL_STORAGE",
               "WRITE_SETTINGS", "RUN_ANY_IN_BACKGROUND", "PROJECT_MEDIA", "ACCESS_NOTIFICATIONS", "BIND_ACCESSIBILITY_SERVICE")
BLOCK_RE = re.compile(r"^  Package \[([^\]]+)\]", re.M)


@dataclass
class AppAudit:
    package: str
    uid: int = 0
    system: bool = False
    signer: str = ""
    granted: List[str] = field(default_factory=list)
    ops: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def split_packages(dump: str) -> Dict[str, str]:
    """`dumpsys package packages` -> {package: its block}."""
    marks = [(m.group(1), m.start()) for m in BLOCK_RE.finditer(dump)]
    out: Dict[str, str] = {}
    for i, (name, start) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(dump)
        out.setdefault(name, dump[start:end])
    return out


def scan(device: "Device", with_ops: bool = True) -> List[AppAudit]:
    """Read-only."""
    blocks = split_packages(device.out("dumpsys package packages"))
    installed = device.packages()
    apps: List[AppAudit] = []
    for name, block in sorted(blocks.items()):
        if name not in installed:
            continue
        m = re.search(r"userId=(\d+)", block)
        apps.append(AppAudit(name, int(m.group(1)) if m else 0, bool(re.search(r"flags=\[[^\]]*\bSYSTEM\b", block)),
                             parse.signer_digest(block),
                             sorted(p for p, g in parse.runtime_perms(block).items() if g)))
    if with_ops:
        users = [a.package for a in apps if not a.system]
        ops = batch_read(device, users, "cmd appops get $p", label="app-ops")
        for a in apps:
            if a.package in ops:
                a.ops = {k: v for k, v in parse.appops(ops[a.package]).items() if k in NOTABLE_OPS and v == "allow"}
    return apps


def rows(apps: Iterable[AppAudit], include_system: bool = False) -> List[Tuple[str, str, str]]:
    """Flat table rows: (package, permission or app-op, kind)."""
    out = []
    for a in apps:
        if a.system and not include_system:
            continue
        out += [(a.package, p, "permission") for p in a.granted]
        out += [(a.package, op, "app-op") for op in a.ops]
    return out


def revoke_plan(device: "Device", picks: Iterable[Tuple[str, str]], uad: Optional[Mapping[str, dict]] = None,
                expert_mode: bool = False) -> Plan:
    """Revoke picked (package, permission) pairs, or set picked app-ops back to default. Undo re-grants."""
    picks = list(picks)
    plan = Plan(title="Revoke permissions (audit)")
    ctx = safety.SafetyContext.from_device(device, uad if uad is not None else {})
    sel = safety.select([p for p, _ in picks], ctx, expert_mode)
    for p, why in sel.rejected.items():
        plan.notes.append(f"Locked, skipped: {p} ({why})")
    for pkg, what in picks:
        if pkg not in sel.allowed:
            continue
        risk = "locked" if pkg in sel.locked else "normal"
        if "." in what:
            plan.steps.append(steps.revoke(pkg, what, "audit", risk))
        else:
            prev = parse.appops(device.read(f"cmd appops get {pkg}").out).get(what)
            if prev not in (None, "default") and what in ("SYSTEM_ALERT_WINDOW", "GET_USAGE_STATS",
                                                          "RUN_ANY_IN_BACKGROUND"):
                plan.steps.append(steps.appop(pkg, what, "default", prev, "audit", risk))
            else:
                plan.notes.append(f"{pkg}: {what} cannot be changed by droidforge - use the app's settings page.")
    if sel.locked:
        safety.make_expert(plan, sel.locked)
    return plan
