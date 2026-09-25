"""P0.4: the simulated ColorOS phone answers the documented commands like the real tools."""

from __future__ import annotations

import re

from droidforge.adb import batch
from droidforge.adb.sim import (
    AOSP_PERMS,
    AOSP_SETTINGS,
    COLOROS_PERMS,
    COLOROS_SETTINGS,
    IME_GBOARD,
    IME_SOGOU,
    PERMISSION_MONITORING_KEY,
    SIM_SERIAL,
    FakePhone,
    SimBackend,
)

SH = "cmd package resolve-activity --brief -a"


def last_component(out: str) -> str:
    lines = [x.strip() for x in out.splitlines() if "/" in x]
    return lines[-1] if lines else ""


# ---------------------------------------------------------------- transport
def test_devices_and_unknown(sim, phone: FakePhone) -> None:
    b = SimBackend(phone)
    assert f"{SIM_SERIAL}\tdevice" in b.run(["devices"]).out
    assert b.run(["-s", "OTHER", "shell", "id"]).exit == 1
    r = sim.read("rm -rf /sdcard")
    assert r.exit == 127 and r.err.startswith("sim: unsupported")
    assert b.run(["reboot-bootloader"]).exit == 127


def test_device_info(sim) -> None:
    assert sim.sdk == 36 and sim.label == "realme RMX8899" and sim.rom_family == "coloros"
    assert "[ro.build.version.sdk]: [36]" in sim.out("getprop")


# ---------------------------------------------------------------- packages
def test_disable_list_enable_roundtrip(sim, phone: FakePhone) -> None:
    p = "com.heytap.market"
    assert p not in sim.packages("-d")
    r = sim.sh(f"pm disable-user --user 0 {p}")
    assert r.ok and r.out == f"Package {p} new state: disabled-user"
    assert p in sim.packages("-d") and p in sim.packages()
    assert sim.sh(f"pm enable --user 0 {p}").out == f"Package {p} new state: enabled"
    assert p not in sim.packages("-d")


def test_remove_restore_roundtrip(sim) -> None:
    p = "com.opos.cs"
    assert sim.sh(f"pm uninstall -k --user 0 {p}").out == "Success"
    assert p not in sim.packages() and p in sim.packages("-u")
    assert sim.sh(f"cmd package install-existing {p}").ok
    assert p in sim.packages()


def test_suspend_and_refusals(sim) -> None:
    r = sim.sh("pm disable-user --user 0 com.oplus.sauhelper")
    assert "SecurityException" in r.err and not r.ok
    assert sim.sh("pm suspend --user 0 com.oplus.sauhelper").out.endswith("suspended state: true")
    assert not sim.sh("pm suspend --user 0 com.oplus.safecenter").ok
    assert not sim.sh("pm disable-user --user 0 com.not.there").ok


def test_list_flags(sim) -> None:
    system, third = sim.packages("-s"), sim.packages("-3")
    assert "com.whatsapp" in third and "com.whatsapp" not in system
    assert "com.android.systemui" in system
    uids = sim.package_uids()
    assert uids["android"] == 1000 and uids["com.whatsapp"] >= 10000
    assert "package:/data/app/" in sim.out("pm list packages -f -3")


def test_perms_and_appops(sim) -> None:
    p = "com.heytap.market"
    out = sim.out(f"dumpsys package {p}")
    assert "runtime permissions:" in out and "android.permission.POST_NOTIFICATIONS: granted=true" in out
    assert sim.sh(f"pm revoke {p} android.permission.POST_NOTIFICATIONS").ok
    assert "POST_NOTIFICATIONS: granted=false" in sim.out(f"dumpsys package {p}")
    assert not sim.sh(f"pm grant {p} android.permission.CAMERA").ok  # not requested
    sim.sh(f"cmd appops set {p} RUN_ANY_IN_BACKGROUND ignore")
    assert "RUN_ANY_IN_BACKGROUND: ignore" in sim.out(f"cmd appops get {p}")
    sim.sh(f"cmd appops set {p} RUN_ANY_IN_BACKGROUND default")
    assert sim.out(f"cmd appops get {p}") == "No operations."


def test_focused_app(sim, phone: FakePhone) -> None:
    phone.focused = "com.tencent.mm"
    out = sim.out("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'")
    assert len(out.splitlines()) == 2 and "u0 com.tencent.mm/" in out


# ---------------------------------------------------------------- language
def test_app_locale_set_get(sim) -> None:
    p = "com.whatsapp"
    assert sim.out(f"cmd locale get-app-locales {p} --user 0") == f"Locales for {p} for user 0 are []"
    assert sim.sh(f"cmd locale set-app-locales {p} --user 0 --locales en-US,ar-EG").ok
    assert sim.out(f"cmd locale get-app-locales {p} --user 0").endswith("[en-US,ar-EG]")
    sim.sh(f"cmd locale set-app-locales {p} --user 0 --locales ''")
    assert sim.out(f"cmd locale get-app-locales {p} --user 0").endswith("[]")


