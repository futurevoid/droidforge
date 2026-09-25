"""Device: one phone behind a Backend.

- `read(cmd)` runs a read-only shell command. The read guard (engine/guard.py) checks it first.
- `sh(cmd)` is the write path. Only `engine/executor.py` may call it (test_package enforces that); the write guard
  re-checks every command against the allowlist and the package caches are invalidated afterwards.
"""

from __future__ import annotations

import re
import shlex
import time
from typing import Callable, Dict, List, Optional, Set, Tuple

from droidforge.adb.backend import Backend, RunResult
from droidforge.log import LOG, Logger

Guard = Callable[[str, "Device"], None]

PKG_RE = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$")


def _default_read_guard(cmd: str, device: "Device") -> None:
    from droidforge.engine import guard  # lazy: adb must not depend on engine at import time
    guard.check_read(cmd, device)


def _default_write_guard(cmd: str, device: "Device") -> None:
    from droidforge.engine import guard
    guard.check_command(cmd, device)


def list_devices(backend: Backend) -> List[Tuple[str, str]]:
    """[(serial, state)] from `adb devices`; state is device / unauthorized / offline ..."""
    r = backend.run(["devices"], timeout=15)
    rows = []
    for line in r.out.splitlines()[1:]:
        if "\t" in line:
            serial, state = line.split("\t", 1)
            rows.append((serial.strip(), state.strip()))
    return rows


def parse_packages(out: str) -> Set[str]:
    """`pm list packages [-d|-u|-s|-3]` -> names. Also copes with `-f` (path=name) and `-U` (uid:N)."""
    names = set()
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("package:"):
            continue
        body = line[8:].split(" uid:")[0].strip()
        if "=" in body:  # -f: /data/app/.../base.apk=com.x
            body = body.rsplit("=", 1)[1]
        if body:
            names.add(body)
    return names


def parse_package_uids(out: str) -> Dict[str, int]:
    """`pm list packages -U` -> {pkg: uid} (shared uids appear as `uid:1000,10123`: first wins)."""
    res = {}
    for line in out.splitlines():
        m = re.match(r"\s*package:(\S+)\s+uid:(\d+)", line)
        if m:
            res[m.group(1)] = int(m.group(2))
    return res


class Device:
    def __init__(self, backend: Backend, serial: Optional[str] = None, log: Optional[Logger] = None,
                 read_guard: Optional[Guard] = _default_read_guard,
                 write_guard: Optional[Guard] = _default_write_guard) -> None:
        self.backend = backend
        self.serial = serial
        self.log = log or LOG
        self.read_guard = read_guard
        self.write_guard = write_guard
        self._props: Dict[str, str] = {}
        self.caps: Dict[str, bool] = {}   # capability probes (firewall, ...), cached for the session
        self._plist: Dict[str, Set[str]] = {}

    # ------------------------------------------------------------------ transport
    def _prefix(self) -> List[str]:
        return ["-s", self.serial] if self.serial else []

    def pretty(self, args: List[str]) -> str:
        parts = ["adb"] + self._prefix() + [a if (a and " " not in a and "'" not in a) else shlex.quote(a)
                                            for a in args]
        return " ".join(parts)

    def adb(self, args: List[str], timeout: float = 30, plumbing: bool = False) -> RunResult:
        """Raw adb call with logging. Callers: read(), sh(), and connection-level queries (get-state)."""
        self.log.command(self.pretty(args), plumbing=plumbing)
        t0 = time.monotonic()
        r = self.backend.run(self._prefix() + list(args), timeout=timeout)
        ms = r.ms or int((time.monotonic() - t0) * 1000)
        self.log.result(r.exit, ms, r.out, r.err, plumbing=plumbing)
        return r

    def read(self, cmd: str, timeout: float = 30, plumbing: bool = True) -> RunResult:
        """Run a read-only shell command (checked against the read allowlist)."""
        if self.read_guard is not None:
            self.read_guard(cmd, self)
        return self.adb(["shell", cmd], timeout=timeout, plumbing=plumbing)

    def out(self, cmd: str, plumbing: bool = True) -> str:
        return self.read(cmd, plumbing=plumbing).out.strip()

    def sh(self, cmd: str, timeout: float = 60) -> RunResult:
        """WRITE path - engine/executor.py only."""
        if self.write_guard is not None:
            self.write_guard(cmd, self)
        try:
            return self.adb(["shell", cmd], timeout=timeout, plumbing=False)
        finally:
            self.invalidate("device changed")

    def state(self) -> str:
        r = self.adb(["get-state"], timeout=10, plumbing=True)
        return r.out.strip() if r.ok else "offline"

    # ------------------------------------------------------------------ caches
    def invalidate(self, why: str = "") -> None:
        if self._plist:
            self._plist.clear()
            self.log.trace(f"package-list cache cleared{f' ({why})' if why else ''}", 3)

    def forget_props(self) -> None:
        """After a reboot / OTA: props may have changed."""
        self._props.clear()

    def getprop(self, name: str) -> str:
        if name in self._props:
            self.log.trace(f"cache hit: getprop {name} = {self._props[name]!r}", 3)
            return self._props[name]
        v = self.out(f"getprop {name}")
        self._props[name] = v
        return v

    def packages(self, flags: str = "") -> Set[str]:
        """`pm list packages <flags>` with a cache that every write clears."""
        key = flags.strip()
        if key in self._plist:
            self.log.trace(f"cache hit: pm list packages {key} ({len(self._plist[key])} pkgs)", 3)
            return set(self._plist[key])
        pk = parse_packages(self.out(f"pm list packages {key}".strip()))
        self._plist[key] = pk
        self.log.trace(f"pm list packages {key or '(installed)'} -> {len(pk)} packages")
        return set(pk)

    def package_uids(self) -> Dict[str, int]:
        return parse_package_uids(self.out("pm list packages -U"))

    # ------------------------------------------------------------------ identity
    @property
    def sdk(self) -> int:
        try:
            return int(self.getprop("ro.build.version.sdk"))
        except ValueError:
            return 0

    @property
    def label(self) -> str:
        return f"{self.getprop('ro.product.brand')} {self.getprop('ro.product.model')}".strip()

    @property
    def fingerprint(self) -> str:
        return self.getprop("ro.build.fingerprint")

    @property
    def rom_family(self) -> str:
        """"coloros" on oplus builds (ColorOS / realme UI / OxygenOS 13+), else "aosp"."""
        return "coloros" if self.getprop("ro.build.version.oplusrom") else "aosp"
