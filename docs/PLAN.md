# droidforge - Implementation plan (v1.0)

One release, built in order. Each task = one commit (`P<phase>.<n>: <summary>`), tests green before commit,
tick the box in the same commit. "Accept" lines are the tests/checks that must exist and pass.
R-ids point to `SPEC.md`; commands must come from `COMMANDS.md`.

**Read `docs/INCIDENT-2026-09-25.md` before starting.** Safety principles P7-P16 in SPEC.md are not a feature to
add later: Phase 1 builds the guard, snapshot, health gate and recovery script, and **no feature plan may run
through the executor until P1.1-P1.10 are done**. Any feature task whose tests do not pass through the guard and
the health gate is not done.

## Phase 0 - Scaffold

- [x] **P0.1** (R-13.1) Package skeleton per ARCHITECTURE.md; complete the draft `pyproject.toml` (hatchling, py>=3.9, deps textual/qrcode/
  platformdirs, dev: pytest/ruff), console script. No data files for the phone (P9).
  Accept: `pip install -e .` works; `droidforge --version`; `ruff check` clean; `pytest` runs (0 tests OK).
- [x] **P0.2** (R-11.6, P3) `config.py` (XDG dirs, config.json with theme/verbosity/last device) and `log.py` (verbosity
  1/2/3, `trace`, `dbg`, sinks). Port the legacy log format. Accept: unit tests for level filtering + debug log
  always full.
- [x] **P0.3** (R-2.6) `adb/backend.py`, `adb/real.py` (timeouts -> 124, missing adb -> 127 + pacman hint), `adb/device.py`
  (getprop cache, package-list cache + invalidation, `sh/out`), `adb/batch.py`. Accept: tests with a stub backend.
- [x] **P0.4** `adb/sim.py` FakePhone + SimBackend covering every command in COMMANDS.md sections Device info,
  Packages, Language, Keyboard, Health probes (others added in their phases). Seed = PACKAGES.md packages + a
  few Google apps, `system` flags, an `mGlobalConfig=` line modelled on the owner's real dump, Settings /
  permission resolve-activity results. Fault injection: `side_effects`, `break_ui()`. Unknown command -> 127.
  Accept: `tests/test_sim.py` round-trips (disable->list -d->enable, app-locale set/get, batch loop output format
  identical to legacy mock, `break_ui()` visible through the probe commands).
- [x] **P0.5** (R-13.2, R-13.3) GitHub Actions: ruff + pytest on 3.9 and 3.13. `packaging/arch/PKGBUILD` builds from git.

## Phase 1 - Engine

- [x] **P1.1** (P8) `engine/guard.py`: READ/WRITE/FORBIDDEN patterns from COMMANDS.md, P12 check for
  `set-app-locales` (system packages, overlays, framework, Settings, SystemUI, PermissionController, launcher,
  IMEs refused). Accept: `tests/test_guard.py` parses COMMANDS.md - every write row has a pattern and every
  pattern has a row; every Forbidden row is refused (incl. `app_process`, `system_locales`, `CHANGE_CONFIGURATION`,
  `cmd overlay`, `pm clear` on system apps); a made-up command is refused.
- [x] **P1.2** (P10, R-11.8) `engine/snapshot.py`: take/diff of settings, package states, app locales, IME,
  launcher, global-config fields. Accept: diff on sim finds exactly the injected changes, nothing else.
  - Open question (owner): a real phone changes some settings on its own (auto-brightness `screen_brightness`,
    `next_alarm_formatted`, ...). P10 as written flags every undeclared change, so these would stop a plan on a
    real device. Implemented strictly for now (no ignore-list). Phase 9 will show which keys are noisy - may
    droidforge then keep a reviewed ignore-list of volatile keys (never containing P9b display/UI keys)?
- [x] **P1.3** (P0, P11, R-11.7) `engine/health.py`: probes + baseline compare. Accept: `break_ui()` on the sim is
  reported as 2+ regressions; a healthy sim reports none; sim `permission_monitoring=True` is reported with the
  "turn it off" message even when the baseline already had it on.
- [x] **P1.4** (R-11.1, R-11.5, P1, P5, P13, P15) `engine/plan.py` (`Step.touches`) + `engine/executor.py`: guard
  -> confirm -> baseline health+snapshot -> recovery script -> batches of <=5 with diff+health after each ->
  stop on first regression -> undo offer. Accept: (a) dry-run touches nothing; (b) fallback escalation works;
  (c) a sim `side_effects` rule that flips an undeclared setting is caught and the plan stops after that batch;
  (d) `break_ui()` triggered by step 3 of 12 stops the plan before batch 2; (e) the recovery script exists before
  the first command is sent and restores the sim when replayed.
- [x] **P1.5** (R-11.2) `engine/history.py` JSONL timeline, `undo(ids)`, `rollback_to(id)` -> Plans (through the
  same executor, so undo is guarded and health-gated too). Accept: disable 3 packages, rollback to the first ->
  sim state equals initial; undone flags set.
