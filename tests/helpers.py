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


# A small UAD-NG sample covering the simulator seed (the real list is downloaded at runtime).
UAD_SAMPLE = {
    "com.heytap.market": {"list": "Oem", "removal": "Recommended", "description": "HeyTap app market",
                          "neededBy": ["com.nearme.gamecenter"], "dependencies": []},
    "com.nearme.gamecenter": {"list": "Oem", "removal": "Recommended", "description": "Game center"},
    "com.heytap.pictorial": {"list": "Oem", "removal": "Recommended", "description": "Lock-screen magazine"},
    "com.coloros.pictorial": {"list": "Oem", "removal": "Unsafe", "description": "Breaks lock-screen settings"},
    "com.opos.cs": {"list": "Oem", "removal": "Recommended", "description": "Hot apps"},
    "com.heytap.mcs": {"list": "Oem", "removal": "Recommended", "description": "Push promos"},
    "com.coloros.assistantscreen": {"list": "Oem", "removal": "Advanced", "description": "-1 screen"},
    "com.coloros.gallery3d": {"list": "Oem", "removal": "Expert", "description": "Gallery"},
    "com.oplus.sauhelper": {"list": "Oem", "removal": "Recommended", "description": "statistics placeholder"},
    "com.coloros.prome.service": {"list": "Oem", "removal": "Recommended", "description": "feedback framework"},
    "com.baidu.input_oppo": {"list": "Oem", "removal": "Recommended", "description": "Baidu keyboard"},
    "com.coloros.gamespace": {"list": "Oem", "removal": "Recommended", "description": "Game space"},
    "com.oplus.statistics.rom": {"list": "Oem", "removal": "Recommended", "description": "User Experience Program"},
    "com.google.android.apps.photos": {"list": "Google", "removal": "Advanced", "description": "Google Photos"},
}


# commands that change the phone (for "nothing was written" assertions)
WRITE_PREFIXES = ("pm disable", "pm enable", "pm suspend", "pm unsuspend", "pm uninstall", "pm grant", "pm revoke",
                  "cmd package install-existing", "settings put", "settings delete", "cmd appops set", "ime enable",
                  "ime disable", "ime set", "cmd locale set", "am force-stop", "cmd connectivity set", "cmd role add")


def make_apk(path, package: str) -> None:
    """A minimal APK (zip) whose binary AndroidManifest.xml declares `package` (for apk.py + the simulator)."""
    import struct
    import zipfile
    strings = ["manifest", "package", package]
    data = b""
    offsets = []
    for s in strings:
        offsets.append(len(data))
        b = s.encode()
        data += bytes([len(s), len(b)]) + b + b"\x00"
    while len(data) % 4:
        data += b"\x00"
    sp_hsize = 28
    start = sp_hsize + 4 * len(strings)
    sp = struct.pack("<HHIIIIII", 0x0001, sp_hsize, start + len(data), len(strings), 0, 1 << 8, start, 0)
    sp += struct.pack(f"<{len(strings)}I", *offsets) + data
    attr = struct.pack("<IIIHBBI", 0xFFFFFFFF, 1, 2, 8, 0, 0x03, 2)
    el = struct.pack("<IIIIHHHHHH", 0, 0xFFFFFFFF, 0xFFFFFFFF, 0, 20, 20, 1, 0, 0, 0) + attr
    el = struct.pack("<HHI", 0x0102, 16, 8 + len(el)) + el
    body = sp + el
    axml = struct.pack("<HHI", 0x0003, 8, 8 + len(body)) + body
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("AndroidManifest.xml", axml)
