"""Package verdicts (R-4.3, R-4.3b, R-4.4, R-4.5), typed confirmations and the executor's locked-package check.

Levels, strongest first:
  locked   core system / telephony / Play services / WebView / UI infrastructure / current IME and launcher /
           UAD Unsafe. Only in expert mode (R-4.3): batch of one, full package name typed, reboot check.
  keep     keep-list (Game space, Smart sidebar) and the OTA path: warn, never part of bulk selections.
  expert   UAD-NG "Expert": can break features -> typed "YES" (legacy behaviour).
  guarded  not rated by UAD-NG but the name looks critical -> typed "I UNDERSTAND" (R-4.5).
  unknown  not rated by UAD-NG.
  ok       UAD-NG Recommended / Advanced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, Iterable, List, Mapping, Optional, Set

from droidforge.adb import parse
from droidforge.data import packages as data
from droidforge.engine.guard import GuardError
from droidforge.engine.plan import Plan, Step

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device

LEVELS = ("locked", "keep", "expert", "guarded", "unknown", "ok")
TYPED_GUARDED = "I UNDERSTAND"
TYPED_EXPERT_TIER = "YES"
HOME_CMD = "cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME"

# touch key prefixes that name a package: pkg:<p>:..., perm:<p>:..., appop:<p>:..., applocale:<p>, fw:<p>, ...
_PKG_TOUCH = re.compile(r"^(?:pkg|perm|appop|applocale|fw|proc|deviceidle|standby):([A-Za-z0-9_.]+)")


@dataclass(frozen=True)
class Verdict:
    level: str
    reason: str

    @property
    def locked(self) -> bool:
        return self.level == "locked"


@dataclass
class SafetyContext:
    ime_pkg: str = ""
    home_pkg: str = ""
    uad: Mapping[str, dict] = field(default_factory=dict)

    @classmethod
    def from_device(cls, device: "Device", uad: Optional[Mapping[str, dict]] = None) -> "SafetyContext":
        ime = device.out("settings get secure default_input_method")
        home = parse.last_component(device.read(HOME_CMD).out)
        if uad is None:
            uad = _cached_uad()
        return cls(ime.split("/")[0] if "/" in ime else "", home.split("/")[0] if home else "", uad)

    def tier(self, p: str) -> str:
        return (self.uad.get(p) or {}).get("removal", "")


def _cached_uad() -> Mapping[str, dict]:
    try:
        from droidforge.data import uad  # P2.3; the cached copy only - never downloads here
        return uad.load_cached()
    except (ImportError, AttributeError):
        return {}


def verdict(p: str, ctx: SafetyContext) -> Verdict:
    if data.is_ui_infra(p):
        return Verdict("locked", "system UI infrastructure (R-4.3b)")
    if any(s in p for s in data.HARD_PROTECTED):
        return Verdict("locked", "core system package")
    if p in data.TELEPHONY:
        return Verdict("locked", "telephony - calls and SMS depend on it")
    if p and p == ctx.ime_pkg:
        return Verdict("locked", "current keyboard - switch keyboards first")
    if p and p == ctx.home_pkg:
        return Verdict("locked", "current home launcher")
    tier = ctx.tier(p)
    if tier == "Unsafe" or p in data.KNOWN_UNSAFE:
        return Verdict("locked", "UAD-NG: Unsafe")
    if data.is_keep(p):
        return Verdict("keep", "keep-list (Game space / Smart sidebar) - you asked to keep these")
    if data.is_ota(p):
        return Verdict("keep", "system update path - updates stay allowed")
    if tier == "Expert":
        return Verdict("expert", "UAD-NG: Expert - can break features")
    if tier:
        return Verdict("ok", f"UAD-NG: {tier}")
    if any(s in p for s in data.FALLBACK_PROTECTED):
        return Verdict("guarded", "not in UAD-NG and its name looks critical")
    return Verdict("unknown", "not in the UAD-NG list")


# ---------------------------------------------------------------------- lists (R-4.3b, R-4.4)
def is_hidden(p: str) -> bool:
    """UI infrastructure is hidden from package lists unless "show system UI infrastructure" is on."""
    return data.is_ui_infra(p)


def visible(pkgs: Iterable[str], show_infra: bool = False) -> List[str]:
    return sorted(p for p in pkgs if show_infra or not is_hidden(p))


def package_list(device: "Device", show_infra: bool = False, include_removed: bool = True) -> List[str]:
    universe = device.packages("-u") if include_removed else device.packages()
    return visible(universe, show_infra)


def bulk_selectable(pkgs: Iterable[str], ctx: SafetyContext, explicit: Iterable[str] = ()) -> List[str]:
    """What "select all" may pick: never locked; keep-list only when explicitly added."""
    explicit = set(explicit)
    out = []
    for p in pkgs:
        v = verdict(p, ctx)
        if v.level == "locked" or (v.level == "keep" and p not in explicit):
            continue
        out.append(p)
    return out


# ---------------------------------------------------------------------- plan requirements
@dataclass
class Requirements:
    typed: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    locked: List[str] = field(default_factory=list)
    verdicts: Dict[str, Verdict] = field(default_factory=dict)


def requirements(pkgs: Iterable[str], ctx: SafetyContext, needed_by: Optional[Mapping[str, List[str]]] = None
                 ) -> Requirements:
    """Typed strings and preview notes a plan over `pkgs` needs (legacy preflight)."""
    req = Requirements()
    pkgs = list(dict.fromkeys(pkgs))
    for p in pkgs:
        v = verdict(p, ctx)
        req.verdicts[p] = v
        if v.level == "locked":
            req.locked.append(p)
            req.typed.append(p)
            req.notes.append(f"LOCKED {p}: {v.reason}. Expert mode only - type the full package name.")
        elif v.level == "keep":
            req.notes.append(f"{p}: {v.reason}.")
        elif v.level == "expert":
            req.notes.append(f"{p}: {v.reason}.")
        elif v.level == "unknown":
            req.notes.append(f"{p}: no UAD-NG rating - you are on your own for this one.")
        for n in (needed_by or {}).get(p, []):
            if n not in pkgs:
                req.notes.append(f"{p} is needed by {n} - it may break.")
    if any(v.level == "guarded" for v in req.verdicts.values()):
        req.typed.append(TYPED_GUARDED)
        req.notes.append("Some packages are not rated by UAD-NG and their names look critical (camera, dialer, "
                         f"radios...). Type {TYPED_GUARDED} to include them.")
    if any(v.level == "expert" for v in req.verdicts.values()):
        req.typed.append(TYPED_EXPERT_TIER)
    return req


def targets(step: Step) -> Set[str]:
    """Packages a step (incl. its fallbacks) touches, from its declared touches and pkg."""
    out = {step.pkg} if step.pkg else set()
    for t in step.all_touches():
        m = _PKG_TOUCH.match(t)
        if m:
            out.add(m.group(1))
    return out


def check_plan(plan: Plan, ctx: SafetyContext, expert_mode: bool = False) -> None:
    """Executor-side re-check (R-4.3): a write that touches a locked package needs an expert plan, expert mode
    on, the package name among the typed strings, and a batch of one."""
    for s in plan.steps:
        if s.risk == "read":
            continue
        for p in sorted(targets(s)):
            v = verdict(p, ctx)
            if not v.locked:
                continue
            if not (plan.expert and expert_mode):
                raise GuardError(s.cmd, f"{p} is locked ({v.reason}) - expert mode only (R-4.3)")
            if p not in plan.typed:
                raise GuardError(s.cmd, f"{p} is locked - its full package name must be typed")


# ---------------------------------------------------------------------- expert mode (R-4.3)
@dataclass
class Selection:
    allowed: List[str] = field(default_factory=list)
    rejected: Dict[str, str] = field(default_factory=dict)   # pkg -> why it cannot be selected
    locked: List[str] = field(default_factory=list)          # allowed only because expert mode is on


def select(pkgs: Iterable[str], ctx: SafetyContext, expert_mode: bool = False) -> Selection:
    """What may enter a plan. Locked packages only with expert mode on - no other way in."""
    sel = Selection()
    for p in dict.fromkeys(pkgs):
        v = verdict(p, ctx)
        if v.locked and not expert_mode:
            sel.rejected[p] = f"locked ({v.reason}) - start droidforge with --expert to select it"
            continue
        sel.allowed.append(p)
        if v.locked:
            sel.locked.append(p)
    return sel


def make_expert(plan: Plan, locked: Iterable[str]) -> Plan:
    """Mark a plan that touches locked packages: batches of one, each full name typed, reboot check offered."""
    locked = list(locked)
    if locked:
        plan.expert = True
        plan.reboot_check = True
        for s in plan.steps:
            if targets(s) & set(locked):
                s.risk = "locked"
        for p in locked:
            if p not in plan.typed:
                plan.typed.append(p)
        plan.notes.insert(0, "EXPERT MODE: this plan touches locked packages. It runs one package per batch with "
                             "the health check in between; type each full package name to confirm. A reboot check "
                             "is offered afterwards.")
    return plan

