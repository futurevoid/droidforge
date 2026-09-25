#!/usr/bin/env python3
"""
cnrom_fix.py - English-ify & debloat a China-ROM realme / OPPO / OnePlus (ColorOS family) over ADB. No root.

Requirements : Python 3.8+, adb (Android platform-tools) in PATH or next to this script,
               Developer options > USB debugging ON, this PC authorized on the phone.
Run          : python cnrom_fix.py            normal
               python cnrom_fix.py --dry-run  preview commands, change nothing
Verbosity    : --ultra (default, level 3)  every adb command, full output, exit code, timing, internal calls,
                                           cache hits, decisions, state diffs, timestamps
               --verbose (level 2)         same but internal calls hidden, output capped at 15 lines
               --quiet   (level 1)         results only
               Menu 'v' cycles the level and remembers it. cnrom_debug.log always gets the full record.
Quick start  : menu 'e' = guided English setup: YOU set the language in Settings > Language (the phone's own path),
               then the keyboard is switched to Gboard.

RETIRED (2026-09-25): replaced by droidforge. This version is kept only because it is safe:
  - removed: the built-in device-language setter (DEX/app_process), writes to system_locales, MoreLocale,
    "Force English everywhere", per-app language on system apps, the "repair" option.
  - NEVER turn on Developer options > "Disable permission monitoring" / "Disable system optimization": it broke
    the ColorOS Settings and permission screens on a realme Neo 8 until Settings > Reset all settings
    (which turns it off). Nothing in this script needs it.
  - per-app language: your own apps only, max 5 at a time.
  - health check: before/after every menu action it compares Settings/permission screens and the display
    configuration; if anything changed it tells you and offers to undo.

Debloat safety ratings come from Universal Android Debloater Next Generation (UAD-NG):
  https://github.com/Universal-Debloater-Alliance/universal-android-debloater-next-generation
  Their package list (GPL-3.0) is downloaded on first use and cached as uad_lists.json next to this script.

Everything is reversible:  disable -> enable,  remove (user 0) -> restore (install-existing).
Changes are recorded in cnrom_state.json so you can re-apply them after an OTA update.
A package snapshot is saved to ./backups/ every session.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / "cnrom_state.json"
BACKUP_DIR = HERE / "backups"
LOG_FILE = HERE / "cnrom_actions.log"
UAD_FILE = HERE / "uad_lists.json"
UAD_URL = ("https://raw.githubusercontent.com/Universal-Debloater-Alliance/"
           "universal-android-debloater-next-generation/main/resources/assets/uad_lists.json")

ADB = None
SERIAL = None
DRY_RUN = "--dry-run" in sys.argv
# Verbosity: 1 = results only, 2 = + every adb command, exit code, timing, first lines of output, decisions,
#            3 = ULTRA (default) = + full untruncated output, internal plumbing calls, cache hits, timestamps.
# Everything is always written in full to cnrom_debug.log regardless of the level on screen.
VERBOSE = 1 if "--quiet" in sys.argv else 2 if "--verbose" in sys.argv else 3
_VERBOSE_FROM_FLAG = any(f in sys.argv for f in ("--quiet", "--verbose", "--ultra"))
DEBUG_LOG = Path(__file__).resolve().parent / "cnrom_debug.log"
_PLIST_CACHE = {}
_DEVICE_LABEL = None
LAST_LIST = []
UAD = None  # {package: {list, description, dependencies, neededBy, removal, ...}}

# Substrings that identify China-ROM / vendor packages when scanning.
CHINA_PATTERNS = ("heytap", "nearme", "coloros", "oplus", "realme", "oppo", "finshell",
                  "baidu", "sogou", "iflytek", "tencent", "alipay", "qihoo", "kuaishou", "ximalaya")

# Always blocked, whatever UAD-NG says: breaking these means bootloop, no calls or no Play Services.
HARD_PROTECTED = ("systemui", "com.android.phone", "telephony", ".ims", "com.android.settings",
                  "permissioncontroller", "packageinstaller", "com.android.shell", "keyguard",
                  "com.google.android.gms", "com.google.android.gsf", "com.android.vending",
                  "webview", "networkstack", "framework")

# Extra caution for packages UAD-NG doesn't know about.
FALLBACK_PROTECTED = ("launcher", "securitypermission", "safecenter", "phonemanager", "providers",
                      "com.qualcomm", "com.qti", "wifi", "bluetooth", "nfc", "carrier", "simsettings",
                      "cellbroadcast", "documentsui", "extservices", "appplatform", "battery", "thermal",
                      "biometric", "fingerprint", "faceunlock", "camera", "dialer", "incallui", "contacts",
                      "setupwizard", "mediaprovider", "externalstorage")

TIERS = ("Recommended", "Advanced", "Expert", "Unsafe")
UAD_LISTS = ("Oem", "Google", "Carrier", "Misc", "Aosp")

GBOARD = "com.google.android.inputmethod.latin"
GBOARD_IME = f"{GBOARD}/com.android.inputmethod.latin.LatinIME"
# Chinese input methods to switch off once Gboard is the default.
CHINA_IME = ("sogou", "sohu", "baidu", "iflytek", "qqpinyin", "tencent", "pinyin", "oplus.inputmethod",
             "coloros.inputmethod", "heytap")


# ---------------------------------------------------------------- output helpers
os.system("")  # enables ANSI colors on Windows 10+


class C:
    R, G, Y, M, CY = "\033[31m", "\033[32m", "\033[33m", "\033[35m", "\033[36m"
    DIM, BOLD, X = "\033[2m", "\033[1m", "\033[0m"


TIER_COL = {"Recommended": C.G, "Advanced": C.Y, "Expert": C.M, "Unsafe": C.R}


def ok(m): print(f"{C.G}[+] {m}{C.X}")
def warn(m): print(f"{C.Y}[!] {m}{C.X}")
def err(m): print(f"{C.R}[x] {m}{C.X}")
def info(m): print(f"{C.CY}[*] {m}{C.X}")


_EOF = False


def ask(prompt, default=""):
    global _EOF
    if _EOF:
        return default
    try:
        v = input(f"{C.BOLD}{prompt}{C.X} ").strip()
    except EOFError:  # input closed (piped / Ctrl+D) - wind down instead of looping forever
        _EOF = True
        print()
        return default
    except KeyboardInterrupt:
        print()
        return default
    return v or default


def confirm(prompt, strong=False):
    if strong:
        return ask(f"{prompt} Type YES to continue:") == "YES"
    return ask(f"{prompt} [y/N]:").lower() in ("y", "yes")


def pause():
    ask(f"{C.DIM}Enter to continue...{C.X}")


def log(line):
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {line}\n")
    dbg(f"ACTION {line}")


def dbg(text):
    """Full, untruncated debug record - always written, whatever the on-screen verbosity."""
    try:
        with DEBUG_LOG.open("a", encoding="utf-8") as f:
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            for line in str(text).splitlines() or [""]:
                f.write(f"{stamp}  {line}\n")
    except OSError:
        pass


def ts():
    return f"{datetime.now():%H:%M:%S} " if VERBOSE >= 3 else ""


def trace(msg, lvl=2):
    """Narrate a decision or internal step."""
    dbg(f"TRACE {msg}")
    if VERBOSE >= lvl:
        print(f"{C.DIM}  {ts()}. {msg}{C.X}")


def invalidate_cache(why=""):
    if _PLIST_CACHE:
        _PLIST_CACHE.clear()
        trace(f"package-list cache cleared{f' ({why})' if why else ''}", 3)


# ---------------------------------------------------------------- adb plumbing
def find_adb():
    for cand in (shutil.which("adb"), HERE / "adb", HERE / "adb.exe",
                 HERE / "platform-tools" / "adb", HERE / "platform-tools" / "adb.exe"):
        if cand and Path(cand).exists():
            return str(cand)
    return None


def adb(*args, timeout=30, plumbing=False):
    """Every adb call goes through here, so this is where 'see everything' happens.
    plumbing=True marks routine internal calls (state checks) that are shown only at ULTRA."""
    cmd = [ADB] + (["-s", SERIAL] if SERIAL else []) + [str(a) for a in args]
    show = VERBOSE >= (3 if plumbing else 2)
    pretty = "adb " + ("-s " + SERIAL + " " if SERIAL else "") + " ".join(
        a if (" " not in a and a) else repr(a) for a in cmd[1 + (2 if SERIAL else 0):])
    dbg(f"RUN   {pretty}")
    if show:
        print(f"{C.CY}  {ts()}$ {pretty}{C.X}")
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        code, o, e = p.returncode, p.stdout.strip(), p.stderr.strip()
    except subprocess.TimeoutExpired:
        code, o, e = 124, "", f"timeout after {timeout}s"
    except OSError as ex:
        code, o, e = 127, "", f"could not start adb: {ex}"
    ms = int((time.monotonic() - t0) * 1000)
    olines, elines = o.splitlines(), e.splitlines()
    dbg(f"EXIT  {code}  ({ms} ms, {len(olines)} stdout / {len(elines)} stderr lines)")
    for l in olines:
        dbg(f"  out | {l}")
    for l in elines:
        dbg(f"  err | {l}")
    if show:
        col = C.G if code == 0 else C.R
        print(f"{C.DIM}    -> {col}exit {code}{C.X}{C.DIM} | {ms} ms | {len(olines)} line(s) out"
              f"{f', {len(elines)} err' if elines else ''}{C.X}")
        limit = None if VERBOSE >= 3 else 15
        for l in olines[:limit]:
            print(f"{C.DIM}    | {l}{C.X}")
        if limit is not None and len(olines) > limit:
            print(f"{C.DIM}    | ... {len(olines) - limit} more line(s) - full text in cnrom_debug.log "
                  f"(or 'v' for ULTRA){C.X}")
        for l in elines[:limit]:
            print(f"{C.Y}    ! {l}{C.X}")
    return code, o, e


def sh(cmd, timeout=30, plumbing=False):
    return adb("shell", cmd, timeout=timeout, plumbing=plumbing)


def out(cmd, plumbing=False):
    return sh(cmd, plumbing=plumbing)[1]


def act(cmd, label):
    """Run a state-changing shell command. Respects dry-run, logs everything."""
    trace(f"about to: {label}")
    if DRY_RUN:
        info(f"(dry-run) adb shell {cmd}")
        return True
    code, o, e = sh(cmd)
    invalidate_cache("device changed")
    text = f"{o} {e}".strip()
    success = code == 0 and not re.search(r"(?i)\b(error|exception|failure|not installed|unknown)\b", text)
    trace(f"result judged {'SUCCESS' if success else 'FAILURE'} (exit {code}"
          f"{', error text in output' if code == 0 and not success else ''})")
    log(f"{'OK ' if success else 'ERR'} {cmd} :: {text}")
    if success:
        ok(label)
    else:
        err(f"{label} -> {text or 'failed'}")
    return success


def select_device():
    global SERIAL
    while True:
        _, o, _ = adb("devices")
        rows = [l.split("\t") for l in o.splitlines()[1:] if "\t" in l]
        ready = [s for s, st in rows if st == "device"]
        unauth = [s for s, st in rows if st == "unauthorized"]
        if len(ready) == 1:
            SERIAL = ready[0]
            return
        if len(ready) > 1:
            for i, s in enumerate(ready, 1):
                print(f"  {i}) {s}")
            c = ask("Pick device #:", "1")
            if c.isdigit() and 1 <= int(c) <= len(ready):
                SERIAL = ready[int(c) - 1]
                return
            continue
        if unauth:
            warn("Phone shows as unauthorized - accept the 'Allow USB debugging' prompt on screen.")
        else:
            warn("No device. Plug in USB and enable Developer options > USB debugging.")
        if ask("Enter to retry, q to quit:").lower() == "q":
            sys.exit(0)


def ensure_connected():
    code, o, _ = adb("get-state", plumbing=True)
    if code != 0 or o != "device":
        warn("Phone disconnected.")
        select_device()


# ---------------------------------------------------------------- UAD-NG list
def update_uad():
    global UAD
    info("Downloading UAD-NG package list...")
    try:
        req = urllib.request.Request(UAD_URL, headers={"User-Agent": "cnrom_fix"})
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
        data = json.loads(raw)
        if not isinstance(data, dict) or len(data) < 1000:
            raise ValueError("unexpected file format")
    except Exception as e:  # network, TLS, JSON - all mean "keep the old copy"
        err(f"Download failed: {e}")
        if UAD_FILE.exists():
            info("Keeping the cached copy.")
        return False
    tmp = UAD_FILE.with_suffix(".tmp")
    tmp.write_bytes(raw)
    tmp.replace(UAD_FILE)
    UAD = data
    ok(f"UAD-NG list updated: {len(data)} packages.")
    return True


def load_uad(interactive=True):
    global UAD
    if UAD is not None:
        return UAD
    if not UAD_FILE.exists() and interactive:
        if confirm("UAD-NG list not downloaded yet (~1.6 MB). Download now?"):
            update_uad()
    if UAD is None:
        try:
            UAD = json.loads(UAD_FILE.read_text(encoding="utf-8")) if UAD_FILE.exists() else {}
        except json.JSONDecodeError:
            warn("Cached UAD-NG list is corrupt - re-download it with 'u'.")
            UAD = {}
    return UAD


def uad_status_line():
    if not UAD_FILE.exists():
        return f"{C.Y}UAD-NG: not downloaded (u){C.X}"
    n = len(load_uad(interactive=False))
    date = datetime.fromtimestamp(UAD_FILE.stat().st_mtime).strftime("%Y-%m-%d")
    return f"{C.DIM}UAD-NG: {n} pkgs, {date}{C.X}"


def uad_tier(p):
    return (load_uad(interactive=False).get(p) or {}).get("removal", "")


def short_desc(p, width=70):
    d = (load_uad(interactive=False).get(p) or {}).get("description", "")
    d = " ".join(d.split())
    return d if len(d) <= width else d[:width - 3] + "..."


# ---------------------------------------------------------------- package model
def plist(flags=""):
    """Package list with a per-action cache (cleared on every change), so screens don't spam pm."""
    if flags in _PLIST_CACHE:
        trace(f"cache hit: pm list packages {flags} ({len(_PLIST_CACHE[flags])} pkgs)", 3)
        return set(_PLIST_CACHE[flags])
    o = out(f"pm list packages {flags}".strip())
    pk = {l[8:].strip() for l in o.splitlines() if l.startswith("package:")}
    _PLIST_CACHE[flags] = pk
    trace(f"pm list packages {flags or '(installed)'} -> {len(pk)} packages")
    return set(pk)


