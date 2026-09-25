"""Command-line entry point. No subcommand -> launch the TUI."""

from __future__ import annotations

import argparse
import sys
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
    return p


def preview_lines(plan: Plan) -> List[str]:
    out = [f"Plan: {plan.title}  ({len(plan.steps)} step(s), {len(plan.batches())} batch(es))"]
    for i, st in enumerate(plan.steps, 1):
        out.append(f" {i:>2}. [{st.risk.upper()}] {st.label}")
        out.append(f"       {'host' if st.host else 'adb shell'}: {st.cmd}")
        out += [f"       undo: {u}" for u in st.undo]
        out += [f"       then if refused: {fb.cmd}" for fb in st.fallbacks]
    out += [f" ! {n}" for n in plan.notes]
    return out


def cli_confirm(yes: bool, ask: Callable[[str], str] = input) -> Callable[[Plan], Confirmation]:
    """P1 for the CLI: print the exact commands and undo, ask [y/N] (--yes skips), ask for every typed string."""
    def hook(plan: Plan) -> Confirmation:
        for line in preview_lines(plan):
            print(ascii_safe(line))
        typed = []
        for t in plan.typed:
            try:
                typed.append(ask(f"Type exactly '{t}' to confirm: "))
            except EOFError:
                return Confirmation(False)
        if yes:
            return Confirmation(True, typed)
        try:
            answer = ask("Run this plan? [y/N]: ").strip().lower()
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
        return 1
    finally:
        LOG.remove_sink(sink)
