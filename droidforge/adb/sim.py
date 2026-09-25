"""Simulated ColorOS phone (`--simulate`, every test).

`FakePhone` holds the device state; `SimBackend.run()` parses the subset of shell commands documented in
docs/COMMANDS.md and answers with output shaped like the real tools. **Anything else returns exit 127 with
`sim: unsupported: <cmd>`**, so a command that is not documented (and simulated) fails loudly in tests.

Fault injection:
- `side_effects={cmd_regex: fn(phone)}` - after a matching command runs, `fn` mutates the phone (an undeclared
  side change, as a ROM might do).
- `break_ui()` - the 2026-09-25 incident: Settings and the permission UI resolve to stock AOSP activities,
  `mMaterialColor` drops to 0, and the "Disable permission monitoring" switch is on.
"""

from __future__ import annotations

import copy
import re
import shlex
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

from droidforge.adb.backend import EXIT_NOT_FOUND, RunResult
from droidforge.data.device_keys import PERMISSION_MONITORING_KEY, PERMISSION_MONITORING_NS

SIM_SERIAL = "SIMNEO8CN01"
SHIZUKU = "moe.shizuku.privileged.api"


COLOROS_SETTINGS = "com.android.settings/com.oplus.settings.feature.homepage.OplusSettingsHomepageActivity"
AOSP_SETTINGS = "com.android.settings/com.android.settings.homepage.SettingsHomepageActivity"
COLOROS_PERMS = ("com.android.permissioncontroller/"
                 "com.oplusos.permissioncontroller.permission.ui.ManagePermissionsActivityTrampoline")
AOSP_PERMS = "com.android.permissioncontroller/com.android.permissioncontroller.permission.ui.ManagePermissionsActivity"
COLOROS_LAUNCHER = "com.android.launcher/com.android.launcher.Launcher"

ACTION_SETTINGS = "android.settings.SETTINGS"
ACTION_PERMS = "android.intent.action.MANAGE_APP_PERMISSIONS"
HOME = "HOME"

BUCKETS = {"active": 10, "working_set": 20, "frequent": 30, "rare": 40, "restricted": 45}

CONNECTIVITY_HELP = """Connectivity service commands:
  help
    Print this help text.
  airplane-mode [enable|disable]
  set-chain3-enabled [true|false]
    Enable or disable FIREWALL_CHAIN_OEM_DENY_3 for debugging.
  get-package-networking-enabled [package name]
  set-package-networking-enabled [true|false] [package name]
    Set the deny bit in FIREWALL_CHAIN_OEM_DENY_3 to package."""

SIGNERS = {"platform": "a40da80a59d170caa950cf15c18c454d47a39b26989d8b640ecd745ba71bf5dc",
           "oem": "c0105e2a9f0c7a1e8b3d4f5a6b7c8d9e0f1a2b3c4d5e6f708192a3b4c5d6e7f8",
           "google": "f0fd6c5b410f25cb25c3b53346c8972fae30f8ee7411df910480ad6b2d60db83",
           "third": "3c9f1ab2d7e04c55b8a61f2e9d0c7b36a5e84f1029d3c6b7a8e9f0d1c2b3a495"}

DEFAULT_ACTIONS = {
    "android.settings.LOCALE_SETTINGS", "android.settings.REGIONAL_PREFERENCES_SETTINGS",
    "android.settings.DATE_SETTINGS", "android.settings.APP_LOCALE_SETTINGS",
    "android.settings.APPLICATION_DEVELOPMENT_SETTINGS", "android.settings.IGNORE_BATTERY_OPTIMIZATION_SETTINGS",
    "android.settings.MANAGE_DEFAULT_APPS_SETTINGS", ACTION_SETTINGS,
}


@dataclass
class Pkg:
    name: str
    system: bool = True
    present: bool = True      # APK on the device (pm list packages -u)
    user0: bool = True        # installed for user 0 (pm uninstall -k --user 0 clears this)
    enabled: bool = True
    suspended: bool = False
    uid: int = 10000
    perms: Dict[str, bool] = field(default_factory=dict)      # runtime permission -> granted
    appops: Dict[str, str] = field(default_factory=dict)      # op -> mode (missing = default)
    signer: str = "oem"
    locales: str = ""                                         # per-app locales, "" = follow system
    activities: List[str] = field(default_factory=list)
    refuse: Set[str] = field(default_factory=set)             # ops the ROM refuses: disable / suspend / uninstall
    running: bool = False

    @property
    def path(self) -> str:
        short = self.name.rsplit(".", 1)[-1]
        return f"/system/priv-app/{short}/{short}.apk" if self.system else f"/data/app/~~sim/{self.name}-1/base.apk"


@dataclass
class GlobalConfig:
    locales: List[str] = field(default_factory=lambda: ["zh_CN_#Hans", "en_US"])
    font_scale: str = "1.0"
    density: int = 480
    night: bool = True
    oem: Dict[str, str] = field(default_factory=lambda: {
        "mUxIconConfig": "3553824075780669440", "mMaterialColor": "17179869184",
        "mFontVariationSettings": "226", "mFlipFont": "0", "mIconPackName": "",
        "mDarkModeBackgroundMaxL": "0.0", "mDarkModeDialogBgMaxL": "27.0", "mDarkModeForegroundMinL": "100.0"})

    def line(self) -> str:
        night = " night" if self.night else ""
        oem = ", ".join(f"{k}={v}" for k, v in self.oem.items())
        return (f"  mGlobalConfig={{{self.font_scale} 460mcc1mnc [{','.join(self.locales)}] ldltr sw392dp w392dp "
                f"h835dp {self.density}dpi nrml long hdr widecg port{night} finger -keyb/v/h -nav/h "
                f"winConfig={{ mBounds=Rect(0, 0 - 1080, 2400) mAppBounds=Rect(0, 0 - 1080, 2400) "
                f"mWindowingMode=fullscreen mActivityType=undefined}} s.217 fontWeightAdjustment=0 "
                f"mOplusExtraConfiguration={{mUserId=0, mAccessibleChanged=-1, {oem}}}}}")


