"""Breakage alert + repair plans (R-12.5).

A breakage comes from (a) an executor stop (health regression or undeclared change after a batch), (b) the
reboot check, or (c) a startup / connect compare against the last healthy baseline of this phone (breakage between
sessions). The repair plan is the undo of the droidforge plan(s) involved, newest first, plus a revert of each
undeclared change from the "before" snapshot when the key is in the allowlist - it runs through the same guard and
health gate. When nothing droidforge did explains the break, there is NO automatic write: the manual path is
Settings > Reset all settings. The permission-monitoring switch is only ever turned off by the user.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional

from droidforge.engine import health
from droidforge.engine.health import (
    DEV_OPTIONS_CMD,
    PERMISSION_MONITORING_ALERT,
    RESET_ALL_SETTINGS,
    HealthReport,
    Regression,
)
from droidforge.engine.plan import Plan
from droidforge.engine.snapshot import Change

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device
    from droidforge.engine.executor import RunReport
    from droidforge.engine.history import Entry, History
    from droidforge.engine.profile import Profile

KIND_WORDS = {"setting": "Setting", "pkg": "Package", "perm": "Permission", "appop": "App-op",
              "applocale": "App language", "ime": "Keyboard", "config": "Display/configuration", "launcher": "Launcher"}


def describe_change(ch: Change) -> str:
    """Plain words + the raw value before/after."""
    kind = ch.key.split(":")[0]
    what = ch.key.split(":", 1)[1] if ":" in ch.key else ch.key
    return f"{KIND_WORDS.get(kind, kind)} {what}: {ch.before if ch.before is not None else '(unset)'} -> " \
           f"{ch.after if ch.after is not None else '(unset)'}"


@dataclass
class Breakage:
    source: str                                        # plan | reboot | startup
    regressions: List[Regression] = field(default_factory=list)
    undeclared: List[Change] = field(default_factory=list)
    recent: List[str] = field(default_factory=list)    # what droidforge changed just before (history labels)
    repair: Optional[Plan] = None                      # None / empty = nothing droidforge can undo
    title: str = ""

    @property
    def switch_on(self) -> bool:
        return any(r.probe == "permission_monitoring" for r in self.regressions)

    @property
    def explained(self) -> bool:
        return bool(self.repair and self.repair.steps)

    def what_broke(self) -> List[str]:
        out = [str(r) for r in self.regressions]
        out += [describe_change(c) for c in self.undeclared]
        return out

    def advice(self) -> List[str]:
        out: List[str] = []
        if self.switch_on:
            out.append(PERMISSION_MONITORING_ALERT)
        if self.explained:
            out.append("Fix it undoes what droidforge changed (newest first) and reverts the undeclared changes it "
                       "may write; then the phone is checked again.")
        else:
            out.append("Nothing droidforge did explains this, so droidforge will not write anything to fix it.")
        out.append(f"If the phone still misbehaves: {RESET_ALL_SETTINGS}")
        return out

    def lines(self) -> List[str]:
        out = [self.title or "Something on the phone broke", "", "What broke:"]
        out += [f"  - {w}" for w in self.what_broke()] or ["  -"]
        out += ["", "What droidforge changed just before:"]
        out += [f"  - {r}" for r in self.recent] or ["  - nothing"]
        out += ["", "What to do:"] + [f"  {a}" for a in self.advice()]
        return out


def from_report(rep: "RunReport") -> Breakage:
    """(a)/(b): an executor stop or a failed reboot check. The executor already built the repair plan."""
    src = "reboot" if rep.plan.steps and rep.plan.steps[0].category == "reboot" else "plan"
    recent = [r.step.label for r in rep.results if r.applied]
    return Breakage(src, list(rep.regressions), list(rep.undeclared), recent, rep.undo_plan,
                    f"Stopped: '{rep.plan.title}' changed something it should not have")


def check_startup(device: "Device", profile: "Profile", history: Optional["History"] = None) -> Optional[Breakage]:
    """(c): at start / connect, compare the health probes with the last healthy baseline of this phone.
    Read-only. None = healthy (or no baseline yet and nothing failing)."""
    now = health.run(device)
    if profile.healthy_baseline:
        regs = health.compare(HealthReport.from_dict(profile.healthy_baseline), now)
    else:
        regs = [Regression(p.name, p.label, "", p.value, p.detail) for p in now.failing]
    if not regs:
        if not now.failing:
            profile.save_healthy(now)        # a healthy connect is a session-level confirmation
            if profile.path:
                profile.save()
        return None
    b = Breakage("startup", regs, title="The phone differs from its last healthy check")
    if history is not None:
        since = [e for e in history.entries() if e.ts >= (profile.healthy_ts or "") and e.undoable]
        b.recent = [f"{e.ts.replace('T', ' ')[:19]}  {e.label}" for e in since]
        b.repair = startup_repair_plan(since, history)
    return b


def startup_repair_plan(entries: List["Entry"], history: "History") -> Plan:
    """Undo of droidforge's changes since the last healthy check, newest first."""
    plan = history.undo([e.id for e in entries], title="Fix it: undo droidforge's changes since the last healthy check")
    plan.notes.append(f"If the phone is still not right afterwards: {RESET_ALL_SETTINGS}")
    return plan


def developer_options_plan() -> Plan:
    """Opens Developer options so the USER can turn 'Disable permission monitoring' off (droidforge never does)."""
    from droidforge.engine.plan import Step
    return Plan(title="Open Developer options", steps=[Step("Open Developer options (turn the switch off yourself, "
                                                            "then reboot)", DEV_OPTIONS_CMD, category="fix",
                                                            risk="read")],
                notes=[PERMISSION_MONITORING_ALERT])


def recheck(device: "Device", profile: "Profile", baseline: Optional[HealthReport] = None) -> List[Regression]:
    """After Fix it: is the phone healthy again - vs the pre-plan baseline when there is one, else vs the last
    healthy baseline of this phone, else absolutely?"""
    now = health.run(device)
    base = baseline or (HealthReport.from_dict(profile.healthy_baseline) if profile.healthy_baseline else None)
    if base is not None:
        return health.compare(base, now)
    return [Regression(p.name, p.label, "", p.value, p.detail) for p in now.failing]