def snapshot():
    installed = plist()
    return installed, plist("-d"), plist("-u") - installed


def status(p, snap):
    installed, disabled, removed = snap
    if p in removed:
        return "removed"
    if p in disabled:
        return "disabled"
    if p in installed:
        return "enabled"
    return "absent"


STATUS_COL = {"enabled": C.G, "disabled": C.Y, "suspended": C.Y, "removed": C.R, "absent": C.DIM}


def current_ime_pkg():
    v = out("settings get secure default_input_method")
    return v.split("/")[0] if "/" in v else ""


def current_home_pkg():
    o = out("cmd package resolve-activity --brief -a android.intent.action.MAIN "
            "-c android.intent.category.HOME")
    last = o.splitlines()[-1] if o else ""
    return last.split("/")[0] if "/" in last else ""


def guard_ctx():
    ctx = {"ime": current_ime_pkg(), "home": current_home_pkg()}
    trace(f"safety context: current keyboard = {ctx['ime'] or '?'}, current launcher = {ctx['home'] or '?'} "
          f"(both locked)", 3)
    return ctx


def verdict(p, ctx):
    """Return (level, reason). level: block | guarded | expert | unknown | ok.
    block   = never touched (bootloop / no calls / no keyboard / no home screen)
    guarded = not rated by UAD-NG but the name looks critical - allowed after a typed confirmation"""
    if any(s in p for s in HARD_PROTECTED):
        return "block", "core system package"
    if p and p == ctx.get("ime"):
        return "block", "current keyboard - switch keyboards first"
    if p and p == ctx.get("home"):
        return "block", "current home launcher"
    tier = uad_tier(p)
    if tier == "Unsafe":
        return "block", "UAD-NG: Unsafe"
    if tier == "Expert":
        return "expert", "UAD-NG: Expert"
    if tier:
        return "ok", f"UAD-NG: {tier}"
    if any(s in p for s in FALLBACK_PROTECTED):
        return "guarded", "not in UAD-NG and its name looks critical"
    return "unknown", "not in UAD-NG list"


