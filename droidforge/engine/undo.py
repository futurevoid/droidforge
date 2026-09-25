"""Undo plans (P2) and reverts of undeclared changes from the "before" snapshot (P10, R-11.8, R-12.5).

Undo and revert plans are ordinary Plans: they go through the same guard, confirmation and health gate.
Reverts are only offered for keys the allowlist lets droidforge write; everything else (display, language,
configuration) gets the manual advice instead - droidforge never "repairs" by toggling settings (P7).
"""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING, Iterable, List, Optional, Sequence, Tuple

from droidforge.engine import guard
from droidforge.engine.health import RESET_ALL_SETTINGS
from droidforge.engine.plan import Plan, Step, StepResult
from droidforge.engine.snapshot import Change

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device


def undo_steps(step: Step) -> List[Step]:
    """One undo Step per undo command of `step` (last command first). Its own undo re-applies `step`."""
    redo = [] if step.host else [step.cmd]
    return [Step(label=f"Undo: {step.label}", cmd=u, undo=list(redo), category=step.category, pkg=step.pkg,
                 risk="normal" if step.risk == "read" else step.risk, touches=list(step.touches))
            for u in reversed(step.undo)]


def undo_plan(results: Sequence[StepResult], title: str) -> Plan:
    """Undo of everything that took effect, newest first."""
    steps: List[Step] = []
    for r in reversed(list(results)):
        if r.dry_run:
            continue
        for stage in reversed(r.applied):
            steps += undo_steps(stage)
    return Plan(title=title, steps=steps)


def _q(v: str) -> str:
    return v if v and all(c.isalnum() or c in "._-:,/" for c in v) else shlex.quote(v)


def revert_command(ch: Change) -> Tuple[Optional[str], Optional[str]]:
    """(command restoring ch.before, command re-applying ch.after) - or (None, None) if not expressible."""
    parts = ch.key.split(":")
    kind = parts[0]
    b, a = ch.before, ch.after
    if kind == "setting" and len(parts) == 3:
        ns, key = parts[1], parts[2]
        back = f"settings delete {ns} {key}" if b is None else f"settings put {ns} {key} {_q(b)}"
        fwd = f"settings delete {ns} {key}" if a is None else f"settings put {ns} {key} {_q(a)}"
        return back, fwd
    if kind == "pkg" and len(parts) == 3:
        p, what = parts[1], parts[2]
        if what == "enabled" and b is not None:
            en, dis = f"pm enable --user 0 {p}", f"pm disable-user --user 0 {p}"
            return (en, dis) if b == "true" else (dis, en)
        if what == "installed" and b in ("true", "false") and a in ("true", "false"):
            ins, rem = f"cmd package install-existing {p}", f"pm uninstall -k --user 0 {p}"
            return (ins, rem) if b == "true" else (rem, ins)
        if what == "suspended" and b is not None:
            sus, uns = f"pm suspend --user 0 {p}", f"pm unsuspend --user 0 {p}"
            return (sus, uns) if b == "true" else (uns, sus)
        return None, None
    if kind == "perm" and len(parts) == 3 and b is not None:
        g, r = f"pm grant {parts[1]} {parts[2]}", f"pm revoke {parts[1]} {parts[2]}"
        return (g, r) if b == "granted" else (r, g)
    if kind == "appop" and len(parts) == 3:
        base = f"cmd appops set {parts[1]} {parts[2]}"
        return f"{base} {b or 'default'}", f"{base} {a or 'default'}"
    if kind == "applocale" and len(parts) == 2:
        base = f"cmd locale set-app-locales {parts[1]} --user 0"
        return (f"{base} --locales {b}" if b else base), (f"{base} --locales {a}" if a else base)
    if kind == "ime" and len(parts) >= 3 and parts[1] == "enabled":
        ime = ":".join(parts[2:])
        on, off = f"ime enable {ime}", f"ime disable {ime}"
        return (on, off) if b == "true" else (off, on)
    return None, None


def revert_steps(changes: Iterable[Change], device: Optional["Device"]) -> Tuple[List[Step], List[Change]]:
    """Steps reverting each change to its "before" value, when the allowlist permits; plus what cannot be."""
    steps: List[Step] = []
    manual: List[Change] = []
    for ch in changes:
        back, fwd = revert_command(ch)
        if back is None:
            manual.append(ch)
            continue
        try:
            touches = sorted(set(guard.touches_of(back, device)) | {ch.key})
            st = Step(label=f"Revert {ch.key} to {ch.before if ch.before is not None else '(unset)'}", cmd=back,
                      undo=[fwd] if fwd else [], category="revert", pkg=ch.key.split(":")[1] if ":" in ch.key
                      else None, touches=touches)
            guard.check(st, device)
        except guard.GuardError as e:
            if device is not None:
                device.log.trace(f"no automatic revert for {ch.key}: {e.reason}")
            manual.append(ch)
            continue
        steps.append(st)
    return steps, manual


def repair_plan(results: Sequence[StepResult], undeclared: Sequence[Change], device: Optional["Device"],
                title: str) -> Plan:
    """Undo of the plan (newest first) plus reverts of undeclared changes (R-11.8, R-12.5)."""
    plan = undo_plan(results, title)
    reverts, manual = revert_steps(undeclared, device)
    plan.steps += reverts
    if manual:
        plan.notes.append("Cannot be reverted by droidforge (not in its allowlist): "
                          + ", ".join(str(c) for c in manual))
        plan.notes.append(f"If the phone still looks wrong afterwards: {RESET_ALL_SETTINGS}")
    return plan
