"""Per-app internet block without root (R-5.5): connectivity firewall chain 3 (OEM_DENY_3).

    cmd connectivity set-chain3-enabled true
    cmd connectivity set-package-networking-enabled false <p>      (undo: ... true <p>)

The rules are cleared when the phone reboots (platform behaviour). On connect droidforge detects the missing rules
and ASKS to re-apply them - never automatically (P14). Blocking a locked package (e.g. Play services) needs expert
mode like any other locked write.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, List, Mapping, Optional

from droidforge.engine import safety
from droidforge.engine.plan import Plan, Step
from droidforge.engine.snapshot import firewall_supported

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device
    from droidforge.engine.profile import Profile

UNSUPPORTED = "This build has no per-app firewall (cmd connectivity has no set-package-networking-enabled)."
REBOOT_NOTE = "Firewall rules are cleared when the phone reboots; droidforge asks to re-apply them when it connects."


def supported(device: "Device") -> bool:
    return firewall_supported(device)


def state(device: "Device", p: str) -> str:
    """blocked | allowed | unknown"""
    v = device.out(f"cmd connectivity get-package-networking-enabled {p}")
    return {"false": "blocked", "true": "allowed"}.get(v, "unknown")


def block_step(p: str, risk: str = "normal") -> Step:
    return Step(f"Block internet for {p}", f"cmd connectivity set-package-networking-enabled false {p}",
                [f"cmd connectivity set-package-networking-enabled true {p}"], "firewall", p, risk,
                verify=f"cmd connectivity get-package-networking-enabled {p}", expect=r"^false$", touches=[f"fw:{p}"])


def unblock_step(p: str, risk: str = "normal") -> Step:
    return Step(f"Allow internet for {p}", f"cmd connectivity set-package-networking-enabled true {p}",
                [f"cmd connectivity set-package-networking-enabled false {p}"], "firewall", p, risk,
                touches=[f"fw:{p}"])


def chain_step() -> Step:
    return Step("Turn on firewall chain 3", "cmd connectivity set-chain3-enabled true",
                ["cmd connectivity set-chain3-enabled false"], "firewall", touches=["fw:chain3"])


def chain_in_use(device: "Device", profile: Optional["Profile"]) -> bool:
    """Is some app already blocked right now? Then the chain is on and must not be switched off by an undo."""
    return any(state(device, p) == "blocked" for p in (profile.firewall if profile else []))


def block_plan(device: "Device", pkgs: Iterable[str], uad: Optional[Mapping[str, dict]] = None,
               expert_mode: bool = False, profile: Optional["Profile"] = None, title: str = "Block internet") -> Plan:
    plan = Plan(title=title)
    if not supported(device):
        plan.notes.append(UNSUPPORTED)
        return plan
    ctx = safety.SafetyContext.from_device(device, uad if uad is not None else {})
    installed = device.packages()
    sel = safety.select([p for p in pkgs if p in installed], ctx, expert_mode)
    for p, why in sel.rejected.items():
        plan.notes.append(f"Locked, skipped: {p} ({why})")
    for p in sel.allowed:
        if state(device, p) == "blocked":
            plan.notes.append(f"Already blocked: {p}")
            continue
        plan.steps.append(block_step(p, "locked" if p in sel.locked else "normal"))
    if plan.steps and not chain_in_use(device, profile):
        plan.steps.append(chain_step())
    if sel.locked:
        safety.make_expert(plan, sel.locked)
    plan.notes.append(REBOOT_NOTE)
    return plan


def unblock_plan(device: "Device", pkgs: Iterable[str], uad: Optional[Mapping[str, dict]] = None,
                 expert_mode: bool = False) -> Plan:
    plan = Plan(title="Allow internet again")
    if not supported(device):
        plan.notes.append(UNSUPPORTED)
        return plan
    ctx = safety.SafetyContext.from_device(device, uad if uad is not None else {})
    sel = safety.select(pkgs, ctx, expert_mode)
    for p in sel.allowed:
        if state(device, p) == "blocked":
            plan.steps.append(unblock_step(p, "locked" if p in sel.locked else "normal"))
    if sel.locked:
        safety.make_expert(plan, sel.locked)
    return plan


def missing_rules(device: "Device", profile: "Profile") -> List[str]:
    """Apps the profile blocks that are not blocked now (typically after a reboot). Read-only."""
    if not profile.firewall or not supported(device):
        return []
    installed = device.packages()
    return [p for p in profile.firewall if p in installed and state(device, p) == "allowed"]


def reapply_plan(device: "Device", profile: "Profile", uad: Optional[Mapping[str, dict]] = None,
                 expert_mode: bool = False) -> Plan:
    """The re-apply the user is ASKED about on connect (P14)."""
    return block_plan(device, missing_rules(device, profile), uad, expert_mode, profile,
                      title="Re-apply firewall rules (cleared by a reboot)")


def last_stage(device: "Device", p: str, neuter: List[Step], risk: str = "normal") -> Optional[Step]:
    """R-4.2 last escalation stage: block its internet, then neuter it (companion steps), chain on."""
    if not supported(device):
        return None
    st = block_step(p, risk)
    st.label = f"Firewall + neuter {p}"
    st.extra = list(neuter)
    if not any(s.cmd == chain_step().cmd for s in st.extra):
        st.extra.append(chain_step())
    return st
