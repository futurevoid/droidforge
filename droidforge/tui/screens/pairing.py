"""Wireless pairing modal (R-2.2): QR code, mDNS polling, code fallback."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from droidforge.adb import hostcmd
from droidforge.adb.device import Device
from droidforge.features import wireless
from droidforge.log import LOG

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.tui.app import DroidforgeApp


class PairingScreen(ModalScreen[Optional[str]]):
    """Returns the ip:port to connect to (or None)."""

    DEFAULT_CSS = """
    PairingScreen { align: center middle; }
    PairingScreen > Vertical { width: 90; height: auto; max-height: 95%; border: thick $primary;
                               background: $surface; padding: 0 1; }
    PairingScreen #qr { width: auto; }
    PairingScreen Horizontal { height: 3; }
    """

    def __init__(self, host: Device) -> None:
        super().__init__()
        self.host = host
        self.pairing = wireless.new_pairing()
        self.busy = False

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Pair a phone over Wi-Fi[/b]")
            yield Static(wireless.PAIRING_HINT, markup=False)
            yield Static(wireless.render_halfblocks(wireless.qr_matrix(self.pairing.payload)), id="qr", markup=False)
            yield Static("Waiting for the phone...", id="pair-status", markup=False)
            yield Static(wireless.CODE_HINT, markup=False)
            with Horizontal():
                yield Input(placeholder="ip:port", id="code-addr")
                yield Input(placeholder="6-digit code", id="code")
                yield Button("Pair with code", id="pair-code")
                yield Button("Close", id="close")

    def on_mount(self) -> None:
        self.set_interval(1.5, self.poll)

    @property
    def dapp(self) -> "DroidforgeApp":
        return self.app  # type: ignore[return-value]

    def poll(self) -> None:
        if self.busy:
            return
        self.busy = True
        self._poll()

    @work(thread=True, group="pairing", exclusive=True)
    def _poll(self) -> None:
        rows = wireless.parse_services(hostcmd.mdns_services(self.host))
        addr = wireless.find_pairing(rows, self.pairing.name)
        if addr is None:
            self.busy = False
            return
        connect = wireless.find_connect(rows, addr.split(":")[0])
        self.app.call_from_thread(self._found, addr, connect)

    def _found(self, addr: str, connect: Optional[str]) -> None:
        self.query_one("#pair-status", Static).update(f"Found the phone at {addr} - confirm the pairing plan.")
        self._pair(addr, self.pairing.password, connect)

    def _pair(self, addr: str, password: str, connect: Optional[str]) -> None:
        try:
            plan = wireless.pair_plan(addr, password, connect)
        except ValueError as e:
            self.query_one("#pair-status", Static).update(str(e))
            self.busy = False
            return

        def done(rep: object) -> None:
            ok = getattr(rep, "status", "") == "done" and all(r.ok for r in getattr(rep, "results", []))
            if ok and connect:
                wireless.remember(connect)
                self.dismiss(connect)
            else:
                self.query_one("#pair-status", Static).update("Pairing did not work - check the code and Wi-Fi.")
                self.busy = False
        self.dapp.run_host_plan(self.host, plan, done)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss(None)
        elif event.button.id == "pair-code":
            addr = self.query_one("#code-addr", Input).value.strip()
            self.busy = True
            self._pair(addr, self.query_one("#code", Input).value.strip(), None)
            LOG.info("After pairing with a code, connect to the address shown under 'IP address & port'.")
