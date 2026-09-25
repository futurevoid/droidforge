"""Constructors for the common single-command steps. Each one declares exactly what it touches (P10) and its
undo from the state the caller read before building the plan (P2). Features and profile re-apply use these so
the same command always carries the same blast radius."""

from __future__ import annotations

from typing import Optional

from droidforge.engine.plan import Step

APPOP_OPS_NEUTER = ("RUN_IN_BACKGROUND", "RUN_ANY_IN_BACKGROUND", "POST_NOTIFICATION", "SYSTEM_ALERT_WINDOW")


def disable(p: str, category: str = "debloat", risk: str = "normal") -> Step:
    return Step(f"Disable {p}", f"pm disable-user --user 0 {p}", [f"pm enable --user 0 {p}"], category, p, risk,
                verify="pm list packages -d", expect=rf"(?m)^package:{_re(p)}$", touches=[f"pkg:{p}:enabled"])


def enable(p: str, category: str = "debloat", risk: str = "normal") -> Step:
    return Step(f"Enable {p}", f"pm enable --user 0 {p}", [f"pm disable-user --user 0 {p}"], category, p, risk,
                touches=[f"pkg:{p}:enabled"])


def suspend(p: str, category: str = "debloat", risk: str = "normal") -> Step:
    return Step(f"Suspend {p} (frozen - cannot open or run)", f"pm suspend --user 0 {p}",
                [f"pm unsuspend --user 0 {p}"], category, p, risk, touches=[f"pkg:{p}:suspended"])


def unsuspend(p: str, category: str = "debloat", risk: str = "normal") -> Step:
    return Step(f"Unsuspend {p}", f"pm unsuspend --user 0 {p}", [f"pm suspend --user 0 {p}"], category, p, risk,
                touches=[f"pkg:{p}:suspended"])


def remove_user0(p: str, category: str = "debloat", risk: str = "normal") -> Step:
    return Step(f"Remove {p} for user 0 (undo: restore)", f"pm uninstall -k --user 0 {p}",
                [f"cmd package install-existing {p}"], category, p, risk, touches=[f"pkg:{p}:installed"])


def restore(p: str, category: str = "debloat", risk: str = "normal") -> Step:
    return Step(f"Restore {p}", f"cmd package install-existing {p}", [f"pm uninstall -k --user 0 {p}"], category,
                p, risk, touches=[f"pkg:{p}:installed"])


def force_stop(p: str, category: str = "debloat", risk: str = "normal") -> Step:
    # nothing to undo: the app simply starts again when opened
    return Step(f"Stop {p}", f"am force-stop {p}", [], category, p, risk, touches=[f"proc:{p}"])


def revoke(p: str, perm: str, category: str = "neuter", risk: str = "normal") -> Step:
    return Step(f"{p}: revoke {perm.rsplit('.', 1)[-1]}", f"pm revoke {p} {perm}", [f"pm grant {p} {perm}"],
                category, p, risk, touches=[f"perm:{p}:{perm}"])


def grant(p: str, perm: str, category: str = "powerperms", risk: str = "normal") -> Step:
    return Step(f"{p}: grant {perm.rsplit('.', 1)[-1]}", f"pm grant {p} {perm}", [f"pm revoke {p} {perm}"],
                category, p, risk, touches=[f"perm:{p}:{perm}"])


def appop(p: str, op: str, mode: str, prev: Optional[str], category: str = "neuter", risk: str = "normal") -> Step:
    return Step(f"{p}: {op} -> {mode}", f"cmd appops set {p} {op} {mode}",
                [f"cmd appops set {p} {op} {prev or 'default'}"], category, p, risk, touches=[f"appop:{p}:{op}"])


def ime_enable(ime: str, category: str = "keyboard") -> Step:
    return Step(f"Enable keyboard {ime.split('/')[0]}", f"ime enable {ime}", [f"ime disable {ime}"], category,
                ime.split("/")[0], touches=[f"ime:enabled:{ime}", "setting:secure:enabled_input_methods"])


def ime_disable(ime: str, category: str = "keyboard") -> Step:
    return Step(f"Switch off keyboard {ime.split('/')[0]}", f"ime disable {ime}", [f"ime enable {ime}"], category,
                ime.split("/")[0], touches=[f"ime:enabled:{ime}", "setting:secure:enabled_input_methods"])


def ime_set(ime: str, prev: str, category: str = "keyboard") -> Step:
    return Step(f"Default keyboard -> {ime.split('/')[0]}", f"ime set {ime}", [f"ime set {prev}"] if prev else [],
                category, ime.split("/")[0],
                touches=["ime:default", "setting:secure:default_input_method",
                         "setting:secure:selected_input_method_subtype"])


def _locale_cmd(p: str, locales: str) -> str:
    base = f"cmd locale set-app-locales {p} --user 0"
    return f"{base} --locales {locales}" if locales else base


def app_locale(p: str, locales: str, prev: str, category: str = "language") -> Step:
    """Per-app language (R-3.2). The guard enforces P12 on both the command and its undo."""
    return Step(f"{p}: app language -> {locales or 'follow system'}", _locale_cmd(p, locales),
                [_locale_cmd(p, prev)], category, p, touches=[f"applocale:{p}"])


def open_screen(action: str, label: str, category: str = "info") -> Step:
    """`am start -a <settings screen>` - an allowed read: opens a screen, changes nothing."""
    return Step(label, f"am start -a {action}", [], category, risk="read")


def _re(p: str) -> str:
    return p.replace(".", r"\.")
