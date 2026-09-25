# droidforge

TUI + CLI for ColorOS-family Android phones (OPPO / OnePlus / realme), built first for a **realme Neo 8 China ROM**
without root, with a root mode for Magisk / KernelSU / APatch devices.

- English setup guide (you set the language in Settings; droidforge checks it), per-app English for picked user apps, Gboard, Chinese keyboards off
- UAD-NG-rated debloat, force-disable escalation, per-app firewall, telemetry and ad removal, Private DNS
- Google/Firefox default swaps, keep-alive for messengers, power permissions - never touches display, theme or UI settings
- Audit (permissions, signers, live connections), tools (scrcpy, logcat, activity launcher, shell), wireless pairing + Shizuku
- Every action previewed with exact commands, recorded in an undoable history timeline; `--simulate` fake phone

Status: **planning complete, implementation in progress** - see `docs/PLAN.md`. Safety model: `docs/INCIDENT-2026-09-25.md` and SPEC P7-P16 (allowlist, blast-radius diff, health gate, no display/UI or language-config writes).
Until v1.0, `legacy/cnrom_fix.py` is the working single-file tool.

License: GPL-3.0-or-later. Debloat ratings from
[UAD-NG](https://github.com/Universal-Debloater-Alliance/universal-android-debloater-next-generation) (GPL-3.0,
downloaded at runtime).