def _tag_to_config(tag: str) -> str:
    """en-US -> en_US, zh-Hans-CN -> zh_CN_#Hans (as in the config line)."""
    parts = tag.split("-")
    if len(parts) == 3:
        return f"{parts[0]}_{parts[2]}_#{parts[1]}"
    return "_".join(parts)


def _config_to_tag(loc: str) -> str:
    m = re.fullmatch(r"(\w+?)_(\w+?)_#(\w+)", loc)
    if m:
        return f"{m.group(1)}-{m.group(3)}-{m.group(2)}"
    return loc.replace("_", "-")


class FakePhone:
    def __init__(self) -> None:
        self.serial = SIM_SERIAL
        self.packages: Dict[str, Pkg] = {}
        self.settings: Dict[str, Dict[str, str]] = {"system": {}, "secure": {}, "global": {}}
        self.props: Dict[str, str] = {}
        self.imes: Dict[str, bool] = {}               # IME id -> enabled
        self.roles: Dict[str, List[str]] = {}
        self.firewall_supported = True
        self.firewall_chain3 = False
        self.firewall_blocked: Set[str] = set()
        self.config = GlobalConfig()
        self.resolve: Dict[str, str] = {}            # action (or HOME) -> component
        self.actions: Set[str] = set(DEFAULT_ACTIONS)
        self.crashes: List[str] = []
        self.root: Optional[str] = None               # None | magisk | ksu | apatch
        self.shizuku_running = False
        self.proc_net: List[str] = []
        self.focused = "com.android.launcher"
        self.deviceidle: Set[str] = set()             # user battery-optimisation whitelist
        self.standby: Dict[str, int] = {}             # app standby buckets (default 30 frequent)
        self.started: List[str] = []                  # `am start` log
        self.logcat: List[str] = [
            "09-25 12:00:00.100  1000  1000 I ActivityManager: Start proc com.android.launcher",
            "09-25 12:00:01.200  4321  4321 D WhatsApp: connecting",
            "09-25 12:00:01.300  4321  4330 W WhatsApp: socket timeout, retrying",
            "09-25 12:00:02.000  4321  4321 E WhatsApp: killed by OplusAthenaAmManager",
            "09-25 12:00:02.500  1000  1100 I OplusHansManager: freeze com.whatsapp",
        ]
        self.side_effects: Dict[str, Callable[["FakePhone"], None]] = {}
        self.log: List[str] = []                      # every shell command received
        self.host_log: List[str] = []                 # host commands (simulated, never executed)
        self.uid_next = 10100
        self.boots = 0
        self.boot_polls_left = 0
        self.on_boot: List[Callable[["FakePhone"], None]] = []   # fault injection "at boot"

    # ------------------------------------------------------------------ seed helpers
    def add(self, name: str, system: bool = True, signer: Optional[str] = None, uid: Optional[int] = None,
            perms: Optional[Dict[str, bool]] = None, running: bool = False, **kw: object) -> Pkg:
        if uid is None:
            uid = self.uid_next
            self.uid_next += 1
        p = Pkg(name=name, system=system, uid=uid, signer=signer or ("oem" if system else "third"),
                perms=dict(perms or {}), running=running, **kw)  # type: ignore[arg-type]
        self.packages[name] = p
        return p

    @property
    def permission_monitoring_disabled(self) -> bool:
        return self.settings[PERMISSION_MONITORING_NS].get(PERMISSION_MONITORING_KEY) == "1"

    @permission_monitoring_disabled.setter
    def permission_monitoring_disabled(self, on: bool) -> None:
        self.settings[PERMISSION_MONITORING_NS][PERMISSION_MONITORING_KEY] = "1" if on else "0"

    def set_device_locales(self, tags: List[str]) -> None:
        """What the user does in Settings > Language (droidforge never does this)."""
        self.props["persist.sys.locale"] = tags[0]
        self.settings["system"]["system_locales"] = ",".join(tags)
        self.config.locales = [_tag_to_config(t) for t in tags]

    def break_ui(self) -> None:
        """Reproduce the 2026-09-25 incident."""
        self.resolve[ACTION_SETTINGS] = AOSP_SETTINGS
        self.resolve[ACTION_PERMS] = AOSP_PERMS
        self.config.oem["mMaterialColor"] = "0"
        self.permission_monitoring_disabled = True

    def sync_imes(self) -> None:
        """Keep `enabled_input_methods` in line with `imes` (as Android does)."""
        self.settings["secure"]["enabled_input_methods"] = ":".join(i for i, on in self.imes.items() if on)

    def set_default_ime(self, ime: str) -> None:
        """What the user does in Settings > Keyboard (test setup)."""
        self.imes[ime] = True
        self.sync_imes()
        self.settings["secure"]["default_input_method"] = ime

    def reboot(self) -> None:
        """Instant reboot: boot hooks run, the crash buffer and running apps reset, boot_count increments, and
        `sys.boot_completed` reads empty for a few polls (the executor must wait for it)."""
        self.boots += 1
        self.shizuku_running = False
        self.crashes = []
        self.firewall_chain3 = False          # platform behaviour: chain-3 rules are cleared at reboot
        self.firewall_blocked = set()
        for p in self.packages.values():
            p.running = p.name in ("android", "com.android.systemui", "com.android.settings", "com.android.launcher")
        g = self.settings["global"]
        g["boot_count"] = str(int(g.get("boot_count", "0")) + 1)
        self.boot_polls_left = 2
        for hook in list(self.on_boot):
            hook(self)

    def unbreak_ui(self) -> None:
        """The reverse of break_ui() (tests: a side effect that the plan's undo also reverses)."""
        self.resolve[ACTION_SETTINGS] = COLOROS_SETTINGS
        self.resolve[ACTION_PERMS] = COLOROS_PERMS
        self.config.oem["mMaterialColor"] = self.settings["system"].get("material_color_value", "17179869184")
        self.permission_monitoring_disabled = False

    def crash(self, pkg: str) -> None:
        n = len(self.crashes)
        self.crashes += [f"09-25 12:{n:02d}:00.000  4242  4242 E AndroidRuntime: FATAL EXCEPTION: main",
                         f"09-25 12:{n:02d}:00.000  4242  4242 E AndroidRuntime: Process: {pkg}, PID: 4242"]

    def clone(self) -> "FakePhone":
        side, self.side_effects = self.side_effects, {}
        try:
            c = copy.deepcopy(self)
        finally:
            self.side_effects = side
        c.side_effects = dict(side)
        return c

    def state(self) -> dict:
        """Comparable device state (for 'restored exactly' assertions)."""
        return {
            "packages": {n: (p.present, p.user0, p.enabled, p.suspended, tuple(sorted(p.perms.items())),
                             tuple(sorted(p.appops.items())), p.locales) for n, p in self.packages.items()
                         if p.present},
            "settings": copy.deepcopy(self.settings), "props": dict(self.props), "imes": dict(self.imes),
            "roles": copy.deepcopy(self.roles), "fw": (self.firewall_chain3, sorted(self.firewall_blocked)),
            "keepalive": (sorted(self.deviceidle), sorted((k, v) for k, v in self.standby.items() if v != 30)),
            "config": self.config.line(), "resolve": dict(self.resolve),
        }

    def pkg_ok(self, name: str) -> bool:
        p = self.packages.get(name)
        return bool(p and p.present and p.user0 and p.enabled and not p.suspended)


