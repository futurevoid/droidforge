# CLAUDE.md - droidforge

droidforge is a Textual TUI + CLI that English-ifies, debloats, de-ads and hardens ColorOS-family Android phones
over adb (no root), with a root mode for Magisk / KernelSU / APatch. Owner: futurevoid (0xlol). GPL-3.0.

## Read first, every session

0. `docs/INCIDENT-2026-09-25.md` - the legacy tool broke the owner's ColorOS Settings. This is why the rules
   below exist. The owner's standing order: **droidforge must never break anything and must not change anything
   that does not need to change.**
1. `docs/SPEC.md` - requirements (R-ids) and the owner's decision log. Do not re-decide what is decided there.
2. `docs/ARCHITECTURE.md` - layers, package layout, core types.
3. `docs/PLAN.md` - the ordered task list. Find the first unchecked task and work on it.
4. `docs/COMMANDS.md` - the only device/host commands you may use. `docs/PACKAGES.md` - package data.
5. `legacy/cnrom_fix.py` - behavioural reference for the ported features (port behaviour, not structure).
   Its language/config features are Forbidden - see ARCHITECTURE.md "Legacy" for the do-not-port list.

## Workflow

- One PLAN task at a time, in order. Each task ends with: tests added/updated, `ruff check .` clean,
  `pytest -q` green, the PLAN checkbox ticked, one commit `P<phase>.<n>: <summary>`.
- Never commit with failing tests. Never skip a task silently - if blocked, write why under the task in PLAN.md
  and stop to ask.
- If a task reveals a spec gap, add a short "Open question" under the task and ask the owner; do not invent
  requirements.
- Keep `docs/` in sync: new command -> COMMANDS.md row (with source link + status) **and** simulator support in
  the same commit.

## Safety rules (non-negotiable)

- **Never run state-changing adb commands against a real phone.** A real phone may be plugged into this machine.
  Development and tests use `--simulate` / the `sim` fixture only. Read-only probes (`getprop`, `pm list`,
  `dumpsys`, `settings get`, `cmd ... help`) against a real device only when the owner explicitly asks in the
  session. Real-device writes happen through the owner running `docs/DEVICE_CHECKLIST.md` (Phase 9).
- No host commands with sudo from Claude Code. droidforge may *offer* `sudo pacman ...` to its user (previewed).
- Invariants P1-P16 in SPEC.md must stay covered by tests (`test_invariants.py`, `test_guard.py`,
  `test_blast_radius.py`, `test_health.py`). Any new plan builder is registered in `test_invariants.py`.
- **Nothing reaches the device except through `engine/executor.py`**, which runs the guard (allowlist), the
  snapshot/blast-radius diff and the health gate. No feature, tool or UI code calls `Device.sh()` with a write.
  Reads go through `Device.read()`, which the guard also checks against the read allowlist.
- **Never add to the allowlist anything from COMMANDS.md "Forbidden"**, never write the device language or any
  display/UI setting (P9, P9b), never target system packages with per-app locales (P12), never add a bulk pass
  over all packages, never add a "repair" that toggles settings. If a task seems to need one of these, stop and
  ask the owner.
- Critical packages need expert mode (`--expert`, typed name, one per batch, health gate, reboot check). Do not
  add shortcuts around it.
- Out of scope: IMEI/serial changes, leaked keyboxes, targeting devices the operator does not own.

## Code rules

- Python >= 3.9: `from __future__ import annotations` in every module; no `match`; no runtime `X | Y` types;
  use `typing.Optional/Union/List/Dict` where evaluated at runtime (dataclass fields are fine with the future
  import).
- `droidforge.engine`, `droidforge.features`, `droidforge.adb` must not import `textual`.
- Features never talk to the user. They read state, return `Plan`s, and interpret results. UI code only renders
  and confirms.
- Every state-changing `Step` has `undo`, computed from state read before the plan was built.
- Every write `Step` declares `touches`. If you cannot say exactly what a command touches, it does not belong
  in droidforge.
- Reads may be batched through `adb/batch.py` (40 per call, `@@pkg` markers). Writes run in executor batches
  of at most 5 packages with the health gate in between (P13).
- CLI output stays ASCII. Log format follows `legacy/cnrom_fix.py` (`$ adb ...`, `-> exit N | ms | lines`,
  `| out`, `! err`, `. trace`).
- Deps: runtime `textual`, `qrcode`, `platformdirs` only (stdlib for HTTP via urllib, HTML report by hand).
  Ask before adding any dependency.
- Ruff defaults, line length 120, type hints on public functions.

## Commands

```
pip install -e '.[dev]'
pytest -q
ruff check .
droidforge --simulate            # TUI against the fake phone
droidforge --simulate doctor     # CLI against the fake phone
```

## No device-side binaries

droidforge ships nothing that runs on the phone in non-root mode. The legacy locale-setter DEX and its smali source
were deleted from this repo on purpose (INCIDENT-2026-09-25). Do not recreate them or anything like them.
