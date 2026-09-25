# droidforge

TUI + CLI for ColorOS-family Android phones (OPPO / OnePlus / realme), built first for a **realme Neo 8 China ROM**
without root, with a root mode for Magisk / KernelSU / APatch devices.

- English setup guide (you set the language in Settings; droidforge checks it), per-app English for picked user apps, Gboard, Chinese keyboards off
- UAD-NG-rated debloat, force-disable escalation, per-app firewall, telemetry and ad removal, Private DNS
- Google/Firefox default swaps, keep-alive for messengers, power permissions - never touches display, theme or UI settings
- Audit (permissions, signers, live connections), tools (scrcpy, logcat, activity launcher, shell), wireless pairing + Shizuku
- Every action previewed with exact commands, recorded in an undoable history timeline; `--simulate` fake phone

Status: **MVP (Phases 0-4 done)** - see `docs/PLAN.md`. Phases 5-8 (tools, audit, root, packaging) and the
real-device validation (Phase 9) are still to come. Safety model: `docs/INCIDENT-2026-09-25.md` and SPEC P7-P16 (allowlist, blast-radius diff, health gate, no display/UI or language-config writes).
Until v1.0, `legacy/cnrom_fix.py` is the working single-file tool.

License: GPL-3.0-or-later. Debloat ratings from
[UAD-NG](https://github.com/Universal-Debloater-Alliance/universal-android-debloater-next-generation) (GPL-3.0,
downloaded at runtime).

## Using the MVP

```
pipx install git+https://github.com/futurevoid/droidforge@claude/eloquent-galileo-bxskuz
droidforge --simulate            # try everything on the built-in fake phone first
droidforge doctor                # read-only check of your phone; saves the healthy baseline
droidforge                       # the TUI (d = dry-run, v = verbosity, ctrl+t = theme, ctrl+e = expert)
```

CLI (every command previews the exact commands + undo and asks `[y/N]`; `--dry-run` sends nothing):

```
droidforge keepalive                  # pick apps from a numbered list (or name them: keepalive com.whatsapp ...)
droidforge telemetry [--force]    droidforge ads [magazine push launcher feed]    droidforge hijack
droidforge dns [adguard|cloudflare|quad9|mullvad|nextdns --nextdns-id ID|custom --host H|off]
droidforge debloat disable|force|neuter|remove|enable|restore <pkg>...   (droidforge uad-update first)
droidforge firewall block|unblock <pkg>... | firewall reapply
droidforge swap browser|sms|dialer|gallery|files|calendar|contacts|notes [--disable-coloros]
droidforge language open | language apps <pkg>... --locales en-US,ar-EG    droidforge keyboard gboard
droidforge install <apk>... | --folder DIR | --official firefox-nightly | --play <pkg>
droidforge history | undo <id>... | rollback <id> | fix | reapply
```

Before anything else on a real phone: several commands are still marked **V** (verify on device) in
`docs/COMMANDS.md`, and the "Disable permission monitoring" health probe reads "unknown" until Phase 9 records
its key. Every change is undoable (`history` / `rollback`), and a recovery script is written before each plan.