# ====================================================================== seed
UI_INFRA_SEED = [
    "android", "oplus", "com.android.systemui", "com.android.settings", "com.android.settings.intelligence",
    "com.android.permissioncontroller", "com.oplus.securitypermission", "com.oplus.uxdesign", "com.oplus.uiengine",
    "com.oplus.systemui.plugins", "com.oplus.framework.overlay", "com.android.internal.display.cutout.emulation.corner",
    "com.android.internal.systemui.navbar.gestural", "android.frameworkres.overlay.oplus",
    "com.android.systemui.auto_generated_characteristics_rro", "com.oplus.wallpapers", "com.heytap.colorfulengine",
    "com.oplus.aod", "com.android.theme.icon.circle",
]
CORE_SEED = [
    "com.android.phone", "com.android.contacts", "com.android.incallui", "com.android.mms",
    "com.android.providers.telephony", "com.android.server.telecom", "com.android.ims.rcsservice",
    "com.android.shell", "com.android.packageinstaller", "com.android.networkstack", "com.android.webview",
    "com.android.launcher", "com.android.vending", "com.google.android.gms", "com.google.android.gsf",
    "com.android.documentsui", "com.android.providers.media",
]
OEM_SEED = [
    # telemetry (PACKAGES.md)
    "com.oplus.statistics.rom", "com.nearme.deamon", "com.oplus.crashbox", "com.oplus.logkit",
    "com.coloros.logkit.plugin.upload", "com.oplus.onetrace", "com.oplus.locationproxy", "com.heytap.openid",
    "com.oplus.powermonitor", "com.oplus.ocloud", "com.coloros.feedback", "com.coloros.remoteguardservice",
    "com.oplus.sauhelper", "com.coloros.regservice", "com.coloros.prome.service", "com.oplus.cosa",
    # ads / promos
    "com.heytap.pictorial", "com.coloros.pictorial", "com.heytap.mcs", "com.heytap.market",
    "com.heytap.themestore", "com.nearme.gamecenter", "com.heytap.browser", "com.opos.cs",
    "com.heytap.quicksearchbox", "com.nearme.instant.platform", "com.coloros.assistantscreen",
    # install hijack
    "com.oplus.appdetail",
    # keep-list
    "com.coloros.gamespace", "com.oplus.games", "com.oplus.stdid", "com.coloros.smartsidebar",
    # OTA path
    "com.oplus.ota", "com.oplus.sau", "com.oplus.romupdate", "com.oplus.cota", "com.oplus.appplatform",
    # secure keyboard, safecenter, apps
    "com.oplus.securitykeyboard", "com.oplus.onet", "com.oplus.safecenter", "com.coloros.gallery3d",
    "com.coloros.filemanager", "com.coloros.calendar", "com.coloros.note", "com.oplus.camera",
    "com.coloros.weather.service", "com.coloros.phonemanager",
    # Chinese IMEs
    "com.sohu.inputmethod.sogouoem", "com.baidu.input_oppo",
]
USER_SEED = [
    "com.google.android.inputmethod.latin", "com.whatsapp", "org.telegram.messenger", "com.tencent.mm",
    "com.eg.android.AlipayGphone", "com.google.android.apps.photos", "org.mozilla.fenix",
]

IME_SOGOU = "com.sohu.inputmethod.sogouoem/.SogouIME"
IME_BAIDU = "com.baidu.input_oppo/.ImeService"
IME_SECURE = "com.oplus.securitykeyboard/.SecurityKeyboardService"
IME_GBOARD = "com.google.android.inputmethod.latin/com.android.inputmethod.latin.LatinIME"

