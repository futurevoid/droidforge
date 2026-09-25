# droidforge - Architecture

## Layers

```
 TUI (Textual)          CLI (argparse)
      \                   /
       \   confirm hook  /        <- only these two know how to ask the user
        v               v
   engine: Plan -> Guard -> Executor (snapshot / health before+after) -> History / Profile / Report
        ^
        | build plans (read state first, compute undo)
   features/*  (language, debloat, privacy, firewall, apps, audit, root, tools ...)
        |
   adb layer: Device -> Backend (RealBackend = subprocess adb | SimBackend = FakePhone)
```

Rule: `droidforge.engine`, `droidforge.features`, `droidforge.adb` never import `textual`.
`droidforge.tui` imports the engine; the engine calls back into the UI only through the hooks below.

## Package layout

```
droidforge/
  __init__.py            __version__
  __main__.py            python -m droidforge  -> cli.main()
  cli.py                 subcommands; no args -> launch TUI
  config.py              XDG paths (platformdirs): ~/.config/droidforge/config.json,
                         ~/.local/share/droidforge/{profiles,history,backups,reports,logs,cache,modules}
  log.py                 verbosity 1/2/3, trace(), dbg() -> debug log; pluggable sinks (console / TUI pane)
  notify.py              notify-send wrapper
  adb/
    backend.py           Backend protocol: run(args: list[str], timeout) -> RunResult(exit, out, err, ms)
    real.py              subprocess implementation (finds adb; android-tools hint)
    sim.py               FakePhone + SimBackend (see "Simulated phone")
    device.py            Device: serial, sh(), out(), getprop cache, sdk, rom family, root flavor, shizuku state,
                         package-list cache (invalidated after every write)
    batch.py             batched per-package loops: `for p in ..; do echo "@@$p"; <cmd> $p 2>&1; done`, 40/chunk
    hostcmd.py           previewed host commands (pacman, scrcpy, notify-send)
  engine/
    plan.py              Step, Plan, StepResult dataclasses
    executor.py          run(plan, device, confirm) - dry-run, verify, escalation, history recording
    history.py           per-device JSONL timeline; undo(entry_ids) / rollback_to(entry_id) -> Plan
    profile.py           per-device desired state; export/import; legacy cnrom_state.json import; OTA fingerprint
    safety.py            verdicts (locked / guarded / expert / keep / unknown / ok), typed confirmations,
                         recovery-script writer
    report.py            HTML session report (stdlib only, inline CSS)
    guard.py             allowlist (P8): READ_PATTERNS, WRITE_PATTERNS (regex per COMMANDS.md row, each
                         with its `touches` kinds) and FORBIDDEN_PATTERNS; `check(step, device)` raises
                         GuardError before anything is sent; also enforces P12 for `set-app-locales`
    snapshot.py          Snapshot(settings{system,secure,global}, packages{state}, app_locales, ime, launcher,
                         global_config fields); `take(device, scope)`, `diff(before, after) -> list[Change]`
    health.py            R-11.7 probes -> HealthReport; `compare(baseline, now)` -> regressions
  data/
    packages.py          curated lists (docs/PACKAGES.md is the human-readable source of truth)
    uad.py               download/cache/lookup of uad_lists.json
    presets.py           DNS providers, power-permission presets, hidden-activity intents, app catalog
                         (package, Play id, official APK source)
  features/
    doctor.py language.py region.py keyboard.py debloat.py privacy.py dns.py ads.py firewall.py
    apps.py defaults.py keepalive.py powerperms.py backup.py ota.py fix.py (R-12.5 repair plans)
    wireless.py shizuku.py update.py
    audit/perms.py audit/signers.py audit/net.py
    tools/scrcpy.py tools/logcat.py tools/activities.py tools/shell.py
    root/detect.py root/modules.py root/debloat_module.py root/firewall_module.py root/hosts_module.py
    root/props.py root/integrity.py
  tui/
    app.py               DroidforgeApp: layout, bindings, workers, theme persistence
    themes.py            "hacker" Theme + registration
    screens/             one Screen/Container per sidebar section
    widgets/             PlanPreview (modal), TypedConfirm (modal), LogPane, QRCode, PackageTable,
                         DeviceBar, HistoryTable
tests/
  conftest.py            `sim` fixture -> Device(SimBackend(FakePhone(...)))
  test_<feature>.py      plan content, execute on sim, verify sim state, undo restores state
  test_invariants.py     P1/P2/P5/P7/P10 invariants across every registered feature
  test_guard.py          every write template in COMMANDS.md has a guard regex and vice versa; every Forbidden
                         row is refused; set-app-locales on a system package is refused
  test_blast_radius.py   sim "side effect" injection (a command that also flips an undeclared key) is caught
  test_health.py         sim regressions (Settings resolves to AOSP, mMaterialColor 0, crash entry) stop the run
  test_tui.py            Textual `App.run_test()` pilot: every screen opens, preview modal appears, no crash
```

