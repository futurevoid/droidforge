"""Command-line entry point. No subcommand -> launch the TUI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, List, Optional

from droidforge import __version__, config
from droidforge.engine.health import RESET_ALL_SETTINGS
from droidforge.engine.plan import Confirmation, Plan
from droidforge.log import LOG, ascii_safe, console_sink
from droidforge.session import ConnectError, Session, open_session

# tests replace this to hand the CLI a prepared simulated phone
SESSION_FACTORY: Callable[..., Session] = open_session

EXPERT_BANNER = ("!!! EXPERT MODE: locked packages (SystemUI, telephony, Play services, WebView, UI infrastructure, "
                 "current keyboard/launcher, UAD Unsafe) can be selected. One package per batch, type its full "
                 "name, health check after each, reboot check afterwards. !!!")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="droidforge",
        description="English-ify, debloat, de-ad and harden ColorOS-family Android phones over adb.",
    )
    p.add_argument("--version", action="version", version=f"droidforge {__version__}")
    p.add_argument("--simulate", action="store_true", help="run against the simulated ColorOS phone")
    p.add_argument("--serial", help="adb serial of the phone to use")
    p.add_argument("--dry-run", action="store_true", help="show and log plans without touching the phone (R-11.5)")
    p.add_argument("--expert", action="store_true",
                   help="expert mode: locked (critical) packages become selectable - one per batch, full package "
                        "name typed, health check and reboot check")
    lv = p.add_mutually_exclusive_group()
    lv.add_argument("-q", "--quiet", dest="verbosity", action="store_const", const=1, help="results only")
    lv.add_argument("-v", "--verbose", dest="verbosity", action="store_const", const=2,
                    help="commands, exit codes, timing, first 15 lines")
    lv.add_argument("--ultra", dest="verbosity", action="store_const", const=3, help="everything (default)")
    p.add_argument("-y", "--yes", action="store_true", help="skip the [y/N] prompt (typed strings still needed)")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("doctor", help="read-only health and capability report (never changes the phone)")
    sub.add_parser("fix", help="breakage check vs the last healthy baseline; offers the repair plan (R-12.5)")
    add_plan_commands(sub)
    return p


def add_plan_commands(sub: "argparse._SubParsersAction") -> None:
    """Every plan builder is reachable from the CLI (P4.10). Each prints the preview and asks (P1)."""
    d = sub.add_parser("debloat", help="disable / force / neuter / remove / enable / restore packages")
    d.add_argument("action", choices=["disable", "force", "neuter", "remove", "enable", "restore"])
    d.add_argument("packages", nargs="+")
    t = sub.add_parser("telemetry", help="kill telemetry (curated preset)")
    t.add_argument("--opt-in", action="store_true", help="also com.oplus.cosa")
    t.add_argument("--force", action="store_true", help="force-disable escalation")
    a = sub.add_parser("ads", help="remove ads / promos")
    a.add_argument("categories", nargs="*", default=["magazine", "push", "launcher", "feed"],
                   choices=["magazine", "push", "launcher", "feed"])
    h = sub.add_parser("hijack", help="stop the install hijack")
    h.add_argument("--lower-verification", action="store_true", help="also switch off adb install verification "
                   "(LOWERS PROTECTION)")
    h.add_argument("--no-store-notifications", action="store_true")
    n = sub.add_parser("dns", help="Private DNS (default AdGuard)")
    n.add_argument("provider", nargs="?", default="adguard")
    n.add_argument("--nextdns-id")
    n.add_argument("--host", help="custom DNS-over-TLS hostname (provider 'custom')")
    f = sub.add_parser("firewall", help="per-app internet block (chain 3)")
    f.add_argument("action", choices=["block", "unblock", "reapply"])
    f.add_argument("packages", nargs="*")
    i = sub.add_parser("install", help="install apps: APK files, a folder, an official download, or a Play page")
    i.add_argument("apks", nargs="*")
    i.add_argument("--folder")
    i.add_argument("--official", help="catalog key, e.g. firefox-nightly, shizuku")
    i.add_argument("--play", help="package whose Play Store page to open on the phone")
    w = sub.add_parser("swap", help="default-app swap (browser, sms, dialer, gallery, files, calendar, ...)")
    w.add_argument("function")
    w.add_argument("--disable-coloros", action="store_true")
    k = sub.add_parser("keepalive", help="keep picked apps alive in the background")
    k.add_argument("packages", nargs="+")
    k.add_argument("--remove", action="store_true")
    pp = sub.add_parser("powerperms", help="grant power permissions")
    pp.add_argument("--preset", nargs="*", default=[])
    pp.add_argument("--app")
    pp.add_argument("--perm", nargs="*", default=[],
                    choices=["WRITE_SECURE_SETTINGS", "READ_LOGS", "DUMP", "PACKAGE_USAGE_STATS"])
    lg = sub.add_parser("language", help="open Settings > Language, or per-app language for your own apps")
    lg.add_argument("action", choices=["open", "apps", "reset"])
    lg.add_argument("packages", nargs="*")
    lg.add_argument("--locales", default="en-US")
    kb = sub.add_parser("keyboard", help="Gboard / Chinese keyboards off / secure keyboard / Gboard languages")
    kb.add_argument("action", choices=["gboard", "chinese-off", "secure", "languages"])
    rg = sub.add_parser("region", help="open Regional preferences or Date & time")
    rg.add_argument("action", choices=["regional", "datetime"])
    sub.add_parser("reapply", help="re-apply the saved profile (after an OTA update)")
    sub.add_parser("history", help="list the history timeline")
    u = sub.add_parser("undo", help="undo history entries")
    u.add_argument("ids", nargs="+")
    rb = sub.add_parser("rollback", help="undo an entry and everything newer")
    rb.add_argument("id")
    sub.add_parser("uad-update", help="download the UAD-NG package list (about 1.6 MB, GitHub)")


def preview_lines(plan: Plan) -> List[str]:
    out = [f"Plan: {plan.title}  ({len(plan.steps)} step(s), {len(plan.batches())} batch(es))"]
    for i, st in enumerate(plan.steps, 1):
        out.append(f" {i:>2}. [{st.risk.upper()}] {st.label}")
        out.append(f"       {'host' if st.host else 'adb shell'}: {st.cmd}")
        out += [f"       undo: {u}" for u in st.undo]
        out += [f"       then if refused: {fb.cmd}" for fb in st.fallbacks]
    out += [f" ! {n}" for n in plan.notes]
    return out


def cli_confirm(yes: bool, ask: Optional[Callable[[str], str]] = None) -> Callable[[Plan], Confirmation]:
    """P1 for the CLI: print the exact commands and undo, ask [y/N] (--yes skips), ask for every typed string."""
    def hook(plan: Plan) -> Confirmation:
        prompt = ask or input
        for line in preview_lines(plan):
            print(ascii_safe(line))
        typed = []
        for t in plan.typed:
            try:
                typed.append(prompt(f"Type exactly '{t}' to confirm: "))
            except EOFError:
                return Confirmation(False)
        if yes:
            return Confirmation(True, typed)
        try:
            answer = prompt("Run this plan? [y/N]: ").strip().lower()
        except EOFError:
            answer = ""
        return Confirmation(answer in ("y", "yes"), typed)
    return hook


def _setup_logging(verbosity: Optional[int]) -> config.Config:
    cfg = config.Config()
    LOG.verbosity = verbosity or cfg.get("verbosity", 3)
    LOG.debug_path = cfg.paths.debug_log
    return cfg


def cmd_doctor(s: Session) -> int:
    from droidforge.features import doctor
    rep = doctor.run(s.device, s.profile, s.history, backup_dir=config.paths().sub("backups"))
    for line in rep.lines():
        print(ascii_safe(line))
    return 0 if rep.healthy else 2


def run_tui(args: argparse.Namespace) -> int:
    from droidforge.tui.app import DroidforgeApp
    DroidforgeApp(simulate=args.simulate, serial=args.serial, expert=args.expert, dry_run=args.dry_run).run()
    return 0


def cmd_fix(s: Session, yes: bool) -> int:
    from droidforge.engine import executor
    from droidforge.features import fix
    b = fix.check_startup(s.device, s.profile, s.history)
    if b is None:
        print("The phone matches its last healthy check - nothing to fix.")
        return 0
    for line in b.lines():
        print(ascii_safe(line))
    if not b.explained or b.repair is None:
        return 2   # nothing droidforge did explains it: no automatic writes
    rep = executor.run(b.repair, s.device, cli_confirm(yes), dry_run=s.dry_run, history=s.history,
                       profile=s.profile, expert_mode=s.expert)
    if rep.status != "done":
        print(f"Repair plan {rep.status}{': ' + rep.error if rep.error else ''}")
        return 2
    regs = fix.recheck(s.device, s.profile)
    if regs:
        print("Still not right after the repair:")
        for r in regs:
            print(ascii_safe(f"  ! {r}"))
        print(ascii_safe(f"Manual path: {RESET_ALL_SETTINGS}"))
        return 2
    print("Healthy again.")
    return 0


def build_plan(args: argparse.Namespace, s: Session) -> Optional[Plan]:
    from droidforge.data import uad
    from droidforge.features import (
        ads, apps, debloat, defaults, dns, firewall, keepalive, keyboard, language, powerperms, privacy, region)
    dev, ex, data = s.device, s.expert, uad.load_cached()
    c = args.command
    if c == "debloat":
        if args.action == "enable":
            return debloat.enable_plan(dev, args.packages, s.profile, data, ex)
        fn = {"disable": debloat.disable_plan, "force": debloat.force_plan, "neuter": debloat.neuter_plan,
              "remove": debloat.remove_plan, "restore": debloat.restore_plan}[args.action]
        return fn(dev, args.packages, data, ex)
    if c == "telemetry":
        return privacy.telemetry_plan(dev, data, args.opt_in, args.force, ex)
    if c == "ads":
        return ads.ads_plan(dev, args.categories, data, ex)
    if c == "hijack":
        return privacy.install_hijack_plan(dev, data, args.lower_verification, not args.no_store_notifications, ex)
    if c == "dns":
        return dns.dns_plan(dev, args.provider, args.nextdns_id, args.host)
    if c == "firewall":
        if args.action == "reapply":
            return firewall.reapply_plan(dev, s.profile, data, ex)
        if args.action == "block":
            return firewall.block_plan(dev, args.packages, data, ex, s.profile)
        return firewall.unblock_plan(dev, args.packages, data, ex)
    if c == "install":
        if args.play:
            return apps.play_plan(dev, args.play)
        if args.folder:
            return apps.folder_plan(dev, Path(args.folder))
        if args.official:
            return apps.install_plan(dev, [apps.download(args.official, config.paths().sub("cache"))])
        return apps.install_plan(dev, [Path(a) for a in args.apks])
    if c == "swap":
        return defaults.swap_plan(dev, args.function, args.disable_coloros, data, ex)
    if c == "keepalive":
        return keepalive.remove_plan(dev, args.packages) if args.remove else keepalive.keepalive_plan(
            dev, args.packages, data, ex)
    if c == "powerperms":
        if args.preset:
            return powerperms.preset_plan(dev, args.preset)
        return powerperms.grant_plan(dev, {args.app: args.perm} if args.app else {}, data, ex)
    if c == "language":
        if args.action == "open":
            return language.open_language_settings(dev)
        if args.action == "reset":
            return language.reset_app_language_plan(dev, args.packages, s.profile.app_locale_prev)
        return language.app_language_plan(dev, args.packages, args.locales)
    if c == "keyboard":
        return {"gboard": keyboard.gboard_plan, "chinese-off": keyboard.chinese_imes_plan,
                "secure": keyboard.secure_keyboard_plan, "languages": keyboard.gboard_languages_plan}[args.action](dev)
    if c == "region":
        return region.regional_plan(dev) if args.action == "regional" else region.datetime_plan(dev)
    if c == "reapply":
        from droidforge.features import ota
        rep = ota.check(dev, s.profile, data, ex)
        return rep.plan if rep.plan is not None else s.profile.reapply(dev, title="Re-apply saved changes")
    if c == "undo":
        return s.history.undo(args.ids)
    if c == "rollback":
        return s.history.rollback_to(args.id)
    return None


def run_cli_plan(s: Session, plan: Plan, yes: bool) -> int:
    """0 done, 1 cancelled / nothing to do, 2 refused or stopped (the phone changed unexpectedly)."""
    from droidforge.engine import executor
    from droidforge.features import fix
    if not plan.steps:
        for line in [plan.title] + [f" ! {n}" for n in plan.notes]:
            print(ascii_safe(line))
        return 1
    rep = executor.run(plan, s.device, cli_confirm(yes), dry_run=s.dry_run, history=s.history, profile=s.profile,
                       expert_mode=s.expert)
    for r in rep.results:
        mark = "ok  " if r.ok else "FAIL"
        print(ascii_safe(f"[{mark}] {r.step.label}" + ("" if r.ok else f" -> {r.err or r.out}")))
    if rep.status == "stopped":
        for line in fix.from_report(rep).lines():
            print(ascii_safe(line))
        print("Run 'droidforge fix' to see the repair plan again.")
        return 2
    if rep.status == "refused":
        print(ascii_safe(f"Refused: {rep.error}"))
        return 2
    if rep.status == "cancelled":
        print("Cancelled - nothing was sent.")
        return 1
    refused = [r.requested.pkg for r in rep.results if not r.ok and r.requested.cmd.startswith("pm disable-user")
               and not r.requested.fallbacks]
    if refused:
        print(ascii_safe("The ROM refused to disable: " + ", ".join(p for p in refused if p)
                         + ". Try: droidforge debloat force <package> (suspend -> remove -> firewall + neuter)."))
    if rep.offer_reboot:
        print("This was a risky plan: reboot the phone and run 'droidforge doctor' to re-check (R-11.9).")
    return 0


def cmd_history(s: Session) -> int:
    for e in s.history.entries():
        state = "dry-run" if e.dry_run else "undone" if e.undone else "ok" if e.ok else "failed"
        print(ascii_safe(f"{e.id}  {e.ts[:19]}  {state:<7}  {e.label}"))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbosity)
    if args.command is None:
        return run_tui(args)
    sink = console_sink()
    LOG.add_sink(sink)
    try:
        if args.expert:
            print(("\033[41;97m" + EXPERT_BANNER + "\033[0m") if sys.stderr.isatty() else EXPERT_BANNER,
                  file=sys.stderr)
        try:
            s = SESSION_FACTORY(simulate=args.simulate, serial=args.serial, expert=args.expert,
                                dry_run=args.dry_run)
        except ConnectError as e:
            LOG.error(str(e))
            return 1
        if args.command == "doctor":
            return cmd_doctor(s)
        if args.command == "fix":
            return cmd_fix(s, args.yes)
        if args.command == "history":
            return cmd_history(s)
        if args.command == "uad-update":
            from droidforge.data import uad
            ok, msg = uad.update()
            print(msg)
            return 0 if ok else 1
        try:
            plan = build_plan(args, s)
        except (ValueError, KeyError) as e:
            LOG.error(str(e))
            return 2
        if plan is None:
            return 1
        code = run_cli_plan(s, plan, args.yes)
        if args.command == "reapply" and code == 0:
            from droidforge.features import ota
            ota.acknowledge(s.profile, s.device)
        return code
        return 1
    finally:
        LOG.remove_sink(sink)