NOTIF = "android.permission.POST_NOTIFICATIONS"


def neo8_cn() -> FakePhone:
    """Default seed: realme Neo 8, China ROM, Android 16 - package set from docs/PACKAGES.md."""
    ph = FakePhone()
    ph.props.update({
        "ro.build.version.sdk": "36", "ro.build.version.release": "16", "ro.product.brand": "realme",
        "ro.product.model": "RMX8899", "ro.build.display.id": "RMX8899_16.0.0.600(CN01)",
        "ro.build.fingerprint": "realme/RMX8899/RE60B2L1:16/BP2A.250605.015/V.2a4f1b-1c2d3e:user/release-keys",
        "ro.build.version.oplusrom": "V16.0.0", "ro.product.locale": "zh-CN", "sys.boot_completed": "1",
    })
    ph.settings["global"]["boot_count"] = "7"
    ph.add("android", uid=1000, signer="platform", running=True)
    for n in UI_INFRA_SEED[1:]:
        ph.add(n, signer="platform" if n.startswith("com.android") else "oem",
               running=n in ("com.android.systemui", "com.android.settings"))
    for n in CORE_SEED:
        ph.add(n, signer="google" if n.startswith(("com.google", "com.android.vending")) else "platform",
               running=n == "com.android.launcher")
    for n in OEM_SEED:
        ph.add(n, perms={NOTIF: True} if n.startswith(("com.heytap", "com.nearme", "com.coloros.gamespace")) else {})
    for n in USER_SEED:
        ph.add(n, system=False, signer="google" if n.startswith("com.google") else "third",
               perms={NOTIF: True, "android.permission.CAMERA": n in ("com.whatsapp", "com.tencent.mm")})
    ph.packages["com.android.systemui"].uid = 10050
    ph.packages["com.oplus.sauhelper"].refuse = {"disable"}              # legacy mock: protected, suspend works
    ph.packages["com.oplus.safecenter"].refuse = {"disable", "suspend"}  # legacy mock: suspend refused too
    ph.packages["com.coloros.prome.service"].refuse = {"disable", "suspend"}  # not locked, ROM refuses both
    ph.packages["com.tencent.mm"].locales = "zh-CN"
    ph.imes = {IME_SOGOU: True, IME_BAIDU: True, IME_SECURE: True, IME_GBOARD: False}
    ph.settings["secure"].update({
        "default_input_method": IME_SOGOU, "enabled_input_methods": f"{IME_SOGOU}:{IME_BAIDU}:{IME_SECURE}",
        "android_id": "5f1c0ffee0000001", "user_setup_complete": "1",
    })
    ph.settings["system"].update({"font_scale": "1.0", "screen_brightness": "102", "time_12_24": "24",
                                  "material_color_value": "17179869184"})
    ph.settings["global"].update({"adb_enabled": "1", "development_settings_enabled": "1",
                                  "private_dns_mode": "off", "package_verifier_enable": "1",
                                  "verifier_verify_adb_installs": "1"})
    ph.permission_monitoring_disabled = False
    ph.set_device_locales(["zh-Hans-CN", "en-US"])
    ph.resolve.update({ACTION_SETTINGS: COLOROS_SETTINGS, ACTION_PERMS: COLOROS_PERMS, HOME: COLOROS_LAUNCHER})
    ph.roles = {"android.app.role.BROWSER": ["com.heytap.browser"], "android.app.role.SMS": ["com.android.mms"],
                "android.app.role.DIALER": ["com.android.contacts"], "android.app.role.HOME": ["com.android.launcher"]}
    return ph


# ====================================================================== shell parsing
def split_top(cmd: str, sep: str) -> List[str]:
    """Split on `sep` outside quotes."""
    parts, cur, q, i = [], "", None, 0
    while i < len(cmd):
        ch = cmd[i]
        if q:
            cur += ch
            if ch == q:
                q = None
        elif ch in "'\"":
            q = ch
            cur += ch
        elif cmd.startswith(sep, i):
            parts.append(cur)
            cur = ""
            i += len(sep)
            continue
        else:
            cur += ch
        i += 1
    parts.append(cur)
    return [p.strip() for p in parts]


def _grep(text: str, args: List[str]) -> Tuple[str, int]:
    max_n, ext, inv, icase, pat = None, False, False, False, None
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("-m"):
            if a == "-m":
                i += 1
                max_n = int(args[i])
            else:
                max_n = int(a[2:])
        elif a.startswith("-") and len(a) > 1 and pat is None:
            ext |= "E" in a
            inv |= "v" in a
            icase |= "i" in a
        else:
            pat = a
        i += 1
    if pat is None:
        raise ValueError("grep: no pattern")
    rx = pat if ext else re.sub(r"([|+?(){}])", r"\\\1", pat)
    flags = re.IGNORECASE if icase else 0
    hits = []
    for line in text.splitlines():
        if bool(re.search(rx, line, flags)) != inv:
            hits.append(line)
            if max_n is not None and len(hits) >= max_n:
                break
    return "\n".join(hits), 0 if hits else 1


class Unsupported(Exception):
    pass


R = RunResult


def _ok(out: str = "") -> RunResult:
    return R(0, out, "", 1)


def _fail(err: str, code: int = 255, out: str = "") -> RunResult:
    return R(code, out, err, 1)


