# droidforge

TUI + CLI for ColorOS-family Android phones (OPPO / OnePlus / realme), built first for a **realme Neo 8 China ROM**
without root.

- English setup guide (you set the language in Settings; droidforge checks it), per-app English for picked user apps, Gboard, Chinese keyboards off
- UAD-NG-rated debloat, force-disable escalation, per-app firewall, telemetry and ad removal, Private DNS
- Google/Firefox default swaps, keep-alive for messengers, power permissions - never touches display, theme or UI settings
- Audit (permissions, signers, live connections), tools (scrcpy, logcat, activity launcher, shell), wireless pairing + Shizuku
- Every action previewed with exact commands, recorded in an undoable history timeline; HTML session report; `--simulate` fake phone

Status: **v1.0.x** (Phases 0-6 and 8 of `docs/PLAN.md`). Root mode (Magisk / KernelSU / APatch) is planned for v2.
Real-device validation (Phase 9, `docs/DEVICE_CHECKLIST.md`) runs after v1 - read "Before your first real run".

License: GPL-3.0-or-later. Debloat ratings from
[UAD-NG](https://github.com/Universal-Debloater-Alliance/universal-android-debloater-next-generation) (GPL-3.0,
downloaded at runtime).

## Install

Needs Python >= 3.9 and `adb` (Arch: `sudo pacman -S android-tools`; optional `scrcpy`, `libnotify`).

```
pipx install git+https://github.com/futurevoid/droidforge     # any distro
cd packaging/arch && makepkg -si                             # Arch (droidforge-git, builds from GitHub)
droidforge update                                              # later: checks GitHub, upgrades pipx / AUR installs
```

From source: `pip install -e '.[dev]' && pytest -q`.

## First run

```
droidforge --simulate            # try everything on the built-in fake phone first - nothing real is touched
droidforge doctor                # read-only check of your phone; saves the healthy baseline
droidforge                       # the TUI (d = dry-run, v = verbosity, ctrl+t = theme, ctrl+e = expert)
droidforge pair                  # wireless debugging: QR pairing from the terminal
```

Enable **USB debugging** (or **Wireless debugging**) in Developer options; droidforge asks for nothing else there.

## CLI

Every command previews the exact commands and their undo and asks `[y/N]`; `--dry-run` sends nothing.

```
droidforge keepalive                  # pick apps from a numbered list (or name them: keepalive com.whatsapp ...)
droidforge telemetry [--force]    droidforge ads [magazine push launcher feed]    droidforge hijack
droidforge dns [adguard|cloudflare|quad9|mullvad|nextdns --nextdns-id ID|custom --host H|off]
droidforge debloat disable|force|neuter|remove|enable|restore <pkg>...   (droidforge uad-update first)
droidforge firewall block|unblock <pkg>... | firewall reapply
droidforge swap browser|sms|dialer|gallery|files|calendar|contacts|notes [--disable-coloros]
droidforge language open | language apps <pkg>... --locales en-US,ar-EG    droidforge keyboard gboard
droidforge install <apk>... | --folder DIR | --official firefox-nightly | --play <pkg>
droidforge audit perms|signers|net [--json]    droidforge report [--audit]    droidforge update [--check]
droidforge history | undo <id>... | rollback <id> | fix | reapply | export --profile F | apply --profile F
```

## Safety model

droidforge exists because a phone's Settings broke after a developer switch was turned on
(`docs/INCIDENT-2026-09-25.md`). Its rule: never break anything, never change what does not need to change.

- **Allowlist.** Every command must match a row of `docs/COMMANDS.md`; the Forbidden list (device language,
  display / UI settings, developer options, per-app locales on system apps, bulk passes) is refused first.
- **Preview + undo.** Each plan shows the exact commands and their undo (computed from state read before),
  writes a recovery script first, and is recorded in an undoable history.
- **Blast radius.** The phone is snapshotted around every batch of at most 5 packages; anything that changed
  outside what the step declared stops the plan and offers the undo.
- **Health gate.** Settings / launcher / SystemUI / keyboard / network probes run between batches; if anything
  breaks, the TUI says so and offers the repair plan (`droidforge fix`).
- **Expert mode** is needed for critical packages: one per batch, full package name typed, reboot check.

## Before your first real run

Several commands are still marked **V** (verify on device) in `docs/COMMANDS.md`, and the "Disable permission
monitoring" health probe reads "unknown" until Phase 9 records its key. Run `droidforge doctor` first; every
change is undoable (`history` / `rollback`), and a recovery script is written before each plan.
