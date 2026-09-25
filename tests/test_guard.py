"""P1.1: the allowlist (P8) matches docs/COMMANDS.md, Forbidden is refused (P0/P9/P9b), P12 holds."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple

import pytest

from droidforge.adb.sim import IME_GBOARD, IME_SOGOU, PERMISSION_MONITORING_KEY, SIM_SERIAL
from droidforge.engine import guard
from droidforge.engine.guard import GuardError

DOCS = Path(__file__).resolve().parents[1] / "docs" / "COMMANDS.md"


def section_short(heading: str) -> str:
    return re.split(r" \(| - ", heading, maxsplit=1)[0].strip()


def parse_commands_md() -> Tuple[Set[Tuple[str, str]], List[str]]:
    """(allowlist rows as (section, purpose), forbidden row cells)."""
    rows, forbidden, sec = set(), [], ""
    for line in DOCS.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            sec = section_short(line[3:])
            continue
        if not line.startswith("|") or re.match(r"\|\s*-", line):
            continue
        first = re.split(r"(?<!\\)\|", line.strip())[1].strip()
        if first in ("Purpose", "Probe", "Command / technique"):
            continue
        if sec == "Forbidden":
            forbidden.append(first)
        elif sec != "Tweaks":
            rows.add((sec, first))
    return rows, forbidden


ROWS, FORBIDDEN_ROWS = parse_commands_md()


# ---------------------------------------------------------------- COMMANDS.md <-> guard sync
def test_sections_match() -> None:
    assert {s for s, _ in ROWS} == set(guard.commands_md_sections())


def test_every_row_has_a_rule_or_is_doc_only() -> None:
    missing = ROWS - guard.rows_covered()
    assert not missing, f"COMMANDS.md rows without a guard rule: {sorted(missing)}"


def test_every_rule_row_exists_in_commands_md() -> None:
    stale = guard.rows_covered() - ROWS
    assert not stale, f"guard rules/doc-only rows naming rows that are not in COMMANDS.md: {sorted(stale)}"


def test_rules_are_unique_and_named() -> None:
    names = [r.name for r in guard.RULES]
    assert len(names) == len(set(names))
    for r in guard.RULES:
        re.compile(r.regex)
        if r.write and not r.host:
            assert r.touches, f"device write rule {r.name} has no touches (P10)"


# one concrete command per rule, so every regex is exercised
EXAMPLES: Dict[str, str] = {
    "getprop": "getprop ro.build.version.sdk",
    "pm-list": "pm list packages -d",
    "focused": "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'",
    "resolve-home": "cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME",
    "dumpsys-package": "dumpsys package com.heytap.market",
    "settings-get": "settings get secure default_input_method",
    "settings-list": "settings list global",
    "open-screen": "am start -a android.settings.LOCALE_SETTINGS",
    "start-component": "am start -n com.android.phone/.settings.RadioInfo",
    "open-play": "am start -a android.intent.action.VIEW -d 'market://details?id=com.google.android.inputmethod.latin'",
    "locale-get": "cmd locale get-app-locales com.whatsapp --user 0",
    "uimode-night": "cmd uimode night",
    "ime-list": "ime list -s",
    "global-config": "dumpsys activity | grep -m1 mGlobalConfig",
    "resolve-settings": "cmd package resolve-activity --brief -a android.settings.SETTINGS",
    "resolve-perms": "cmd package resolve-activity --brief -a android.intent.action.MANAGE_APP_PERMISSIONS",
    "crash-buffer": "logcat -b crash -d -t 200",
    "pidof": "pidof com.android.systemui",
    "connectivity-help": "cmd connectivity help",
    "role-get": "cmd role get-role-holders --user 0 android.app.role.SMS",
    "standby-get": "am get-standby-bucket com.whatsapp",
    "dumpsys-packages": "dumpsys package packages",
    "appops-get": "cmd appops get com.whatsapp",
    "proc-net": "su -c 'cat /proc/net/tcp /proc/net/tcp6 /proc/net/udp /proc/net/udp6'",
    "pm-path": "pm path moe.shizuku.privileged.api",
    "root-id": "su -c id",
    "root-flavor": "su -c 'magisk -V'",
    "root-start": "su -c 'am start -n com.android.settings/.Hidden'",
    "disable": "pm disable-user --user 0 com.heytap.market",
    "enable": "pm enable --user 0 com.heytap.market",
    "suspend": "pm suspend --user 0 com.heytap.market",
    "remove-user0": "pm uninstall -k --user 0 com.heytap.market",
    "install-existing": "cmd package install-existing com.heytap.market",
    "remove-user0-wipe": "pm uninstall --user 0 com.oplus.securitykeyboard",
    "force-stop": "am force-stop com.heytap.market",
    "perm": "pm revoke com.heytap.market android.permission.POST_NOTIFICATIONS",
    "appops-set": "cmd appops set com.heytap.market RUN_ANY_IN_BACKGROUND ignore",
    "locale-set": "cmd locale set-app-locales com.whatsapp --user 0 --locales en-US,ar-EG",
    "ime-toggle": f"ime enable {IME_GBOARD}",
    "ime-set": f"ime set {IME_GBOARD}",
    "dns-mode": "settings put global private_dns_mode hostname",
    "dns-host": "settings put global private_dns_specifier dns.adguard-dns.com",
    "dns-delete": "settings delete global private_dns_specifier",
    "verifier": "settings put global verifier_verify_adb_installs 0",
    "verifier-delete": "settings delete global package_verifier_enable",
    "fw-chain": "cmd connectivity set-chain3-enabled true",
    "fw-app": "cmd connectivity set-package-networking-enabled false com.heytap.market",
    "role-add": "cmd role add-role-holder --user 0 android.app.role.BROWSER org.mozilla.fenix",
    "deviceidle": "dumpsys deviceidle whitelist +com.whatsapp",
    "standby-set": "am set-standby-bucket com.whatsapp active",
    "uninstall-user-app": "pm uninstall org.mozilla.fenix",
    "shizuku-lib": "/data/app/~~abc==/moe.shizuku.privileged.api-xyz==/lib/arm64/libshizuku.so",
    "shizuku-sh": "sh /storage/emulated/0/Android/data/moe.shizuku.privileged.api/start.sh",
    "module-install": "su -c 'magisk --install-module /data/local/tmp/droidforge_debloat.zip'",
    "resetprop": "su -c 'resetprop ro.build.fingerprint google/husky/husky:15/AP4A/123:user/release-keys'",
    "adb-install": f"adb -s {SIM_SERIAL} install -r /home/u/.local/share/droidforge/cache/fenix.apk",
    "mdns": "adb mdns services",
    "pair": "adb pair 192.168.1.20:37123 123456",
    "pacman": "sudo pacman -S android-tools",
    "notify": "notify-send -a droidforge 'Done' 'Plan finished'",
    "self-update": "pipx upgrade droidforge",
    "scrcpy": f"scrcpy -s {SIM_SERIAL} --turn-screen-off --stay-awake",
    "logcat-stream": f"adb -s {SIM_SERIAL} logcat -v threadtime --pid=1234 '*:E'",
    "reboot": f"adb -s {SIM_SERIAL} reboot",
    "wait-for-device": f"adb -s {SIM_SERIAL} wait-for-device",
}

CONTEXT_FREE = {n for n in EXAMPLES if not next(r for r in guard.RULES if r.name == n).context}


def test_every_rule_has_an_example() -> None:
    assert set(EXAMPLES) == {r.name for r in guard.RULES}


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_example_matches_its_rule(name: str, sim) -> None:
    rule = next(r for r in guard.RULES if r.name == name)
    v = guard.check_command(EXAMPLES[name], sim, host=rule.host)
    assert v.rule == name and v.write == rule.write


def test_touches_are_derived() -> None:
    assert guard.touches_of("pm disable-user --user 0 com.x") == ["pkg:com.x:enabled"]
    assert guard.touches_of("cmd appops set com.x POST_NOTIFICATION ignore") == ["appop:com.x:POST_NOTIFICATION"]
    assert guard.touches_of("settings delete global private_dns_mode") == ["setting:global:private_dns_mode"]
    assert "setting:secure:default_input_method" in guard.touches_of(f"ime set {IME_GBOARD}")
    assert guard.touches_of(EXAMPLES["resetprop"]) == ["prop:ro.build.fingerprint"]


# ---------------------------------------------------------------- Forbidden
SUBST = {"<any>": "com.example.app", "<system package>": "com.android.settings", "<mode>": "yes", "...": "x"}


def _expand_alts(item: str) -> List[str]:
    toks = item.split(" ")
    for i, t in enumerate(toks):
        if "\\|" in t:
            return [" ".join(toks[:i] + [alt] + toks[i + 1:]) for alt in t.split("\\|")]
    return [item]


def forbidden_candidates(cell: str) -> List[str]:
    items = re.findall(r"`([^`]+)`", cell)
    is_prop_row = "resetprop" in cell and "props" in cell
    out: List[str] = []
    for it in items:
        for s in _expand_alts(it):
            for k, v in SUBST.items():
                s = s.replace(k, v)
            s = s.replace("*", "x").strip()
            if s in ("settings put", "resetprop", "setprop", "resetprop/setprop"):
                continue
            if " " not in s and not s.startswith("app_process") and "Configuration" not in s:
                if is_prop_row:
                    out += [f"setprop {s} 1", f"su -c 'resetprop {s} 1'"]
                else:
                    out += [f"settings put {ns} {s} 1" for ns in ("system", "secure", "global")]
                continue
            if s.startswith(("settings put", "setprop", "resetprop", "pm grant", "cmd overlay")):
                s += " x" if s.count(" ") < 3 else ""
            out.append(s)
    return out


EXTRA_FORBIDDEN = [
    f"settings put global {PERMISSION_MONITORING_KEY} 1",
    f"settings put global {PERMISSION_MONITORING_KEY} 0",
    "settings put global development_settings_enabled 0",
    "settings put global adb_enabled 1",
    "settings put secure oplus_permission_monitor_disabled 1",
    "setprop persist.sys.oplus.system_optimization 0",
    "settings reset global untrusted_defaults",
    'for p in com.whatsapp com.tencent.mm; do echo "@@$p"; cmd locale set-app-locales $p --user 0 --locales en-US 2>&1; done',
    "cmd uimode night no",
    "cmd uimode night yes",
    "pm clear com.android.settings",
    "pm clear com.whatsapp",
    "cmd overlay enable com.android.theme.icon.circle",
    "app_process / com.example.Main",
    "CLASSPATH=/data/local/tmp/x.dex app_process / X",
    "settings put system system_locales en-US",
    "settings put system font_scale 1.0",
    "settings put global window_animation_scale 1",
    "settings put secure ui_night_mode 2",
    "settings put system time_12_24 24",
    "settings put global auto_time 1",
    "settings put global auto_time_zone 1",
    "settings put system key_ux_icon_config 1",
    "settings put secure theme_customization_overlay_packages {}",
    "wm density 400",
    "wm size reset",
    "cmd display set-saturation-level 1",
    "su -c 'resetprop ro.sf.lcd_density 400'",
    "su -c 'resetprop persist.sys.locale en-US'",
    "pm grant com.example.morelocale android.permission.CHANGE_CONFIGURATION",
]


@pytest.mark.parametrize("cell", FORBIDDEN_ROWS, ids=lambda c: re.sub(r"\W+", "_", c)[:40])
def test_forbidden_rows_refused(cell: str, sim) -> None:
    cands = forbidden_candidates(cell)
    if "Instructing the user" in cell or "Blanket" in cell or "set-app-locales" in cell:
        pass  # no concrete command in the cell: covered by EXTRA_FORBIDDEN / P12 tests
    else:
        assert cands, f"no concrete commands extracted from Forbidden row: {cell}"
    for c in cands:
        with pytest.raises(GuardError):
            guard.check_command(c, sim)


@pytest.mark.parametrize("cmd", EXTRA_FORBIDDEN)
def test_forbidden_explicit(cmd: str, sim) -> None:
    with pytest.raises(GuardError) as e:
        guard.check_command(cmd, sim)
    assert e.value.forbidden, f"{cmd!r} refused, but not as Forbidden: {e.value.reason}"


def test_display_keys_forbidden_even_on_read_rule_namespaces(sim) -> None:
    for key in ("font_scale", "peak_refresh_rate", "material_color_value", "wallpaper_x", "icon_blacklist"):
        with pytest.raises(GuardError) as e:
            guard.check_command(f"settings put system {key} 1", sim)
        assert e.value.forbidden
        guard.check_read(f"settings get system {key}", sim)  # reading stays allowed (health baseline)


# ---------------------------------------------------------------- refusal of the unknown
@pytest.mark.parametrize("cmd", [
    "reboot", "rm -rf /sdcard", "pm disable-user --user 0 com.x; reboot", "pm disable-user --user 0 com.x && id",
    "pm disable-user --user 0 $(id)", "pm disable-user --user 0 `id`", "pm disable-user --user 0 com.x\nreboot",
    " pm disable-user --user 0 com.x", "pm disable-user com.x", "settings put global private_dns_specifier a;b",
    "settings put global some_other_key 1", "settings put secure private_dns_mode off",
    "am start -a android.intent.action.CALL -d tel:123", "am start -a android.settings.NOT_CURATED",
    "cmd role add-role-holder --user 0 android.app.role.HOME com.x", "ime enable x", "",
    "cmd appops set com.x CAMERA allow", "su -c 'resetprop ro.debuggable 1'", "setprop ro.x 1",
    "pm uninstall --user 0 com.heytap.market",
])
def test_unknown_or_malformed_refused(cmd: str, sim) -> None:
    with pytest.raises(GuardError):
        guard.check_command(cmd, sim)


def test_host_and_device_rules_do_not_mix(sim) -> None:
    with pytest.raises(GuardError):
        guard.check_command("sudo pacman -S android-tools", sim)             # not a device command
    with pytest.raises(GuardError):
        guard.check_command("pm disable-user --user 0 com.x", sim, host=True)
    with pytest.raises(GuardError):
        guard.check_command("sudo pacman -S firefox", sim, host=True)


# ---------------------------------------------------------------- P12
def test_p12_user_app_allowed(sim) -> None:
    guard.check_command("cmd locale set-app-locales com.whatsapp --user 0 --locales en-US", sim)
    guard.check_command("cmd locale set-app-locales com.whatsapp --user 0", sim)  # reset to follow system


@pytest.mark.parametrize("pkg", [
    "com.android.settings", "com.android.systemui", "com.android.permissioncontroller", "android",
    "com.oplus.uxdesign", "com.android.launcher", "com.sohu.inputmethod.sogouoem", "com.heytap.market",
    "com.android.systemui.auto_generated_characteristics_rro", "com.android.internal.display.cutout.emulation.corner",
    "com.not.installed",
])
def test_p12_refused(pkg: str, sim) -> None:
    with pytest.raises(GuardError) as e:
        guard.check_command(f"cmd locale set-app-locales {pkg} --user 0 --locales en-US", sim)
    assert "P12" in e.value.reason


def test_p12_current_ime_even_if_user_app(sim, phone) -> None:
    sim_cmd = "cmd locale set-app-locales com.google.android.inputmethod.latin --user 0 --locales en-US"
    with pytest.raises(GuardError):
        guard.check_command(sim_cmd, sim)  # substring 'inputmethod'
    phone.packages["com.whatsapp"].system = False
    phone.settings["secure"]["default_input_method"] = "com.whatsapp/.FakeIme"
    with pytest.raises(GuardError) as e:
        guard.check_command("cmd locale set-app-locales com.whatsapp --user 0 --locales en-US", sim)
    assert "keyboard" in e.value.reason


def test_p12_needs_device_context() -> None:
    with pytest.raises(GuardError):
        guard.check_command("cmd locale set-app-locales com.whatsapp --user 0 --locales en-US")


def test_uninstall_only_user_apps(sim) -> None:
    guard.check_command("pm uninstall org.mozilla.fenix", sim)
    with pytest.raises(GuardError):
        guard.check_command("pm uninstall com.heytap.market", sim)


# ---------------------------------------------------------------- read path / write path
def test_read_path_refuses_writes(sim, phone) -> None:
    before = list(phone.log)
    with pytest.raises(GuardError):
        sim.read("pm disable-user --user 0 com.heytap.market")
    assert phone.log == before and phone.packages["com.heytap.market"].enabled


def test_write_path_refuses_unlisted(sim, phone) -> None:
    before = list(phone.log)
    for cmd in ("settings put system font_scale 1.3", "cmd locale set-app-locales com.android.settings --user 0"):
        with pytest.raises(GuardError):
            sim.sh(cmd)
    assert phone.log == before


def test_batch_reads_allowed_writes_refused(sim) -> None:
    ok = 'for p in com.whatsapp com.tencent.mm; do echo "@@$p"; cmd locale get-app-locales $p --user 0 2>&1; done'
    guard.check_read(ok, sim)
    for bad in ('for p in com.x; do echo "@@$p"; pm disable-user --user 0 $p 2>&1; done',
                'for p in com.x; do echo "@@$p"; rm $p 2>&1; done',
                'for p in com.x;id; do echo "@@$p"; pidof $p 2>&1; done'):
        with pytest.raises(GuardError):
            guard.check_command(bad, sim)


# ---------------------------------------------------------------- step checks
@dataclass
class S:
    cmd: str
    undo: List[str] = field(default_factory=list)
    touches: List[str] = field(default_factory=list)
    verify: object = None
    fallbacks: list = field(default_factory=list)
    host: bool = False


def test_step_touch_declarations(sim) -> None:
    p = "com.heytap.market"
    guard.check(S(f"pm disable-user --user 0 {p}", [f"pm enable --user 0 {p}"], [f"pkg:{p}:enabled"]), sim)
    with pytest.raises(GuardError, match="declares no touches"):
        guard.check(S(f"pm disable-user --user 0 {p}", [f"pm enable --user 0 {p}"]), sim)
    with pytest.raises(GuardError, match="undeclared touches"):
        guard.check(S(f"pm disable-user --user 0 {p}", [], ["pkg:other:enabled"]), sim)
    with pytest.raises(GuardError, match="undo touches more"):
        guard.check(S(f"pm disable-user --user 0 {p}", [f"pm uninstall -k --user 0 {p}"], [f"pkg:{p}:enabled"]),
                    sim)
    with pytest.raises(GuardError):
        guard.check(S(f"pm disable-user --user 0 {p}", [], [f"pkg:{p}:enabled"],
                      verify=f"pm enable --user 0 {p}"), sim)  # verify must be a read
    guard.check(S(f"pm disable-user --user 0 {p}", [], [f"pkg:{p}:enabled"], verify="pm list packages -d"), sim)


def test_fallbacks_checked(sim) -> None:
    p = "com.heytap.market"
    bad_fb = S("settings put system font_scale 2", [], ["setting:system:font_scale"])
    with pytest.raises(GuardError) as e:
        guard.check(S(f"pm disable-user --user 0 {p}", [], [f"pkg:{p}:enabled"], fallbacks=[bad_fb]), sim)
    assert e.value.forbidden


def test_ime_ids(sim) -> None:
    guard.check_command(f"ime disable {IME_SOGOU}", sim)