def tier_cell(p):
    t = uad_tier(p)
    return f"{TIER_COL.get(t, C.DIM)}{(t or '-'):<11}{C.X}"


def show_table(pkgs, snap=None, desc=False):
    global LAST_LIST
    snap = snap or snapshot()
    ctx = guard_ctx()
    LAST_LIST = list(pkgs)
    if not LAST_LIST:
        warn("Nothing found.")
        return
    suspended = set(load_state().get("suspended", []))
    for i, p in enumerate(LAST_LIST, 1):
        st = status(p, snap)
        if st == "enabled" and p in suspended:
            st = "suspended"
        level, _ = verdict(p, ctx)
        lock = {"block": f" {C.R}[locked]{C.X}", "guarded": f" {C.Y}[guarded]{C.X}"}.get(level, "")
        note = f"\n        {C.DIM}{short_desc(p)}{C.X}" if desc and short_desc(p) else ""
        print(f" {i:>3}) {STATUS_COL[st]}{st:<9}{C.X} {tier_cell(p)} {p}{lock}{note}")


def parse_sel(s):
    picked = []
    for tok in re.split(r"[,\s]+", s.strip()):
        if not tok:
            continue
        if re.fullmatch(r"\d+-\d+", tok):
            a, b = map(int, tok.split("-"))
            picked += [LAST_LIST[i - 1] for i in range(a, b + 1) if 1 <= i <= len(LAST_LIST)]
        elif tok.isdigit():
            i = int(tok)
            if 1 <= i <= len(LAST_LIST):
                picked.append(LAST_LIST[i - 1])
        elif tok.lower() == "all":
            picked += LAST_LIST
        elif "." in tok:
            picked.append(tok)
    return list(dict.fromkeys(picked))


