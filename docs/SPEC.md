# droidforge - Requirements (v1.0)

Owner: 0xlol (futurevoid) - repo `futurevoid/droidforge` - license GPL-3.0
Status: planning complete, implementation not started. Every requirement below comes from an explicit
answer by the owner (see "Decision log" at the end). IDs (R-x.y) are referenced by `PLAN.md` tasks.

## 0. Scope

| | |
|---|---|
| Primary target | realme Neo 8, **China ROM** (realme UI / ColorOS 16 family, Android 16, SDK 36), **no root** |
| Secondary target | realme 10 (global ROM) with **root** - root mode auto-detects Magisk / KernelSU(-Next) / APatch |
| Also works on | any ColorOS-family phone (OPPO / OnePlus / realme); generic Android where commands are AOSP |
| Host | **Arch Linux** only (pacman hints). Python **>= 3.9** |
| UI | **Textual TUI** (theme switcher) + **headless CLI** for scripts/cron |
| Packaging | pipx (`pipx install git+https://github.com/futurevoid/droidforge`) + AUR `droidforge-git` PKGBUILD |
| Release strategy | **one v1.0 release containing everything**, built in ordered phases (see PLAN.md) |

Out of scope (refused, do not implement): IMEI/serial changes; sourcing leaked keyboxes; anything aimed at
devices the operator does not own.

## 1. Principles (hard invariants - each needs tests)

- **P1 Confirm every action.** Nothing that changes the device runs without a preview of the *exact* commands
  (and their undo) and an explicit confirmation. CLI may skip prompts only with `--yes`; hard-locked packages
  additionally need `--allow-locked <pkg,...>` even with `--yes`.
- **P2 Everything reversible.** Every state-changing step carries its undo command(s), computed from the state
  read *before* the change, and is recorded in the history timeline.
- **P3 Everything visible.** Verbosity 1 (results) / 2 (commands, exit, timing, first 15 lines, decisions) /
  3 ULTRA (default: everything, full output, internal calls, cache hits, timestamps). A full debug log is always
  written regardless of level. (Ported from `legacy/cnrom_fix.py`.)
- **P4 Engine and UI are separate.** Features build `Plan`s; TUI and CLI only render/confirm/execute them.
  The engine never imports Textual.
- **P5 Read before write, verify after write.** Features read current state to compute undo; after executing,
  they re-read and report whether the device actually changed.
- **P6 Simulated phone.** `--simulate` runs the whole app against a fake ColorOS phone. All tests use it.

### Safety principles added after the 2026-09-25 incident

