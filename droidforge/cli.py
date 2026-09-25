"""Command-line entry point. No subcommand -> launch the TUI."""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from droidforge import __version__


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="droidforge",
        description="English-ify, debloat, de-ad and harden ColorOS-family Android phones over adb.",
    )
    p.add_argument("--version", action="version", version=f"droidforge {__version__}")
    p.add_argument("--simulate", action="store_true", help="run against the simulated ColorOS phone")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    print("droidforge: the TUI is not built yet (see docs/PLAN.md).", file=sys.stderr)
    return 0