## Core types (engine/plan.py)

```python
@dataclass
class Step:
    label: str                       # human text: "Disable com.heytap.market"
    cmd: str                         # exact shell command run via `adb shell` (or host=True for host commands)
    undo: list[str]                  # commands that revert it, computed from state read before the plan
    category: str                    # "debloat", "language", "dns", "firewall", "root", ...
    pkg: str | None = None
    risk: str = "normal"             # "read" | "normal" | "risky" | "locked"
    verify: str | None = None        # command whose output proves success
    expect: str | None = None        # regex the verify output must match
    fallbacks: list["Step"] = field(default_factory=list)   # escalation chain (force-disable)
    host: bool = False               # run on the PC instead of the phone
    touches: list[str] = field(default_factory=list)
    # declared blast radius (P10), e.g. "pkg:com.heytap.market:enabled", "setting:global:private_dns_mode",
    # "applocale:com.whatsapp", "ime:default", "appop:com.x:RUN_ANY_IN_BACKGROUND", "role:android.app.role.SMS"

@dataclass
class Plan:
    title: str
    steps: list[Step]
    notes: list[str]                 # warnings shown in preview (neededBy, keep-list, VoLTE, reboot needed)
    typed: list[str]                 # strings the user must type (locked package names, "I UNDERSTAND")
    recovery: str | None = None      # path of the recovery script written before execution
```

`Executor.run(plan, device, confirm)`:
1. `guard.check()` every step, fallback and undo command. Any GuardError aborts before confirmation.
2. `confirm(plan) -> bool` (TUI modal or CLI prompt; typed strings checked by the UI, re-checked here).
3. `health.run()` + `snapshot.take()` (baseline). If a probe is already failing, say so before running.
4. If any step is `locked`, write the recovery script first (safety.write_recovery).
5. For each step: run; on failure try `fallbacks` in order; run `verify`/`expect`; record a history entry
   (success or failure, with undo only for what actually took effect).
6. `snapshot.take()` + `snapshot.diff()`: changes not covered by any step's `touches` -> regressions.
   `health.run()` + `compare()`: newly failing probes -> regressions.
7. Regressions: stop, print them, offer an undo plan for the whole plan (and a revert of each undeclared change
   from the "before" snapshot), show "Settings > Reset all settings" as the last-resort advice.
8. Invalidate device caches; update profile desired-state; return results.
Dry-run: steps are logged as "(dry-run)" and not sent; history marks them `dry_run: true`.

## Confirm hooks

- TUI: `PlanPreview` modal lists steps with risk badges, exact `cmd`, `undo`, notes; `TypedConfirm` input for
  every `plan.typed` string. Buttons: Run / Cancel / Copy commands.
- CLI: prints the same, asks `[y/N]`; `--yes` skips; locked packages need `--allow-locked pkg1,pkg2`.

