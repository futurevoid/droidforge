"""P5.1 mechanics: QR payload, mDNS discovery, pair + connect as previewed host-only plans (R-2.2)."""

from __future__ import annotations

from droidforge.adb.device import Device
from droidforge.adb.sim import FakePhone, SimBackend
from droidforge.engine import executor
from droidforge.features import wireless
from droidforge.log import Logger
from tests.helpers import yes


def test_payload_and_qr() -> None:
    p = wireless.new_pairing()
    assert p.payload == f"WIFI:T:ADB;S:{p.name};P:{p.password};;" and len(p.password) == 10
    m = wireless.qr_matrix(p.payload)
    assert len(m) == len(m[0]) > 20
    assert wireless.render_ascii(m).isascii()
    assert len(wireless.render_halfblocks(m).splitlines()) == (len(m) + 1) // 2


def test_discovery_parse() -> None:
    out = ("List of discovered mdns services\n"
           "droidforge-abc\t_adb-tls-pairing._tcp.\t192.168.1.20:37123\n"
           "adb-SER-xyz\t_adb-tls-connect._tcp.\t192.168.1.20:40001\n"
           "junk line\n")
    rows = wireless.parse_services(out)
    assert wireless.find_pairing(rows, "droidforge-abc") == "192.168.1.20:37123"
    assert wireless.find_connect(rows, "192.168.1.20") == "192.168.1.20:40001"
    assert wireless.find_pairing(rows, "other") is None


def test_pair_and_connect_before_any_device(phone: FakePhone, df_home) -> None:
    host = Device(SimBackend(phone), None, log=Logger(1))       # no phone selected yet
    phone.pairing = ("droidforge-abc", "abcdef1234")
    phone.mdns = [("droidforge-abc", "_adb-tls-pairing._tcp.", "192.168.1.20:37123"),
                  ("adb-SER", "_adb-tls-connect._tcp.", "192.168.1.20:40001")]
    rows = wireless.parse_services(host.backend.run(["mdns", "services"]).out)
    plan = wireless.pair_plan(wireless.find_pairing(rows, "droidforge-abc"), "abcdef1234",
                              wireless.find_connect(rows, "192.168.1.20"))
    rep = executor.run(plan, host, yes)
    assert rep.status == "done" and all(r.ok for r in rep.results)
    assert phone.host_log[-2:] == ["adb pair 192.168.1.20:37123 abcdef1234", "adb connect 192.168.1.20:40001"]
    wireless.remember("192.168.1.20:40001", "realme")
    assert wireless.remembered()[0]["addr"] == "192.168.1.20:40001"


def test_wrong_code_fails_and_bad_input_refused(phone: FakePhone) -> None:
    host = Device(SimBackend(phone), None, log=Logger(1))
    rep = executor.run(wireless.pair_plan("192.168.1.20:37123", "999999"), host, yes)
    assert rep.status == "done" and not rep.results[0].ok
    import pytest
    with pytest.raises(ValueError):
        wireless.pair_plan("192.168.1.300:1", "123456")
    assert executor.run(wireless.pair_plan("10.0.0.2:5555", "12345"), host, yes).status == "refused"


def test_cli_pair_qr_flow(phone: FakePhone, monkeypatch, capsys, df_home) -> None:
    from droidforge import cli
    host = Device(SimBackend(phone), None, log=Logger(1))
    monkeypatch.setattr(cli, "HOST_FACTORY", lambda simulate: host)
    orig = wireless.new_pairing
    fixed = orig()
    monkeypatch.setattr(wireless, "new_pairing", lambda: fixed)
    phone.pairing = (fixed.name, fixed.password)
    phone.mdns = [(fixed.name, "_adb-tls-pairing._tcp.", "192.168.1.20:37123"),
                  ("adb-SER", "_adb-tls-connect._tcp.", "192.168.1.20:40001")]
    assert cli.main(["-q", "--simulate", "--yes", "pair"]) == 0
    out = capsys.readouterr().out
    assert "##" in out and "droidforge --serial 192.168.1.20:40001" in out and out.isascii()


def test_cli_pair_code(phone: FakePhone, monkeypatch, capsys, df_home) -> None:
    from droidforge import cli
    host = Device(SimBackend(phone), None, log=Logger(1))
    monkeypatch.setattr(cli, "HOST_FACTORY", lambda simulate: host)
    phone.pairing = ("x", "123456")
    assert cli.main(["-q", "--simulate", "--yes", "pair", "--code", "192.168.1.20:37123", "123456",
                     "--connect", "192.168.1.20:40001"]) == 0


async def test_tui_pairing_modal(df_home) -> None:
    from droidforge.adb.sim import neo8_cn
    from droidforge.tui.app import DroidforgeApp
    from droidforge.tui.screens.pairing import PairingScreen
    from tests.test_tui import run_previewed
    phone = neo8_cn()
    app = DroidforgeApp(simulate=True, show_limits=False, phone=phone)
    async with app.run_test(size=(140, 50)) as pilot:
        await pilot.pause(0.3)
        await app.workers.wait_for_complete()
        await pilot.press("p")
        await pilot.pause(0.2)
        scr = app.screen
        assert isinstance(scr, PairingScreen)
        phone.pairing = (scr.pairing.name, scr.pairing.password)
        phone.mdns = [(scr.pairing.name, "_adb-tls-pairing._tcp.", "192.168.1.20:37123"),
                      ("adb-SER", "_adb-tls-connect._tcp.", "192.168.1.20:40001")]
        await run_previewed(app, pilot)
        await pilot.pause(0.3)
        assert "adb connect 192.168.1.20:40001" in phone.host_log
        assert wireless.remembered()[0]["addr"] == "192.168.1.20:40001"
