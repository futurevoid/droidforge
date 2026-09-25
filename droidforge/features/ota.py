"""OTA detection (R-2.5): the profile stores `ro.build.fingerprint`. When it changes, droidforge shows what the
update re-enabled / reinstalled / reset compared with the profile and ASKS to re-apply (P14) - never automatic.
Updates themselves stay allowed (the OTA path is never debloated)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Mapping, Optional

from droidforge.engine import safety
from droidforge.engine.plan import Plan

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device
    from droidforge.engine.profile import Profile


@dataclass
class OtaReport:
    changed: bool
    old: str = ""
    new: str = ""
    reverted: List[str] = field(default_factory=list)   # plain lines: what the update undid
    plan: Optional[Plan] = None                          # the re-apply plan the user is asked about


def check(device: "Device", profile: "Profile", uad: Optional[Mapping[str, dict]] = None,
          expert_mode: bool = False) -> OtaReport:
    """Read-only. `changed` is False on the first connect (nothing stored yet)."""
    new = device.fingerprint
    if not profile.fingerprint or profile.fingerprint == new:
        return OtaReport(False, profile.fingerprint, new)
    ctx = safety.SafetyContext.from_device(device, uad if uad is not None else {})

    def vet(p: str) -> str:
        v = safety.verdict(p, ctx)
        return f"locked ({v.reason}) - re-apply it in expert mode" if v.locked and not expert_mode else ""
    plan = profile.reapply(device, vet, title="Re-apply your changes after the system update")
    rep = OtaReport(True, profile.fingerprint, new, plan=plan)
    for s in plan.steps:
        rep.reverted.append(f"{s.pkg or ''}: {s.label}".strip(": "))
    return rep


def acknowledge(profile: "Profile", device: "Device") -> None:
    """The update was dealt with (re-applied, or the user keeps it as it is): remember the new build."""
    profile.set_build(device)
    if profile.path:
        profile.save()
