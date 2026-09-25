# Changelog

## Unreleased

- App names next to package names (plan preview, debloat list, keep-alive / firewall pickers, CLI keep-alive
  picker): read from each app's own APK (English first), cached per APK version, so the right app is picked.
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
