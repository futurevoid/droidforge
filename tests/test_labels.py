"""App names next to package names (owner request 2026-09-25): read from the APK, English first, cached."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from droidforge.adb import labels
from droidforge.adb.sim import FakePhone, _element, _pool, fake_arsc, fake_manifest
from droidforge.engine import guard
from tests.helpers import make_apk


def test_english_first_then_default() -> None:
    m = fake_manifest("com.x")
    assert labels.label_from(m, fake_arsc({"": "软件商店", "en": "App Market", "zh": "软件商店"})) == "App Market"
    assert labels.label_from(m, fake_arsc({"": "默认", "zh": "中文"})) == "默认"
    assert labels.label_from(m, fake_arsc({"fr": "Boutique"})) == "Boutique"   # only one choice: take it
    assert labels.label_from(m, None) is None


def test_literal_and_missing_labels(tmp_path: Path) -> None:
    make_apk(tmp_path / "a.apk", "com.no.label")   # manifest without <application>
    import zipfile
    axml = zipfile.ZipFile(tmp_path / "a.apk").read("AndroidManifest.xml")
    with pytest.raises(labels.LabelError):
        labels.manifest_label(axml)
    # android:label="My App" written as a plain string (no resources.arsc needed)
    body = _pool(["label", "manifest", "package", "com.x", "application", "My App"]) + \
        struct.pack("<HHI", 0x0180, 8, 12) + struct.pack("<I", labels.ATTR_LABEL) + \
        _element(1, [(2, 3, 0x03, 3)]) + _element(4, [(0, 5, 0x03, 5)])
    axml = struct.pack("<HHI", 0x0003, 8, 8 + len(body)) + body
    assert labels.manifest_label(axml) == ("My App", None) and labels.label_from(axml, None) == "My App"
    assert labels.clean("  App\n Market  ") == "App Market" and labels.clean(None) == ""
    assert len(labels.clean("x" * 500)) == labels.MAX_LABEL


def test_reference_outside_the_app_is_unknown() -> None:
    arsc = fake_arsc({"": "Name"})
    assert labels.resolve(arsc, 0x7F010000) == "Name"
    assert labels.resolve(arsc, 0x01040000) is None     # framework resource: not in this table
    assert labels.resolve(arsc, 0x7F010005) is None     # no such entry


def test_lookup_on_the_phone_and_cache(sim, phone: FakePhone) -> None:
    names = labels.lookup(sim, ["com.heytap.market", "com.whatsapp", "com.tencent.mm", "not.installed"])
    assert names == {"com.heytap.market": "App Market", "com.whatsapp": "WhatsApp", "com.tencent.mm": "WeChat"}
    before = phone.state()
    reads = []
    orig = sim.read
    sim.read = lambda cmd, **kw: (reads.append(cmd), orig(cmd, **kw))[1]  # type: ignore[method-assign]
    assert labels.lookup(sim, ["com.heytap.market"]) == {"com.heytap.market": "App Market"}
    assert not [c for c in reads if c.startswith("unzip")]          # cached: nothing re-read
    assert phone.state() == before                                    # reads only


def test_updated_app_is_read_again(sim, phone: FakePhone) -> None:
    assert labels.lookup(sim, ["com.whatsapp"]) == {"com.whatsapp": "WhatsApp"}
    p = phone.packages["com.whatsapp"]
    p.labels = {"": "WhatsApp Business"}
    assert labels.lookup(sim, ["com.whatsapp"]) == {"com.whatsapp": "WhatsApp"}   # same APK path: cached
    p.system = True                                                                # new path = updated APK
    assert labels.lookup(sim, ["com.whatsapp"]) == {"com.whatsapp": "WhatsApp Business"}


def test_guard_allows_only_the_two_label_reads() -> None:
    ok = labels.unzip_cmd("/data/app/~~gG-Ftn5k==/com.x-Mq4D==/base.apk", "AndroidManifest.xml")
    assert guard.check_read(ok).rule == "app-label"
    for bad in ("unzip -o '/data/app/x/base.apk' -d /sdcard", "unzip -p '/data/app/x/base.apk' classes.dex | base64",
                "unzip -p '/x.apk;rm -rf /' AndroidManifest.xml | base64",
                "unzip -p '/data/app/x/base.apk' resources.arsc | base64 > /sdcard/x"):
        with pytest.raises(guard.GuardError):
            guard.check_read(bad)
    with pytest.raises(labels.LabelError):
        labels.unzip_cmd("/x'.apk", "AndroidManifest.xml")


def test_plan_preview_names_the_app(sim, phone: FakePhone) -> None:
    from droidforge import cli
    from droidforge.engine import executor
    from tests.helpers import disable_plan
    seen = []

    def confirm(plan):
        seen.extend(cli.preview_lines(plan))
        return False
    executor.run(disable_plan(["com.heytap.market"]), sim, confirm)
    assert any('com.heytap.market' in line and 'app: "App Market"' in line for line in seen)
    assert phone.packages["com.heytap.market"].enabled


def test_reads_are_bounded_and_capped(sim, phone: FakePhone, monkeypatch: pytest.MonkeyPatch) -> None:
    cmds = []
    orig = sim.read
    sim.read = lambda cmd, **kw: (cmds.append(cmd), orig(cmd, **kw))[1]  # type: ignore[method-assign]
    pkgs = ["com.heytap.market", "com.whatsapp", "com.tencent.mm", "org.telegram.messenger"]
    assert len(labels.lookup(sim, pkgs, max_new=2)) == 2                  # only two new APKs read
    assert all("| head -c " in c for c in cmds if c.startswith("unzip"))
    assert len(labels.lookup(sim, pkgs)) == 4                             # the rest on a later call
    monkeypatch.setitem(labels.LIMITS, "resources.arsc", 40)              # a table too big for the cap
    phone.packages["com.whatsapp"].system = True                          # new APK path -> read again
    assert "com.whatsapp" not in labels.lookup(sim, ["com.whatsapp"])     # unknown, no crash


def test_label_data_never_reaches_the_log_pane(phone: FakePhone) -> None:
    from droidforge.adb.sim import sim_device
    from droidforge.log import Logger
    lg = Logger(3)
    lines = []
    lg.add_sink(lines.append)
    labels.lookup(sim_device(phone, log=lg), ["com.heytap.market"])
    idx = [i for i, ln in enumerate(lines) if ln.kind == "cmd" and "unzip -p" in ln.text]
    assert idx
    for i in idx:                       # after each name read: the exit line, then no output lines
        assert lines[i + 1].kind == "exit" and (i + 2 >= len(lines) or lines[i + 2].kind != "out")


def test_decode_tolerates_noise_and_headers() -> None:
    import base64
    m = fake_manifest("com.x")
    noisy = "WARNING: linker: something\n" + base64.b64encode(b"Archive:  /x.apk\n" + m).decode() + "\n"
    assert labels.decode_member(noisy, labels.MAGIC["AndroidManifest.xml"]) == m
    assert labels.decode_member("", b"") is None
    assert labels.decode_member(base64.b64encode(b"garbage").decode(), labels.MAGIC["resources.arsc"]) is None