See `docs/INCIDENT-2026-09-25.md` (root cause: the ColorOS developer switch "Disable permission monitoring",
turned on on Claude's advice). These override anything below that conflicts with them.

- **P0 Never the permission-monitoring switch.** droidforge never tells the user to enable "Disable permission
  monitoring" / "Disable system optimization" (禁止权限监控) or any other developer-option switch, never writes
  the setting behind it, and has no feature that depends on it. A command ColorOS refuses without that switch
  is reported as unsupported and the feature is dropped. The switch's state is a health probe (R-11.7 #6).

  *Owner exception (2026-09-25):* droidforge may name **USB debugging** and **Wireless debugging** - the adb
  connection switches it cannot work without (connection help, wireless pairing). It never names, suggests or
  writes any other developer option.

  *Owner exception (2026-09-25, later):* keep-alive may write the developer option **"Disable child process
  restrictions"** (`settings_enable_monitor_phantom_procs`) and the `activity_manager` key `max_phantom_processes`,
  in its own opt-in plan (never by default), previewed, with undo to the previous value. The "Disable permission monitoring" switch stays forbidden.

- **P7 Minimal footprint.** A feature touches only the exact package, setting or app-op the user chose.
  No side changes, no "repair" toggles, no bulk passes over every installed package.
- **P8 Command allowlist.** The executor only sends device commands that match a template in
  `droidforge/engine/guard.py` (generated from COMMANDS.md "Allowed writes" / "Allowed reads").
  COMMANDS.md "Forbidden" lists what may never be added.
- **P9 No configuration-level writes.** droidforge never writes the persisted global `Configuration`
  (no `updatePersistentConfiguration`/`updateConfiguration`, no `app_process` helpers, no
  `CHANGE_CONFIGURATION` grants), never `system_locales`/`persist.sys.locale`, never `cmd overlay` writes,
  and never `settings put` on a key outside the allowlist.
- **P9b No display or UI configuration at all (owner decision).** droidforge never writes anything that changes
  how the phone looks: font scale/weight, density/DPI, display size, refresh rate, animation scales, dark/night
  mode, themes, accent/material colours, icon shapes/packs, wallpapers, status-bar icons, navigation mode, time
  and date format, accessibility display options, overlays. These keys and commands are Forbidden (COMMANDS.md)
  and are part of the health baseline, so any change to them is a regression even if something else caused it.
- **P10 Declared blast radius.** Each `Step` declares what it touches. The executor snapshots settings
  (system/secure/global), package states, app locales and the global configuration line before and after each
  plan. Any difference outside the declared keys is flagged as a regression, logged, and undo is offered.
- **P11 Health gate.** Read-only health probes (R-11.7) run before and after every plan. A probe that was
  healthy before and fails after stops the session and offers undo plus the recovery advice.
- **P12 System apps are never language targets.** Per-app locales only on user-picked packages that are not
  in `pm list packages -s`; framework, SystemUI, Settings, PermissionController, launcher, IMEs and every
  overlay/RRO are excluded even if picked.
- **P13 Small steps, checked in between.** Multi-package plans run in batches of at most 5 packages; the health
  probes and blast-radius diff run after each batch, and the first regression stops the plan (later batches are
  not sent). Single changes are one batch.
- **P14 Nothing automatic.** No change is ever made without the P1 confirmation, including OTA re-apply, firewall
  re-apply on connect, and profile import. Read-only work (doctor, audit, health) may run on its own.
- **P15 Always recoverable.** Before every plan a host-side recovery script is written (undo of every step, in
  reverse order, as plain `adb shell` lines) so the phone can be restored even if droidforge crashes midway.
- **P16 Honest limits.** droidforge cannot promise a ROM will never react badly to a supported, reversible change
  (the 2026-09-25 incident came from a call that "worked"). What it guarantees: only allowlisted commands, only
  what the user picked, every change reversible, damage detected right after the change, the plan stopped, undo
  offered, and "Settings > Reset all settings" named as the last resort. The UI states this once, on first run.

## 2. Connection & devices

- **R-2.1** USB adb auto-detect; device picker; one active device at a time; switch without restarting.
- **R-2.2** Wireless pairing: QR code drawn in the TUI (`WIFI:T:ADB;S:<name>;P:<password>;;`), discovery through
  `adb mdns services` (`_adb-tls-pairing._tcp`), then `adb pair ip:port password` and connect
  (`_adb-tls-connect._tcp`). Fallback: type `ip:port` + 6-digit code. Remember paired devices.
- **R-2.3** Shizuku: if not installed, download the latest APK from the **RikkaApps/Shizuku GitHub release** and
  install it; **auto-start on every connect** (libshizuku.so path from `pm path`, fallback `start.sh`). Show status.
- **R-2.4** Per-device profiles keyed by serial (+ model), auto-selected on connect; **export/import** as JSON.
  Import of the legacy `cnrom_state.json` is supported.
- **R-2.5** OTA detection: store `ro.build.fingerprint` in the profile. On change: show what the update
  re-enabled/reinstalled/reset vs the profile, then **prompt** to re-apply (never automatic).
- **R-2.6** Missing host tools: adb -> `sudo pacman -S android-tools`; scrcpy -> `sudo pacman -S scrcpy`.
  Offer to run the command (it is a host command, still previewed/confirmed).
- **R-2.7** Desktop notifications through `notify-send` (if present): long job finished, device disconnected,
  OTA detected.
- **R-2.8** `doctor` (read-only): SDK, ROM family, root flavor, Shizuku state, `cmd locale` support,
  firewall-chain support, the R-11.7 health probes, and droidforge's history on this device. Recovery advice in
  order: (1) if the permission-monitoring switch is on, turn it off and reboot; (2) undo droidforge's recent
  plans; (3) **Settings > Reset all settings** (keeps apps and data - it also resets developer options). It never
  tries to repair configuration itself.

## 3. Language & input (rewritten after the incident: P9, P12)

- **R-3.1** Device language is set by the user in the phone's own Settings, never by droidforge.
  droidforge reads the current list (`getprop persist.sys.locale`, `settings get system system_locales`, both
  read-only), and if Chinese is first it opens `android.settings.LOCALE_SETTINGS` with short instructions
  (add English, drag it to the top, optionally add Arabic), then re-reads and reports. The legacy DEX setter,
  MoreLocale and every `CHANGE_CONFIGURATION` path are removed (see COMMANDS.md "Forbidden").
- **R-3.2** Per-app language (kept by owner decision, health-gated), for single stubborn apps only: the user picks apps from a list that already
  excludes system packages and every package covered by P12. One `cmd locale set-app-locales` per picked app,
  previous value recorded for exact undo. There is no "all apps" option.
- **R-3.3** Regional formats and time: droidforge only **opens** Regional preferences
  (`android.settings.REGIONAL_PREFERENCES_SETTINGS`, API 34+) and Date & time (`android.settings.DATE_SETTINGS`).
  It writes no time, date or format settings (owner decision).
- **R-3.4** Keyboard: switch to Gboard (`ime enable` + `ime set`), optionally disable the ROM's Chinese IMEs
  (only after Gboard is confirmed as the current IME), and remove the ColorOS secure keyboard for user 0
  (PACKAGES.md; the owner wants it gone). Gboard's layouts follow the system languages the user set in
  Settings; droidforge opens Gboard's language screen for the rest. Undo restores the previous default IME,
  and restore logic only ever selects an IME that was the default before (never a remote/accessory IME).

## 4. Debloat (ported + extended)

- **R-4.1** UAD-NG list (downloaded at runtime, cached, GPL-3.0) with Recommended/Advanced/Expert/Unsafe ratings,
  descriptions, `neededBy` warnings. **No default preset: always show the list and ask.**
- **R-4.2** Actions: disable, **force-disable escalation** (disable -> suspend -> uninstall user 0 ->
  firewall + neuter; automatic after one confirmation per owner decision, but the preview lists every stage up
  front, each stage is its own batch, and health + blast-radius checks run after each stage), neuter (revoke runtime perms + background/notification/overlay app-ops), remove (user 0),
  enable/unsuspend/un-neuter, restore (install-existing), info.
- **R-4.3** Critical packages are **locked**: SystemUI, telephony/IMS, GMS/GSF/Play Store, WebView,
  networkstack, framework, current keyboard, current launcher, UAD Unsafe, and the R-4.3b UI infrastructure.
  They can only be touched in **expert mode** (owner decision 2026-09-25): start with `--expert` (TUI: toggle
  in the header, red banner while on), then type the full package name per package. Expert actions are always
  batches of one, health-gated, followed by the reboot check (R-11.9). Outside expert mode they are listed as
  "locked" and cannot be selected.
- **R-4.3b** UI infrastructure is hidden from package lists by default and locked when shown (toggle
  "show system UI infrastructure"): `android`, `oplus`, every overlay / RRO (`*overlay*`, `*.rro*`,
  `*auto_generated_characteristics_rro`), `com.oplus.uxdesign`, `com.oplus.uiengine`, `com.oplus.systemui.plugins`,
  `com.android.settings*`, `com.android.permissioncontroller`, `com.oplus.securitypermission`.
- **R-4.4** Keep-list (warn, excluded from bulk "select all" unless explicitly added): **Game space**
  (`com.coloros.gamespace`, `com.coloros.gamespaceui`, `com.oplus.games`, `com.oplus.stdid`) and **Smart sidebar**
  (`com.coloros.smartsidebar`, plus any installed `*smartsidebar*`).
- **R-4.5** Heuristic "guarded" packages (unknown to UAD but look critical) keep the `I UNDERSTAND` phrase.

## 5. Privacy & ads

- **R-5.1** Kill telemetry: curated preset (docs/PACKAGES.md "telemetry"), filtered to installed packages, previewed.
- **R-5.2** Private DNS: **AdGuard default** (`dns.adguard-dns.com`); menu also offers Cloudflare, Quad9, Mullvad,
  NextDNS (asks for ID), custom hostname, off. Previous mode/specifier recorded for undo.
- **R-5.3** Stop install hijack: disable `com.oplus.appdetail` (ColorOS "secure app installation"), optionally
  `verifier_verify_adb_installs 0` / `package_verifier_enable 0` (flagged as lowering protection), silence HeyTap
  store notifications.
- **R-5.4** Ads/promos, all four: lock-screen magazine (`com.heytap.pictorial`; **never** `com.coloros.pictorial`,
  UAD Unsafe - breaks lock-screen settings), system push promos (store/theme/game-center/mcs notifications off),
  launcher suggestions (`com.opos.cs` hot apps, quick-search boxes), -1 screen feed (`com.coloros.assistantscreen`).
- **R-5.5** Non-root firewall: per-app internet block for **any** app via connectivity firewall chain 3
  (`cmd connectivity set-chain3-enabled true`, `set-package-networking-enabled false <pkg>`). Rules reset on
  reboot (platform behaviour): on connect droidforge detects missing rules and **asks** to re-apply them (P14).
  Also the last stage of force-disable (R-4.2).

## 6. Apps & defaults

- **R-6.1** Install sources, choosable per app: open Play Store page on the phone; download APK from an
  **official** source only (GitHub releases, F-Droid, Mozilla) and `adb install`; bulk-install a local folder
  (splits via `install-multiple`).
- **R-6.2** Default swaps (roles where Android has them; never disable ColorOS telephony components):
  - Browser -> **Firefox Nightly** (`org.mozilla.fenix`), role `android.app.role.BROWSER`
  - Gallery -> Google Photos; Files -> Files by Google (no role; optional disable of the ColorOS app with a
    warning that the camera's thumbnail shortcut may break)
  - SMS -> Google Messages (role SMS); Dialer -> Google Phone (role DIALER). `com.android.contacts`,
    `com.android.incallui`, `com.android.mms` are never disabled. After swap, show IMS/VoLTE status and ask for a
    test call.
  - Calendar -> Google Calendar; Contacts -> Google Contacts; Notes -> Google Keep
- **R-6.3** Keep-alive for apps **the user picks**: deviceidle whitelist, `RUN_ANY_IN_BACKGROUND allow`,
  standby bucket `active`, display over other apps (`SYSTEM_ALERT_WINDOW allow`), then open ColorOS's app info for
  the part adb cannot set (auto launch, background activity, pop-ups while running in background).
- **R-6.4** Power permissions: presets (Tasker, SystemUI Tuner, Automate, MacroDroid - only if installed) + custom
  app/permission: `WRITE_SECURE_SETTINGS`, `READ_LOGS`, `DUMP`, `PACKAGE_USAGE_STATS` (app-op `GET_USAGE_STATS`).

## 7. Tweaks - removed (P9b)

No display, UI, animation, refresh-rate, font, density, status-bar or time-format tweaks. The earlier R-7.x items
are withdrawn by the owner (2026-09-25).

## 8. Audit

- **R-8.1** Permission audit: every app's granted dangerous permissions + notable app-ops; sortable/filterable
  table; revoke from the table (goes through P1/P2).
- **R-8.2** Signer check: group packages by signing-certificate digest from `dumpsys package`; label groups by
  reference packages (`android` = platform, `com.google.android.gms` = Google, a known OPPO/realme app = OEM,
  rest = third-party/unknown).
- **R-8.3** Live connections: parse `/proc/net/{tcp,tcp6,udp,udp6}`, map UID -> package (`pm list packages -U`),
  refresh loop; best-effort without root, full with root.

## 9. Tools (TUI tabs)

- **R-9.1** scrcpy launcher (serial-aware; options: screen off, stay awake, record to file).
- **R-9.2** Live logcat pane: filters for focused app (pid), level, tag, regex; pause/clear/save.
- **R-9.3** Hidden activity launcher: curated intents (Developer options, app languages, regional prefs, battery
  optimisation, default apps, radio info...) + browse exported activities of any package; non-exported via root.
- **R-9.4** adb shell pane (line-based; each line runs `adb shell`; history; output into log). This is the user's
  own manual terminal, outside P8: lines that look like writes (`put`, `disable`, `uninstall`, `grant`, `set`,
  `clear`, `rm`) need a second Enter, and every line is recorded in history as "manual - no automatic undo".

## 10. Root mode (realme 10) - auto-detect Magisk / KernelSU(-Next) / APatch

- **R-10.1** Detect flavor + version; module install via the flavor's CLI; list/enable/disable/remove modules.
- **R-10.2** Systemless removal: build a `droidforge_debloat` module on the host that hides chosen system apps
  (Magisk `.replace` dirs; KernelSU/APatch `REMOVE=` whiteouts). Reversible by removing the module.
- **R-10.3** Persistent firewall: module `service.sh` with `iptables`/`ip6tables -m owner --uid-owner` rules.
- **R-10.4** Hosts blocking: module shipping `system/etc/hosts` built from a downloaded blocklist (StevenBlack
  unified by default).
- **R-10.5** Prop tweaks through `resetprop`, limited to an allowlist of Play-Integrity/build-identity props
  (`ro.build.fingerprint`-family, `ro.product.*` spoof values used by PI modules); display, density, locale,
  font, theme and UI props are Forbidden (P9, P9b). Prior values saved for undo.
- **R-10.6** Play Integrity helpers: check Zygisk availability (Magisk Zygisk, or ZygiskNext/ReZygisk/NeoZygisk on
  KSU/APatch), download + install **Play Integrity Fork** (osm0sis) and **Tricky Store** (official release), write
  Tricky Store `target.txt`, open a Play Integrity checker's Play page. No keybox sourcing.

## 11. Safety, history, backup, reporting

- **R-11.1** Plan preview for every action (P1): title, steps, exact commands, undo commands, risk badges.
- **R-11.2** **History timeline**: every executed step is an entry (time, device, fingerprint, category, command,
  result, undo). Undo any single entry, or roll back to a point in time (undo newer entries newest-first).
  Undo is itself a previewed plan.
- **R-11.3** Backups: full settings dump (`system`/`secure`/`global`), package snapshot, app locales and the global
  configuration line at every session start. These are evidence and diff baselines. Restore only reverts keys
  droidforge itself changed (from history); there is **no blanket settings restore** (writing hundreds of keys is
  its own risk). For damage droidforge did not cause, `doctor` recommends Settings > Reset all settings.
- **R-11.4** HTML session report (standalone file): device, what changed, what failed, audit results, undo hints.
- **R-11.5** Dry-run mode: plans are shown and "executed" without touching the device.
- **R-11.6** Debug log always complete (commands, exit codes, full stdout/stderr, traces, tracebacks).
- **R-11.7** Health probes (all read-only, baseline taken at session start):
  1. Settings home resolves to the ROM's own activity (`cmd package resolve-activity --brief -a
     android.settings.SETTINGS`; ColorOS: `com.oplus.settings...`).
  2. Permission UI resolves as at baseline (`... -a android.intent.action.MANAGE_APP_PERMISSIONS`).
  3. Global configuration fields unchanged vs baseline except those a step declared: locale list, font scale,
     density, night flag, and on ColorOS `mMaterialColor`, `mUxIconConfig`, `mFontVariationSettings`,
     `mDarkMode*` (parsed from `dumpsys activity | grep -m1 mGlobalConfig`).
  4. `font_scale`, `ui_night_mode` / `cmd uimode night`, default IME and default launcher as at baseline unless
     declared.
  5. SystemUI and Settings processes alive; crash buffer (`logcat -b crash`) has no new entries for them.
  6. **"Disable permission monitoring" is off.** Read-only check of the setting behind the switch (key found in
     Phase 9, COMMANDS.md "Health probes"). If it is on - even if droidforge did not turn it on - the breakage
     alert says: "ColorOS developer switch 'Disable permission monitoring' is ON. It breaks the Settings and
     permission screens. Turn it off: Developer options > bottom of the list, then reboot." droidforge does not
     flip it itself; it opens Developer options for the user.
- **R-11.9** Reboot check: after risky plans (debloat of any system app, keyboard/default-app changes, expert
  actions, every root action) droidforge offers "reboot now and re-check"; after boot it waits for
  `sys.boot_completed=1`, re-runs the health probes and snapshot against the pre-plan baseline, and offers undo on
  any regression.
- **R-11.8** Blast-radius diff (P10): before/after snapshots of R-11.3 data around every plan; undeclared changes
  are listed per key/package with an undo plan built from the "before" snapshot.

## 12. Interface

- **R-12.1** Textual TUI: sidebar of sections, main panel, collapsible bottom log pane (live adb traffic at the
  current verbosity), header with device/profile/root/Shizuku/verbosity/dry-run state.
- **R-12.5** **Breakage alert (owner requirement): if anything broke, the TUI tells the user and asks to fix it.**
  Triggers: a health regression or undeclared change after any plan or batch (P10/P11), after the reboot check
  (R-11.9), and at every connect/startup when the phone differs from the last healthy baseline saved for that
  device (so breakage between sessions is caught too). The alert is a modal that cannot be missed: what broke
  (plain words + the raw value before/after), what droidforge changed just before it (history entries), and
  buttons **Fix it** / Details / Ignore. **Fix it** builds and shows the repair plan: undo of the droidforge
  plan(s) involved, newest first, plus a revert of each undeclared change from the "before" snapshot when the
  key is in the allowlist; it runs through the same guard + health gate, then re-checks and reports whether the
  phone is healthy again. If nothing droidforge did explains it, or the revert does not bring the probe back,
  the alert says so and gives the manual path: **Settings > Reset all settings** (keeps apps and data). The CLI
  prints the same and exits non-zero; `droidforge fix` runs the repair plan. Ignored alerts stay listed on the
  dashboard until the phone is healthy.
- **R-12.2** Theme switcher: Textual built-in themes + a custom **"hacker"** theme (black, green/amber).
  Choice persisted.
- **R-12.3** Headless CLI (same engine): e.g. `droidforge apply --profile neo8.json`, `droidforge reapply`,
  `droidforge undo <id>`, `droidforge audit perms --json`, `droidforge doctor`, `droidforge --simulate ...`.
- **R-12.4** Self-update from GitHub releases of `futurevoid/droidforge`: check latest tag, detect install method
  (pipx / AUR / source) and run or print the right upgrade command.

## 13. Packaging

- **R-13.1** `pyproject.toml` (hatchling), console script `droidforge`, runtime deps: `textual`, `qrcode`,
  `platformdirs`. No device-side binaries or DEX files are shipped (P9).
- **R-13.2** AUR `droidforge-git` PKGBUILD in `packaging/arch/`. **R-13.3** GitHub Actions: pytest on 3.9 + latest.

## Decision log (owner answers, 2026-09-25)

| Topic | Answer |
|---|---|
| Host OS | Linux - Arch/Manjaro |
| Privacy | kill telemetry, Private DNS blocking, stop install hijack |
| Default swaps | browser, gallery/files, SMS/dialer; plus calendar+contacts, notes->Keep |
| Browser | Firefox Nightly |
| App install | all of: Play pages, official APK download, local folder |
| UI tweaks / region | ~~optional menus~~ withdrawn 2026-09-25 (P9b): no display/UI/time writes |
| Timezone | ~~automatic from network~~ withdrawn 2026-09-25: Date & time screen is only opened |
| Connection | USB + wireless (QR + code) + Shizuku (install + auto-start) |
| Root mode | yes - auto-detect + Play Integrity helpers; extras: systemless removal, persistent firewall, hosts, props |
| Debloat default | always ask |
| Interface | Textual TUI + headless CLI, theme switcher |
| Keep-alive | yes, user picks apps |
| Backups | settings dump + package snapshot |
| Private DNS | AdGuard default |
| Keep features | Game space, Smart sidebar |
| Firewall / locks | "all apps must be disableable" -> revised 2026-09-25: critical packages need expert mode; firewall fallback kept |
| Ads | lock-screen magazine, push promos, launcher suggestions, -1 feed |
| Tools | scrcpy, live logcat, hidden activity launcher, shell pane |
| OTA | allow updates; detect + prompt re-apply |
| Confirmation | every action (preview exact commands) |
| Audit | permission audit, signer check, live connections |
| Undo | history timeline |
| Pairing | QR + code |
| Profiles | per-device + export/import |
| Updates | self-update from futurevoid/droidforge |
| Report | HTML |
| Gboard | English + Arabic |
| Power perms | presets + custom |
| Packaging | AUR PKGBUILD + pipx |
| License | GPL-3.0 |
| Sim mode | yes |
| Multi-phone | switch between (one active) |
| Notifications | notify-send |
| Build order | everything in v1.0; phases Neo 8 -> tools -> audit -> root; milestone + tests + commit workflow |
| Python | >= 3.9 |
| Critical packages | locked; `--expert` + typed name + health gate + reboot check |
| Force-disable escalation | automatic after one confirm; health-gated per stage |
| Display / UI | never touched (font, DPI, refresh, animations, dark mode, theme, colours, icons, status bar, time format) |
| Per-app language | kept for user-picked non-system apps, health-gated |
| Time settings | none written; screens only opened |
| Reboot check | offered after risky plans |
| Legacy cnrom_fix.py | stripped of language/config features now; retired when droidforge v1 ships |
| Developer options wording | USB debugging and Wireless debugging may be named (adb connection); every other developer option stays forbidden (P0 exception) |
| Self-changing settings | A reviewed ignore-list of settings the ROM changes on its own (screen brightness, next alarm): logged and reported, never a stop reason. Display/UI keys (P9b) can never be on it; it grows only from Phase 9 findings |
| Keep-alive, phone-wide (2026-09-25) | Owner: apps must not be killed. Allowed as a separate opt-in plan, off by default, undoable on its own: "Disable child process restrictions" + the phantom-process cap (the background CPU limit was considered and dropped by the owner). Per-app keep-alive adds RUN_IN_BACKGROUND, the Android 13+ restriction level `exempted` and the Android 14+ power-restriction exemption. Every plan prints its own undo command and recovery script |
| Keep-alive pop-ups (2026-09-26) | Owner: apps that react in the background (e.g. play audio on unlock) also need "display over other apps"; per-app keep-alive adds `SYSTEM_ALERT_WINDOW allow` (undo: previous mode). ColorOS's "Show pop-ups while running in background" is not adb-writable, so the plan's note sends the user to App info > Permissions |
| Doctor and the switch (2026-09-25) | Owner: `doctor` no longer checks or mentions the "Disable permission monitoring" switch (kept on for Shizuku when needed). The executor health gate and the TUI breakage check still read it (R-11.7 #6) |
| Doctor / connect check: problems only (2026-09-26) | Owner: between sessions only a probe that now fails, new crashes or (at connect) the permission-monitoring switch are problems. Changed-but-passing values (font size, dark mode, accent colour, keyboard) are information and become the new reference. Settings being open or closed is never a change. Self-changing ColorOS keys from the owner's diffs join the reviewed ignore-list (the wallpaper-engine clock is reviewed by name: a timestamp, not a display setting) |
| Publishing v1 | PR to main, then tag v1.0.0 on main |
| v1 scope (2026-09-25, later) | v1 is published with Phases 0-6 and 8; root mode (Phase 7) moves to v2; the real-device validation (Phase 9) is deferred and runs after v1. The V-status commands stay marked V until then |
| Incident 2026-09-25 | ColorOS "Disable permission monitoring" switch (turned on on Claude's advice) broke Settings; Reset all settings turned it off. Owner confirmed. Owner order: never break anything, never change what doesn't need changing -> P0, P7-P16, R-11.7 #6. Initially blamed on the legacy language setter (kept forbidden as defence in depth). Owner: droidforge must not change anything it does not need to and must not be able to cause this again -> P7-P12, R-3 rewrite, R-11.7/11.8 |
