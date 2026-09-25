"""Reboot check (R-11.9): after risky plans droidforge offers "reboot now and re-check". The reboot is a normal
confirmed plan; after boot (`sys.boot_completed=1`) the health probes and the snapshot are compared with the
baseline taken before the risky plan, and any regression stops and offers the undo of that plan."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Callable

from droidforge.engine import executor
from droidforge.engine.executor import ConfirmHook, RunReport
from droidforge.engine.plan import Plan, Step

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device

# a reboot restarts processes and bumps the ROM's own boot counter; nothing else may change
REBOOT_TOUCHES = ["reboot", "setting:global:boot_count"]


def reboot_plan(serial: str, title: str = "Reboot and re-check") -> Plan:
    step = Step(label="Reboot the phone and wait until it has finished booting", cmd=f"adb -s {serial} reboot",
                undo=[], category="reboot", risk="risky", host=True, touches=list(REBOOT_TOUCHES))
    return Plan(title=title, steps=[step],
                notes=["After boot, droidforge compares the phone with how it was before the last plan."])


def reboot_check(device: "Device", before: RunReport, confirm: ConfirmHook,
                 sleep: Callable[[float], None] = time.sleep, boot_timeout: float = 240, **kw: object) -> RunReport:
    """Reboot, wait for boot, then diff + health against `before`'s pre-plan baseline."""
    if before.baseline_health is None or before.baseline_snapshot is None:
        raise ValueError("the reboot check needs the report of an executed plan")
    declared = [t for r in before.results for st in r.applied for t in st.touches]
    return executor.run(reboot_plan(device.serial or "device", f"Reboot check after: {before.plan.title}"),
                        device, confirm, baseline=(before.baseline_health, before.baseline_snapshot),
                        declared_before=declared, prior_results=before.results, sleep=sleep,
                        boot_timeout=boot_timeout, **kw)  # type: ignore[arg-type]
