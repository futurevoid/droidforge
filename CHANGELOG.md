# Changelog

## 1.1.3 - 2026-09-26

- Fixed: doctor and the check at connect flagged harmless things as "changed". Only real problems count now: a
  check that fails, new crashes, or the permission-monitoring switch (at connect). Values that changed but are
  fine - font size, dark mode, accent colour from a new wallpaper, keyboard - are shown as information and become
  the new reference, so they are not reported again. Settings being open or closed is no longer a "change".
- Fixed: plans stopped with "changed something it should not" when ColorOS updated its own counters mid-plan.
  Reviewed ignore-list additions from the owner's diffs: the wallpaper-engine clock (ticks every 60 s), the unlock
  counter, the last screen-off time and the status-bar keyboard switcher state.

## 1.1.2 - 2026-09-25

- Fixed: Enter (pick / unpick) in the debloat table sent the cursor back to the top - it rebuilt the whole
  table. Picking, select-all and clear now change only the checkbox cells; reloading or filtering keeps the
  cursor on the same package.
- Fixed: key presses seemed lost in the keep-alive / firewall app lists while names were loading - each batch of
  names rebuilt the list. Names now update the rows in place; names are searchable.
- Fixed: short freezes while adb works - the log pane wrote each line separately on the screen thread. It now
  writes at most 60 lines per 0.1 s refresh, in one call.

## 1.1.1 - 2026-09-25

- Fixed: the TUI froze while adb was working. Command output on screen is capped (200 lines per command at
  ultra verbosity, the debug log keeps everything), the log pane writes a bounded number of lines per refresh,
  and the debug log is written once per command instead of once per line.
- Fixed: app names made package loading slow and heavy. Lists and pickers now show at once and names fill in
  afterwards in the background, a few apps at a time, without holding up other actions; every read is size-capped
  (`head -c`), its data is never printed to the log, the plan preview reads at most 15 new names, and names are
  cached per APK version.
- `doctor` no longer checks the "Disable permission monitoring" switch (owner decision).

## 1.1.0 - 2026-09-25

- App names next to package names (plan preview, debloat list, keep-alive / firewall pickers, CLI keep-alive
  picker): read from each app's own APK (English first), cached per APK version, so the right app is picked.
- Keep-alive also sets RUN_IN_BACKGROUND, the Android 13+ restriction level `exempted` and the Android 14+
  power-restriction exemption per app. New opt-in phone-wide plan `keepalive --child-processes` (Developer option
  "Disable child process restrictions" + phantom cap), undoable on its own. Every CLI plan prints its own undo
  command and recovery script.
- The "Disable permission monitoring" health probe reads `persist.sys.permission.enable` (confirmed on the Neo 8).

## 1.0.2 - 2026-09-25

- TUI keeps looking for the phone when none is connected at start: plugging in USB or accepting the
  "Allow USB debugging" prompt later connects without a restart.
- Clear messages for Linux USB states: `no permissions` (udev rules), `offline`, `authorizing`.
- ruff rule set pinned to the classic defaults (ruff 0.16 widened its defaults).
- `droidforge update` understands release tags named like `DroidForge-v1.0.2`.

## 1.0.0 - 2026-09-25

First release. Non-root ColorOS-family phones over adb; everything tested against the `--simulate` phone.

- Safety layer: command allowlist + Forbidden list, snapshot / blast-radius diff, health gate (incl. the
  permission-monitoring probe), recovery script before every plan, undoable history and rollback, expert mode
  for critical packages, reboot check after risky plans, breakage alert with repair plan (`fix`).
- English setup guide (language is set by the user in Settings), per-app English for user apps, Gboard setup,
  Chinese keyboards off.
- Debloat with UAD-NG ratings: disable, force-disable escalation, neuter, remove, restore.
- Privacy: telemetry and ads removal, install hijack off, Private DNS presets, per-app firewall.
- Apps: official APK sources, default-app swaps, keep-alive picker, power permissions, region / date format,
  OTA re-apply prompt.
- Tools: scrcpy, logcat, activity launcher, shell pane. Audit: permissions, signers, live connections.
- Wireless pairing (QR / code) and Shizuku.
- CLI for every feature, HTML session report, self-update (`droidforge update`), Arch PKGBUILD.

Deferred: root mode (v2), real-device validation of the **V** commands (Phase 9).
