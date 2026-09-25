"""Core plan types. Features build Plans; the executor runs them; TUI/CLI only render and confirm (P4)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

RISKS = ("read", "normal", "risky", "locked")
BATCH_SIZE = 5  # P13
# Touches that leave nothing to undo: a stopped process restarts, a reboot bumps the ROM's own boot counter.
# host:* is the PC (pacman / pipx / adb pairing), not the phone: nothing on the phone to undo.
EPHEMERAL_TOUCHES = ("proc:", "reboot", "setting:global:boot_count", "fw:*", "shizuku", "host:")


def is_ephemeral(touch: str) -> bool:
    return touch.startswith(EPHEMERAL_TOUCHES)


@dataclass
class Step:
    label: str                       # "Disable com.heytap.market"
    cmd: str                         # exact shell command (adb shell), or a host command when host=True
    undo: List[str] = field(default_factory=list)   # reverting commands, from state read before the plan
    category: str = ""               # debloat, language, dns, firewall, root, ...
    pkg: Optional[str] = None        # package this step is about (batching unit, P13)
    risk: str = "normal"             # read | normal | risky | locked
    verify: Optional[str] = None     # read command whose output proves success
    expect: Optional[str] = None     # regex the verify output must match
    fallbacks: List["Step"] = field(default_factory=list)   # escalation chain (force-disable)
    host: bool = False               # run on the PC instead of the phone
    touches: List[str] = field(default_factory=list)       # declared blast radius (P10)
    undoes: Optional[str] = None     # history entry id this step reverts (history marks it undone)
    extra: List["Step"] = field(default_factory=list)       # companions run after this step succeeds (compound stage)

    def all_undo(self) -> List[str]:
        """Undo of this step, its companions and every fallback stage, in the order they would be applied."""
        out = list(self.undo)
        for ex in self.extra:
            out += ex.all_undo()
        for fb in self.fallbacks:
            out += fb.all_undo()
        return out

    def all_touches(self) -> List[str]:
        out = list(self.touches)
        for ex in self.extra:
            out += ex.all_touches()
        for fb in self.fallbacks:
            out += fb.all_touches()
        return out


@dataclass
class Plan:
    title: str
    steps: List[Step] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)   # warnings shown in the preview
    typed: List[str] = field(default_factory=list)   # strings the user must type (locked names, "I UNDERSTAND")
    recovery: Optional[str] = None                   # recovery script path, written before execution (P15)
    id: str = field(default_factory=lambda: f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}")
    batch_size: int = BATCH_SIZE
    reboot_check: bool = False                       # R-11.9: offer "reboot now and re-check" afterwards
    expert: bool = False                             # contains locked packages (expert mode, batches of one)

    @property
    def writes(self) -> List[Step]:
        return [s for s in self.steps if s.risk != "read"]

    def packages(self) -> List[str]:
        return list(dict.fromkeys(s.pkg for s in self.steps if s.pkg))

    def batches(self) -> List[List[Step]]:
        """Group consecutive steps into batches of at most `batch_size` packages (P13). Steps without a package
        count as one unit each; expert plans use batches of one package."""
        size = 1 if self.expert else max(1, self.batch_size)
        batches: List[List[Step]] = []
        cur: List[Step] = []
        units: List[str] = []
        for i, s in enumerate(self.steps):
            unit = s.pkg or f"#step{i}"
            if unit not in units and len(units) >= size:
                batches.append(cur)
                cur, units = [], []
            if unit not in units:
                units.append(unit)
            cur.append(s)
        if cur:
            batches.append(cur)
        return batches


@dataclass
class Confirmation:
    ok: bool
    typed: List[str] = field(default_factory=list)


@dataclass
class StepResult:
    step: Step                        # the stage that finally ran (primary or a fallback)
    requested: Step                   # the step as planned
    ok: bool
    exit: int = 0
    out: str = ""
    err: str = ""
    attempts: List[str] = field(default_factory=list)   # every command sent for this step
    applied: List[Step] = field(default_factory=list)   # stages that took effect (undo applies to these)
    dry_run: bool = False
    verified: Optional[bool] = None
    effect: str = "unknown"           # changed | unchanged | unknown (P5, from the batch diff)
    history_id: Optional[str] = None