class SimBackend:
    def __init__(self, phone: Optional[FakePhone] = None) -> None:
        self.phone = phone or neo8_cn()

    # ------------------------------------------------------------------ adb entry
    def run(self, args: List[str], timeout: float = 30) -> RunResult:
        args = list(args)
        if args[:1] == ["-s"]:
            if args[1] != self.phone.serial:
                return _fail(f"adb: device '{args[1]}' not found", 1)
            args = args[2:]
        if not args:
            return _fail("adb: no command", 1)
        if args[0] == "shell":
            return self.shell(" ".join(args[1:]))
        if args[0] == "devices":
            return _ok(f"List of devices attached\n{self.phone.serial}\tdevice")
        if args[0] == "get-state":
            return _ok("device")
        if args == ["reboot"]:
            self.phone.reboot()
            return _ok()
        if args == ["wait-for-device"]:
            return _ok()
        if args[0] in ("install", "install-multiple"):
            return self._install([a for a in args[1:] if not a.startswith("-")])
        return self._unsupported("adb " + " ".join(args))

    def run_host(self, args: List[str], timeout: float = 600) -> RunResult:
        """Host commands in --simulate mode are recorded, never executed on this machine."""
        self.phone.host_log.append(" ".join(args))
        if args[:1] == ["adb"]:
            return self.run(args[1:], timeout)
        return _ok(f"sim: host command recorded: {' '.join(args)}")

    def _install(self, paths: List[str]) -> RunResult:
        from pathlib import Path

        from droidforge.adb.apk import ApkError, package_name
        try:
            pkg = package_name(Path(paths[0]))
        except (ApkError, OSError, IndexError):
            return _fail("adb: failed to install: Failure [INSTALL_PARSE_FAILED_NOT_APK]", 1)
        existing = self.phone.packages.get(pkg)
        if existing is not None and existing.present:
            existing.user0 = existing.enabled = True
        else:
            self.phone.add(pkg, system=False, perms={"android.permission.POST_NOTIFICATIONS": False})
        return _ok("Performing Streamed Install\nSuccess")

    def stream_host(self, args: List[str]) -> List[str]:
        """`adb -s S logcat -v threadtime [--pid=N] ['*:E']` -> the simulated log buffer."""
        self.phone.host_log.append(" ".join(args))
        pid = next((a.split("=", 1)[1] for a in args if a.startswith("--pid=")), None)
        return [ln for ln in self.phone.logcat if pid is None or f" {pid} " in ln]

    def _unsupported(self, cmd: str) -> RunResult:
        return R(EXIT_NOT_FOUND, "", f"sim: unsupported: {cmd}", 0)

    # ------------------------------------------------------------------ shell
    def shell(self, cmd: str) -> RunResult:
        cmd = cmd.strip()
        self.phone.log.append(cmd)
        try:
            r = self._shell(cmd)
        except Unsupported:
            return self._unsupported(cmd)
        except (ValueError, IndexError) as ex:
            return self._unsupported(f"{cmd} ({ex})")
        for rx, fn in list(self.phone.side_effects.items()):
            if re.search(rx, cmd):
                fn(self.phone)
        return r

    def _shell(self, cmd: str) -> RunResult:
        if re.fullmatch(r"/data/app/\S+/lib/arm64/libshizuku\.so", cmd) or \
                cmd == "sh /storage/emulated/0/Android/data/moe.shizuku.privileged.api/start.sh":
            if not self.phone.pkg_ok(SHIZUKU):
                return R(127, "", f"/system/bin/sh: {cmd.split()[-1]}: not found", 1)
            self.phone.shizuku_running = True
            return _ok("info: starter begin\ninfo: shizuku_server started")
        m = re.fullmatch(r"sh -c (.+)", cmd, re.S)
        if m:
            return self._shell(shlex.split(m.group(1))[0])
        if cmd.startswith("for p in "):
            return self._for(cmd)
        pipe = split_top(cmd, "|")
        if len(pipe) > 1:
            r = self._shell(pipe[0])
            out, code = r.out, r.exit
            for stage in pipe[1:]:
                toks = shlex.split(stage)
                if toks[:1] != ["grep"]:
                    raise Unsupported(stage)
                out, code = _grep(out, toks[1:])
            return R(code, out, r.err, 1)
        t = shlex.split(cmd)
        if not t:
            raise Unsupported(cmd)
        h = getattr(self, f"_c_{t[0].replace('-', '_')}", None)
        if h is None:
            raise Unsupported(cmd)
        return h(t)

    def _for(self, cmd: str) -> RunResult:
        m = re.fullmatch(r"for p in (.*?); do (.*); done", cmd, re.S)
        if not m:
            raise Unsupported(cmd)
        out: List[str] = []
        for p in m.group(1).split():
            for part in split_top(m.group(2), ";"):
                if not part:
                    continue
                merge = part.endswith("2>&1")
                part = part[:-4].strip() if merge else part
                part = part.replace('"$p"', p).replace("$p", p)
                r = self._shell(part)
                if r.exit == EXIT_NOT_FOUND and r.err.startswith("sim: unsupported"):
                    raise Unsupported(part)
                if r.out:
                    out.append(r.out)
                if merge and r.err:
                    out.append(r.err)
        return _ok("\n".join(out))

    # ------------------------------------------------------------------ simple commands
    def _c_su(self, t: List[str]) -> RunResult:
        if self.phone.root is None:
            return R(127, "", "/system/bin/sh: su: inaccessible or not found", 1)
        raise Unsupported(" ".join(t))  # root commands are simulated in Phase 7

    def _c_echo(self, t: List[str]) -> RunResult:
        return _ok(" ".join(t[1:]))

    def _c_getprop(self, t: List[str]) -> RunResult:
        if t[1:] == ["sys.boot_completed"] and self.phone.boot_polls_left > 0:
            self.phone.boot_polls_left -= 1
            return _ok("")
        if len(t) == 1:
            return _ok("\n".join(f"[{k}]: [{v}]" for k, v in sorted(self.phone.props.items())))
        return _ok(self.phone.props.get(t[1], ""))

    def _c_pidof(self, t: List[str]) -> RunResult:
        if t[1:] == ["shizuku_server"]:
            return _ok("31337") if self.phone.shizuku_running else R(1, "", "", 1)
        p = self.phone.packages.get(t[1])
        if p and p.running and self.phone.pkg_ok(p.name):
            return _ok(str(1000 + p.uid % 9000))
        return R(1, "", "", 1)

    def _c_logcat(self, t: List[str]) -> RunResult:
        if t[1:3] == ["-b", "crash"] and "-d" in t:
            n = int(t[t.index("-t") + 1]) if "-t" in t else len(self.phone.crashes)
            return _ok("\n".join(self.phone.crashes[-n:]))
        raise Unsupported(" ".join(t))

    # ------------------------------------------------------------------ settings
    def _c_settings(self, t: List[str]) -> RunResult:
        verb, ns = t[1], t[2]
        if ns not in self.phone.settings:
            return _fail(f"Invalid namespace '{ns}'", 1)
        table = self.phone.settings[ns]
        if verb == "get":
            return _ok(table.get(t[3], "null"))
        if verb == "list":
            return _ok("\n".join(f"{k}={v}" for k, v in sorted(table.items())))
        if verb == "put":
            table[t[3]] = t[4] if len(t) > 4 else ""
            return _ok()
        if verb == "delete":
            existed = table.pop(t[3], None) is not None
            return _ok(f"Deleted {1 if existed else 0} rows")
        raise Unsupported(" ".join(t))

    # ------------------------------------------------------------------ pm
    def _pkg(self, name: str) -> Optional[Pkg]:
        p = self.phone.packages.get(name)
        return p if p and p.present else None

    def _c_pm(self, t: List[str]) -> RunResult:
        verb = t[1]
        if verb == "list" and t[2] == "packages":
            return self._pm_list(t[3:])
        if verb == "path":
            p = self._pkg(t[2])
            return _ok(f"package:{p.path}") if p and p.user0 else R(1, "", "", 1)
        rest = [a for a in t[2:]]
        if rest[:2] == ["--user", "0"]:
            rest = rest[2:]
        if verb in ("disable-user", "enable", "suspend", "unsuspend"):
            return self._pm_state(verb, rest[0])
        if verb == "uninstall":
            return self._pm_uninstall(rest)
        if verb in ("grant", "revoke"):
            return self._pm_perm(verb, rest[0], rest[1])
        raise Unsupported(" ".join(t))

    def _pm_list(self, flags: List[str]) -> RunResult:
        letters = "".join(f[1:] for f in flags if f.startswith("-"))
        rows = []
        for n in sorted(self.phone.packages):
            p = self.phone.packages[n]
            if not p.present or (not p.user0 and "u" not in letters):
                continue
            if "d" in letters and p.enabled:
                continue
            if "e" in letters and not p.enabled:
                continue
            if "s" in letters and not p.system:
                continue
            if "3" in letters and p.system:
                continue
            body = f"{p.path}={n}" if "f" in letters else n
            rows.append(f"package:{body}" + (f" uid:{p.uid}" if "U" in letters else ""))
        return _ok("\n".join(rows))

    def _pm_state(self, verb: str, name: str) -> RunResult:
        p = self._pkg(name)
        if p is None:
            return _fail(f"Error: java.lang.IllegalArgumentException: Unknown package: {name}")
        if verb == "disable-user":
            if "disable" in p.refuse:
                return _fail(f"Error: java.lang.SecurityException: Cannot disable a protected package: {name}")
            p.enabled, p.running = False, False
            return _ok(f"Package {name} new state: disabled-user")
        if verb == "enable":
            p.enabled = True
            return _ok(f"Package {name} new state: enabled")
        if verb == "suspend":
            if "suspend" in p.refuse:
                return _fail(f"Error: java.lang.SecurityException: Cannot suspend package: {name}")
            p.suspended = True
            return _ok(f"Package {name} new suspended state: true")
        p.suspended = False
        return _ok(f"Package {name} new suspended state: false")

    def _pm_uninstall(self, rest: List[str]) -> RunResult:
        keep = "-k" in rest
        rest = [a for a in rest if a != "-k"]
        user = False
        if rest[:2] == ["--user", "0"]:
            rest, user = rest[2:], True
        p = self._pkg(rest[0])
        if p is None or not p.user0:
            return _fail("Failure [DELETE_FAILED_INTERNAL_ERROR]", 1, "")
        if "uninstall" in p.refuse:
            return _fail("Failure [DELETE_FAILED_USER_RESTRICTED]", 1)
        if p.system or user:
            p.user0 = False
            p.running = False
            if not keep:
                p.perms = {k: False for k in p.perms}
        else:
            p.present = False
        return _ok("Success")

    def _pm_perm(self, verb: str, name: str, perm: str) -> RunResult:
        p = self._pkg(name)
        if p is None:
            return _fail(f"Exception occurred while executing '{verb}':\njava.lang.IllegalArgumentException: "
                         f"Unknown package: {name}")
        if perm not in p.perms:
            return _fail(f"Exception occurred while executing '{verb}':\njava.lang.SecurityException: Package "
                         f"{name} has not requested permission {perm}")
        p.perms[perm] = verb == "grant"
        return _ok()

    # ------------------------------------------------------------------ cmd
    def _c_cmd(self, t: List[str]) -> RunResult:
        svc = t[1]
        if svc == "package":
            if t[2] == "resolve-activity":
                return self._resolve(t[3:])
            if t[2] == "install-existing":
                p = self._pkg(t[-1])
                if p is None:
                    return _fail(f"Error: java.lang.IllegalArgumentException: Unknown package: {t[-1]}", 1)
                p.user0 = True
                return _ok(f"Package {p.name} installed for user: 0")
        if svc == "locale":
            return self._locale(t[2:])
        if svc == "role" and len(t) >= 6 and t[3:5] == ["--user", "0"]:
            role = t[5]
            if t[2] == "get-role-holders":
                return _ok("\n".join(self.phone.roles.get(role, [])))
            if t[2] == "add-role-holder" and len(t) == 7:
                if not self.phone.pkg_ok(t[6]):
                    return _fail(f"java.lang.IllegalArgumentException: Unknown package: {t[6]}", 255)
                self.phone.roles[role] = [t[6]]   # BROWSER / SMS / DIALER are exclusive
                return _ok()
        if svc == "appops":
            return self._appops(t[2:])
        if svc == "connectivity":
            return self._connectivity(t[2:])
        if svc == "uimode" and t[2:] == ["night"]:
            return _ok(f"Night mode: {'yes' if self.phone.config.night else 'no'}")
        raise Unsupported(" ".join(t))

    def _connectivity(self, a: List[str]) -> RunResult:
        ph = self.phone
        if a == ["help"]:
            return _ok(CONNECTIVITY_HELP if ph.firewall_supported else "Connectivity service commands:\n"
                       "  help\n  airplane-mode [enable|disable]")
        if not ph.firewall_supported:
            return _fail(f"Unknown command: {a[0]}", 255)
        if a[0] == "set-chain3-enabled" and a[1:] in (["true"], ["false"]):
            ph.firewall_chain3 = a[1] == "true"
            return _ok()
        if a[0] in ("set-package-networking-enabled", "get-package-networking-enabled"):
            pkg = a[-1]
            if self._pkg(pkg) is None:
                return _fail(f"java.lang.IllegalArgumentException: No package {pkg}", 255)
            if a[0].startswith("get"):
                return _ok("false" if pkg in ph.firewall_blocked else "true")
            if a[1] == "false":
                ph.firewall_blocked.add(pkg)
            else:
                ph.firewall_blocked.discard(pkg)
            return _ok()
        raise Unsupported(" ".join(a))

    def _resolve(self, a: List[str]) -> RunResult:
        action = a[a.index("-a") + 1] if "-a" in a else ""
        cat = a[a.index("-c") + 1] if "-c" in a else ""
        key = HOME if cat == "android.intent.category.HOME" else action
        comp = self.phone.resolve.get(key)
        if not comp or not self.phone.pkg_ok(comp.split("/")[0]):
            return _ok("No activity found")
        return _ok(f"priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true\n{comp}")

    def _locale(self, a: List[str]) -> RunResult:
        verb, name = a[0], a[1]
        p = self._pkg(name)
        if p is None or not p.user0:
            return _fail(f"Unknown package name: {name}", 255)
        if verb == "get-app-locales":
            return _ok(f"Locales for {name} for user 0 are [{p.locales}]")
        if verb == "set-app-locales":
            p.locales = a[a.index("--locales") + 1] if "--locales" in a and a.index("--locales") + 1 < len(a) else ""
            return _ok()
        raise Unsupported(" ".join(a))

    def _appops(self, a: List[str]) -> RunResult:
        verb, name = a[0], a[1]
        p = self._pkg(name)
        if p is None:
            return _fail(f"Error: Unknown package: {name}", 255)
        if verb == "get":
            ops = sorted(p.appops.items())
            return _ok("\n".join(f"{k}: {v}" for k, v in ops) if ops else "No operations.")
        if verb == "set":
            op, mode = a[2], a[3]
            if mode == "default":
                p.appops.pop(op, None)
            else:
                p.appops[op] = mode
            return _ok()
        raise Unsupported(" ".join(a))

    # ------------------------------------------------------------------ ime
    def _c_ime(self, t: List[str]) -> RunResult:
        ph = self.phone
        verb = t[1]
        live = {i: on for i, on in ph.imes.items() if ph.pkg_ok(i.split("/")[0])}
        if verb == "list" and "-s" in t:
            return _ok("\n".join(i for i, on in live.items() if on))
        ime = t[2]
        if ime not in live:
            return _fail(f"Unknown input method {ime} cannot be enabled for user #0", 255)
        if verb == "enable":
            was = ph.imes[ime]
            ph.imes[ime] = True
            self._sync_imes()
            return _ok(f"Input method {ime}: {'already enabled' if was else 'now enabled'}")
        if verb == "disable":
            was = ph.imes[ime]
            ph.imes[ime] = False
            if ph.settings["secure"].get("default_input_method") == ime:
                nxt = next((i for i, on in live.items() if on and i != ime), "")
                ph.settings["secure"]["default_input_method"] = nxt
            self._sync_imes()
            return _ok(f"Input method {ime}: {'now disabled' if was else 'already disabled'}")
        if verb == "set":
            if not ph.imes[ime]:
                return _fail(f"Input method {ime} is not enabled for user #0", 255)
            ph.settings["secure"]["default_input_method"] = ime
            return _ok(f"Input method {ime} selected for user #0")
        raise Unsupported(" ".join(t))

    def _sync_imes(self) -> None:
        self.phone.sync_imes()

    # ------------------------------------------------------------------ am
    def _c_am(self, t: List[str]) -> RunResult:
        verb = t[1]
        if verb == "force-stop":
            p = self._pkg(t[2])
            if p:
                p.running = False
            return _ok()
        if verb in ("get-standby-bucket", "set-standby-bucket"):
            p = self._pkg(t[2])
            if p is None:
                return _fail(f"Unknown package: {t[2]}", 255)
            if verb.startswith("get"):
                return _ok(str(self.phone.standby.get(p.name, 30)))
            self.phone.standby[p.name] = BUCKETS[t[3]]
            return _ok()
        if verb == "start":
            a = t[2:]
            if a[:2] == ["-a", "android.settings.APPLICATION_DETAILS_SETTINGS"] and "-d" in a:
                self.phone.started.append(f"app-info {a[a.index('-d') + 1]}")
                return _ok("Starting: Intent { act=android.settings.APPLICATION_DETAILS_SETTINGS }")
            if "-n" in a:
                comp = a[a.index("-n") + 1]
                if not self.phone.pkg_ok(comp.split("/")[0]):
                    return _fail(f"Error: Activity class {{{comp}}} does not exist.", 1)
                self.phone.started.append(comp)
                return _ok(f"Starting: Intent {{ cmp={comp} }}")
            action = a[a.index("-a") + 1]
            data = a[a.index("-d") + 1] if "-d" in a else ""
            if data.startswith("market://"):
                if not self.phone.pkg_ok("com.android.vending"):
                    return _fail(f"Error: Activity not started, unable to resolve Intent {{ act={action} "
                                 f"dat={data} }}", 1)
            elif action not in self.phone.actions:
                return _fail(f"Error: Activity not started, unable to resolve Intent {{ act={action} }}", 1)
            self.phone.started.append(action + (f" {data}" if data else ""))
            return _ok(f"Starting: Intent {{ act={action}{f' dat={data}' if data else ''} }}")
        raise Unsupported(" ".join(t))

    # ------------------------------------------------------------------ dumpsys
    def _c_dumpsys(self, t: List[str]) -> RunResult:
        what = t[1]
        if what == "activity" and len(t) == 2:
            return _ok("ACTIVITY MANAGER SETTINGS (dumpsys activity settings) activity_manager_constants:\n"
                       "  max_cached_processes=32\n"
                       "ACTIVITY MANAGER CONFIGURATION (dumpsys activity configuration)\n"
                       f"{self.phone.config.line()}\n  mConfigWillChange: false")
        if what == "window" and len(t) == 2:
            f = self.phone.focused
            act = COLOROS_LAUNCHER if f == "com.android.launcher" else f"{f}/{f}.MainActivity"
            return _ok("WINDOW MANAGER POLICY STATE (dumpsys window policy)\n"
                       f"  mCurrentFocus=Window{{8e1f2a u0 {act}}}\n"
                       f"  mFocusedApp=ActivityRecord{{3b7c19 u0 {act} t42}}\n  mInTouchMode=true")
        if what == "deviceidle" and t[2:3] == ["whitelist"]:
            if len(t) == 3:
                return _ok("\n".join([f"system,{p},{self.phone.packages[p].uid}" for p in ("com.google.android.gms",)
                                      if p in self.phone.packages] +
                                     [f"user,{p},{self.phone.packages[p].uid}" for p in sorted(self.phone.deviceidle)]))
            arg = t[3]
            pkg = arg[1:]
            if self._pkg(pkg) is None:
                return _fail(f"Package not found: {pkg}", 255)
            if arg.startswith("+"):
                self.phone.deviceidle.add(pkg)
                return _ok(f"Added: {pkg}")
            self.phone.deviceidle.discard(pkg)
            return _ok(f"Removed: {pkg}")
        if what == "package" and len(t) == 3:
            return self._dumpsys_package(t[2])
        raise Unsupported(" ".join(t))

    def _dumpsys_package(self, name: str) -> RunResult:
        p = self._pkg(name)
        if p is None:
            return _ok(f"Unable to find package: {name}")
        perms = "\n".join(f"        {k}: granted={'true' if v else 'false'}, flags=[ USER_SENSITIVE_WHEN_GRANTED ]"
                          for k, v in sorted(p.perms.items()))
        flags = "[ SYSTEM HAS_CODE ALLOW_CLEAR_USER_DATA ]" if p.system else "[ HAS_CODE ALLOW_CLEAR_USER_DATA ]"
        sig = SIGNERS.get(p.signer, p.signer)[:8]
        return _ok(
            "Packages:\n"
            f"  Package [{name}] (5a1b2c3):\n"
            f"    userId={p.uid}\n"
            f"    pkg=Package{{7d8e9f0 {name}}}\n"
            f"    codePath={p.path.rsplit('/', 1)[0]}\n"
            f"    versionCode=16000 minSdk=30 targetSdk=36\n"
            f"    flags={flags}\n"
            f"    signatures=PackageSignatures{{1f2e3d4 version:3, signatures:[{sig}], past signatures:[]}}\n"
            f"    signingCertificateDigest (sha256)={SIGNERS.get(p.signer, p.signer)}\n"
            f"    User 0: ceDataInode=12345 installed={'true' if p.user0 else 'false'} hidden=false "
            f"suspended={'true' if p.suspended else 'false'} stopped=false notLaunched=false "
            f"enabled={0 if p.enabled else 3} instant=false virtual=false\n"
            "      gids=[3003]\n"
            "      runtime permissions:\n"
            f"{perms}\n"
            "      disabledComponents:\n"
            "      enabledComponents:"
        )


def sim_device(phone: Optional[FakePhone] = None, **kw: object):  # -> Device (import cycle avoided at module load)
    from droidforge.adb.device import Device
    ph = phone or neo8_cn()
    return Device(SimBackend(ph), ph.serial, **kw)  # type: ignore[arg-type]
