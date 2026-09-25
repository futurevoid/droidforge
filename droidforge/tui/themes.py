"""Themes (R-12.2): Textual's built-in themes plus a custom "hacker" theme (black, green / amber)."""

from __future__ import annotations

from textual.theme import Theme

HACKER = Theme(
    name="hacker",
    primary="#00ff41",
    secondary="#ffb000",
    accent="#ffb000",
    warning="#ffb000",
    error="#ff3131",
    success="#00ff41",
    foreground="#00ff41",
    background="#000000",
    surface="#050805",
    panel="#0c140c",
    dark=True,
)

DEFAULT_THEME = "textual-dark"
