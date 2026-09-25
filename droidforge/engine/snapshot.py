"""Before/after snapshots and the blast-radius diff (P10, R-11.3, R-11.8).

Every value is flattened to a key in the same vocabulary as `Step.touches` / the guard's derived touches:

    setting:<ns>:<key>          settings list system|secure|global
    pkg:<p>:installed           pm list packages -u / (installed for user 0) -> true | false | absent
    pkg:<p>:enabled             pm list packages -d
    pkg:<p>:suspended           dumpsys package <p>            (scope packages)
    perm:<p>:<permission>       dumpsys package <p> runtime permissions (scope packages)
    appop:<p>:<OP>              cmd appops get <p>             (scope packages)
    applocale:<p>               cmd locale get-app-locales     (user apps + scope; every package when full=True)
    ime:enabled:<id>            ime list -s
    role:<role>                 cmd role get-role-holders (browser / SMS / dialer)
    launcher                    resolve-activity HOME
    config:<field>              dumpsys activity | grep -m1 mGlobalConfig

`diff(before, after)` lists every key whose value differs; the executor flags the ones no step declared.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from fnmatch import fnmatchcase
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional

from droidforge.adb import parse
from droidforge.adb.batch import batch_read

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device

NAMESPACES = ("system", "secure", "global")
HOME_CMD = "cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME"
CONFIG_CMD = "dumpsys activity | grep -m1 mGlobalConfig"
ROLES = ("android.app.role.BROWSER", "android.app.role.SMS", "android.app.role.DIALER")


@dataclass
class Snapshot:
    serial: str = ""
    fingerprint: str = ""
    ts: str = ""
    settings: Dict[str, Dict[str, str]] = field(default_factory=dict)
    packages: Dict[str, Dict[str, bool]] = field(default_factory=dict)   # {pkg: {installed, enabled}}
    details: Dict[str, dict] = field(default_factory=dict)              # {pkg: {suspended, perms, appops}}
    app_locales: Dict[str, str] = field(default_factory=dict)
    imes: List[str] = field(default_factory=list)
    roles: Dict[str, str] = field(default_factory=dict)
    launcher: str = ""
    config: Dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------ flatten
    def flat(self) -> Dict[str, str]:
        f: Dict[str, str] = {}
        for ns, table in self.settings.items():
            for k, v in table.items():
                f[f"setting:{ns}:{k}"] = v
        for p, st in self.packages.items():
            f[f"pkg:{p}:installed"] = "true" if st.get("installed") else "false"
            f[f"pkg:{p}:enabled"] = "true" if st.get("enabled") else "false"
        for p, d in self.details.items():
            f[f"pkg:{p}:suspended"] = "true" if d.get("suspended") else "false"
            for perm, granted in d.get("perms", {}).items():
                f[f"perm:{p}:{perm}"] = "granted" if granted else "denied"
            for op, mode in d.get("appops", {}).items():
                f[f"appop:{p}:{op}"] = mode
            if "fw" in d:
                f[f"fw:{p}"] = d["fw"]
            if "deviceidle" in d:
                f[f"deviceidle:{p}"] = d["deviceidle"]
                f[f"standby:{p}"] = d.get("standby", "")
        for p, loc in self.app_locales.items():
            f[f"applocale:{p}"] = loc
        for i in self.imes:
            f[f"ime:enabled:{i}"] = "true"
        for role, holders in self.roles.items():
            f[f"role:{role}"] = holders
        f["launcher"] = self.launcher
        for k, v in self.config.items():
            f[f"config:{k}"] = v
        return f

    # ------------------------------------------------------------------ persistence
    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=1, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "Snapshot":
        return cls(**json.loads(text))

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> "Snapshot":
        return cls.from_json(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Change:
    key: str
    before: Optional[str]
    after: Optional[str]

    def __str__(self) -> str:
        return f"{self.key}: {self.before if self.before is not None else '-'} -> " \
               f"{self.after if self.after is not None else '-'}"


def firewall_supported(device: "Device") -> bool:
    """Chain-3 firewall available on this build (`cmd connectivity help`), cached per device."""
    caps = device.caps
    if "firewall" not in caps:
        caps["firewall"] = "set-package-networking-enabled" in device.read("cmd connectivity help").out
    return caps["firewall"]


# ---------------------------------------------------------------------- take
def take(device: "Device", scope: Iterable[str] = (), full: bool = False) -> Snapshot:
    """Read-only snapshot. `scope` = packages whose suspension / permissions / app-ops are recorded
    (the packages a plan touches). `full` also records the app locale of every installed package."""
    scope = sorted(set(scope))
    device.invalidate("snapshot reads fresh state")  # a change made outside droidforge must be seen
    s = Snapshot(serial=device.serial or "", fingerprint=device.fingerprint,
                 ts=datetime.now().isoformat(timespec="milliseconds"))
    for ns in NAMESPACES:
        s.settings[ns] = parse.settings_list(device.read(f"settings list {ns}").out)
    present = device.packages("-u")
    installed = device.packages()
    disabled = device.packages("-d")
    s.packages = {p: {"installed": p in installed, "enabled": p not in disabled} for p in sorted(present)}
    fw = firewall_supported(device) if scope else False
    idle = parse.deviceidle_whitelist(device.out("dumpsys deviceidle whitelist")) if scope else {}
    for p in scope:
        if p not in present:
            continue
        dump = device.read(f"dumpsys package {p}").out
        s.details[p] = {"suspended": parse.suspended(dump), "perms": parse.runtime_perms(dump),
                        "appops": parse.appops(device.read(f"cmd appops get {p}").out)}
        s.details[p]["deviceidle"] = idle.get(p, "")
        s.details[p]["standby"] = parse.standby_bucket(device.out(f"am get-standby-bucket {p}"))
        if fw:
            v = device.out(f"cmd connectivity get-package-networking-enabled {p}")
            if v in ("true", "false"):
                s.details[p]["fw"] = "allowed" if v == "true" else "blocked"
    if device.sdk >= 33:
        targets = sorted(installed) if full else sorted((device.packages("-3") | set(scope)) & installed)
        res = batch_read(device, targets, "cmd locale get-app-locales $p --user 0", label="app locales")
        s.app_locales = {p: parse.app_locales(o) for p, o in res.items()}
    for role in ROLES:
        r = device.read(f"cmd role get-role-holders --user 0 {role}")
        s.roles[role] = ",".join(sorted(x.strip() for x in r.out.splitlines() if x.strip())) if r.ok else ""
    s.imes = parse.ime_ids(device.read("ime list -s").out)
    s.launcher = parse.last_component(device.read(HOME_CMD).out)
    s.config = parse.global_config(device.read(CONFIG_CMD).out)
    device.log.trace(f"snapshot: {sum(len(t) for t in s.settings.values())} settings, {len(s.packages)} packages, "
                     f"{len(s.details)} detailed, {len(s.app_locales)} app locales, {len(s.imes)} IMEs")
    return s


# ---------------------------------------------------------------------- diff
def diff(before: Snapshot, after: Snapshot) -> List[Change]:
    a, b = before.flat(), after.flat()
    # details are only comparable for packages recorded in both snapshots
    both = set(before.details) & set(after.details)
    changes = []
    for k in sorted(set(a) | set(b)):
        if k.startswith(("perm:", "appop:", "fw:", "deviceidle:", "standby:")) or k.endswith(":suspended"):
            if k.split(":")[1] not in both:
                continue
        if k.startswith("applocale:") and (k not in a or k not in b):
            continue  # coverage differs (full vs plan scope), not a change
        if a.get(k) != b.get(k):
            changes.append(Change(k, a.get(k), b.get(k)))
    return changes


# Owner decision (P1.2): settings the ROM changes on its own. Changes are logged and reported but never stop a plan.
# Reviewed list only - it grows from Phase 9 findings - and it can never contain a display/UI key (P9b):
# tests/test_blast_radius.py enforces that.
VOLATILE_KEYS = {
    "setting:system:screen_brightness": "auto-brightness adjusts it all the time",
    "setting:system:screen_brightness_float": "auto-brightness (float variant)",
    "setting:system:next_alarm_formatted": "the clock app rewrites it when alarms fire",
}


def volatile(changes: Iterable[Change]) -> List[Change]:
    return [c for c in changes if c.key in VOLATILE_KEYS]


def covered(key: str, declared: Iterable[str]) -> bool:
    """Is `key` declared (exactly or by an fnmatch pattern such as `pkg:com.x:*`)?"""
    return any(key == d or fnmatchcase(key, d) for d in declared)


def undeclared(changes: Iterable[Change], declared: Iterable[str]) -> List[Change]:
    declared = list(declared)
    return [c for c in changes if not covered(c.key, declared)]