def test_device_locale_reads(sim, phone: FakePhone) -> None:
    assert sim.out("getprop persist.sys.locale") == "zh-Hans-CN"
    assert sim.out("settings get system system_locales") == "zh-Hans-CN,en-US"
    assert "[zh_CN_#Hans,en_US]" in sim.out("dumpsys activity | grep -m1 mGlobalConfig")
    phone.set_device_locales(["en-US", "ar-EG"])
    assert "[en_US,ar_EG]" in sim.out("dumpsys activity | grep -m1 mGlobalConfig")


def test_open_screens(sim, phone: FakePhone) -> None:
    assert sim.sh("am start -a android.settings.LOCALE_SETTINGS").out.startswith("Starting: Intent")
    assert sim.sh("am start -a android.settings.DATE_SETTINGS").ok
    assert phone.started == ["android.settings.LOCALE_SETTINGS", "android.settings.DATE_SETTINGS"]
    assert not sim.sh("am start -a android.settings.NOPE").ok
    assert sim.out("cmd uimode night") == "Night mode: yes"


# ---------------------------------------------------------------- keyboard
def test_ime_switch(sim, phone: FakePhone) -> None:
    assert IME_GBOARD not in sim.out("ime list -s")
    assert sim.out("settings get secure default_input_method") == IME_SOGOU
    assert not sim.sh(f"ime set {IME_GBOARD}").ok  # must be enabled first
    assert sim.sh(f"ime enable {IME_GBOARD}").out.endswith("now enabled")
    assert sim.sh(f"ime set {IME_GBOARD}").ok
    assert sim.out("settings get secure default_input_method") == IME_GBOARD
    assert sim.sh(f"ime disable {IME_SOGOU}").out.endswith("now disabled")
    assert IME_SOGOU not in sim.out("ime list -s")


def test_ime_disable_current_falls_back(sim) -> None:
    sim.sh(f"ime disable {IME_SOGOU}")
    assert sim.out("settings get secure default_input_method") != IME_SOGOU


# ---------------------------------------------------------------- batch format
def test_batch_loop_output_format(sim) -> None:
    pkgs = ["com.whatsapp", "com.tencent.mm", "org.telegram.messenger"]
    raw = sim.read(batch.batch_script(pkgs, "cmd locale get-app-locales $p --user 0")).out
    assert raw.splitlines() == [
        "@@com.whatsapp", "Locales for com.whatsapp for user 0 are []",
        "@@com.tencent.mm", "Locales for com.tencent.mm for user 0 are [zh-CN]",
        "@@org.telegram.messenger", "Locales for org.telegram.messenger for user 0 are []",
    ]
    res = batch.batch_read(sim, pkgs + ["com.not.there"], "cmd locale get-app-locales $p --user 0")
    assert res["com.tencent.mm"].strip().endswith("[zh-CN]")
    assert "Unknown package name" in res["com.not.there"]  # 2>&1 merges stderr like the real shell


def test_batch_with_unsupported_inner_command(sim) -> None:
    assert sim.read('for p in a.b; do echo "@@$p"; rm -rf $p 2>&1; done').exit == 127


# ---------------------------------------------------------------- health probes / fault injection
def probes(sim) -> dict:
    return {
        "settings": last_component(sim.out(f"{SH} android.settings.SETTINGS")),
        "perms": last_component(sim.out(f"{SH} android.intent.action.MANAGE_APP_PERMISSIONS")),
        "config": sim.out("dumpsys activity | grep -m1 mGlobalConfig"),
        "pm": sim.out(f"settings get global {PERMISSION_MONITORING_KEY}"),
        "home": last_component(sim.out(f"{SH} android.intent.action.MAIN -c android.intent.category.HOME")),
        "crash": sim.out("logcat -b crash -d -t 200"),
        "sysui": sim.read("pidof com.android.systemui").ok,
    }


def test_healthy_probes(sim) -> None:
    p = probes(sim)
    assert p["settings"] == COLOROS_SETTINGS and p["perms"] == COLOROS_PERMS
    assert re.search(r"mMaterialColor=17179869184", p["config"]) and "480dpi" in p["config"]
    assert p["pm"] == "0" and p["home"].startswith("com.android.launcher/") and p["crash"] == "" and p["sysui"]
    assert "font_scale=1.0" in sim.out("settings list system")


def test_break_ui_visible_through_probes(sim, phone: FakePhone) -> None:
    phone.break_ui()
    phone.crash("com.android.settings")
    p = probes(sim)
    assert p["settings"] == AOSP_SETTINGS and p["perms"] == AOSP_PERMS
    assert "mMaterialColor=0" in p["config"] and p["pm"] == "1"
    assert "Process: com.android.settings" in p["crash"]


def test_disabled_settings_does_not_resolve(sim) -> None:
    sim.sh("pm disable-user --user 0 com.android.launcher")
    assert "No activity found" in sim.out(f"{SH} android.intent.action.MAIN -c android.intent.category.HOME")


def test_side_effects(sim, phone: FakePhone) -> None:
    phone.side_effects[r"pm disable-user .* com\.heytap\.market$"] = \
        lambda ph: ph.settings["system"].__setitem__("font_scale", "1.3")
    sim.sh("pm disable-user --user 0 com.heytap.market")
    assert sim.out("settings get system font_scale") == "1.3"


def test_clone_and_state(phone: FakePhone) -> None:
    c = phone.clone()
    assert c.state() == phone.state()
    c.packages["com.whatsapp"].enabled = False
    assert c.state() != phone.state()
