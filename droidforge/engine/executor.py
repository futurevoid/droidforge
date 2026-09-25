"""The only path from droidforge to the phone (CLAUDE.md, P1, P5, P8, P10, P11, P13, P15).

run(plan, device, confirm):
 1. guard.check() every step, fallback, verify and undo command - any refusal aborts before confirmation;
 2. confirm(plan) (TUI modal / CLI prompt); typed strings are re-checked here;
 3. baseline: health.run() + snapshot.take();
 4. the recovery script is written before the first command is sent;
 5. batches of <= 5 packages: run each step (fallback escalation, health-gated between stages), verify,
    record history; after each batch the blast-radius diff and health compare against the baseline;
 6. the first regression stops the plan - later batches are not sent - and an undo/revert plan is offered;
 7. caches invalidated, report returned.
Dry-run: nothing is sent; steps are logged as "(dry-run)" and history marks them dry_run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, List, Optional, Protocol, Sequence, Tuple, Union

from droidforge.adb.backend import RunResult
from droidforge.adb.hostcmd import run_host
from droidforge.engine import guard, health, recovery, safety, snapshot, undo
from droidforge.engine.health import HealthReport, Probe, Regression
from droidforge.engine.plan import Confirmation, Plan, Step, StepResult
from droidforge.engine.snapshot import Change, Snapshot

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device
    from droidforge.engine.profile import Profile

ERR_RE = re.compile(r"(?i)\b(error|exception|failure|unknown package|not installed)\b")
OBSERVABLE = ("setting:", "pkg:", "perm:", "appop:", "applocale:", "ime:enabled:", "launcher", "config:")

ConfirmHook = Callable[[Plan], Union[bool, Confirmation]]


class History(Protocol):  # engine/history.py implements it
    def record(self, plan: Plan, result: StepResult, device: "Device") -> str:
        ...


@dataclass
class RunReport:
    plan: Plan
    status: str = "done"             # refused | cancelled | dry-run | done | stopped
    error: str = ""
    results: List[StepResult] = field(default_factory=list)
    pre_failing: List[Probe] = field(default_factory=list)
    regressions: List[Regression] = field(default_factory=list)
    undeclared: List[Change] = field(default_factory=list)
    batches_total: int = 0
    batches_run: int = 0
    undo_plan: Optional[Plan] = None
    recovery: Optional[str] = None
    advice: Tuple[str, ...] = ()
    baseline_health: Optional[HealthReport] = None
    baseline_snapshot: Optional[Snapshot] = None
    final_health: Optional[HealthReport] = None

    @property
    def ok(self) -> bool:
        return self.status in ("done", "dry-run") and all(r.ok for r in self.results)

    @property
    def broke_something(self) -> bool:
        return bool(self.regressions or self.undeclared)


def succeeded(r: RunResult) -> bool:
    return r.exit == 0 and not ERR_RE.search(f"{r.out} {r.err}")


def _typed_ok(plan: Plan, answer: Union[bool, Confirmation]) -> Tuple[bool, str]:
    if isinstance(answer, Confirmation):
        if not answer.ok:
            return False, "cancelled"
        missing = [t for t in plan.typed if t not in answer.typed]
        if missing:
            return False, f"typed confirmation missing or wrong: {', '.join(missing)}"
        return True, ""
    if not answer:
        return False, "cancelled"
    if plan.typed:
        return False, f"this plan needs typed confirmation: {', '.join(plan.typed)}"
    return True, ""


def _send(step: Step, device: "Device") -> RunResult:
    return run_host(step.cmd, device) if step.host else device.sh(step.cmd)


def run(plan: Plan, device: "Device", confirm: ConfirmHook, *, dry_run: bool = False,
        history: Optional[History] = None, recovery_dir: Optional[Path] = None,
        profile: Optional["Profile"] = None, expert_mode: bool = False) -> RunReport:
    log = device.log
    rep = RunReport(plan=plan, batches_total=len(plan.batches()))

    # 1. guard + locked-package check - before anything is shown as runnable
    try:
        for s in plan.steps:
            guard.check(s, device)
            if s.risk == "locked" and not (plan.expert and expert_mode):
                raise guard.GuardError(s.cmd, "locked package outside expert mode (R-4.3)")
        safety.check_plan(plan, safety.SafetyContext.from_device(device), expert_mode)
    except guard.GuardError as e:
        rep.status, rep.error = "refused", str(e)
        log.error(f"Plan refused by the guard: {e.reason} ({e.cmd})")
        return rep

    # 2. confirm (P1)
    ok, why = _typed_ok(plan, confirm(plan))
    if not ok:
        rep.status, rep.error = ("cancelled", "") if why == "cancelled" else ("refused", why)
        log.info(f"{plan.title}: {why}")
        return rep

    if dry_run:
        for s in plan.steps:
            log.info(f"(dry-run) {'host' if s.host else 'adb shell'} {s.cmd}")
            res = StepResult(step=s, requested=s, ok=True, dry_run=True)
            if history is not None:
                res.history_id = history.record(plan, res, device)
            rep.results.append(res)
        rep.status = "dry-run"
        return rep

    # 3. baseline (P11, P10)
    scope = plan.packages()
    rep.baseline_health = base_h = health.run(device)
    rep.baseline_snapshot = base_s = snapshot.take(device, scope=scope)
    rep.pre_failing = base_h.failing
    for p in rep.pre_failing:
        log.warn(f"Already failing before this plan: {p.label} = {p.value or '-'}"
                 + (f" - {p.detail}" if p.detail else ""))

    # 4. recovery script (P15)
    rdir = recovery_dir or _default_recovery_dir()
    rep.recovery = str(recovery.write(plan, device.serial or "device", rdir))
    log.trace(f"recovery script written: {rep.recovery}")

    declared: List[str] = []

    def gate() -> bool:
        """Blast-radius diff + health compare vs the baseline. True = healthy, continue."""
        now_s = snapshot.take(device, scope=scope)
        changes = snapshot.diff(base_s, now_s)
        rep.undeclared = snapshot.undeclared(changes, declared)
        now_h = rep.final_health = health.run(device)
        regs = health.compare(base_h, now_h, declared)
        pre = {p.name for p in base_h.failing}
        rep.regressions = [r for r in regs if r.probe not in pre]
        _effects(rep.results, changes)
        return not (rep.undeclared or rep.regressions)

    # 5. batches (P13)
    stopped = False
    for n, batch in enumerate(plan.batches(), 1):
        log.trace(f"batch {n}/{rep.batches_total}: {len(batch)} step(s)")
        for step in batch:
            res = _run_step(step, device, declared, gate)
            if history is not None:
                res.history_id = history.record(plan, res, device)
            rep.results.append(res)
            if res.ok:
                log.ok(res.step.label + ("" if res.step is step else f" (after escalation: {res.step.cmd})"))
            else:
                log.error(f"{step.label} -> {res.err or res.out or 'failed'}")
            if rep.regressions or rep.undeclared:
                stopped = True  # a stage gate inside the escalation found damage
                break
        rep.batches_run = n
        if stopped or not gate():
            stopped = True
            break

    # 6. stop + undo offer
    if stopped:
        rep.status = "stopped"
        rep.undo_plan = undo.repair_plan(rep.results, rep.undeclared, device, f"Undo: {plan.title}")
        rep.advice = health.advice(rep.regressions)
        log.error(f"STOPPED after batch {rep.batches_run}/{rep.batches_total}: the phone changed in a way this "
                  f"plan did not declare. Later batches were not sent.")
        for r in rep.regressions:
            log.error(f"  health: {r}")
        for c in rep.undeclared:
            log.error(f"  undeclared change: {c}")
        for a in rep.advice:
            log.warn(a)
    else:
        rep.status = "done"

    # 7. caches + desired state (profile) + last healthy baseline (R-12.5)
    device.invalidate("plan finished")
    if profile is not None:
        profile.apply_results(rep.results)
        profile.note_device(device)
        if rep.status == "done" and rep.final_health is not None and not rep.final_health.failing:
            profile.healthy_baseline = rep.final_health.to_dict()
        if profile.path:
            profile.save()
    return rep


def _default_recovery_dir() -> Path:
    from droidforge import config
    return config.paths().sub("recovery")


def _run_step(step: Step, device: "Device", declared: List[str], gate: Callable[[], bool]) -> StepResult:
    stages = [step] + list(step.fallbacks)
    res = StepResult(step=step, requested=step, ok=False)
    for i, stage in enumerate(stages):
        if i > 0:
            # R-4.2: each escalation stage is health- and blast-radius-checked before the next one is sent
            if not gate():
                res.err = "escalation stopped: a check failed after the previous stage"
                return res
            device.log.warn(f"{step.pkg or step.label}: {stages[i - 1].cmd.split(' --user')[0]} refused, "
                            f"trying: {stage.label}")
        declared.extend(stage.touches)
        try:
            r = _send(stage, device)
        except guard.GuardError as e:  # pre-checked, so only if the device changed under us (e.g. P12 context)
            r = RunResult(1, "", str(e))
        res.attempts.append(stage.cmd)
        res.step, res.exit, res.out, res.err = stage, r.exit, r.out, r.err
        if succeeded(r):
            res.ok = True
            res.applied.append(stage)
            if stage.verify:
                v = device.read(stage.verify)
                res.verified = bool(re.search(stage.expect, v.out)) if stage.expect else v.ok
                if not res.verified:
                    device.log.warn(f"{stage.label}: verify did not confirm the change")
            return res
    return res


def _effects(results: Sequence[StepResult], changes: Sequence[Change]) -> None:
    keys = [c.key for c in changes]
    for r in results:
        if r.dry_run or not r.applied:
            continue
        touches = [t for st in r.applied for t in st.touches]
        observable = [t for t in touches if t.startswith(OBSERVABLE)]
        if not observable:
            r.effect = "unknown"
        elif any(snapshot.covered(k, observable) for k in keys):
            r.effect = "changed"
        else:
            r.effect = "unchanged"