## History (engine/history.py)

File: `history/<serial>.jsonl`, one JSON object per executed step:
`{id, ts, serial, fingerprint, plan_id, plan_title, category, label, cmd, exit, out_tail, undo[], undone, dry_run}`.
`undo([ids])` and `rollback_to(id)` return a Plan (reverse chronological) that goes through the normal
confirm/execute path; executed undo entries mark the originals `undone: true`.

## Profiles (engine/profile.py)

File: `profiles/<serial>.json`:
`{serial, model, fingerprint, disabled[], removed[], suspended[], neutered{pkg:[perms]}, firewall[], english[],
app_locale_prev{}, region{}, dns_prev{}, roles_prev{},
ime_disabled[], keepalive[], powerperms{pkg:[perms]}, root{modules[], props_prev{}}, healthy_baseline{}}`.
- `reapply()` builds one Plan from the desired state (used after OTA, and for firewall on every connect).
- Export = the JSON minus `serial`/`fingerprint`; import merges into the active device's profile (previewed).
- Legacy import maps `legacy/cnrom_fix.py`'s `cnrom_state.json` package keys (disabled/removed/suspended/neutered).
  Its language keys (`english`, `device_locale_prev`, `system_locales_prev`) are **ignored**: they describe the
  forbidden language features (docs/INCIDENT-2026-09-25.md).

## Simulated phone (adb/sim.py)

`FakePhone` holds: packages `{name: {installed, enabled, user0, suspended, system, uid, perms{}, appops{},
signer, app_locales, activities[]}}`, `settings{system,secure,global}`, `props`, IMEs (enabled/current), roles,
firewall chain state, global configuration `{locales, font_scale, density, night, oem{mMaterialColor,
mUxIconConfig, mFontVariationSettings, mDarkMode*}}` rendered as an `mGlobalConfig=` line like the owner's real
dump, resolve-activity results for Settings / permissions, crash buffer, root flavor (`None|magisk|ksu|apatch`),
Shizuku installed/running, `protected` packages (disable refused), `/proc/net` lines, and a
`permission_monitoring` flag exposed through a placeholder setting until Phase 9 records the real key
(`break_ui()` also turns it on, as in the real incident).
Fault injection for tests: `side_effects={cmd_regex: mutation}` (a command also changes an undeclared key),
`break_ui()` (Settings resolves to an AOSP activity, `mMaterialColor` -> 0).
`SimBackend.run()` parses the subset of commands listed in `docs/COMMANDS.md` (including the `for p in ...` batch
form and `sh -c`). **Unknown commands return exit 127 with `sim: unsupported: <cmd>`** so tests catch any command
not documented in COMMANDS.md. Default seed = a realme Neo 8 China ROM package set taken from PACKAGES.md.

## Threading (TUI)

Engine calls run in Textual workers (`@work(thread=True)`); log lines reach the LogPane through
`app.call_from_thread`. The confirm hook blocks the worker on a `threading.Event` while the modal is open.
Long-running streams (logcat, live connections) are cancellable workers.

## Device-side files

- None in non-root mode. droidforge ships no DEX/binaries for the phone (P9).
- Root modules are built on the host in `~/.local/share/droidforge/modules/` and pushed to `/data/local/tmp/`.

## Legacy

`legacy/cnrom_fix.py` (1.4k lines) is the behavioural reference for: verbosity/log format, batching,
UAD handling, verdicts/preflight, force-disable escalation, neuter, IME handling. Port the behaviour; do not copy
the structure. **Do not port** its language features - menu `e` "Force English everywhere", the device-locale
DEX (`locale_tool`, `set_device_locale`), `set_system_locales`, the all-packages `force_english`, MoreLocale, and
the menu 7 "repair" option, and any message telling the user to enable "Disable permission monitoring" (the
actual cause of the 2026-09-25 incident). All are Forbidden in COMMANDS.md.
