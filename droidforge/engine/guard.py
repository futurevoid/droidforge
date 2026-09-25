"""Command allowlist (P8), forbidden list (P9 / P9b / P0) and the P12 per-app-locale check.

Every command droidforge sends to a phone, or runs on the host, must fully match one `Rule` below. Each rule names
the docs/COMMANDS.md row(s) it implements (`tests/test_guard.py` parses COMMANDS.md and checks both directions)
and, for writes, the `touches` it implies (P10). FORBIDDEN patterns are checked first, on every path, and can
never be allowlisted.

Arguments are restricted to strict character classes and patterns are anchored (fullmatch), so a matching
command cannot carry shell metacharacters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from droidforge.data.packages import LANGUAGE_NEVER_SUBSTRINGS, is_ui_infra

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device


class GuardError(Exception):
    """A command was refused before anything was sent."""

    def __init__(self, cmd: str, reason: str, forbidden: bool = False) -> None:
        super().__init__(f"refused: {cmd!r}: {reason}")
        self.cmd = cmd
        self.reason = reason
        self.forbidden = forbidden


# ---------------------------------------------------------------------- argument classes
PKG = r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*"
PERM = r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+"
IME = r"[A-Za-z0-9_.]+/[A-Za-z0-9_.$]+"
COMP = r"[A-Za-z0-9_.]+/[A-Za-z0-9_.$]+"
KEY = r"[A-Za-z0-9_.\-]+"
NS = r"(?:system|secure|global)"
TAGS = r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*(?:,[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*)*"
LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
HOSTNAME = rf"{LABEL}(?:\.{LABEL})+"
SERIAL = r"[A-Za-z0-9._:\-]+"
IPPORT = r"[0-9]{1,3}(?:\.[0-9]{1,3}){3}:[0-9]{1,5}"
HOSTPATH = r"(?:'[^'\n\\]+'|[A-Za-z0-9_./~+\-]+)"
PROPNAME = r"[A-Za-z0-9_.\-]+"
PROPVAL = r"[A-Za-z0-9_.:/\-+=,]*"
ZIP = r"/data/local/tmp/[A-Za-z0-9_.\-]+\.zip"

APPOPS = "RUN_IN_BACKGROUND|RUN_ANY_IN_BACKGROUND|POST_NOTIFICATION|SYSTEM_ALERT_WINDOW|GET_USAGE_STATS"
APPOP_MODES = "allow|ignore|deny|default|foreground"
ROLES = r"android\.app\.role\.(?:BROWSER|SMS|DIALER)"
BUCKETS = "active|working_set|frequent|rare|restricted"

# `am start -a` is only allowed for these screens (COMMANDS.md Language / Tools "Curated intents" / Health).
OPENABLE_ACTIONS = (
    "android.settings.LOCALE_SETTINGS", "android.settings.REGIONAL_PREFERENCES_SETTINGS",
    "android.settings.DATE_SETTINGS", "android.settings.APP_LOCALE_SETTINGS",
    "android.settings.APPLICATION_DEVELOPMENT_SETTINGS", "android.settings.IGNORE_BATTERY_OPTIMIZATION_SETTINGS",
    "android.settings.MANAGE_DEFAULT_APPS_SETTINGS",
)
ACTIONS = "|".join(re.escape(a) for a in OPENABLE_ACTIONS)

# Settings droidforge may write (COMMANDS.md Privacy / DNS). Nothing else, ever (P9).
PRIVATE_DNS_MODES = "off|opportunistic|hostname"

# R-10.5: Play-Integrity / build-identity props only.
PI_PROPS = (r"ro\.build\.(?:fingerprint|id|tags|type|version\.security_patch)"
            r"|ro\.product\.(?:brand|device|manufacturer|model|name|first_api_level)"
            r"|ro\.(?:system|vendor|bootimage|odm|product|system_ext)\.build\.fingerprint")
RESETPROP = r"(?:resetprop|/data/adb/ksu/bin/resetprop|/data/adb/ap/bin/resetprop)"


# ---------------------------------------------------------------------- forbidden (P0, P9, P9b)
_SETW = r"\bsettings\s+(?:put|delete|reset)\s+\S+\s+"
_PROPW = r"\b(?:setprop|resetprop)\s+(?:-\S+\s+)*"
FORBIDDEN: Tuple[Tuple[str, str], ...] = (
    (r"\bapp_process\b|CLASSPATH=|\bdalvikvm\b|\.dex\b", "device-side DEX / app_process (incident 2026-09-25)"),
    (r"update(?:Persistent)?Configuration", "writes the persisted global configuration (P9)"),
    (_SETW + r"system_locales\b", "device language is set by the user in Settings (P9)"),
    (_PROPW + r"\S*locale\S*", "locale props are never written (P9)"),
    (r"CHANGE_CONFIGURATION", "CHANGE_CONFIGURATION grants are forbidden (P9)"),
    (r"\bfor\s+p\s+in\b.*set-app-locales", "no bulk per-app locale pass (P12)"),
    (r"\bcmd\s+overlay\s+(?:enable|enable-exclusive|disable|fabricate|set-priority)\b", "overlay writes (P9)"),
    (r"\bcmd\s+uimode\s+(?!night\s*$)\S|\bcmd\s+uimode\s+night\s+\S", "uimode writes (P9b)"),
    (r"\bpm\s+clear\b", "pm clear is not needed by any feature"),
    (r"\bsettings\s+reset\b", "blanket settings restores are forbidden - use Settings > Reset all settings"),
    (r"(?:" + _SETW + r"|" + _PROPW + r")\S*(?:permission_monitor|system_optimi|development_settings|adb_enabled"
     r"|placeholder_permission_monitoring)",
     "developer options / the permission-monitoring switch are never written (P0)"),
    (_SETW + r"\S*(?:font|color|colour|theme|icon|density|refresh|animation|animator|wallpaper|night_mode|dark_"
     r"|navigation_mode|accessibility_display|high_text_contrast|ux_icon|material)",
     "display / UI settings are never written (P9b)"),
    (_SETW + r"(?:auto_time|auto_time_zone|time_zone|date_format|time_12_24)\b",
     "time / date settings are never written"),
    (r"\bwm\s+(?:density|size|font-scale)\b", "display writes (P9b)"),
    (r"\bcmd\s+(?:display|wallpaper|theme|color_display)\b", "display / theme writes (P9b)"),
    (_PROPW + r"\S*(?:lcd_density|density|dpi|font|theme)", "display props are never written (P9b)"),
)


# ---------------------------------------------------------------------- rules
Row = Tuple[str, str]  # (COMMANDS.md section, Purpose cell)


@dataclass(frozen=True)
class Rule:
    name: str
    regex: str
    rows: Tuple[Row, ...]
    write: bool = False
    host: bool = False
    touches: Tuple[str, ...] = ()     # templates formatted with the regex's named groups
    context: str = ""                 # "p12" | "user_app" - needs device state

    def match(self, cmd: str) -> Optional["re.Match[str]"]:
        return re.fullmatch(self.regex, cmd)


DI, PK, LA, KB = "Device info / discovery", "Packages", "Language", "Keyboard"
PR, FW, AP, AU = "Privacy / DNS / ads / install", "Firewall, non-root", "Apps & defaults", "Audit"
TO, WS, RT, HO, HP = "Tools", "Wireless & Shizuku", "Root", "Host", "Health probes"

R = Rule
RULES: Tuple[Rule, ...] = (
    # ------------------------------------------------------------ reads
    R("getprop", rf"getprop(?: (?P<prop>{PROPNAME}))?",
      ((DI, "SDK / release / build"), (DI, "Brand / model"), (DI, "ROM family"), (LA, "Read device locales"),
       (HP, "Boot completed (R-11.9)"))),
    R("pm-list", r"pm list packages(?: -[dus3Ufe]+)*", ((DI, "Package lists"), (AU, "UID map"))),
    R("focused", r"dumpsys window \| grep -E 'mCurrentFocus\|mFocusedApp'", ((DI, "Focused app"),)),
    R("resolve-home", r"cmd package resolve-activity --brief -a android\.intent\.action\.MAIN "
                      r"-c android\.intent\.category\.HOME", ((DI, "Current launcher"), (HP, "IME / launcher"))),
    R("dumpsys-packages", r"dumpsys package packages", ((AU, "All packages with perms"),)),
    R("dumpsys-package", rf"dumpsys package (?P<p>{PKG})", ((DI, "Package details / runtime perms / signer"),)),
    R("settings-get", rf"settings get {NS} {KEY}",
      ((LA, "Read device locales"), (KB, "List / current"), (HP, "Night mode / font"), (HP, "IME / launcher"),
       (HP, "Permission-monitoring switch off"))),
    R("settings-list", rf"settings list {NS}", ((HP, "Settings snapshot"),)),
    R("open-screen", rf"am start -a (?:{ACTIONS})",
      ((LA, "Open language settings"), (LA, "Open regional preferences"), (LA, "Open Date & time"),
       (TO, "Curated intents"), (HP, "Open Developer options (for the user to turn the switch off)"))),
    R("start-component", rf"am start -n {COMP}",
      ((TO, "Start activity"), (TO, "Curated intents"), (KB, "Open Gboard settings (languages)"))),
    R("open-play", rf"am start -a android\.intent\.action\.VIEW -d 'market://details\?id={PKG}'",
      ((AP, "Open Play page"),)),
    R("locale-get", rf"cmd locale get-app-locales {PKG} --user 0", ((LA, "Per-app get"),)),
    R("uimode-night", r"cmd uimode night", ((LA, "Night mode (read only)"), (HP, "Night mode / font"))),
    R("ime-list", r"ime list -s", ((KB, "List / current"),)),
    R("global-config", r"dumpsys activity \| grep -m1 mGlobalConfig", ((HP, "Global configuration"),)),
    R("resolve-settings", r"cmd package resolve-activity --brief -a android\.settings\.SETTINGS",
      ((HP, "Settings home activity"),)),
    R("resolve-perms", r"cmd package resolve-activity --brief -a android\.intent\.action\.MANAGE_APP_PERMISSIONS",
      ((HP, "Permission UI"),)),
    R("crash-buffer", r"logcat -b crash -d -t [0-9]{1,4}", ((HP, "Crashes"),)),
    R("pidof", rf"pidof {PKG}", ((HP, "Process alive"), (TO, "logcat (host stream)"), (WS, "Shizuku status"))),
    R("connectivity-help", r"cmd connectivity help", ((FW, "Capability probe"),)),
    R("fw-get", rf"cmd connectivity get-package-networking-enabled {PKG}", ((FW, "Read app block state"),)),
    R("role-get", rf"cmd role get-role-holders --user 0 {ROLES}|cmd role help", ((AP, "Role holders"),)),
    R("standby-get", rf"am get-standby-bucket {PKG}", ((AP, "Keep-alive"), (AP, "Keep-alive state (read)"))),
    R("deviceidle-get", r"dumpsys deviceidle whitelist", ((AP, "Keep-alive state (read)"),)),
    R("open-app-info", rf"am start -a android\.settings\.APPLICATION_DETAILS_SETTINGS -d package:{PKG}",
      ((AP, "Open app info (ColorOS: Battery usage > allow background activity / auto launch)"),)),
    R("appops-get", rf"cmd appops get {PKG}", ((AU, "App-ops"),)),
    R("proc-net", r"(su -c ')?cat /proc/net/tcp /proc/net/tcp6 /proc/net/udp /proc/net/udp6(?(1)')",
      ((AU, "Sockets"),)),
    R("pm-path", rf"pm path {PKG}", ((WS, "Shizuku path"),)),
    R("root-id", r"su -c id", ((RT, "Root present"),)),
    R("root-flavor", r"(su -c ')?(?:magisk -V|ksud -V|apd -V|ls /data/adb/ksu|ls /data/adb/ap)(?(1)')",
      ((RT, "Flavor"),)),
    R("root-start", rf"su -c 'am start -n {COMP}'", ((TO, "Start activity"),)),

    # ------------------------------------------------------------ writes (device)
    R("disable", rf"pm disable-user --user 0 (?P<p>{PKG})", ((PK, "Disable"),), True, touches=("pkg:{p}:enabled",)),
    R("enable", rf"pm enable --user 0 (?P<p>{PKG})", ((PK, "Disable"),), True, touches=("pkg:{p}:enabled",)),
    R("suspend", rf"pm (?:un)?suspend --user 0 (?P<p>{PKG})", ((PK, "Suspend"),), True,
      touches=("pkg:{p}:suspended",)),
    R("remove-user0", rf"pm uninstall -k --user 0 (?P<p>{PKG})", ((PK, "Remove for user"),), True,
      touches=("pkg:{p}:installed",)),
    R("remove-user0-wipe", r"pm uninstall --user 0 (?P<p>com\.(?:oplus|coloros)\.securitykeyboard)",
      ((PK, "Remove for user, data wiped (ColorOS secure keyboard only)"),), True, touches=("pkg:{p}:installed",)),
    R("install-existing", rf"cmd package install-existing (?P<p>{PKG})", ((PK, "Remove for user"),), True,
      touches=("pkg:{p}:installed",)),
    R("force-stop", rf"am force-stop (?P<p>{PKG})", ((PK, "Force stop"),), True, touches=("proc:{p}",)),
    R("perm", rf"pm (?:grant|revoke) (?P<p>{PKG}) (?P<perm>{PERM})",
      ((PK, "Neuter perms"), (PR, "Notifications off"), (AP, "Power perms")), True, touches=("perm:{p}:{perm}",)),
    R("appops-set", rf"cmd appops set (?P<p>{PKG}) (?P<op>{APPOPS}) (?:{APPOP_MODES})",
      ((PK, "Neuter app-ops"), (PR, "Notifications off"), (AP, "Keep-alive"), (AP, "Power perms")), True,
      touches=("appop:{p}:{op}",)),
    R("locale-set", rf"cmd locale set-app-locales (?P<p>{PKG}) --user 0(?: --locales {TAGS})?",
      ((LA, "Per-app set"),), True, touches=("applocale:{p}",), context="p12"),
    R("ime-toggle", rf"ime (?:enable|disable) (?P<ime>{IME})", ((KB, "Enable/set Gboard"), (KB, "Disable IME")), True,
      touches=("ime:enabled:{ime}", "setting:secure:enabled_input_methods")),
    R("ime-set", rf"ime set (?P<ime>{IME})", ((KB, "Enable/set Gboard"),), True,
      touches=("ime:default", "setting:secure:default_input_method",
               "setting:secure:selected_input_method_subtype")),
    R("dns-mode", rf"settings put global private_dns_mode (?:{PRIVATE_DNS_MODES})", ((PR, "Private DNS"),), True,
      touches=("setting:global:private_dns_mode",)),
    R("dns-host", rf"settings put global private_dns_specifier {HOSTNAME}", ((PR, "Private DNS"),), True,
      touches=("setting:global:private_dns_specifier",)),
    R("dns-delete", r"settings delete global (?P<k>private_dns_mode|private_dns_specifier)", ((PR, "Private DNS"),),
      True, touches=("setting:global:{k}",)),
    R("verifier", r"settings put global (?P<k>verifier_verify_adb_installs|package_verifier_enable) [01]",
      ((PR, "ADB install verification"),), True, touches=("setting:global:{k}",)),
    R("verifier-delete", r"settings delete global (?P<k>verifier_verify_adb_installs|package_verifier_enable)",
      ((PR, "ADB install verification"),), True, touches=("setting:global:{k}",)),
    R("fw-chain", r"cmd connectivity set-chain3-enabled (?:true|false)", ((FW, "Enable chain"), (FW, "Disable chain")),
      True, touches=("fw:chain3",)),
    R("fw-app", rf"cmd connectivity set-package-networking-enabled (?:true|false) (?P<p>{PKG})",
      ((FW, "Block / unblock app"),), True, touches=("fw:{p}",)),
    R("role-add", rf"cmd role add-role-holder --user 0 (?P<role>{ROLES}) {PKG}", ((AP, "Role holders"),), True,
      touches=("role:{role}",)),
    R("deviceidle", rf"dumpsys deviceidle whitelist [+-](?P<p>{PKG})", ((AP, "Keep-alive"),), True,
      touches=("deviceidle:{p}",)),
    R("standby-set", rf"am set-standby-bucket (?P<p>{PKG}) (?:{BUCKETS})", ((AP, "Keep-alive"),), True,
      touches=("standby:{p}",)),
    R("uninstall-user-app", rf"pm uninstall (?P<p>{PKG})", ((AP, "Install APK(s) (host)"),), True,
      touches=("pkg:{p}:installed",), context="user_app"),
    R("shizuku-lib", r"/data/app/[A-Za-z0-9_.~=\-]+(?:/[A-Za-z0-9_.~=\-]+)?/lib/arm64/libshizuku\.so",
      ((WS, "Shizuku path"),), True, touches=("shizuku",)),
    R("shizuku-sh", r"sh /storage/emulated/0/Android/data/moe\.shizuku\.privileged\.api/start\.sh",
      ((WS, "Shizuku fallback"),), True, touches=("shizuku",)),
    R("module-install", rf"su -c '(?:magisk --install-module|ksud module install|apd module install) (?P<zip>{ZIP})'",
      ((RT, "Install module"),), True, touches=("root:module:{zip}",)),
    R("resetprop", rf"su -c '{RESETPROP} (?:(?P<name>{PI_PROPS}) {PROPVAL}|(?:-d|--delete) (?P<dname>{PI_PROPS}))'",
      ((RT, "Props"),), True, touches=("prop:{name}{dname}",)),

    # ------------------------------------------------------------ host
    R("adb-install", rf"adb -s {SERIAL} install(?:-multiple)? -r {HOSTPATH}(?: {HOSTPATH})*",
      ((AP, "Install APK(s) (host)"),), True, True),
    R("mdns", r"adb mdns (?:check|services)", ((WS, "mDNS discovery (host)"),), host=True),
    R("pair", rf"adb (?:pair {IPPORT} [A-Za-z0-9]{{6,16}}|connect {IPPORT})", ((WS, "Pair / connect (host)"),), True, True,
      touches=("host:adb-pairing",)),
    R("pacman", r"sudo pacman -S (?P<hp>android-tools|scrcpy)", ((HO, "adb / scrcpy install"),), True, True,
      touches=("host:pkg:{hp}",)),
    R("notify", r"notify-send -a droidforge '[^'\n]*' '[^'\n]*'", ((HO, "Notification"),), host=True),
    R("self-update", r"pipx upgrade droidforge|yay -S droidforge-git", ((HO, "Self-update"),), True, True,
      touches=("host:droidforge",)),
    R("scrcpy", rf"scrcpy -s {SERIAL}(?: --turn-screen-off| --stay-awake| --record {HOSTPATH})*",
      ((TO, "scrcpy (host)"),), host=True),
    R("reboot", rf"adb -s {SERIAL} reboot", ((HO, "Reboot check (R-11.9)"),), True, True,
      touches=("reboot", "setting:global:boot_count")),
    R("wait-for-device", rf"adb -s {SERIAL} wait-for-device", ((HO, "Reboot check (R-11.9)"),), host=True),
    R("logcat-stream", rf"adb -s {SERIAL} logcat -v threadtime(?: --pid=[0-9]+)?(?: '\*:[VDIWEF]')?",
      ((TO, "logcat (host stream)"),), host=True),
)

# COMMANDS.md rows that describe data, file contents or URLs rather than a command droidforge runs.
DOC_ONLY_ROWS: Dict[Row, str] = {
    (PK, "Recovery script (host)"): "lines written into the host recovery script; the user runs them, not droidforge",
    (PR, "DNS hostnames"): "hostname data for the Private DNS rule",
    (WS, "QR payload"): "text encoded in the pairing QR code",
    (WS, "Shizuku APK"): "HTTPS download URL; the APK is installed via adb-install",
    (AP, "Official APK sources (host HTTPS, only when the user asks)"): "HTTPS downloads on the host (urllib), "
                                                                        "then adb-install",
    (RT, "Module dir"): "module layout built on the host",
    (RT, "Hide system app"): "module contents built on the host",
    (RT, "Firewall"): "iptables lines inside the module's service.sh",
    (RT, "Hosts"): "hosts file shipped inside a module",
    (RT, "Play Integrity"): "release downloads; installed via module-install (target.txt write added in P7.6)",
}

BATCH_ROW: Row = (DI, "Batch form")
_BATCH_RE = re.compile(r'for p in (?P<pkgs>[A-Za-z0-9_. ]+); do echo "@@\$p"; (?P<body>.+?) 2>&1; done')


# ---------------------------------------------------------------------- verdicts
@dataclass(frozen=True)
class Verdict:
    cmd: str
    rule: str
    write: bool
    host: bool
    touches: Tuple[str, ...]


def _forbidden(cmd: str) -> None:
    for rx, why in FORBIDDEN:
        if re.search(rx, cmd, re.IGNORECASE):
            raise GuardError(cmd, f"forbidden: {why}", forbidden=True)


def check_forbidden(cmd: str) -> None:
    """Forbidden patterns only (the manual shell pane, R-9.4: outside the allowlist, never outside Forbidden)."""
    if not isinstance(cmd, str) or not cmd.strip() or any(c in cmd for c in "\r\x00"):
        raise GuardError(str(cmd), "malformed command")
    _forbidden(cmd)


def _find(cmd: str, host: bool) -> Tuple[Rule, "re.Match[str]"]:
    for rule in RULES:
        if rule.host != host:
            continue
        m = rule.match(cmd)
        if m:
            return rule, m
    raise GuardError(cmd, "not in the allowlist (docs/COMMANDS.md)")


def _touches(rule: Rule, m: "re.Match[str]") -> Tuple[str, ...]:
    groups = {k: (v or "") for k, v in m.groupdict().items()}
    return tuple(t.format(**groups) for t in rule.touches)


def check_command(cmd: str, device: Optional["Device"] = None, host: bool = False) -> Verdict:
    """Classify `cmd` or raise GuardError. Context rules (P12, user-app uninstall) need `device`."""
    if not isinstance(cmd, str) or not cmd or any(c in cmd for c in "\n\r\x00") or cmd != cmd.strip():
        raise GuardError(str(cmd), "malformed command")
    _forbidden(cmd)
    if not host and cmd.startswith("for p in "):
        return _check_batch(cmd, device)
    rule, m = _find(cmd, host)
    if rule.context:
        _check_context(rule, m, cmd, device)
    return Verdict(cmd, rule.name, rule.write, rule.host, _touches(rule, m))


def _check_batch(cmd: str, device: Optional["Device"]) -> Verdict:
    m = _BATCH_RE.fullmatch(cmd)
    if not m:
        raise GuardError(cmd, "malformed batch loop")
    pkgs = m.group("pkgs").split()
    if not pkgs or not all(re.fullmatch(PKG, p) for p in pkgs):
        raise GuardError(cmd, "batch loop package list")
    for p in pkgs:
        inner = m.group("body").replace("$p", p)
        v = check_command(inner, device)
        if v.write:
            raise GuardError(cmd, "batch loops are read-only (writes go one step at a time through the executor)")
    return Verdict(cmd, "batch", False, False, ())


def check_read(cmd: str, device: Optional["Device"] = None) -> Verdict:
    v = check_command(cmd, device)
    if v.write:
        raise GuardError(cmd, "state-changing command on the read path - it must go through the executor")
    return v


def classify(cmd: str, host: bool = False) -> str:
    """Rule name for bookkeeping (profile / history views). Never used to permit anything; "" if unknown."""
    try:
        _forbidden(cmd)
        return _find(cmd, host)[0].name
    except GuardError:
        return ""


def touches_of(cmd: str, device: Optional["Device"] = None, host: bool = False) -> List[str]:
    return list(check_command(cmd, device, host).touches)


# ---------------------------------------------------------------------- P12 / context
class Context:
    """Device facts the context rules need (cached per check)."""

    def __init__(self, device: "Device") -> None:
        self.device = device
        self._system: Optional[Set[str]] = None
        self._ime: Optional[str] = None
        self._home: Optional[str] = None

    @property
    def system(self) -> Set[str]:
        if self._system is None:
            self._system = self.device.packages("-s")
        return self._system

    @property
    def ime_pkg(self) -> str:
        if self._ime is None:
            v = self.device.out("settings get secure default_input_method")
            self._ime = v.split("/")[0] if "/" in v else ""
        return self._ime

    @property
    def home_pkg(self) -> str:
        if self._home is None:
            o = self.device.out("cmd package resolve-activity --brief -a android.intent.action.MAIN "
                                "-c android.intent.category.HOME")
            last = [x for x in o.splitlines() if "/" in x]
            self._home = last[-1].strip().split("/")[0] if last else ""
        return self._home


def language_refusal(pkg: str, ctx: Context) -> str:
    """Why `pkg` may not get a per-app locale (P12), or "" if it may."""
    if is_ui_infra(pkg):
        return "UI infrastructure (framework, overlays, Settings, permission UI) is never a language target"
    if any(s in pkg for s in LANGUAGE_NEVER_SUBSTRINGS):
        return "system UI, keyboards and launchers are never language targets"
    if pkg in ctx.system:
        return "system apps follow the device language - set it in Settings > Language"
    if pkg == ctx.ime_pkg:
        return "the current keyboard is never a language target"
    if pkg == ctx.home_pkg:
        return "the current launcher is never a language target"
    if pkg not in ctx.device.packages("-3"):
        return "not an installed user app"
    return ""


def _check_context(rule: Rule, m: "re.Match[str]", cmd: str, device: Optional["Device"]) -> None:
    if device is None:
        raise GuardError(cmd, "needs device context to check (P12 / user app)")
    ctx = Context(device)
    pkg = m.group("p")
    if rule.context == "p12":
        why = language_refusal(pkg, ctx)
        if why:
            raise GuardError(cmd, f"P12: {pkg}: {why}")
    elif rule.context == "user_app" and pkg in ctx.system:
        raise GuardError(cmd, f"{pkg} is a system package - full uninstall is only for user apps")


# ---------------------------------------------------------------------- steps
def check(step: object, device: Optional["Device"] = None) -> List[Verdict]:
    """Check a Step: its command, verify (read), undo and fallbacks. Writes must declare every touch they imply.

    Duck-typed on engine.plan.Step (cmd, undo, verify, fallbacks, host, touches)."""
    verdicts = []
    cmd: str = getattr(step, "cmd")
    host: bool = getattr(step, "host", False)
    declared = set(getattr(step, "touches", []) or [])
    v = check_command(cmd, device, host)
    verdicts.append(v)
    if v.write:
        if not declared:
            raise GuardError(cmd, "write step declares no touches (P10)")
        missing = set(v.touches) - declared
        if missing:
            raise GuardError(cmd, f"undeclared touches: {', '.join(sorted(missing))} (P10)")
    verify = getattr(step, "verify", None)
    if verify:
        verdicts.append(check_read(verify, device))
    for u in getattr(step, "undo", []) or []:
        uv = check_command(u, device)
        extra = set(uv.touches) - declared
        if extra:
            raise GuardError(u, f"undo touches more than its step declares: {', '.join(sorted(extra))}")
        verdicts.append(uv)
    for fb in list(getattr(step, "fallbacks", []) or []) + list(getattr(step, "extra", []) or []):
        verdicts += check(fb, device)
    return verdicts


def check_all(steps: Iterable[object], device: Optional["Device"] = None) -> None:
    for s in steps:
        check(s, device)


def rows_covered() -> Set[Row]:
    rows: Set[Row] = {BATCH_ROW} | set(DOC_ONLY_ROWS)
    for r in RULES:
        rows.update(r.rows)
    return rows


def commands_md_sections() -> Sequence[str]:
    return (DI, PK, LA, KB, PR, FW, AP, AU, TO, WS, RT, HO, HP)
