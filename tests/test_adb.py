"""P0.3: adb backend / real / device / batch, with a stub backend (no phone, no adb)."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Callable, Dict, List

import pytest

from droidforge.adb import batch
from droidforge.adb.backend import RunResult
from droidforge.adb.device import Device, list_devices, parse_package_uids, parse_packages
from droidforge.adb.real import ADB_HINT, RealBackend
from droidforge.log import Logger


class StubBackend:
    """Answers shell commands from a dict of callables / strings; records every call."""

    def __init__(self, answers: Dict[str, object]) -> None:
        self.answers = answers
        self.calls: List[List[str]] = []

    def run(self, args: List[str], timeout: float = 30) -> RunResult:
        self.calls.append(list(args))
        if args[:2] == ["-s", "SER"]:
            args = args[2:]
        key = args[1] if args[0] == "shell" else " ".join(args)
        a = self.answers.get(key, "")
        if callable(a):
            return a(key)
        if isinstance(a, RunResult):
            return a
        return RunResult(0, str(a), "", 1)


def dev(answers: Dict[str, object], **kw) -> Device:
    return Device(StubBackend(answers), "SER", log=Logger(3), read_guard=None, write_guard=None, **kw)


# ---------------------------------------------------------------- parsing
def test_parse_packages_variants() -> None:
    out = "package:com.a\npackage:/data/app/x/base.apk=com.b\npackage:com.c uid:10123\ngarbage\n"
    assert parse_packages(out) == {"com.a", "com.b", "com.c"}
    assert parse_package_uids("package:com.c uid:10123\npackage:android uid:1000") == {"com.c": 10123,
                                                                                        "android": 1000}


def test_list_devices() -> None:
    b = StubBackend({"devices": "List of devices attached\nAAA\tdevice\nBBB\tunauthorized\n"})
    assert list_devices(b) == [("AAA", "device"), ("BBB", "unauthorized")]


# ---------------------------------------------------------------- device
def test_getprop_cache_and_identity() -> None:
    d = dev({"getprop ro.build.version.sdk": "36", "getprop ro.product.brand": "realme",
             "getprop ro.product.model": "RMX8899", "getprop ro.build.version.oplusrom": "V16.0.0"})
    assert d.sdk == 36 and d.sdk == 36
    assert sum(1 for c in d.backend.calls if c[-1] == "getprop ro.build.version.sdk") == 1
    assert d.label == "realme RMX8899" and d.rom_family == "coloros"
    d.forget_props()
    assert d.sdk == 36
    assert sum(1 for c in d.backend.calls if c[-1] == "getprop ro.build.version.sdk") == 2


def test_rom_family_aosp() -> None:
    assert dev({}).rom_family == "aosp"


def test_sdk_garbage_is_zero() -> None:
    assert dev({"getprop ro.build.version.sdk": "?"}).sdk == 0


def test_package_cache_invalidated_by_write() -> None:
    d = dev({"pm list packages": "package:com.a", "pm disable-user --user 0 com.a": "ok"})
    assert d.packages() == {"com.a"}
    d.packages()
    assert sum(1 for c in d.backend.calls if c[-1] == "pm list packages") == 1
    d.sh("pm disable-user --user 0 com.a")
    d.packages()
    assert sum(1 for c in d.backend.calls if c[-1] == "pm list packages") == 2


def test_serial_prefix_and_pretty() -> None:
    d = dev({})
    d.read("getprop ro.x")
    assert d.backend.calls[-1] == ["-s", "SER", "shell", "getprop ro.x"]
    assert d.pretty(["shell", "pm list packages"]) == "adb -s SER shell 'pm list packages'"


def test_guards_are_called() -> None:
    seen: List[str] = []

    def rg(c: str) -> None:
        seen.append("r:" + c)

    def wg(c: str) -> None:
        if "evil" in c:
            raise PermissionError(c)
        seen.append("w:" + c)
    d = Device(StubBackend({}), "SER", log=Logger(1), read_guard=rg, write_guard=wg)
    d.read("getprop x")
    d.sh("pm enable --user 0 com.a")
    with pytest.raises(PermissionError):
        d.sh("evil")
    assert seen == ["r:getprop x", "w:pm enable --user 0 com.a"]
    assert all("evil" not in " ".join(c) for c in d.backend.calls)  # refused before sending


# ---------------------------------------------------------------- batch
def _batch_answer(key: str) -> RunResult:
    import re
    pkgs = re.match(r"for p in (.*?); do", key).group(1).split()
    return RunResult(0, "".join(f"@@{p}\nLocales for {p} for user 0 are [en-US]\n" for p in pkgs), "", 5)


def test_batch_read_chunks_and_parses() -> None:
    pkgs = [f"com.p{i}" for i in range(95)] + ["bad name;rm"]
    b = StubBackend({})
    b.answers = _AnyFor(_batch_answer)
    d = Device(b, "SER", log=Logger(1), read_guard=None, write_guard=None)
    res = batch.batch_read(d, pkgs, "cmd locale get-app-locales $p --user 0")
    assert len(res) == 95 and "[en-US]" in res["com.p94"]
    assert len(b.calls) == 3  # 40 + 40 + 15
    assert 'for p in com.p0 ' in b.calls[0][-1] and b.calls[0][-1].endswith("2>&1; done")


class _AnyFor(dict):
    def __init__(self, fn: Callable[[str], RunResult]) -> None:
        super().__init__()
        self.fn = fn

    def get(self, key, default=None):  # type: ignore[override]
        return self.fn if key.startswith("for p in") else default


def test_batch_script_format_matches_legacy() -> None:
    assert batch.batch_script(["a.b", "c.d"], "pm path $p") == 'for p in a.b c.d; do echo "@@$p"; pm path $p 2>&1; done'
    assert batch.parse_batch("@@a.b\nx\ny\n@@c.d\n") == {"a.b": "x\ny\n", "c.d": ""}


# ---------------------------------------------------------------- real backend (fake adb binary on the host)
def _fake_adb(tmp_path: Path, body: str) -> str:
    p = tmp_path / "adb"
    p.write_text("#!/bin/sh\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


@pytest.mark.skipif(os.name != "posix", reason="shell script fake adb")
def test_real_backend_runs_and_strips(tmp_path: Path) -> None:
    r = RealBackend(_fake_adb(tmp_path, 'echo "args:$*"; echo oops >&2; exit 3\n')).run(["shell", "getprop x"])
    assert r.exit == 3 and r.out == "args:shell getprop x" and r.err == "oops"


@pytest.mark.skipif(os.name != "posix", reason="shell script fake adb")
def test_real_backend_timeout_is_124(tmp_path: Path) -> None:
    r = RealBackend(_fake_adb(tmp_path, "sleep 5\n")).run(["devices"], timeout=0.3)
    assert r.exit == 124 and "timeout" in r.err


def test_real_backend_missing_adb_is_127(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("droidforge.adb.real.find_adb", lambda: None)
    r = RealBackend().run(["devices"])
    assert r.exit == 127 and ADB_HINT in r.err and "sudo pacman -S android-tools" in r.err


def test_real_backend_unstartable_is_127(tmp_path: Path) -> None:
    r = RealBackend(str(tmp_path / "nope" / "adb")).run(["devices"])
    assert r.exit == 127 and "pacman" in r.err
