"""Audit (R-8.x): permissions + app-ops with revoke, signer groups; live connections join in P6.3."""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Tuple

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Checkbox, Label, SelectionList, Static

from droidforge.features.audit import net, perms, signers
from droidforge.tui.screens.base import Section

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.tui.app import DroidforgeApp


class AuditSection(Section):
    DEFAULT_CSS = """
    AuditSection #audit-perms { height: 18; }
    """

    def compose(self) -> ComposeResult:
        yield Label("[b]Audit[/b]  (read-only until you revoke something)")
        with Horizontal(classes="buttons"):
            yield Button("Scan permissions + signers", id="audit-scan", variant="primary")
            yield Checkbox("include system apps", id="audit-system")
            yield Button("Revoke selected", id="audit-revoke", variant="error")
        yield SelectionList[str](id="audit-perms")
        yield Label("Signers", classes="subtitle")
        yield Static("", id="audit-signers", markup=False)
        yield Label("Live connections", classes="subtitle")
        with Horizontal(classes="buttons"):
            yield Button("Refresh connections", id="audit-net")
            yield Checkbox("auto-refresh every 3 s", id="audit-net-auto")
            yield Checkbox("show listening / loopback", id="audit-net-all")
        yield Static("", id="audit-conns", markup=False)

    def refresh_from(self, app: "DroidforgeApp") -> None:
        pass

    def on_mount(self) -> None:
        self.set_interval(3.0, self._auto_net)

    def _auto_net(self) -> None:
        if self.display and self.query_one("#audit-net-auto", Checkbox).value:
            self._net()

    def _net(self) -> None:
        dev = self.device
        if dev is None:
            return
        allc = self.query_one("#audit-net-all", Checkbox).value
        self.dapp.background(lambda: net.scan(dev, allc, allc), self._show_net)

    def _show_net(self, rep: "net.NetReport") -> None:
        lines = [rep.note] if rep.note else []
        lines += [f"{c.proto:<5} {c.local:<26} {c.remote:<26} {c.state:<12} {', '.join(c.apps) or c.uid}"
                  for c in rep.conns]
        self.query_one("#audit-conns", Static).update("\n".join(lines) or "no connections")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app, dev = self.dapp, self.device
        if dev is None:
            return
        if event.button.id == "audit-net":
            self._net()
        elif event.button.id == "audit-scan":
            app.background(lambda: perms.scan(dev), self.show)
        elif event.button.id == "audit-revoke":
            picks = [tuple(v.split("|", 1)) for v in self.query_one("#audit-perms", SelectionList).selected]
            app.run_plan(lambda: perms.revoke_plan(dev, picks, None, app.expert),  # type: ignore[arg-type]
                         on_done=lambda rep: app.background(lambda: perms.scan(dev), self.show))

    def show(self, apps: List[perms.AppAudit]) -> None:
        include = self.query_one("#audit-system", Checkbox).value
        rows: List[Tuple[str, str, str]] = perms.rows(apps, include)
        sl = self.query_one("#audit-perms", SelectionList)
        sl.clear_options()
        sl.add_options([(f"{p:<42} {kind:<10} {what}", f"{p}|{what}") for p, what, kind in rows])
        lines = []
        for g in signers.group(apps):
            shown = ", ".join(g.packages[:6]) + (f" ... (+{len(g.packages) - 6})" if len(g.packages) > 6 else "")
            lines.append(f"{g.label:<30} {g.digest[:16]:<16}  {len(g.packages):>3} app(s): {shown}")
        self.query_one("#audit-signers", Static).update("\n".join(lines))