- [x] **P1.6** (R-2.4) `engine/profile.py` per-device desired state, export/import (import = previewed plan, P14),
  legacy `cnrom_state.json` import of package keys only (language keys ignored). Accept: round-trip; legacy
  sample with `english`/`device_locale_prev` imports without creating any language step.
- [x] **P1.7** `engine/safety.py` verdicts (locked/guarded/expert/keep/unknown/ok), typed requirements, R-4.3b UI
  infrastructure hidden+locked. Accept: locked package without typed name is rejected by the executor; overlays
  are absent from default package lists.
- [x] **P1.8** `tests/test_invariants.py`: for every registered plan builder on the sim - every write step passes
  the guard, declares `touches`, has undo; execute -> diff shows only declared keys -> undo -> snapshot equals
  the original. Grows with each phase; a builder that is not registered fails the suite.
- [x] **P1.9** `features/doctor.py` (R-2.8): read-only report incl. health probes; on failure recommends Settings >
  Reset all settings. Accept: `break_ui()` sim -> doctor prints the regressions and the advice, sends no writes.
- [x] **P1.10** (R-4.3, R-11.9) Expert mode + reboot check: `--expert` flag / TUI toggle with red banner; locked
  packages selectable only then, one per batch, typed name; reboot check waits for `sys.boot_completed`, re-runs
  health + snapshot vs pre-plan baseline. Accept: without `--expert` a locked package cannot enter a plan even
  via CLI; the sim reboot check catches a regression injected "at boot".
  - Done in P1.10: `--expert` CLI flag + ASCII banner, `Session.expert`, `safety.select/make_expert`, executor
    `expert_mode`, `engine/reboot.py`. The TUI toggle + red banner is built with the TUI itself (P3.1 header,
    P3.3 screens) on top of the same `Session.expert` flag.

## Phase 2 - Port legacy features

- [x] **P2.1** `features/language.py` (R-3.1, R-3.2): read-only device-language check; open Language settings with
  instructions; re-read and report. Per-app language for user-picked non-system apps only, previous value kept.
  Accept: no plan built by this module contains a Forbidden command (guard test); picking a system app is
  refused with an explanation; undo restores the exact previous app locale.
- [x] **P2.2** `features/keyboard.py` (R-3.4): Gboard switch, Chinese IMEs off, secure keyboard removal (IME ids
  disabled first; refuses if it is the current IME), Gboard language screen.
- [x] **P2.3** `data/uad.py` + `features/debloat.py` (R-4.x): list/filter/tiers, neededBy notes, actions incl.
  force escalation (disable->suspend->remove; firewall+neuter hook left for P4.5), neuter/un-neuter,
  keep-list, guarded phrase. Accept: port of legacy mock scenarios (protected package, suspend refused, etc.).
- [x] **P2.4** `features/backup.py` (R-11.3): session-start snapshot saved to disk (evidence + diff baseline);
  restore only of keys droidforge changed, via history. No blanket restore.
- [x] **P2.5** "English setup" guide (replaces legacy menu `e`): step 1 opens Language settings and waits for the
  user; step 2 offers Gboard + Chinese-IME switch (R-3.4); step 3 lists apps still showing Chinese via the
  focused-app watcher and offers per-app language for those non-system apps only. Each step is its own
  confirmed, health-gated plan.

## Phase 3 - TUI shell

- [x] **P3.1** (R-12.1, R-2.1) `tui/app.py` layout: header DeviceBar, sidebar sections, main area, collapsible LogPane fed by
  `log.py` sink; workers; device picker; `--simulate` flag. Accept: `run_test()` boots on sim.
- [x] **P3.2** Widgets: PlanPreview modal (exact cmd + undo + risk badges + notes), TypedConfirm, PackageTable
  (UAD tier, status, description, multi-select, filter), HistoryTable. Accept: pilot test opens preview from a
  debloat action and cancels -> sim unchanged.
- [x] **P3.3** Screens for Phase 2 features: Dashboard (device info, doctor), Language, Keyboard, Debloat,
  Backup & History (undo entry, rollback). Accept: pilot navigates each and runs one action on sim.
- [x] **P3.4** (R-12.2) Themes: built-in list + custom "hacker" (black / green / amber) via `textual.theme.Theme`,
  switcher (key `ctrl+t` + command palette), persisted. Verbosity toggle key `v`, dry-run toggle.

- [x] **P3.5** (R-12.5) Breakage alert modal + dashboard list + `droidforge fix`: triggered by executor
  regressions, reboot check, and startup/connect compare against the last healthy baseline. Accept: pilot test -
  sim `break_ui()` during a plan shows the modal; **Fix it** runs the undo plan and the modal reports healthy;
  a break injected between two sessions is reported at the next start; an unexplained break shows the
  "Reset all settings" advice and no automatic writes.
## Phase 4 - Neo 8 features

- [x] **P4.1** `features/privacy.py` telemetry preset (R-5.1) + `features/ads.py` (R-5.4).
- [x] **P4.2** `features/dns.py` Private DNS menu, AdGuard default (R-5.2).
- [x] **P4.3** Install hijack (R-5.3).
- [x] **P4.4** `features/firewall.py` chain3 (R-5.5): capability probe, block/unblock any app, detect missing rules on
  connect and **ask** to re-apply (P14);
  plug into force-disable as last stage together with neuter.
