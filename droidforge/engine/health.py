"""Read-only health probes (R-11.7) and the baseline compare behind the health gate (P0, P11).

Each probe has a value and an `ok` verdict (True / False / None = unknown). `compare(baseline, now, declared)`
returns the regressions:
- the permission-monitoring switch is ON - **always**, even if it was already on at baseline (P0);
- a probe whose value changed and no step declared the matching key;
- a probe that was healthy and is not any more.
droidforge never repairs anything here; it reports and advises (R-2.8).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Tuple

from droidforge.adb import parse
from droidforge.data.device_keys import PERMISSION_MONITORING_PROP
from droidforge.engine.snapshot import CONFIG_CMD, HOME_CMD, covered

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device

SETTINGS_CMD = "cmd package resolve-activity --brief -a android.settings.SETTINGS"
PERMS_CMD = "cmd package resolve-activity --brief -a android.intent.action.MANAGE_APP_PERMISSIONS"
PM_SWITCH_CMD = f"getprop {PERMISSION_MONITORING_PROP}"
DEV_OPTIONS_CMD = "am start -a android.settings.APPLICATION_DEVELOPMENT_SETTINGS"
WATCHED_PROCS = ("com.android.systemui", "com.android.settings")

PERMISSION_MONITORING_ALERT = (
    "ColorOS developer switch 'Disable permission monitoring' is ON. It breaks the Settings and permission "
    "screens. Turn it off: Developer options > bottom of the list, then reboot.")
RESET_ALL_SETTINGS = ("Settings > search 'Reset' > Reset phone > Reset all settings. It keeps your apps, files and "
                      "accounts (it also puts developer options back to their defaults).")
ADVICE = (
    "1) If the 'Disable permission monitoring' developer switch is on, turn it off and reboot.",
    "2) Undo droidforge's recent plans (history).",
    f"3) Last resort: {RESET_ALL_SETTINGS}",
)

LABELS = {
    "settings_home": "Settings home screen", "permission_ui": "Permission screen",
    "font_scale": "Font size", "night": "Dark mode", "ime": "Keyboard", "launcher": "Home screen app",
    "alive:com.android.systemui": "System UI process", "alive:com.android.settings": "Settings process",
    "crashes": "System UI / Settings crashes", "permission_monitoring": "'Disable permission monitoring' switch",
    "cfg:fontScale": "Display font scale", "cfg:density": "Display density", "cfg:locales": "Language",
    "cfg:night": "Dark mode (configuration)", "cfg:mMaterialColor": "System accent colour",
    "cfg:mUxIconConfig": "Icon style", "cfg:mFontVariationSettings": "Font weight", "cfg:mFlipFont": "Font",
    "cfg:mIconPackName": "Icon pack", "cfg:mDarkModeBackgroundMaxL": "Dark-mode background",
    "cfg:mDarkModeDialogBgMaxL": "Dark-mode dialogs", "cfg:mDarkModeForegroundMinL": "Dark-mode text",
}

# probe -> the touch key a step would declare if it meant to change it
DECLARABLE = {"ime": "ime:default", "launcher": "launcher", "font_scale": "setting:system:font_scale",
              "night": "setting:secure:ui_night_mode"}


@dataclass
class Probe:
    name: str
    value: str
    ok: Optional[bool] = True
    detail: str = ""

    @property
    def label(self) -> str:
        return LABELS.get(self.name, self.name)


@dataclass
class HealthReport:
    probes: Dict[str, Probe] = field(default_factory=dict)

    def add(self, name: str, value: str, ok: Optional[bool] = True, detail: str = "") -> None:
        self.probes[name] = Probe(name, value, ok, detail)

    def get(self, name: str) -> Optional[Probe]:
        return self.probes.get(name)

    @property
    def failing(self) -> List[Probe]:
        return [p for p in self.probes.values() if p.ok is False]

    @property
    def permission_monitoring_on(self) -> bool:
        p = self.probes.get("permission_monitoring")
        return bool(p and p.ok is False)

    def to_dict(self) -> dict:
        return {k: asdict(v) for k, v in self.probes.items()}

    @classmethod
    def from_dict(cls, d: dict) -> "HealthReport":
        return cls({k: Probe(**v) for k, v in d.items()})


@dataclass(frozen=True)
class Regression:
    probe: str
    label: str
    before: str
    after: str
    message: str

    def __str__(self) -> str:
        return f"{self.label}: {self.before or '-'} -> {self.after or '-'}" + (f" ({self.message})"
                                                                                if self.message else "")


# ---------------------------------------------------------------------- run
def _crash_counts(text: str) -> Dict[str, int]:
    counts = {p: 0 for p in WATCHED_PROCS}
    for p in re.findall(r"Process: ([\w.]+)", text):
        if p in counts:
            counts[p] += 1
    return counts


def run(device: "Device") -> HealthReport:
    """All R-11.7 probes. Read-only."""
    h = HealthReport()
    coloros = device.rom_family == "coloros"

    home = parse.last_component(device.read(SETTINGS_CMD).out)
    ok = bool(home) and (not coloros or ".oplus." in home)
    h.add("settings_home", home, ok, "" if ok else "Settings does not open the ROM's own home screen")

    perms = parse.last_component(device.read(PERMS_CMD).out)
    ok = bool(perms) and (not coloros or "oplus" in perms)
    h.add("permission_ui", perms, ok, "" if ok else "the permission screen is not the ROM's own")

    cfg = parse.global_config(device.read(CONFIG_CMD).out)
    saved_colour = device.out("settings get system material_color_value")
    for k, v in cfg.items():
        ok, detail = True, ""
        if k == "mMaterialColor" and coloros and v in ("0", "") and saved_colour not in ("", "null", "0"):
            ok, detail = False, f"live colour {v or '-'} but saved material_color_value={saved_colour}"
        h.add(f"cfg:{k}", v, ok, detail)

    h.add("font_scale", device.out("settings get system font_scale"))
    h.add("night", device.out("cmd uimode night"))
    ime = device.out("settings get secure default_input_method")
    h.add("ime", ime, bool(ime) and ime != "null", "" if ime and ime != "null" else "no default keyboard")
    launcher = parse.last_component(device.read(HOME_CMD).out)
    h.add("launcher", launcher, bool(launcher), "" if launcher else "no home screen app resolves")

    for p in WATCHED_PROCS:
        alive = device.read(f"pidof {p}").ok
        # Settings is not always running; only SystemUI must be. Changes vs baseline are caught by compare().
        h.add(f"alive:{p}", "yes" if alive else "no", alive if p == "com.android.systemui" else True)
    counts = _crash_counts(device.out("logcat -b crash -d -t 200"))
    h.add("crashes", ",".join(f"{p}={n}" for p, n in counts.items()))

    sw = device.out(PM_SWITCH_CMD).strip()
    if sw == "false":  # permission monitoring disabled = the switch is on
        h.add("permission_monitoring", "on", False, PERMISSION_MONITORING_ALERT)
    elif sw == "true":
        h.add("permission_monitoring", "off", True)
    else:
        h.add("permission_monitoring", "unknown", None,
              f"{PERMISSION_MONITORING_PROP} is not set on this ROM; check Developer options by hand")
    device.log.trace("health: " + ", ".join(f"{p.name}={p.value}{'' if p.ok is not False else ' (FAIL)'}"
                                            for p in h.probes.values()), 3)
    return h


# ---------------------------------------------------------------------- compare
def _crash_increase(before: str, after: str) -> List[str]:
    def parse_c(s: str) -> Dict[str, int]:
        return {k: int(v) for k, v in (x.split("=") for x in s.split(",") if "=" in x)}
    b, a = parse_c(before), parse_c(after)
    return [p for p, n in a.items() if n > b.get(p, 0)]


def compare(baseline: HealthReport, now: HealthReport, declared: Iterable[str] = (),
            reference: Optional[HealthReport] = None) -> List[Regression]:
    """Regressions of `now` vs `baseline`. A probe that was failing and passes now, or whose value went back to the
    last known-healthy `reference` value, is a recovery - not a regression (legacy check_health)."""
    declared = list(declared)
    regs: List[Regression] = []
    for name, cur in now.probes.items():
        base = baseline.get(name) or Probe(name, "", None)
        ref = reference.get(name) if reference is not None else None
        if name != "permission_monitoring" and base.value != cur.value and (
                (base.ok is False and cur.ok is True) or (ref is not None and ref.value == cur.value)):
            continue  # recovered
        if name == "permission_monitoring":
            if cur.ok is False:
                regs.append(Regression(name, cur.label, base.value, cur.value, PERMISSION_MONITORING_ALERT))
            continue
        if name.startswith("alive:") and cur.ok is not False:
            continue  # Settings running or not is not a change anyone made; only "SystemUI is dead" counts
        if name == "crashes":
            new = _crash_increase(base.value, cur.value)
            if new:
                regs.append(Regression(name, cur.label, base.value, cur.value, f"new crash entries: {', '.join(new)}"))
            continue
        key = DECLARABLE.get(name) or (f"config:{name[4:]}" if name.startswith("cfg:") else "")
        if key and covered(key, declared):
            continue
        if base.value != cur.value and (base.ok is not None or cur.ok is False):
            regs.append(Regression(name, cur.label, base.value, cur.value, cur.detail))
        elif base.ok is True and cur.ok is False:
            regs.append(Regression(name, cur.label, base.value, cur.value, cur.detail))
    return regs


def problems(regs: Iterable[Regression], now: HealthReport) -> List[Regression]:
    """Between sessions (doctor, the check at connect) only these count (owner, 2026-09-26): a probe that now FAILS,
    new crashes, or the permission-monitoring switch. A value that changed but still passes (font size, dark mode,
    accent colour, keyboard) is the user's own business - information, not an error."""
    out = []
    for r in regs:
        p = now.get(r.probe)
        if r.probe in ("crashes", "permission_monitoring") or (p is not None and p.ok is False):
            out.append(r)
    return out