# ---------------------------------------------------------------- state
def load_state():
    base = {"disabled": [], "removed": [], "english": [],
            "english_prev": {},          # package -> locales it had before this tool touched it
            "system_locales_prev": None,  # system locale list before this tool changed it
            "fallback": "ar-EG",          # used when an app has no English strings ("" = none)
            "device_locale_prev": None,   # real device language before this tool changed it
            "ime_disabled": [],           # Chinese keyboards this tool switched off
            "suspended": [],              # apps frozen with pm suspend (when disable is refused)
            "neutered": {}}               # package -> runtime permissions revoked by this tool
    if STATE_FILE.exists():
        try:
            base.update(json.loads(STATE_FILE.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            warn("State file unreadable - starting fresh.")
    return base


def save_state(st):
    if DRY_RUN:
        trace("dry-run: state file not written")
        return
    for k, v in st.items():
        if isinstance(v, list):
            st[k] = sorted(set(v))
    old = {}
    if STATE_FILE.exists():
        try:
            old = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    STATE_FILE.write_text(json.dumps(st, indent=2), encoding="utf-8")
    changes = []
    for k, v in st.items():
        o = old.get(k)
        if o == v:
            continue
        if isinstance(v, list) and isinstance(o, list):
            add, rem = sorted(set(v) - set(o)), sorted(set(o) - set(v))
            changes.append(f"{k}: +{len(add)} -{len(rem)}")
            if add:
                trace(f"state {k} += {', '.join(add)}", 3)
            if rem:
                trace(f"state {k} -= {', '.join(rem)}", 3)
        elif isinstance(v, dict) and isinstance(o, dict):
            changes.append(f"{k}: {len(o)} -> {len(v)} entries")
        else:
            changes.append(f"{k}: {o!r} -> {v!r}")
    trace(f"state saved to {STATE_FILE.name}: {'; '.join(changes) or 'no changes'}")


def device_locale():
    """Current device language (read-only: getprop / settings get). This tool never changes it."""
    return out("getprop persist.sys.locale") or out("settings get system system_locales")


def english_locales():
    fb = load_state().get("fallback") or ""
    return "en-US" + (f",{fb}" if fb and not fb.lower().startswith("en") else "")


def _drop(lst, p):
    while p in lst:
        lst.remove(p)


# ---------------------------------------------------------------- actions
def do_packages(pkgs, action):
    st = load_state()
    ctx = guard_ctx()
    for p in pkgs:
        if action in ("disable", "remove", "force", "neuter"):
            level, why = verdict(p, ctx)
            if level == "block":
                warn(f"Skipped {p} ({why})")
                continue
        if action == "disable":
            if act(f"pm disable-user --user 0 {p}", f"Disabled {p}"):
                st["disabled"].append(p)
                _drop(st["removed"], p)
        elif action == "remove":
            if act(f"pm uninstall -k --user 0 {p}", f"Removed {p} (user 0)"):
                st["removed"].append(p)
                _drop(st["disabled"], p)
        elif action == "force":
            force_disable(p, st)
        elif action == "neuter":
            neuter(p, st)
        elif action == "enable":
            if p in st["suspended"] and act(f"pm unsuspend --user 0 {p}", f"Unsuspended {p}"):
                _drop(st["suspended"], p)
            if p in st.get("neutered", {}):
                unneuter(p, st)
            if act(f"pm enable --user 0 {p}", f"Enabled {p}"):
                _drop(st["disabled"], p)
        elif action == "restore":
            if act(f"cmd package install-existing {p}", f"Restored {p}"):
                if not DRY_RUN:
                    sh(f"pm enable --user 0 {p}")
                _drop(st["removed"], p)
                _drop(st["disabled"], p)
    save_state(st)


def force_disable(p, st):
    """What the greyed-out Disable button can't do. Escalates until something sticks:
    1) pm disable-user   2) pm suspend (frozen: can't open or run, icon greyed)   3) remove for user 0."""
    if act(f"pm disable-user --user 0 {p}", f"Disabled {p}"):
        st["disabled"].append(p)
        return True
    warn(f"{p}: disable refused, trying suspend...")
    if act(f"pm suspend --user 0 {p}", f"Suspended {p} (frozen - can't open or run)"):
        st["suspended"].append(p)
        if not DRY_RUN:
            sh(f"am force-stop {p}")
        return True
    warn(f"{p}: suspend refused too.")
    if confirm(f"Last resort - remove {p} for user 0? (undo: restore)", strong=True):
        if act(f"pm uninstall -k --user 0 {p}", f"Removed {p} (user 0)"):
            st["removed"].append(p)
            return True
    info(f"{p} is protected by the ROM itself. Option 'n' (neuter) can still silence it.")
    return False


def granted_runtime_perms(p):
    o = out(f"dumpsys package {p}")
    sec = o.split("runtime permissions:", 1)
    if len(sec) < 2:
        return []
    perms = []
    for line in sec[1].splitlines()[1:]:
        m = re.match(r"\s+([\w.]+): granted=(true|false)", line)
        if not m:
            if line.strip() and not line.startswith(" " * 6):
                break
            continue
        if m.group(2) == "true":
            perms.append(m.group(1))
    return list(dict.fromkeys(perms))


def neuter(p, st):
    """Keep the app installed but silence it: stop it, block background running,
    notifications and auto-start, revoke its runtime permissions."""
    revoked = []
    for perm in granted_runtime_perms(p):
        if DRY_RUN or sh(f"pm revoke {p} {perm}")[0] == 0:
            revoked.append(perm)
    for op in ("RUN_IN_BACKGROUND", "RUN_ANY_IN_BACKGROUND", "POST_NOTIFICATION", "SYSTEM_ALERT_WINDOW"):
        act(f"cmd appops set {p} {op} ignore", f"{p}: {op} blocked")
    act(f"am force-stop {p}", f"Stopped {p}")
    st.setdefault("neutered", {})[p] = revoked
    ok(f"{p} neutered ({len(revoked)} permission(s) revoked).")


def unneuter(p, st):
    for perm in st.get("neutered", {}).get(p, []):
        if not DRY_RUN:
            sh(f"pm grant {p} {perm}")
    for op in ("RUN_IN_BACKGROUND", "RUN_ANY_IN_BACKGROUND", "POST_NOTIFICATION", "SYSTEM_ALERT_WINDOW"):
        act(f"cmd appops set {p} {op} default", f"{p}: {op} restored")
    st.get("neutered", {}).pop(p, None)


def preflight(pkgs, verb):
    """Safety review before disable/remove. Returns the packages allowed to proceed, or []."""
    ctx = guard_ctx()
    installed = plist()
    chosen = set(pkgs)
    allowed, expert, unknown, guarded = [], [], [], []
    for p in pkgs:
        level, why = verdict(p, ctx)
        if level == "block":
            warn(f"Locked, skipping: {p} ({why})")
            continue
        allowed.append(p)
        {"expert": expert, "unknown": unknown, "guarded": guarded}.get(level, []).append(p)
        needed = [n for n in (load_uad(interactive=False).get(p) or {}).get("neededBy", [])
                  if n in installed and n not in chosen]
        if needed:
            warn(f"{p} is needed by: {', '.join(needed)} - they may break.")
    if not allowed:
        return []
    if guarded:
        err(f"{len(guarded)} package(s) aren't rated by UAD-NG and their names look critical "
            f"(camera, dialer, contacts, radios...):")
        for p in guarded:
            print(f"      {p}")
        if ask("Type I UNDERSTAND to include them:") != "I UNDERSTAND":
            allowed = [p for p in allowed if p not in guarded]
            if not allowed:
                return []
    if unknown:
        warn(f"{len(unknown)} package(s) have no UAD-NG rating - you are on your own for these.")
    if expert:
        err(f"{len(expert)} package(s) rated Expert by UAD-NG (can break features):")
        for p in expert:
            print(f"      {p}  {C.DIM}{short_desc(p, 60)}{C.X}")
        if not confirm(f"{verb.capitalize()} them anyway?", strong=True):
            allowed = [p for p in allowed if p not in expert]
            if not allowed:
                return []
    strong = verb == "remove"
    label = {"force": "Force-disable", "neuter": "Neuter"}.get(verb, verb.capitalize())
    msg = f"{label} {len(allowed)} package(s)" + (" for user 0 (undo with restore)." if strong else "?")
    return allowed if confirm(msg, strong=strong) else []


def show_pkg_info(pkgs):
    snap = snapshot()
    uad = load_uad(interactive=False)
    for p in pkgs:
        e = uad.get(p) or {}
        print(f"\n {C.BOLD}{p}{C.X}  [{STATUS_COL[status(p, snap)]}{status(p, snap)}{C.X}]")
        if not e:
            print(f"   {C.DIM}Not in the UAD-NG list.{C.X}")
            continue
        t = e.get("removal", "-")
        print(f"   Rating : {TIER_COL.get(t, '')}{t}{C.X}    List: {e.get('list', '-')}")
        for line in (e.get("description") or "-").splitlines():
            print(f"   {line}")
        if e.get("dependencies"):
            print(f"   Depends on : {', '.join(e['dependencies'])}")
        if e.get("neededBy"):
            print(f"   Needed by  : {', '.join(e['neededBy'])}")
        if e.get("suggestions"):
            print(f"   Alternatives: {e['suggestions']}")


def sdk():
    try:
        return int(out("getprop ro.build.version.sdk"))
    except ValueError:
        return 0


PKG_RE = re.compile(r"^[A-Za-z0-9_.]+$")
LOCALE_RE = re.compile(r"^[A-Za-z0-9,_-]*$")
ERR_RE = re.compile(r"(?i)\b(error|exception|failure|unknown package|not installed)\b")


def batch(pkgs, cmd_tmpl, mutate=True, chunk=40, label=""):
    """Run cmd_tmpl (which uses $p) for many packages in a few adb calls. Returns {pkg: output}."""
    safe = [p for p in pkgs if PKG_RE.match(p)]
    if mutate and DRY_RUN:
        info(f"(dry-run) {len(safe)} x adb shell {cmd_tmpl.replace('$p', '<pkg>')}")
        return {p: "" for p in safe}
    skipped = [p for p in pkgs if not PKG_RE.match(p)]
    if skipped:
        warn(f"Skipped {len(skipped)} invalid package name(s): {', '.join(skipped[:5])}")
    chunks = (len(safe) + chunk - 1) // chunk
    trace(f"batch{f' [{label}]' if label else ''}: {len(safe)} package(s) in {chunks} adb call(s) of <= {chunk} - "
          f"command per package: {cmd_tmpl.replace('$p', '<pkg>')}")
    res, cur = {}, None
    for n, i in enumerate(range(0, len(safe), chunk), 1):
        grp = safe[i:i + chunk]
        trace(f"chunk {n}/{chunks}: {grp[0]} ... {grp[-1]} ({len(grp)} pkgs)")
        script = f'for p in {" ".join(grp)}; do echo "@@$p"; {cmd_tmpl} 2>&1; done'
        _, o, e = sh(script, timeout=180)
        for line in f"{o}\n{e}".splitlines():
            if line.startswith("@@"):
                cur = line[2:].strip()
                res[cur] = ""
            elif cur:
                res[cur] += line + "\n"
        if VERBOSE < 2 and label and len(safe) > chunk:
            print(f"\r{C.DIM}  {label}: {min(i + chunk, len(safe))}/{len(safe)}{C.X}", end="", flush=True)
    if VERBOSE < 2 and label and len(safe) > chunk:
        print()
    missing = [p for p in safe if p not in res]
    if missing:
        warn(f"No response for {len(missing)} package(s) (shell cut off?): {', '.join(missing[:5])}")
    if mutate:
        invalidate_cache("batch change")
        bad = 0
        for p, o in res.items():
            failed = bool(ERR_RE.search(o))
            bad += failed
            log(f"{'ERR' if failed else 'OK '} {cmd_tmpl.replace('$p', p)} :: {o.strip()}")
            trace(f"{p}: {'FAILED - ' + o.strip()[:120] if failed else 'ok'}", 3 if not failed else 2)
        trace(f"batch done: {len(res) - bad} ok, {bad} failed")
    return res


def get_app_locales(pkgs):
    """{pkg: 'en-US,ar-EG'} - empty string means the app follows the system language."""
    out_ = batch(pkgs, "cmd locale get-app-locales $p --user 0", mutate=False, label="Reading")
    parsed = {}
    for p, o in out_.items():
        m = re.search(r"\[(.*?)\]", o)
        parsed[p] = m.group(1).replace(" ", "") if m else ""
    return parsed


UI_INFRA = ("overlay", ".rro", "auto_generated_characteristics_rro", "com.android.theme.", "uxdesign", "uiengine",
            "systemui", "com.android.settings", "permissioncontroller", "securitypermission", "launcher",
            "inputmethod", "keyguard", "com.oplus.framework", "com.oplus.wallpapers", "colorfulengine")


def ui_infra(p):
    return p in ("android", "oplus") or any(x in p for x in UI_INFRA)


def force_english(pkgs, reset=False, keep_custom=True):
    """Per-app language override (Android 13+). Batched, remembers each app's previous setting for undo.
    keep_custom: leave apps you deliberately set to another language (not English/Chinese) alone."""
    pkgs = list(dict.fromkeys(pkgs))
    if not pkgs:
        return
    if sdk() < 33:
        err("Per-app language needs Android 13+.")
        return
    st = load_state()
    prev = st.setdefault("english_prev", {})

    if reset:
        groups = {}
        for p in pkgs:
            groups.setdefault(prev.get(p, ""), []).append(p)
        for loc, grp in groups.items():
            if not LOCALE_RE.match(loc):
                loc = ""
            cmd = "cmd locale set-app-locales $p --user 0" + (f" --locales {loc}" if loc else "")
            res = batch(grp, cmd, label="Resetting")
            done = [p for p in grp if p in res and not ERR_RE.search(res[p])]
            for p in done:
                _drop(st["english"], p)
                prev.pop(p, None)
        save_state(st)
        ok(f"Language reset on {len(pkgs)} app(s).")
        return

    system = plist("-s")
    blocked = [p for p in pkgs if p in system or ui_infra(p)]
    if blocked:
        warn(f"Skipped {len(blocked)} system/UI package(s) - per-app language is only for your own apps "
             f"(system apps follow the device language): {', '.join(blocked[:6])}" + (" ..." if len(blocked) > 6 else ""))
    pkgs = [p for p in pkgs if p not in blocked]
    if not pkgs:
        return
    if len(pkgs) > 5:
        warn("At most 5 apps at a time.")
        return
    locs = english_locales()
    current = get_app_locales(pkgs)
    todo, kept = [], []
    for p in pkgs:
        cur = current.get(p, "")
        if keep_custom and cur and not cur.lower().startswith(("en", "zh")):
            kept.append(f"{p} ({cur})")
            continue
        if cur == locs:
            st["english"].append(p)  # already done
            continue
        prev.setdefault(p, cur)
        todo.append(p)

    res = batch(todo, f"cmd locale set-app-locales $p --user 0 --locales {locs}", label="Forcing English")
    done = [p for p in todo if p in res and not ERR_RE.search(res[p])]
    failed = [p for p in todo if p not in done]
    st["english"] += done
    for p in failed:
        if prev.get(p, "") == current.get(p, ""):
            prev.pop(p, None)
    save_state(st)

    ok(f"English ({locs}) set on {len(done)} app(s); {len(pkgs) - len(todo) - len(kept)} already set.")
    if kept:
        info(f"Left {len(kept)} app(s) on the language you chose for them: {', '.join(kept[:5])}"
             + (" ..." if len(kept) > 5 else ""))
    if failed:
        warn(f"{len(failed)} app(s) refused the override: {', '.join(failed[:8])}" + (" ..." if len(failed) > 8 else ""))
    if 0 < len(done) <= 5 and not DRY_RUN:
        ctx = guard_ctx()
        for p in done:
            if verdict(p, ctx)[0] != "block":
                sh(f"am force-stop {p}")  # restart so the new locale applies
    elif len(done) > 5:
        info("Reboot (menu r) so every app picks up the new language.")


def open_play(pkg, name):
    act(f"am start -a android.intent.action.VIEW -d 'market://details?id={pkg}'", f"Opened {name} in Play Store")


def disable_chinese_imes():
    """Switch off Chinese keyboards (ime disable - the app stays installed, fully reversible)."""
    cur = out("settings get secure default_input_method")
    ids = [i.strip() for i in out("ime list -s").splitlines() if "/" in i]
    targets = [i for i in ids if i != cur and not i.startswith(GBOARD)
               and any(x in i.split("/")[0].lower() for x in CHINA_IME)]
    if not targets:
        ok("No Chinese keyboards left enabled.")
        return
    st = load_state()
    for i in targets:
        if act(f"ime disable {i}", f"Keyboard switched off: {i.split('/')[0]}"):
            st["ime_disabled"].append(i)
    save_state(st)


def restore_imes():
    st = load_state()
    for i in list(st.get("ime_disabled", [])):
        if act(f"ime enable {i}", f"Keyboard re-enabled: {i.split('/')[0]}"):
            _drop(st["ime_disabled"], i)
    save_state(st)


def set_gboard_quiet():
    if GBOARD not in plist():
        warn("Gboard not installed - skipped keyboard (install it, then use menu 6).")
        return
    if current_ime_pkg() == GBOARD:
        ok("Keyboard already Gboard.")
        return
    act(f"ime enable {GBOARD_IME}", "Gboard enabled")
    act(f"ime set {GBOARD_IME}", "Gboard is now the default keyboard")


# ---------------------------------------------------------------- menus
def package_action_prompt():
    print(f"\n {C.DIM}Select: 3 | 1,4,7 | 2-9 | all | com.pkg.name   (Enter = back){C.X}")
    sel = ask("Packages:")
    if not sel:
        return
    pkgs = parse_sel(sel)
    if not pkgs:
        warn("Nothing selected.")
        return
    print(" d) disable     f) FORCE-disable (when the button is greyed: disable -> suspend -> remove)\n"
          " n) neuter (keep installed, block background/notifications/permissions)\n"
          " r) remove (user 0)   e) enable / unsuspend / un-neuter   s) restore removed\n"
          " l) force English     i) info")
    a = ask("Action:").lower()
    if a == "i":
        show_pkg_info(pkgs)
    elif a == "l":
        force_english(pkgs)
    elif a in ("d", "r", "f", "n"):
        verb = {"d": "disable", "r": "remove", "f": "force", "n": "neuter"}[a]
        allowed = preflight(pkgs, verb)
        if allowed:
            do_packages(allowed, verb)
    elif a == "e":
        do_packages(pkgs, "enable")
    elif a == "s":
        do_packages(pkgs, "restore")


def menu_info():
    rows = {
        "Device": device_label(),
        "Serial": SERIAL,
        "Android / SDK": f"{out('getprop ro.build.version.release')} / {sdk()}",
        "Build": out("getprop ro.build.display.id") or "-",
        "Locale": out("getprop persist.sys.locale") or out("settings get system system_locales") or "-",
        "Device lang": device_locale() or "-",
        "System langs": out("settings get system system_locales") or "-",
        "App fallback": load_state().get("fallback") or "none",
        "Keyboard": out("settings get secure default_input_method") or "-",
        "Launcher": current_home_pkg() or "-",
        "Dry-run": "ON" if DRY_RUN else "off",
    }
    for k, v in rows.items():
        print(f"  {C.BOLD}{k:<14}{C.X} {v}")
    print(f"  {uad_status_line()}")


def menu_uad():
    uad = load_uad()
    if not uad:
        err("No UAD-NG list available. Use 'u' to download it.")
        return
    print(" Show apps rated:\n"
          f"  1) {C.G}Recommended{C.X} only   (safe to remove)\n"
          f"  2) + {C.Y}Advanced{C.X}          (may remove features you use)\n"
          f"  3) + {C.M}Expert{C.X}            (can break things)\n"
          f"  4) everything incl. {C.R}Unsafe{C.X} (view only - Unsafe stays locked)")
    c = ask("Choice [1]:", "1")
    tiers = TIERS[:{"1": 1, "2": 2, "3": 3, "4": 4}.get(c, 1)]
    print(f" List: 0) all  " + "  ".join(f"{i}) {n}" for i, n in enumerate(UAD_LISTS, 1)))
    lc = ask("Choice [0]:", "0")
    lst = UAD_LISTS[int(lc) - 1] if lc.isdigit() and 1 <= int(lc) <= len(UAD_LISTS) else None
    kw = ask("Keyword filter (Enter = none, e.g. heytap):").lower()

    snap = snapshot()
    universe = snap[0] | snap[2]
    rank = {t: i for i, t in enumerate(TIERS)}
    pk = [p for p in universe if p in uad
          and uad[p].get("removal") in tiers
          and (lst is None or uad[p].get("list") == lst)
          and (not kw or kw in p.lower())]
    pk.sort(key=lambda p: (rank.get(uad[p].get("removal"), 9), p))
    info(f"{len(pk)} matching packages on this phone "
         f"({sum(1 for p in pk if p in snap[0])} still installed).")
    show_table(pk, snap, desc=True)
    if pk:
        package_action_prompt()


def menu_scan():
    kw = ask("Filter (Enter = China-ROM packages, 'all' = everything, or a keyword):")
    snap = snapshot()
    universe = snap[0] | snap[2]
    if kw.lower() == "all":
        pk = sorted(universe)
    elif kw:
        pk = sorted(p for p in universe if kw.lower() in p.lower())
    else:
        pk = sorted(p for p in universe if any(x in p for x in CHINA_PATTERNS))
    show_table(pk, snap)
    if pk:
        package_action_prompt()


FOCUS_RE = re.compile(r"u\d+\s+([A-Za-z]\w*(?:\.\w+)+)")


def focused_pkg():
    o = out("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'")
    for line in o.splitlines():
        m = FOCUS_RE.search(line)
        if m:
            return m.group(1)
    return None


def menu_watch():
    info("Live watch: open every screen/popup that shows Chinese. Ctrl+C when done.")
    snap = snapshot()
    caught, last = [], None
    try:
        while True:
            p = focused_pkg()
            if p and p != last:
                last = p
                st = status(p, snap)
                print(f"  {datetime.now():%H:%M:%S}  {STATUS_COL.get(st, '')}{st:<8}{C.X} {tier_cell(p)} {p}")
                if p not in caught:
                    caught.append(p)
            time.sleep(0.7)
    except KeyboardInterrupt:
        print()
    if caught:
        info("Caught:")
        show_table(caught, snap, desc=True)
        package_action_prompt()


def menu_english_setup():
    """Guided, low-risk English setup. The device language is set by YOU in Settings (the phone's own path)."""
    info(f"Device language now: {device_locale() or '-'}")
    print(" Step 1: set the language in the phone's own Settings (safe, official path).\n"
          "         Add 'English (United States)', drag it to the top. Optional: add Arabic below it.")
    if confirm("Open Language settings on the phone now?"):
        act("am start -a android.settings.LOCALE_SETTINGS", "Opened language settings")
        pause()
        info(f"Device language now: {device_locale() or '-'}")
    print(" Step 2: keyboard.")
    if confirm("Switch the keyboard to Gboard?"):
        set_gboard_quiet()
        if current_ime_pkg() == GBOARD and confirm("Switch off the Chinese keyboards?"):
            disable_chinese_imes()
    info("Step 3: if one of YOUR apps still shows Chinese, use menu 5 > 4 on it (one app at a time).")


def menu_english():
    fb = load_state().get("fallback") or "none"
    print(" Per-app language is for YOUR apps only (never system apps), max 5 at a time.\n"
          " 1) Pick packages from a list\n"
          " 4) App currently on screen\n"
          " 5) Show an app's language\n"
          " 6) Reset apps this tool changed\n"
          f" f) Fallback when an app has no English: {fb}")
    c = ask("Choice:").lower()
    if c == "1":
        info("Pick packages, then choose action 'l'.")
        menu_scan()
    elif c == "4":
        p = focused_pkg()
        if not p:
            warn("Could not read the foreground app.")
        elif confirm(f"Force English on {p}?"):
            force_english([p], keep_custom=False)
    elif c == "5":
        p = ask("Package:")
        if p:
            info(get_app_locales([p]).get(p) or "(follows the system language)")
    elif c == "6":
        pk = load_state()["english"]
        if not pk:
            warn("Nothing recorded.")
        elif confirm(f"Restore the previous language on {len(pk)} app(s)?"):
            force_english(pk, reset=True)
    elif c == "f":
        print(" Apps that have no English strings will show this language instead of Chinese.\n"
              " 1) Arabic (ar-EG)   2) none - English only   3) custom tag (e.g. fr-FR)")
        f = ask("Choice:")
        new = {"1": "ar-EG", "2": ""}.get(f)
        if f == "3":
            new = ask("Locale tag:")
            if not re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*", new or ""):
                warn("Invalid tag.")
                return
        if new is None:
            return
        st = load_state()
        st["fallback"] = new
        save_state(st)
        ok(f"Fallback set to: {new or 'none'}. It applies to apps you set from now on.")


def menu_keyboard():
    if GBOARD not in plist():
        warn("Gboard not installed - opening Play Store on the phone.")
        act(f"am start -a android.intent.action.VIEW -d 'market://details?id={GBOARD}'", "Opened Play Store")
        info("Install it, open it once, then run this option again.")
        return
    set_gboard_quiet()
    info("Add Arabic in Gboard > Languages. The Chinese keyboard is now unlocked for disabling.")


def menu_language():
    """Read-only language check + shortcuts. This tool never writes the device language (see RETIRED note)."""
    info(f"Device language: {device_locale() or '-'}   (change it yourself in Settings > Language)")
    print(" 1) Open Language settings on the phone (add English, drag it to the top)\n"
          " 2) Open App languages settings\n"
          " 3) Switch off Chinese keyboards (Gboard must be default first)")
    c = ask("Choice:")
    if c == "1":
        act("am start -a android.settings.LOCALE_SETTINGS", "Opened language settings")
    elif c == "2":
        act("am start -a android.settings.APP_LOCALE_SETTINGS", "Opened app language settings")
    elif c == "3":
        if current_ime_pkg() != GBOARD:
            warn("Make Gboard the default first (menu 6), or you'd have no keyboard.")
        else:
            disable_chinese_imes()


def has_changes(st):
    return bool(st["removed"] or st["disabled"] or st["english"] or st.get("ime_disabled")
                or st.get("suspended") or st.get("neutered")
                )


def menu_reapply():
    st = load_state()
    if not has_changes(st):
        warn("Nothing saved yet.")
        return
    installed, disabled, removed = snapshot()
    to_remove = [p for p in st["removed"] if p in installed]
    to_disable = [p for p in st["disabled"] if p in installed and p not in disabled]
    info(f"Saved profile: {len(st['removed'])} removed, {len(st['disabled'])} disabled, "
         f"{len(st['english'])} English-forced.")
    info(f"Needs re-applying: {len(to_remove)} to remove, {len(to_disable)} to disable.")
    if not confirm("Re-apply now?"):
        return
    do_packages(to_remove, "remove")
    do_packages(to_disable, "disable")
    if st.get("suspended"):
        batch(st["suspended"], "pm suspend --user 0 $p", label="Re-suspending")
    mine = [p for p in st["english"] if p in installed]
    for i in range(0, len(mine), 5):
        force_english(mine[i:i + 5])
    if st.get("ime_disabled") and current_ime_pkg() == GBOARD:
        disable_chinese_imes()


def menu_restore_all():
    st = load_state()
    if not has_changes(st):
        warn("Nothing to undo.")
        return
    if not confirm("Undo every change this tool recorded?"):
        return
    do_packages(list(st["removed"]), "restore")
    do_packages(list(set(st["disabled"]) | set(st["suspended"]) | set(st.get("neutered", {}))), "enable")
    force_english(list(st["english"]), reset=True)
    restore_imes()
    if st["english"]:
        info("Per-app languages were restored; reopen those apps.")


HEALTH_CFG_KEYS = ("mMaterialColor", "mUxIconConfig", "mFontVariationSettings", "mFlipFont", "mIconPackName",
                   "mDarkModeBackgroundMaxL", "mDarkModeDialogBgMaxL", "mDarkModeForegroundMinL")
HEALTH_LABELS = {"settings_home": "Settings home screen", "permission_ui": "Permission screen",
                 "font_scale": "Font size", "night": "Dark mode", "launcher": "Home screen app",
                 "cfg_fontScale": "Display font scale", "cfg_density": "Display density", "cfg_locale": "Language",
                 "mMaterialColor": "System accent colour", "mUxIconConfig": "Icon style",
                 "mFontVariationSettings": "Font weight", "mFlipFont": "Font", "mIconPackName": "Icon pack",
                 "mDarkModeBackgroundMaxL": "Dark-mode background", "mDarkModeDialogBgMaxL": "Dark-mode dialogs",
                 "mDarkModeForegroundMinL": "Dark-mode text"}


def health():
    """Read-only snapshot of what makes the phone look and work normally (nothing is changed)."""
    def last(cmd):
        lines = [x.strip() for x in out(cmd, True).splitlines() if "/" in x]
        return lines[-1] if lines else ""
    h = {"settings_home": last("cmd package resolve-activity --brief -a android.settings.SETTINGS"),
         "permission_ui": last("cmd package resolve-activity --brief -a android.intent.action.MANAGE_APP_PERMISSIONS"),
         "font_scale": out("settings get system font_scale", True),
         "night": out("cmd uimode night", True),
         "launcher": current_home_pkg() or ""}
    cfg = out("dumpsys activity | grep -m1 mGlobalConfig", True)
    m = re.search(r"\{([0-9.]+) ", cfg)
    h["cfg_fontScale"] = m.group(1) if m else ""
    m = re.search(r" (\d+)dpi", cfg)
    h["cfg_density"] = m.group(1) if m else ""
    m = re.search(r"\[([^\]]*)\]", cfg)
    h["cfg_locale"] = m.group(1) if m else ""
    for k in HEALTH_CFG_KEYS:
        m = re.search(rf"{k}\s*=\s*([^,}}]*)", cfg)
        h[k] = m.group(1).strip() if m else ""
    trace("health: " + ", ".join(f"{k}={v}" for k, v in h.items()), 3)
    return h


_SESSION_START = {}


def check_health(baseline, action, expected=()):
    """Compare with the baseline; if anything changed that the action didn't intend, say so and offer a fix.
    A value that went back to how it was at session start counts as a recovery, not a problem."""
    now = health()
    diffs = [(k, baseline.get(k, ""), now.get(k, "")) for k in now
             if k not in expected and baseline.get(k, "") != now.get(k, "")
             and not (_SESSION_START and now.get(k, "") == _SESSION_START.get(k, ""))]
    recovered = [k for k in now if baseline.get(k, "") != now.get(k, "") and _SESSION_START
                 and now.get(k, "") == _SESSION_START.get(k, "")]
    if recovered:
        ok("Back to normal: " + ", ".join(HEALTH_LABELS.get(k, k) for k in recovered))
    if not diffs:
        trace(f"health check after '{action}': unchanged", 2)
        return now
    print(f"\n{C.R}{C.BOLD}!! Something on the phone changed that '{action}' was not supposed to change:{C.X}")
    for k, b, a in diffs:
        print(f"{C.R}   {HEALTH_LABELS.get(k, k):24} {b or '-'}  ->  {a or '-'}{C.X}")
    dbg(f"HEALTH REGRESSION after {action}: {diffs}")
    print(" 1) Undo everything this tool recorded (same as menu 9)\n"
          " 2) Show how to reset it with the phone's own tools\n"
          " 3) Ignore (accept the new state)")
    c = ask("Choice:", "1")
    if c == "1":
        menu_restore_all()
        after = health()
        still = [k for k, b, _ in diffs if after.get(k, "") != b]
        if still:
            warn("Still different: " + ", ".join(HEALTH_LABELS.get(k, k) for k in still)
                 + ". Use Settings > search 'Reset' > Reset all settings (keeps apps and data).")
        else:
            ok("Back to how it was.")
        return after
    if c == "2":
        info("Settings > search 'Reset' > Reset phone > Reset all settings. It keeps your apps, files and accounts; "
             "Wi-Fi passwords and your setting changes are reset.")
        return baseline
    return now


def device_label():
    global _DEVICE_LABEL
    if _DEVICE_LABEL is None:
        _DEVICE_LABEL = f"{out('getprop ro.product.brand', True)} {out('getprop ro.product.model', True)}".strip()
    return _DEVICE_LABEL


def backup(quiet=False):
    BACKUP_DIR.mkdir(exist_ok=True)
    inst, dis, rem = snapshot()
    f = BACKUP_DIR / f"packages_{datetime.now():%Y%m%d_%H%M%S}.json"
    f.write_text(json.dumps({"device": device_label(), "installed": sorted(inst),
                             "disabled": sorted(dis), "removed": sorted(rem)}, indent=2), encoding="utf-8")
    if not quiet:
        ok(f"Snapshot saved: backups/{f.name}")


def cycle_verbose():
    global VERBOSE
    VERBOSE = VERBOSE % 3 + 1
    st = load_state()
    st["verbosity"] = VERBOSE
    save_state(st)
    info(f"Verbosity {VERBOSE}: " + {1: "results only",
                                     2: "every adb command + exit code + timing + first 15 output lines + decisions",
                                     3: "ULTRA - everything, full output, internal calls, cache hits, timestamps"}[VERBOSE])


def toggle_dry():
    global DRY_RUN
    DRY_RUN = not DRY_RUN
    info(f"Dry-run {'ON - nothing will change' if DRY_RUN else 'off'}")


def reboot():
    if confirm("Reboot the phone now?"):
        if DRY_RUN:
            info("(dry-run) adb reboot")
        else:
            adb("reboot")
            ok("Rebooting - reconnect when it's back up.")


MENU = [
    ("e", "English setup   (opens Settings > Language, then Gboard - guided, no system writes)", menu_english_setup),
    ("1", "Device info", menu_info),
    ("2", "UAD-NG debloat   (curated list with safety ratings)", menu_uad),
    ("3", "Scan / search packages   (disable, remove, restore, English)", menu_scan),
    ("4", "Catch the app showing Chinese   (live watch)", menu_watch),
    ("5", "Force English - choose apps / fallback language", menu_english),
    ("6", "Switch keyboard to Gboard", menu_keyboard),
    ("7", "System language / MoreLocale", menu_language),
    ("8", "Re-apply saved changes   (after an OTA)", menu_reapply),
    ("9", "Undo everything", menu_restore_all),
    ("u", "Update UAD-NG list", update_uad),
    ("b", "Backup package snapshot", backup),
    ("t", "Toggle dry-run", toggle_dry),
    ("v", "Cycle verbosity   (1 results / 2 verbose / 3 ULTRA)", cycle_verbose),
    ("r", "Reboot phone", reboot),
    ("q", "Quit", None),
]


def header():
    if VERBOSE >= 2:
        print(f"\n{C.DIM}{'=' * 78}{C.X}")  # keep history on screen instead of clearing
    else:
        os.system("cls" if os.name == "nt" else "clear")
    dry = f"  {C.Y}[DRY-RUN]{C.X}" if DRY_RUN else ""
    dry += f"  {C.M}[verbosity {VERBOSE}]{C.X}"
    print(f"{C.BOLD}{C.CY}== China-ROM English & Debloat =={C.X}  {device_label()}  "
          f"{C.DIM}({SERIAL}){C.X}{dry}\n  {uad_status_line()}\n")


def main():
    global ADB
    ADB = find_adb()
    if not ADB:
        err("adb not found. Install Android platform-tools and add it to PATH, or put adb next to this script.")
        sys.exit(1)
    global VERBOSE
    if not _VERBOSE_FROM_FLAG and isinstance(load_state().get("verbosity"), int):
        VERBOSE = min(3, max(1, load_state()["verbosity"]))
    dbg("=" * 60)
    dbg(f"SESSION START  python {sys.version.split()[0]}  adb={ADB}  argv={sys.argv[1:]}  verbosity={VERBOSE}")
    trace(f"python {sys.version.split()[0]} on {sys.platform}; adb = {ADB}")
    trace(f"working folder {HERE}; full log: {DEBUG_LOG.name}; action log: {LOG_FILE.name}")
    select_device()
    trace(f"device serial {SERIAL}")
    backup(quiet=True)
    base = health()
    _SESSION_START.update(base)
    import traceback
    while True:
        ensure_connected()
        invalidate_cache("new menu action")
        header()
        for k, label, _ in MENU:
            print(f"  {C.BOLD}{k}{C.X}) {label}")
        c = ask("\nSelect:").lower()
        if c == "q" or _EOF:
            break
        fn = next((f for k, _, f in MENU if k == c), None)
        if fn:
            trace(f"menu '{c}' -> {fn.__name__}()")
            dbg(f"MENU  {c} -> {fn.__name__}")
            t0 = time.monotonic()
            try:
                fn()
            except KeyboardInterrupt:
                print()
                trace("interrupted by Ctrl+C")
            except Exception:
                tb = traceback.format_exc()
                dbg(tb)
                err("Unexpected error (full traceback below and in cnrom_debug.log):")
                print(f"{C.R}{tb}{C.X}")
            trace(f"{fn.__name__}() finished in {time.monotonic() - t0:.1f}s")
            if c not in ("1", "v", "t", "b", "u") and not DRY_RUN:
                expected = ("cfg_locale",) if c in ("e", "7") else ()
                if c == "r":
                    info("After the phone is back, the health check runs on the next menu action.")
                else:
                    label = next((lb for k, lb, _ in MENU if k == c), c).split("   (")[0].strip()
                    base = check_health(base, label, expected)
            pause()
    dbg("SESSION END")


if __name__ == "__main__":
    main()
