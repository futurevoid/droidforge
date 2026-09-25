"""Ads and promos (R-5.4), all four: lock-screen magazine, system push promos, launcher suggestions, -1 screen feed.

Notifications off = `pm revoke <p> android.permission.POST_NOTIFICATIONS` + app-op POST_NOTIFICATION ignore (store,
theme store, game center, browser). Theme stores are never disabled (theme apply depends on them - P9b), and
com.coloros.pictorial is never touched (UAD Unsafe - breaks lock-screen settings; it is locked).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, List, Mapping, Optional

from droidforge.adb import parse
from droidforge.data.packages import ADS_CATEGORIES, ADS_DISABLE, ADS_NOTIFICATIONS_OFF
from droidforge.engine import safety, steps
from droidforge.engine.plan import Plan, Step
from droidforge.features import debloat

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device

NOTIF = "android.permission.POST_NOTIFICATIONS"


def notifications_off_steps(device: "Device", p: str, category: str = "ads", risk: str = "normal") -> List[Step]:
    """Revoke the notification permission (if granted) and set the app-op to ignore; undo from the state now."""
    out: List[Step] = []
    if parse.runtime_perms(device.read(f"dumpsys package {p}").out).get(NOTIF):
        out.append(steps.revoke(p, NOTIF, category, risk))
    prev = parse.appops(device.read(f"cmd appops get {p}").out).get("POST_NOTIFICATION")
    if prev != "ignore":
        out.append(steps.appop(p, "POST_NOTIFICATION", "ignore", prev, category, risk))
    for s in out:
        s.label = f"{p}: notifications off ({s.label.split(': ', 1)[1]})"
    return out


def ads_plan(device: "Device", categories: Iterable[str], uad: Optional[Mapping[str, dict]] = None,
             expert_mode: bool = False) -> Plan:
    cats = [c for c in categories if c in ADS_CATEGORIES]
    installed = device.packages()
    disable = [p for c in cats for p in ADS_DISABLE.get(c, ()) if p in installed]
    plan = debloat.disable_plan(device, disable, uad, expert_mode)
    plan.title = "Remove ads and promos: " + ", ".join(ADS_CATEGORIES[c] for c in cats)
    if "push" in cats:
        ctx = safety.SafetyContext.from_device(device, uad if uad is not None else {})
        sel = safety.select([p for p in ADS_NOTIFICATIONS_OFF if p in installed], ctx, expert_mode)
        for p, why in sel.rejected.items():
            plan.notes.append(f"Locked, skipped: {p} ({why})")
        for p in sel.allowed:
            plan.steps += notifications_off_steps(device, p, risk="locked" if p in sel.locked else "normal")
        if sel.locked:
            safety.make_expert(plan, sel.locked)
    if plan.steps and "Nothing to do." in plan.notes:
        plan.notes.remove("Nothing to do.")
    if not plan.steps:
        plan.notes.append("Nothing to do: none of these packages is installed / enabled.")
    return plan
