"""P1.2: snapshot take/diff finds exactly the injected changes (P10, R-11.8)."""

from __future__ import annotations

from pathlib import Path

from droidforge.adb import parse
from droidforge.adb.sim import IME_GBOARD, FakePhone
from droidforge.engine import guard, snapshot
from droidforge.engine.snapshot import Change, Snapshot


def test_take_reads_everything(sim, phone: FakePhone) -> None:
    s = snapshot.take(sim, scope=["com.heytap.market"])
    assert s.settings["system"]["font_scale"] == "1.0"
    assert s.packages["com.heytap.market"] == {"installed": True, "enabled": True}
    assert s.details["com.heytap.market"]["perms"] == {"android.permission.POST_NOTIFICATIONS": True}
    assert s.app_locales["com.tencent.mm"] == "zh-CN" and "com.android.settings" not in s.app_locales
    assert s.launcher.startswith("com.android.launcher/")
    assert s.config["mMaterialColor"] == "17179869184" and s.config["density"] == "480"
    assert s.config["locales"] == "zh_CN_#Hans,en_US" and s.config["night"] == "yes"
    assert s.serial == phone.serial and s.fingerprint.startswith("realme/")


def test_take_is_read_only(sim, phone: FakePhone) -> None:
    before = phone.state()
    n = len(phone.log)
    snapshot.take(sim, scope=["com.whatsapp", "com.heytap.market"], full=True)
    assert phone.state() == before
    for cmd in phone.log[n:]:
        assert not guard.check_read(cmd, sim).write


def test_full_scope_covers_system_app_locales(sim) -> None:
    s = snapshot.take(sim, full=True)
    assert "com.android.settings" in s.app_locales and "com.oplus.uxdesign" in s.app_locales


def test_no_change_no_diff(sim) -> None:
    a = snapshot.take(sim, scope=["com.whatsapp"])
    b = snapshot.take(sim, scope=["com.whatsapp"])
    assert snapshot.diff(a, b) == []


def test_diff_finds_exactly_injected_changes(sim, phone: FakePhone) -> None:
    scope = ["com.heytap.market", "com.whatsapp"]
    a = snapshot.take(sim, scope=scope)
    phone.settings["system"]["font_scale"] = "1.3"                        # display regression
    phone.settings["global"]["brand_new_key"] = "1"                       # key appears
    phone.packages["com.heytap.market"].enabled = False
    phone.packages["com.heytap.market"].perms["android.permission.POST_NOTIFICATIONS"] = False
    phone.packages["com.heytap.market"].appops["RUN_ANY_IN_BACKGROUND"] = "ignore"
    phone.packages["com.whatsapp"].suspended = True
    phone.packages["com.whatsapp"].locales = "en-US"
    phone.packages["com.opos.cs"].user0 = False
    phone.imes[IME_GBOARD] = True
    phone.config.oem["mMaterialColor"] = "0"
    b = snapshot.take(sim, scope=scope)
    got = {c.key: (c.before, c.after) for c in snapshot.diff(a, b)}
    assert got == {
        "setting:system:font_scale": ("1.0", "1.3"),
        "setting:global:brand_new_key": (None, "1"),
        "pkg:com.heytap.market:enabled": ("true", "false"),
        "perm:com.heytap.market:android.permission.POST_NOTIFICATIONS": ("granted", "denied"),
        "appop:com.heytap.market:RUN_ANY_IN_BACKGROUND": (None, "ignore"),
        "pkg:com.whatsapp:suspended": ("false", "true"),
        "applocale:com.whatsapp": ("", "en-US"),
        "pkg:com.opos.cs:installed": ("true", "false"),
        f"ime:enabled:{IME_GBOARD}": (None, "true"),
        "config:mMaterialColor": ("17179869184", "0"),
    }


def test_break_ui_shows_in_diff(sim, phone: FakePhone) -> None:
    a = snapshot.take(sim)
    phone.break_ui()
    keys = {c.key for c in snapshot.diff(a, snapshot.take(sim))}
    assert "config:mMaterialColor" in keys
    assert "prop:persist.sys.permission.enable" in keys


def test_side_effect_is_the_only_extra_change(sim, phone: FakePhone) -> None:
    phone.side_effects[r"disable-user .* com\.heytap\.market$"] = \
        lambda ph: ph.settings["secure"].__setitem__("ui_night_mode", "1")
    a = snapshot.take(sim)
    sim.sh("pm disable-user --user 0 com.heytap.market")
    changes = snapshot.diff(a, snapshot.take(sim))
    extra = snapshot.undeclared(changes, ["pkg:com.heytap.market:enabled"])
    assert [str(c) for c in extra] == ["setting:secure:ui_night_mode: - -> 1"]


def test_covered_patterns() -> None:
    assert snapshot.covered("pkg:com.x:enabled", ["pkg:com.x:*"])
    assert not snapshot.covered("pkg:com.y:enabled", ["pkg:com.x:*"])
    ch = [Change("a", "1", "2"), Change("b", None, "1")]
    assert snapshot.undeclared(ch, ["a"]) == [Change("b", None, "1")]


def test_json_roundtrip(sim, tmp_path: Path) -> None:
    s = snapshot.take(sim, scope=["com.heytap.market"])
    p = s.save(tmp_path / "snap.json")
    assert Snapshot.load(p) == s
    assert snapshot.diff(s, Snapshot.load(p)) == []


def test_parse_helpers() -> None:
    assert parse.last_component("priority=0 x\ncom.a/.B") == "com.a/.B"
    assert parse.last_component("No activity found") == ""
    assert parse.appops("RUN_IN_BACKGROUND: ignore; time=+1d\nPOST_NOTIFICATION: allow") == \
        {"RUN_IN_BACKGROUND": "ignore", "POST_NOTIFICATION": "allow"}
    assert parse.app_locales("Locales for x for user 0 are [en-US, ar-EG]") == "en-US,ar-EG"
    cfg = parse.global_config("mGlobalConfig={1.15 [en_US] 440dpi nrml port finger "
                              "mOplusExtraConfiguration={mMaterialColor= 0, mDarkModeFooL=3.0}}")
    assert cfg["fontScale"] == "1.15" and cfg["density"] == "440" and cfg["night"] == "no"
    assert cfg["mMaterialColor"] == "0" and cfg["mDarkModeFooL"] == "3.0"
    assert parse.global_config("") == {}
