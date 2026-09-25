"""Plan-building helpers for tests (features have their own builders)."""

from __future__ import annotations

from typing import List, Optional

from droidforge.adb.sim import SimBackend
from droidforge.engine import recovery
from droidforge.engine.plan import Confirmation, Plan, Step

TELEMETRY = ["com.oplus.statistics.rom", "com.nearme.deamon", "com.oplus.crashbox", "com.oplus.logkit",
             "com.coloros.logkit.plugin.upload", "com.oplus.onetrace", "com.oplus.locationproxy", "com.heytap.openid",
             "com.oplus.powermonitor", "com.oplus.ocloud", "com.coloros.feedback", "com.coloros.remoteguardservice"]


def disable_step(p: str) -> Step:
    return Step(f"Disable {p}", f"pm disable-user --user 0 {p}", undo=[f"pm enable --user 0 {p}"],
                category="debloat", pkg=p, touches=[f"pkg:{p}:enabled"])


def suspend_step(p: str) -> Step:
    return Step(f"Suspend {p}", f"pm suspend --user 0 {p}", undo=[f"pm unsuspend --user 0 {p}"],
                category="debloat", pkg=p, touches=[f"pkg:{p}:suspended"])


def force_step(p: str) -> Step:
    s = disable_step(p)
    s.fallbacks = [suspend_step(p)]
    return s


def disable_plan(pkgs: List[str], title: str = "Disable test packages") -> Plan:
    return Plan(title=title, steps=[disable_step(p) for p in pkgs])


def yes(plan: Plan) -> bool:
    return True


def no(plan: Plan) -> bool:
    return False


def typed(*strings: str):
    def hook(plan: Plan) -> Confirmation:
        return Confirmation(True, list(strings))
    return hook


def replay_recovery(path: str, backend: SimBackend, serial: Optional[str] = None) -> None:
    from pathlib import Path
    for ser, cmd in recovery.parse(Path(path)):
        backend.run(["-s", serial or ser, "shell", cmd])
