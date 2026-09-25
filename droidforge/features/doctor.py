"""`doctor` (R-2.8): read-only report - device, ROM, root, Shizuku, capabilities, the R-11.7 health probes, the
comparison with the last healthy baseline, droidforge's history on this device, and the recovery advice in order:
(1) the permission-monitoring switch, (2) undo droidforge's recent plans, (3) Settings > Reset all settings.
It never repairs anything itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Tuple

from droidforge.engine import health, snapshot
from droidforge.engine.health import HealthReport, Probe, Regression

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device
    from droidforge.engine.history import History
    from droidforge.engine.profile import Profile

SHIZUKU = "moe.shizuku.privileged.api"


@dataclass
class DoctorReport:
    rows: List[Tuple[str, str]] = field(default_factory=list)
    health: Optional[HealthReport] = None
    failing: List[Probe] = field(default_factory=list)
    regressions: List[Regression] = field(default_factory=list)   # vs the last healthy baseline
    advice: Tuple[str, ...] = ()
    baseline_saved: Optional[str] = None

    @property
    def healthy(self) -> bool:
        return not self.failing and not self.regressions

    def lines(self) -> List[str]:
        out = ["droidforge doctor", ""]
        w = max((len(k) for k, _ in self.rows), default=10)
        out += [f"  {k:<{w}}  {v}" for k, v in self.rows]
        out += ["", "Health probes (read-only):"]
        for p in (self.health.probes.values() if self.health else []):
            mark = {True: "ok  ", False: "FAIL", None: "??  "}[p.ok]
            out.append(f"  [{mark}] {p.label}: {p.value or '-'}" + (f" - {p.detail}" if p.detail else ""))
        if self.regressions:
            out += ["", "Changed since the last healthy check:"]
            out += [f"  ! {r}" for r in self.regressions]
        if self.healthy:
            out += ["", "Everything droidforge checks looks healthy."]
        else:
            out += ["", "Something is wrong. What to do, in this order:"]
            out += [f"  {a}" for a in self.advice]
        if self.baseline_saved:
            out += ["", f"Healthy baseline saved ({self.baseline_saved})."]
        return out


def run(device: "Device", profile: Optional["Profile"] = None, history: Optional["History"] = None,
        save_baseline: bool = True, backup_dir: Optional[Path] = None, mark_time: bool = True) -> DoctorReport:
    """`mark_time`: an explicit doctor run is a session-level healthy confirmation (see Profile.save_healthy);
    the TUI's automatic dashboard refresh after each plan only refreshes the values."""
    rep = DoctorReport()
    sdk = device.sdk
    rows = rep.rows
    rows.append(("Device", f"{device.label} ({device.serial})"))
    rows.append(("Android / SDK", f"{device.getprop('ro.build.version.release')} / {sdk}"))
    rows.append(("Build", device.getprop("ro.build.display.id") or "-"))
    rom = device.rom_family
    rows.append(("ROM family", f"ColorOS family {device.getprop('ro.build.version.oplusrom')}" if rom == "coloros"
                 else "generic Android (AOSP commands only)"))
    root = device.read("su -c id")
    rows.append(("Root", "yes (flavor detection: Phase 7)" if root.ok and "uid=0" in root.out else "no"))
    shizuku = device.read(f"pm path {SHIZUKU}")
    rows.append(("Shizuku", "installed" if shizuku.ok and shizuku.out.strip() else "not installed"))
    rows.append(("Device language", device.out("getprop persist.sys.locale")
                 or device.out("settings get system system_locales") or "-"))
    rows.append(("Per-app language", "supported (cmd locale)" if sdk >= 33 else "needs Android 13+"))
    fw = "set-package-networking-enabled" in device.read("cmd connectivity help").out
    rows.append(("Per-app firewall", "supported (chain 3)" if fw else "not available on this build"))
    rows.append(("Keyboard", device.out("settings get secure default_input_method") or "-"))
    if history is not None:
        es = history.entries()
        live = [e for e in es if e.ok and not e.dry_run and not e.undone and e.undo]
        last = es[-1] if es else None
        rows.append(("droidforge history", f"{len(es)} step(s), {len(live)} undoable"
                     + (f"; last: {last.plan_title} ({last.ts})" if last else "")))

    h = rep.health = health.run(device)
    rep.failing = h.failing
    if profile is not None and profile.healthy_baseline:
        base = HealthReport.from_dict(profile.healthy_baseline)
        rep.regressions = [r for r in health.compare(base, h) if r.probe != "permission_monitoring"]
    alerts: List[Regression] = [Regression(p.name, p.label, "", p.value, p.detail) for p in rep.failing]
    rep.advice = health.advice(alerts + rep.regressions)

    if save_baseline and rep.healthy and profile is not None:
        profile.save_healthy(h, mark_time=mark_time)
        profile.note_device(device)
        if profile.path:
            profile.save()
        if backup_dir is not None:
            snap = snapshot.take(device, full=True)
            path = snap.save(backup_dir / f"{snap.ts.replace(':', '')}-doctor.json")
            rep.baseline_saved = str(path)
        else:
            rep.baseline_saved = "profile"
    return rep
