"""Command-line entry point. No subcommand -> launch the TUI (Phase 3)."""

from __future__ import annotations

import argparse
import sys
from typing import Callable, List, Optional

from droidforge import __version__, config
from droidforge.log import LOG, console_sink
from droidforge.session import ConnectError, Session, open_session

# tests replace this to hand the CLI a prepared simulated phone
SESSION_FACTORY: Callable[..., Session] = open_session


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="droidforge",
        description="English-ify, debloat, de-ad and harden ColorOS-family Android phones over adb.",
    )
    p.add_argument("--version", action="version", version=f"droidforge {__version__}")
    p.add_argument("--simulate", action="store_true", help="run against the simulated ColorOS phone")
    p.add_argument("--serial", help="adb serial of the phone to use")
    lv = p.add_mutually_exclusive_group()
    lv.add_argument("-q", "--quiet", dest="verbosity", action="store_const", const=1, help="results only")
    lv.add_argument("-v", "--verbose", dest="verbosity", action="store_const", const=2,
                    help="commands, exit codes, timing, first 15 lines")
    lv.add_argument("--ultra", dest="verbosity", action="store_const", const=3, help="everything (default)")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("doctor", help="read-only health and capability report (never changes the phone)")
    return p


def _setup_logging(verbosity: Optional[int]) -> config.Config:
    cfg = config.Config()
    LOG.verbosity = verbosity or cfg.get("verbosity", 3)
    LOG.debug_path = cfg.paths.debug_log
    return cfg


def cmd_doctor(s: Session) -> int:
    from droidforge.features import doctor
    rep = doctor.run(s.device, s.profile, s.history, backup_dir=config.paths().sub("backups"))
    for line in rep.lines():
        print(line.encode("ascii", "backslashreplace").decode("ascii"))
    return 0 if rep.healthy else 2


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbosity)
    sink = console_sink()
    LOG.add_sink(sink)
    try:
        if args.command is None:
            print("droidforge: the TUI is not built yet (see docs/PLAN.md). Try: droidforge --simulate doctor",
                  file=sys.stderr)
            return 0
        try:
            s = SESSION_FACTORY(simulate=args.simulate, serial=args.serial)
        except ConnectError as e:
            LOG.error(str(e))
            return 1
        if args.command == "doctor":
            return cmd_doctor(s)
        return 1
    finally:
        LOG.remove_sink(sink)
