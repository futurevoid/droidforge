"""One connected phone plus its profile and history - shared by the CLI and the TUI (no textual here)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from droidforge import config
from droidforge.adb.device import Device, list_devices
from droidforge.adb.real import RealBackend
from droidforge.adb.sim import FakePhone, SimBackend, neo8_cn
from droidforge.engine.history import History
from droidforge.engine.profile import Profile
from droidforge.log import LOG, Logger


class ConnectError(Exception):
    pass


@dataclass
class Session:
    device: Device
    profile: Profile
    history: History
    simulate: bool = False
    expert: bool = False
    dry_run: bool = False
    phone: Optional[FakePhone] = None   # the simulated phone (only with --simulate)


def pick_serial(rows: List[Tuple[str, str]], wanted: Optional[str]) -> str:
    ready = [s for s, st in rows if st == "device"]
    if wanted:
        if wanted in ready:
            return wanted
        raise ConnectError(f"device {wanted} is not connected (connected: {', '.join(ready) or 'none'})")
    if len(ready) == 1:
        return ready[0]
    if len(ready) > 1:
        raise ConnectError(f"several devices connected - pick one with --serial: {', '.join(ready)}")
    if any(st == "unauthorized" for _, st in rows):
        raise ConnectError("the phone shows as unauthorized - accept the 'Allow USB debugging' prompt on screen")
    raise ConnectError("no device - plug in USB and enable Developer options > USB debugging")


def open_session(simulate: bool = False, serial: Optional[str] = None, expert: bool = False,
                 dry_run: bool = False, log: Optional[Logger] = None,
                 phone: Optional[FakePhone] = None) -> Session:
    lg = log or LOG
    fake = None
    if simulate:
        fake = phone or neo8_cn()
        dev = Device(SimBackend(fake), fake.serial, log=lg)
    else:
        backend = RealBackend()
        if not backend.adb:
            from droidforge.adb.real import ADB_HINT
            raise ConnectError(ADB_HINT)
        dev = Device(backend, pick_serial(list_devices(backend), serial), log=lg)
    paths = config.paths()
    prof = Profile.for_device(dev.serial or "device", paths.sub("profiles"))
    hist = History(dev.serial or "device", paths.sub("history"))
    lg.dbg(f"SESSION device={dev.serial} simulate={simulate} expert={expert} dry_run={dry_run}")
    return Session(dev, prof, hist, simulate, expert, dry_run, fake)
