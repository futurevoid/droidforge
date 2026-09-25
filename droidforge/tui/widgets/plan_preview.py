"""PlanPreview modal (R-11.1, P1): exact commands, their undo, risk badges, notes, typed confirmations.
Buttons: Run / Cancel / Copy commands. Returns a Confirmation; the executor re-checks the typed strings."""

from __future__ import annotations

from typing import List

from rich.markup import escape
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from droidforge.engine.plan import Confirmation, Plan, Step

BADGE = {"read": ("READ", "black on grey70"), "normal": ("WRITE", "black on cyan"),
         "risky": ("RISKY", "black on yellow"), "locked": ("LOCKED", "white on red")}


class TypedConfirm(Input):
    """One input per string the user must type (locked package names, I UNDERSTAND, YES)."""

    def __init__(self, expected: str, **kw: object) -> None:
        super().__init__(placeholder=f"type: {expected}", **kw)  # type: ignore[arg-type]
        self.expected = expected

    @property
    def matches(self) -> bool:
        return self.value == self.expected


def step_text(i: int, s: Step, name: str = "") -> Text:
    label, style = BADGE.get(s.risk, BADGE["normal"])
    t = Text()
    t.append(f"{i:>2}. ")
    t.append(f" {label} ", style=style)
    t.append(f" {s.label}", style="bold")
    if name:
        t.append(f"  app: {name}", style="bold cyan")
    t.append("\n")
    t.append(f"      {'host' if s.host else 'adb shell'}: {s.cmd}\n")
    for u in s.undo:
        t.append(f"      undo: {u}\n", style="green")
    if not s.undo and s.risk != "read":
        t.append("      undo: - (nothing persists)\n", style="dim")
    for n, fb in enumerate(s.fallbacks, 2):
        t.append(f"      stage {n} if refused: {fb.cmd}\n", style="yellow")
        for u in fb.undo:
            t.append(f"        undo: {u}\n", style="green")
        for ex in fb.extra:
            t.append(f"        + {ex.cmd}\n", style="yellow")
            for u in ex.undo:
                t.append(f"          undo: {u}\n", style="green")
    return t


def commands_text(plan: Plan) -> str:
    lines: List[str] = [f"# {plan.title}"]
    for s in plan.steps:
        lines.append(s.cmd)
        lines += [f"#   undo: {u}" for u in s.undo]
        lines += [f"#   then: {fb.cmd}" for fb in s.fallbacks]
    return "\n".join(lines)


class PlanPreview(ModalScreen[Confirmation]):
    DEFAULT_CSS = """
    PlanPreview { align: center middle; }
    PlanPreview > Vertical { width: 95%; height: 90%; border: thick $primary; background: $surface; padding: 0 1; }
    PlanPreview #steps { height: 1fr; border: round $panel; }
    PlanPreview #notes { color: $warning; height: auto; max-height: 10; }
    PlanPreview #buttons { height: 3; }
    PlanPreview #typed-help { color: $error; }
    """
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, plan: Plan, dry_run: bool = False) -> None:
        super().__init__()
        self.plan = plan
        self.dry_run = dry_run

    def compose(self) -> ComposeResult:
        p = self.plan
        with Vertical():
            head = f"[b]{escape(p.title)}[/b]  -  {len(p.steps)} step(s), {len(p.batches())} batch(es)"
            if p.expert:
                head += "  [white on red] EXPERT [/]"
            if self.dry_run:
                head += "  [black on yellow] DRY-RUN: nothing will be sent [/]"
            yield Label(head)
            with VerticalScroll(id="steps"):
                for i, s in enumerate(p.steps, 1):
                    yield Static(step_text(i, s, p.names.get(s.pkg or "", "")), classes="step")
            if p.notes:
                yield Static("\n".join(f"! {n}" for n in p.notes), id="notes", markup=False)
            if p.typed:
                yield Label("Type exactly to confirm:", id="typed-help")
                for n, t in enumerate(p.typed):
                    yield TypedConfirm(t, id=f"typed-{n}")
            with Horizontal(id="buttons"):
                yield Button("Run" if not self.dry_run else "Dry-run", id="run", variant="error" if p.expert
                             else "primary", disabled=bool(p.typed))
                yield Button("Cancel", id="cancel")
                yield Button("Copy commands", id="copy")

    def on_input_changed(self, event: Input.Changed) -> None:
        self.query_one("#run", Button).disabled = not all(t.matches for t in self.query(TypedConfirm))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "run":
            typed = [t.value for t in self.query(TypedConfirm)]
            self.dismiss(Confirmation(True, typed))
        elif event.button.id == "copy":
            self.app.copy_to_clipboard(commands_text(self.plan))
            self.notify("Commands copied to the clipboard")
        else:
            self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss(Confirmation(False))