- [x] **P4.5** `features/apps.py` install sources (R-6.1): Play page, official APK download (GitHub releases API,
  F-Droid index, Mozilla - verify Firefox Nightly URL and record it in COMMANDS.md), local folder incl. splits.
- [x] **P4.6** `features/defaults.py` swaps + roles (R-6.2) with telephony safeguards + IMS/VoLTE notice.
- [x] **P4.7** `features/keepalive.py` (R-6.3) and `features/powerperms.py` (R-6.4).
- [x] **P4.8** `features/region.py` (R-3.3): opens Regional preferences and Date & time only - no writes.
  Accept: guard test proves the module can only emit `am start` reads. (Tweaks removed - P9b.)
- [x] **P4.9** `features/ota.py` fingerprint change -> diff vs profile -> prompt re-apply (R-2.5, P14);
  `notify.py` (R-2.7).
- [x] **P4.10** TUI screens for all of Phase 4; CLI can reach every plan.

## Phase 5 - Tools & connectivity

- [ ] **P5.1** `features/wireless.py` QR pairing (TUI QR widget from `qrcode` matrix, half-block rendering),
  mDNS polling, pair + connect, code fallback, remembered devices (R-2.2).
  - Open question (owner): pairing only works with Developer options > Wireless debugging on, but P0 says
    droidforge never tells the user to enable any developer-option switch (the same applies to USB debugging in
    the "no device" message). (a) allow naming USB / Wireless debugging only, or (b) never name any developer
    option? Built with neutral wording until answered; task stays open.
- [x] **P5.2** `features/shizuku.py` install from GitHub release + auto-start on connect + status (R-2.3).
  - "Auto-start on every connect" is done as an ASK on every connect (P14 overrides: nothing runs unconfirmed).
- [x] **P5.3** `tools/scrcpy.py` (R-9.1) with pacman hint. **P5.4** `tools/logcat.py` streaming pane (R-9.2).
- [x] **P5.5** `tools/activities.py` curated intents + exported-activity browser (R-9.3).
  **P5.6** `tools/shell.py` pane (R-9.4).

## Phase 6 - Audit

- [ ] **P6.1** `audit/perms.py` + table with revoke (R-8.1). **P6.2** `audit/signers.py` (R-8.2).
- [ ] **P6.3** `audit/net.py` live connections (R-8.3). **P6.4** audit JSON output in CLI.

## Phase 7 - Root mode (moved to v2 by owner decision, 2026-09-25)

- [ ] **P7.1** `root/detect.py` flavor/version; `root/modules.py` build zip (module.prop, scripts), push, install,
  list/remove (R-10.1). Sim gets a `root` flavor option.
- [ ] **P7.2** `root/debloat_module.py` systemless removal (R-10.2). **P7.3** `root/firewall_module.py` (R-10.3).
- [ ] **P7.4** `root/hosts_module.py` (R-10.4). **P7.5** `root/props.py` with saved prior values (R-10.5).
- [ ] **P7.6** `root/integrity.py` Zygisk check, PIFork + Tricky Store install, target.txt, checker Play page
  (R-10.6). Every root action still previewed and in history (module removal = undo).

## Phase 8 - CLI, report, update, packaging

- [ ] **P8.1** Complete CLI (R-12.3) incl. `--yes`, `--allow-locked`, `--simulate`, `--dry-run`, verbosity flags.
- [ ] **P8.2** `engine/report.py` HTML session report (R-11.4).
- [ ] **P8.3** `features/update.py` self-update (R-12.4).
- [ ] **P8.4** README (install via pipx / AUR, first run, safety model, screenshots from sim), CHANGELOG,
  PKGBUILD finalised, tag v1.0.0 only after Phase 9 passes.
  - Owner decision (2026-09-25): publish v1.0.0 after Phases 5, 6 and 8; Phase 7 is v2; Phase 9 runs after v1.

## Phase 9 - Real-device validation (owner runs; Claude Code prepares)

Claude Code writes `docs/DEVICE_CHECKLIST.md`: for every **V** command in COMMANDS.md, a read-only probe first,
then the smallest reversible write, the expected output, and the undo. The owner runs it on the Neo 8
(non-root) and realme 10 (root), pastes outputs back, and Claude Code updates statuses, fixes parsers,
and adds `tests/data/neo8_cn_packages.txt` (from `pm list packages -f -u`) to re-seed the simulator.
- Permission-monitoring key (health probe R-11.7 #6): droidforge saves `settings list system/secure/global` +
  `getprop`; the owner turns the switch ON, droidforge saves again and diffs, the owner turns it OFF and reboots,
  droidforge confirms the key flipped back. droidforge itself only reads. Record the key in COMMANDS.md.
- Before any write in the checklist: `droidforge doctor` saves the healthy baseline (health probes + settings
  snapshot) so every later step is compared against the phone as it is now (after "Reset all settings").
- [ ] **P9.1** Checklist written. - [ ] **P9.2** Neo 8 results applied. - [ ] **P9.3** realme 10 results applied.
