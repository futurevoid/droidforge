"""Debloat (R-4.1 - R-4.5), ported from the legacy tool's preflight / do_packages / force_disable / neuter.

Every action returns a Plan (nothing runs here). Preflight (legacy `preflight`) becomes plan content:
- locked packages are rejected unless expert mode is on (then: batch of one, typed name, reboot check);
- UAD-NG "Expert" packages need a typed YES, unrated-but-critical-looking ones a typed I UNDERSTAND;
- neededBy warnings, keep-list and OTA-path warnings, "no rating" notes;
- no default preset: the user always picks (R-4.1).
Force-disable (R-4.2) is one step with its escalation chain listed up front: disable -> suspend -> remove for
user 0; the executor health- and blast-radius-checks between stages. (Firewall + neuter join the chain in P4.4.)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, Iterable, List, Mapping, Optional, Sequence

from droidforge.adb import labels, parse
from droidforge.data import uad as uadmod
from droidforge.engine import safety, steps
from droidforge.engine.plan import Plan, Step, StepResult
from droidforge.engine.safety import SafetyContext, Verdict

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device
    from droidforge.engine.profile import Profile

# Legacy CHINA_PATTERNS: what "scan" shows by default.
CHINA_PATTERNS = ("heytap", "nearme", "coloros", "oplus", "realme", "oppo", "finshell", "baidu", "sogou", "iflytek",
                  "tencent", "alipay", "qihoo", "kuaishou", "ximalaya")
TIER_RANK = {t: i for i, t in enumerate(uadmod.TIERS)}
PROTECTED_BY_ROM = "{p} is protected by the ROM itself. Neuter can still silence it."

Uad = Mapping[str, dict]


# ---------------------------------------------------------------------- listing (read-only)
@dataclass
class Row:
    pkg: str
    status: str            # enabled | disabled | suspended | removed
    tier: str
    description: str
    verdict: Verdict
    name: str = ""          # app name shown in Settings (adb/labels.py)


def statuses(device: "Device", suspended: Iterable[str] = ()) -> Dict[str, str]:
    present, installed, disabled = device.packages("-u"), device.packages(), device.packages("-d")
    sus = set(suspended)
    out = {}
    for p in present:
        if p not in installed:
            out[p] = "removed"
        elif p in disabled:
            out[p] = "disabled"
        elif p in sus:
            out[p] = "suspended"
        else:
            out[p] = "enabled"
    return out


def _rows(device: "Device", pkgs: Iterable[str], uad: Uad, suspended: Iterable[str]) -> List[Row]:
    st = statuses(device, suspended)
    ctx = SafetyContext.from_device(device, uad)
    pkgs = list(pkgs)
    names = labels.lookup(device, pkgs)
    return [Row(p, st.get(p, "absent"), uadmod.tier(dict(uad), p), uadmod.description(dict(uad), p, 70),
                safety.verdict(p, ctx), names.get(p, "")) for p in pkgs]


def listing(device: "Device", uad: Uad, tiers: Sequence[str] = ("Recommended",), lst: Optional[str] = None,
            keyword: str = "", show_infra: bool = False, suspended: Iterable[str] = ()) -> List[Row]:
    """UAD-NG list filtered by tier / list / keyword, as on this phone (legacy menu 2)."""
    kw = keyword.lower()
    pkgs = [p for p in safety.package_list(device, show_infra)
            if p in uad and uad[p].get("removal") in tiers and (lst is None or uad[p].get("list") == lst)
            and (not kw or kw in p.lower())]
    pkgs.sort(key=lambda p: (TIER_RANK.get(uad[p].get("removal", ""), 9), p))
    return _rows(device, pkgs, uad, suspended)


def scan(device: "Device", uad: Uad, keyword: str = "", show_infra: bool = False,
         suspended: Iterable[str] = ()) -> List[Row]:
    """Legacy menu 3: China-ROM packages by default, 'all', or a keyword."""
    universe = safety.package_list(device, show_infra)
    kw = keyword.lower()
    if kw == "all":
        pkgs = universe
    elif kw:
        pkgs = [p for p in universe if kw in p.lower()]
    else:
        pkgs = [p for p in universe if any(x in p for x in CHINA_PATTERNS)]
    return _rows(device, pkgs, uad, suspended)


def info(device: "Device", pkgs: Iterable[str], uad: Uad) -> List[str]:
    """Legacy show_pkg_info (read-only text)."""
    st = statuses(device)
    lines: List[str] = []
    for p in pkgs:
        e = uadmod.entry(dict(uad), p)
        lines.append(f"{p}  [{st.get(p, 'absent')}]")
        if not e:
            lines.append("   Not in the UAD-NG list.")
            continue
        lines.append(f"   Rating : {e.get('removal', '-')}    List: {e.get('list', '-')}")
        lines += [f"   {ln}" for ln in (e.get("description") or "-").splitlines()]
        if e.get("dependencies"):
            lines.append(f"   Depends on : {', '.join(e['dependencies'])}")
        if e.get("neededBy"):
            lines.append(f"   Needed by  : {', '.join(e['neededBy'])}")
    return lines


# ---------------------------------------------------------------------- preflight
@dataclass
class Prep:
    plan: Plan
    allowed: List[str] = field(default_factory=list)
    locked: List[str] = field(default_factory=list)
    imes: Dict[str, List[str]] = field(default_factory=dict)   # pkg -> its enabled IME ids


def _uad(uad: Optional[Uad]) -> Uad:
    return uadmod.load_cached() if uad is None else uad


def _prepare(device: "Device", pkgs: Iterable[str], title: str, uad: Uad, expert_mode: bool,
             want: str = "installed") -> Prep:
    ctx = SafetyContext.from_device(device, uad)
    sel = safety.select(pkgs, ctx, expert_mode)
    plan = Plan(title=title)
    for p, why in sel.rejected.items():
        plan.notes.append(f"Locked, skipped: {p} ({why})")
    present, installed = device.packages("-u"), device.packages()
    allowed = []
    for p in sel.allowed:
        if p not in present:
            plan.notes.append(f"Not on this phone: {p}")
        elif want == "installed" and p not in installed:
            plan.notes.append(f"Already removed for user 0: {p} (use restore)")
        elif want == "removed" and p in installed:
            plan.notes.append(f"Not removed: {p}")
        else:
            allowed.append(p)
    needed = {p: [n for n in uadmod.needed_by(dict(uad), p) if n in installed] for p in allowed}
    req = safety.requirements(allowed, ctx, needed)
    plan.typed = list(req.typed)
    plan.notes += req.notes
    system = device.packages("-s")
    plan.reboot_check = any(p in system for p in allowed)  # R-11.9: debloat of any system app
    imes: Dict[str, List[str]] = {}
    for i in parse.ime_ids(device.read("ime list -s").out):
        imes.setdefault(i.split("/")[0], []).append(i)
    return Prep(plan, allowed, [p for p in sel.locked if p in allowed], imes)


def _finish(prep: Prep) -> Plan:
    if prep.locked:
        safety.make_expert(prep.plan, prep.locked)
    if not prep.plan.steps:
        prep.plan.notes.append("Nothing to do.")
    return prep.plan


def _with_ime_touches(step: Step, prep: Prep) -> Step:
    """A package that provides enabled keyboards takes them away when it goes: declare that (P10)."""
    ids = prep.imes.get(step.pkg or "", [])
    if ids:
        step.touches += [f"ime:enabled:{i}" for i in ids] + ["setting:secure:enabled_input_methods"]
        for fb in step.fallbacks:
            _with_ime_touches(fb, prep)
    return step


def _risk(p: str, prep: Prep) -> str:
    return "locked" if p in prep.locked else "normal"


# ---------------------------------------------------------------------- actions -> plans
def disable_plan(device: "Device", pkgs: Iterable[str], uad: Optional[Uad] = None, expert_mode: bool = False
                 ) -> Plan:
    u = _uad(uad)
    prep = _prepare(device, pkgs, "Disable packages", u, expert_mode)
    disabled = device.packages("-d")
    for p in prep.allowed:
        if p in disabled:
            prep.plan.notes.append(f"Already disabled: {p}")
            continue
        prep.plan.steps.append(_with_ime_touches(steps.disable(p, risk=_risk(p, prep)), prep))
    return _finish(prep)


def remove_plan(device: "Device", pkgs: Iterable[str], uad: Optional[Uad] = None, expert_mode: bool = False) -> Plan:
    u = _uad(uad)
    prep = _prepare(device, pkgs, "Remove packages for user 0", u, expert_mode)
    for p in prep.allowed:
        prep.plan.steps.append(_with_ime_touches(steps.remove_user0(p, risk=_risk(p, prep)), prep))
    if prep.plan.steps:
        prep.plan.notes.append("Removed for user 0 only - 'restore' brings them back (cmd package install-existing).")
    return _finish(prep)


def force_step(p: str, risk: str = "normal", last: Optional[Step] = None) -> Step:
    """R-4.2 escalation chain for one package: disable -> suspend -> remove for user 0 [-> firewall + neuter]."""
    s = steps.disable(p, risk=risk)
    s.label = f"Force-disable {p}"
    s.fallbacks = [steps.suspend(p, risk=risk), steps.remove_user0(p, risk=risk)]
    if last is not None:
        s.fallbacks.append(last)
    return s


def force_plan(device: "Device", pkgs: Iterable[str], uad: Optional[Uad] = None, expert_mode: bool = False) -> Plan:
    u = _uad(uad)
    prep = _prepare(device, pkgs, "Force-disable packages", u, expert_mode)
    disabled = device.packages("-d")
    from droidforge.features import firewall
    fw = firewall.supported(device)
    for p in prep.allowed:
        if p in disabled:
            prep.plan.notes.append(f"Already disabled: {p}")
            continue
        r = _risk(p, prep)
        last = firewall.last_stage(device, p, neuter_steps(device, p, r), r) if fw else None
        prep.plan.steps.append(_with_ime_touches(force_step(p, r, last), prep))
    if prep.plan.steps:
        prep.plan.notes.append("Escalation, stage by stage with the health check in between: disable -> suspend "
                               "(frozen: cannot open or run) -> remove for user 0"
                               + (" -> block its internet + neuter it" if fw else "")
                               + ". Undo reverses whichever stage took effect.")
        if fw:
            prep.plan.notes.append(firewall.REBOOT_NOTE)
    return _finish(prep)


def neuter_steps(device: "Device", p: str, risk: str = "normal") -> List[Step]:
    """Keep the app installed but silence it: revoke granted runtime permissions, block background / notifications
    / overlays, stop it (legacy `neuter`). Undo values come from the state read now."""
    granted = [perm for perm, g in parse.runtime_perms(device.read(f"dumpsys package {p}").out).items() if g]
    ops = parse.appops(device.read(f"cmd appops get {p}").out)
    out = [steps.revoke(p, perm, "neuter", risk) for perm in granted]
    out += [steps.appop(p, op, "ignore", ops.get(op), "neuter", risk) for op in steps.APPOP_OPS_NEUTER
            if ops.get(op) != "ignore"]
    out.append(steps.force_stop(p, "neuter", risk))
    return out


def neuter_plan(device: "Device", pkgs: Iterable[str], uad: Optional[Uad] = None, expert_mode: bool = False) -> Plan:
    u = _uad(uad)
    prep = _prepare(device, pkgs, "Neuter packages (keep installed, silence)", u, expert_mode)
    for p in prep.allowed:
        prep.plan.steps += neuter_steps(device, p, _risk(p, prep))
    return _finish(prep)


def enable_plan(device: "Device", pkgs: Iterable[str], profile: Optional["Profile"] = None,
                uad: Optional[Uad] = None, expert_mode: bool = False) -> Plan:
    """Legacy 'enable / unsuspend / un-neuter': undo whatever state the package is in now."""
    u = _uad(uad)
    prep = _prepare(device, pkgs, "Enable / unsuspend / un-neuter", u, expert_mode)
    disabled = device.packages("-d")
    neutered = dict(profile.neutered) if profile else {}
    for p in prep.allowed:
        r = _risk(p, prep)
        dump = device.read(f"dumpsys package {p}").out
        if parse.suspended(dump):
            prep.plan.steps.append(steps.unsuspend(p, risk=r))
        if p in neutered:
            perms = parse.runtime_perms(dump)
            prep.plan.steps += [steps.grant(p, perm, "neuter", r) for perm in neutered[p] if perms.get(perm) is False]
            ops = parse.appops(device.read(f"cmd appops get {p}").out)
            prep.plan.steps += [steps.appop(p, op, "default", ops.get(op), "neuter", r)
                                for op in steps.APPOP_OPS_NEUTER if ops.get(op) == "ignore"]
        if p in disabled:
            prep.plan.steps.append(steps.enable(p, risk=r))
    return _finish(prep)


def restore_plan(device: "Device", pkgs: Iterable[str], uad: Optional[Uad] = None, expert_mode: bool = False
                 ) -> Plan:
    """Bring back packages removed for user 0 (and enable them, as the legacy tool did)."""
    u = _uad(uad)
    prep = _prepare(device, pkgs, "Restore removed packages", u, expert_mode, want="removed")
    disabled = device.packages("-d")
    for p in prep.allowed:
        prep.plan.steps.append(steps.restore(p, risk=_risk(p, prep)))
        if p in disabled:
            prep.plan.steps.append(steps.enable(p, risk=_risk(p, prep)))
    return _finish(prep)


def bulk(rows: Iterable[Row], ctx: SafetyContext, explicit: Iterable[str] = ()) -> List[str]:
    """'Select all' over a listing: never locked packages, keep-list only when explicitly added (R-4.4)."""
    return safety.bulk_selectable([r.pkg for r in rows], ctx, explicit)


def protected_by_rom(results: Iterable["StepResult"]) -> List[str]:
    """Advice after a run: packages the ROM refused at every escalation stage (legacy force_disable)."""
    return [PROTECTED_BY_ROM.format(p=r.requested.pkg) for r in results
            if not r.ok and not r.dry_run and r.requested.fallbacks and r.requested.pkg]