# snapshot key <-> probe (for recoveries seen by the blast-radius diff)
PROBE_KEYS = {"font_scale": "setting:system:font_scale", "night": "setting:secure:ui_night_mode",
              "ime": "setting:secure:default_input_method", "launcher": "launcher",
              "permission_monitoring": f"prop:{PERMISSION_MONITORING_PROP}"}


def recovered_keys(baseline: HealthReport, now: HealthReport, reference: Optional[HealthReport] = None) -> List[str]:
    """Snapshot keys whose probe got BETTER (failing -> passing, or back to the last known-healthy value).
    A change towards healthy must never stop a plan."""
    out = []
    for name, cur in now.probes.items():
        base = baseline.get(name)
        if base is None or base.value == cur.value:
            continue
        ref = reference.get(name) if reference is not None else None
        if (base.ok is False and cur.ok is True) or (ref is not None and ref.value == cur.value and cur.ok):
            key = PROBE_KEYS.get(name) or (f"config:{name[4:]}" if name.startswith("cfg:") else "")
            if key:
                out.append(key)
    return out


def advice(regressions: Iterable[Regression]) -> Tuple[str, ...]:
    """Recovery advice in R-2.8 order (the switch first when it is on)."""
    regs = list(regressions)
    if any(r.probe == "permission_monitoring" for r in regs):
        return ADVICE
    return ADVICE[1:]
