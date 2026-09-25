"""Per-device desired state (R-2.4, R-2.5): profiles/<serial>.json.

- `apply_results()` updates the desired state from what the executor actually applied.
- `reapply(device)` builds ONE plan that brings the phone back to the desired state (after an OTA, or an import).
  It is only a plan: nothing runs without the P1 confirmation (P14).
- Export = the JSON without device identity; import returns a previewed plan and never edits the stored profile
  directly (the profile follows the executed results).
- Legacy `cnrom_state.json` import maps the package keys only (disabled / removed / suspended / neutered). Its
  language keys are ignored: they describe features that are forbidden now (INCIDENT-2026-09-25).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, List, Optional

from droidforge.adb import parse
from droidforge.engine import guard, steps
from droidforge.engine.plan import Plan, Step, StepResult

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device

LEGACY_PACKAGE_KEYS = ("disabled", "removed", "suspended", "neutered")
LEGACY_IGNORED_KEYS = ("english", "english_prev", "device_locale_prev", "system_locales_prev", "fallback")
DEVICE_KEYS = ("serial", "model", "fingerprint", "healthy_baseline", "healthy_ts")

# (pkg, step) -> reason it must not be re-applied automatically ("" = fine); set by engine.safety (P1.7)
Vetter = Callable[[str], str]


def _safe(serial: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", serial) or "device"


@dataclass
class Profile:
    serial: str = ""
    model: str = ""
    fingerprint: str = ""
    disabled: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    suspended: List[str] = field(default_factory=list)
    neutered: Dict[str, List[str]] = field(default_factory=dict)       # pkg -> revoked runtime permissions
    firewall: List[str] = field(default_factory=list)
    english: List[str] = field(default_factory=list)                   # apps with a per-app language set
    app_locales: Dict[str, str] = field(default_factory=dict)          # desired per-app locales
    app_locale_prev: Dict[str, str] = field(default_factory=dict)      # what they had before droidforge
    region: Dict[str, str] = field(default_factory=dict)
    dns_prev: Dict[str, str] = field(default_factory=dict)
    roles_prev: Dict[str, str] = field(default_factory=dict)
    ime_disabled: List[str] = field(default_factory=list)
    keepalive: List[str] = field(default_factory=list)
    powerperms: Dict[str, List[str]] = field(default_factory=dict)
    root: Dict[str, Any] = field(default_factory=lambda: {"modules": [], "props_prev": {}})
    healthy_baseline: Dict[str, Any] = field(default_factory=dict)
    healthy_ts: str = ""                                                # when that baseline was taken
    path: Optional[str] = field(default=None, repr=False, compare=False)

    # ------------------------------------------------------------------ storage
    @classmethod
    def for_device(cls, serial: str, directory: Optional[Path] = None) -> "Profile":
        if directory is None:
            from droidforge import config
            directory = config.paths().sub("profiles")
        p = Path(directory) / f"{_safe(serial)}.json"
        prof = cls.from_dict(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else cls(serial=serial)
        prof.serial = prof.serial or serial
        prof.path = str(p)
        return prof

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Profile":
        known = {f.name for f in fields(cls)} - {"path"}
        return cls(**{k: v for k, v in d.items() if k in known})

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("path", None)
        return d

    def save(self) -> None:
        if not self.path:
            raise ValueError("profile has no path (use Profile.for_device)")
        p = Path(self.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(p)

    def export(self) -> Dict[str, Any]:
        d = self.to_dict()
        for k in DEVICE_KEYS:
            d.pop(k, None)
        return d

    # ------------------------------------------------------------------ bookkeeping
    def note_device(self, device: "Device") -> None:
        self.model = device.label
        self.fingerprint = device.fingerprint

    def save_healthy(self, report: Any, mark_time: bool = True) -> None:
        """Remember the phone as healthy now (R-12.5 compares every start against this).

        `healthy_ts` marks a session-level confirmation (connect / doctor): droidforge's changes made after it
        are the ones "involved" if the phone breaks later, e.g. after a reboot. A plan that ends healthy refreshes
        the probe values (mark_time=False) but not that mark - its changes stay candidates until the next
        session-level check."""
        from datetime import datetime
        self.healthy_baseline = report.to_dict()
        if mark_time or not self.healthy_ts:
            self.healthy_ts = datetime.now().isoformat(timespec="milliseconds")

    def ota_changed(self, device: "Device") -> bool:
        return bool(self.fingerprint) and device.fingerprint != self.fingerprint

    def apply_results(self, results: Iterable[StepResult]) -> None:
        for r in results:
            if r.dry_run:
                continue
            for st in r.applied:
                self._apply(st)
        self._normalise()

    def _apply(self, st: Step) -> None:
        rule = guard.classify(st.cmd, st.host)
        words = st.cmd.split()
        p = st.pkg or (words[-1] if words else "")
        if rule == "disable":
            _add(self.disabled, p)
        elif rule == "enable":
            _drop(self.disabled, p)
        elif rule == "suspend":
            (_drop if words[1] == "unsuspend" else _add)(self.suspended, p)
        elif rule == "remove-user0":
            _add(self.removed, p)
            _drop(self.disabled, p)
        elif rule == "install-existing":
            _drop(self.removed, p)
        elif rule == "perm":
            target = self.powerperms if st.category == "powerperms" else self.neutered
            pkg, perm = words[2], words[3]
            revoking = words[1] == "revoke"
            if (st.category == "powerperms") != revoking:  # grant power perm / revoke (neuter)
                _add(target.setdefault(pkg, []), perm)
            else:
                _drop(target.get(pkg, []), perm)
        elif rule == "ime-toggle":
            (_add if words[1] == "disable" else _drop)(self.ime_disabled, words[2])
        elif rule == "locale-set":
            pkg = words[3]
            if "--locales" in words:
                _add(self.english, pkg)
                self.app_locales[pkg] = words[words.index("--locales") + 1]
                if st.undo and pkg not in self.app_locale_prev:
                    u = st.undo[0].split()
                    self.app_locale_prev[pkg] = u[u.index("--locales") + 1] if "--locales" in u else ""
            else:
                _drop(self.english, pkg)
                self.app_locales.pop(pkg, None)
                self.app_locale_prev.pop(pkg, None)
        elif rule == "fw-app":
            (_add if words[3] == "false" else _drop)(self.firewall, words[4])
        elif rule in ("dns-mode", "dns-host"):
            key = words[3]
            if key not in self.dns_prev and st.undo:
                u = st.undo[0].split()
                self.dns_prev[key] = u[4] if u[1] == "put" and len(u) > 4 else ""
        elif rule == "deviceidle":
            arg = words[3]
            (_add if arg.startswith("+") else _drop)(self.keepalive, arg[1:])

    def _normalise(self) -> None:
        for k in ("disabled", "removed", "suspended", "firewall", "english", "ime_disabled", "keepalive"):
            setattr(self, k, sorted(set(getattr(self, k))))
        for d in (self.neutered, self.powerperms):
            for k in [k for k, v in d.items() if not v]:
                d.pop(k)
            for k in d:
                d[k] = sorted(set(d[k]))

    def is_empty(self) -> bool:
        return not (self.disabled or self.removed or self.suspended or self.neutered or self.ime_disabled
                    or self.english or self.firewall or self.keepalive or self.powerperms)

    # ------------------------------------------------------------------ re-apply (one plan, P14)
    def reapply(self, device: "Device", vet: Optional[Vetter] = None, title: str = "Re-apply saved changes") -> Plan:
        """Plan the steps that bring the phone back to this desired state. Only reads the device."""
        plan = Plan(title=title)
        vet = vet or (lambda p: "")
        present, installed, disabled = device.packages("-u"), device.packages(), device.packages("-d")

        def allowed(p: str) -> bool:
            why = vet(p)
            if why:
                plan.notes.append(f"Skipped {p}: {why}")
            return not why

        for p in self.removed:
            if p in installed and allowed(p):
                plan.steps.append(steps.remove_user0(p))
        for p in self.disabled:
            if p in installed and p not in disabled and p not in self.removed and allowed(p):
                plan.steps.append(steps.disable(p))
        for p in self.suspended:
            if p in installed and allowed(p) and not parse.suspended(device.read(f"dumpsys package {p}").out):
                plan.steps.append(steps.suspend(p))
        for p, perms in self.neutered.items():
            if p not in installed or not allowed(p):
                continue
            dump = device.read(f"dumpsys package {p}").out
            granted = parse.runtime_perms(dump)
            ops = parse.appops(device.read(f"cmd appops get {p}").out)
            plan.steps += [steps.revoke(p, perm) for perm in perms if granted.get(perm)]
            plan.steps += [steps.appop(p, op, "ignore", ops.get(op)) for op in steps.APPOP_OPS_NEUTER
                           if ops.get(op) != "ignore"]
        if self.ime_disabled:
            enabled = parse.ime_ids(device.read("ime list -s").out)
            current = device.out("settings get secure default_input_method")
            for ime in self.ime_disabled:
                if ime in enabled:
                    if ime == current:
                        plan.notes.append(f"Skipped {ime}: it is the current keyboard - switch keyboards first")
                    else:
                        plan.steps.append(steps.ime_disable(ime))
        for p, tags in self.app_locales.items():
            if p in installed:
                cur = parse.app_locales(device.read(f"cmd locale get-app-locales {p} --user 0").out)
                if cur != tags:
                    plan.steps.append(steps.app_locale(p, tags, cur))
        gone = sorted({*self.disabled, *self.removed, *self.suspended} - present)
        if gone:
            plan.notes.append("Not on the phone any more (nothing to do): " + ", ".join(gone))
        return plan


def _add(lst: List[str], x: str) -> None:
    if x and x not in lst:
        lst.append(x)


def _drop(lst: List[str], x: str) -> None:
    while x in lst:
        lst.remove(x)


# ---------------------------------------------------------------------- import / export
def import_plan(data: Dict[str, Any], device: "Device", vet: Optional[Vetter] = None) -> Plan:
    """Previewed plan for an exported profile (P14). The stored profile is not touched."""
    incoming = Profile.from_dict({k: v for k, v in data.items() if k not in DEVICE_KEYS})
    return incoming.reapply(device, vet, title="Import profile")


def legacy_profile(path: Path) -> Profile:
    """cnrom_state.json -> Profile with the package keys only."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    prof = Profile()
    for k in LEGACY_PACKAGE_KEYS:
        v = raw.get(k)
        if k == "neutered" and isinstance(v, dict):
            prof.neutered = {p: list(perms or []) for p, perms in v.items()}
        elif isinstance(v, list):
            setattr(prof, k, sorted({x for x in v if isinstance(x, str)}))
    return prof


def legacy_import_plan(path: Path, device: "Device", vet: Optional[Vetter] = None) -> Plan:
    plan = legacy_profile(path).reapply(device, vet, title="Import legacy cnrom_state.json")
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    ignored = [k for k in LEGACY_IGNORED_KEYS if raw.get(k)]
    if ignored:
        plan.notes.append("Ignored legacy language keys (these features are forbidden now): " + ", ".join(ignored))
    return plan
