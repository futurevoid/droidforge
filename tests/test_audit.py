"""P6.x: permission audit (R-8.1), signers (R-8.2)."""

from __future__ import annotations

from droidforge.adb.sim import FakePhone
from droidforge.engine import executor
from droidforge.features.audit import perms, signers
from tests.helpers import yes


def test_perm_scan(sim, phone: FakePhone) -> None:
    phone.packages["com.whatsapp"].appops["SYSTEM_ALERT_WINDOW"] = "allow"
    before = phone.state()
    apps = {a.package: a for a in perms.scan(sim)}
    assert phone.state() == before
    wa = apps["com.whatsapp"]
    assert "android.permission.CAMERA" in wa.granted and wa.ops == {"SYSTEM_ALERT_WINDOW": "allow"} and not wa.system
    assert apps["com.heytap.market"].system and "com.oplus.securitykeyboard" in apps
    table = perms.rows(apps.values())
    assert ("com.whatsapp", "android.permission.CAMERA", "permission") in table
    assert all(not apps[p].system for p, _, _ in table)


def test_revoke_from_table_and_undo(sim, phone: FakePhone) -> None:
    initial = phone.clone().state()
    plan = perms.revoke_plan(sim, [("com.whatsapp", "android.permission.CAMERA"),
                                   ("com.android.vending", "android.permission.POST_NOTIFICATIONS")])
    assert [s.cmd for s in plan.steps] == ["pm revoke com.whatsapp android.permission.CAMERA"]
    assert any("Locked, skipped: com.android.vending" in n for n in plan.notes)
    rep = executor.run(plan, sim, yes)
    assert rep.status == "done" and not phone.packages["com.whatsapp"].perms["android.permission.CAMERA"]
    from droidforge.engine import undo
    executor.run(undo.undo_plan(rep.results, "u"), sim, yes)
    assert phone.state() == initial


def test_signer_groups(sim) -> None:
    groups = {g.label: g for g in signers.group(perms.scan(sim, with_ops=False))}
    assert "android" in groups["platform (signed like the OS)"].packages
    assert "com.google.android.gms" in groups["Google"].packages
    assert "com.heytap.market" in groups["OEM (OPPO / realme / OnePlus)"].packages
    assert "com.whatsapp" in groups["third-party / unknown"].packages


async def test_tui_audit_revoke(df_home) -> None:
    from droidforge.adb.sim import neo8_cn
    from droidforge.tui.app import DroidforgeApp
    from tests.test_tui import run_previewed
    phone = neo8_cn()
    app = DroidforgeApp(simulate=True, show_limits=False, phone=phone)
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause(0.3)
        await app.workers.wait_for_complete()
        app.show_section("audit")
        await pilot.pause(0.1)
        app.query_one("#audit-scan").press()
        await pilot.pause(0.2)
        await app.workers.wait_for_complete()
        await pilot.pause(0.1)
        assert "OEM (OPPO" in str(app.query_one("#audit-signers").render())
        app.query_one("#audit-perms").select("com.whatsapp|android.permission.CAMERA")
        app.query_one("#audit-revoke").press()
        await run_previewed(app, pilot)
        assert not phone.packages["com.whatsapp"].perms["android.permission.CAMERA"]


# ---------------------------------------------------------------- P6.3 connections, P6.4 CLI JSON
def test_proc_net_parse() -> None:
    from droidforge.features.audit import net
    assert net._addr("0100007F:1F90") == "127.0.0.1:8080"
    assert net._addr("0000000000000000FFFF00000501A8C0:C001") == "192.168.1.5:49153"
    assert net._addr("00000000000000000000000001000000:0035") == "::1:53"


def test_connections(sim, phone: FakePhone) -> None:
    from droidforge.features.audit import net
    rep = net.scan(sim)
    by = {c.proto: c for c in rep.conns}
    assert by["tcp"].apps == ["com.whatsapp"] and by["tcp"].state == "ESTABLISHED"
    assert by["tcp"].remote == "157.240.33.26:443"
    assert by["tcp6"].apps == ["org.telegram.messenger"] and by["tcp6"].remote.endswith(":443")
    assert by["udp"].apps == ["netd / DNS"] and by["udp"].remote == "8.8.8.8:53"
    assert not any(c.state == "LISTEN" for c in rep.conns)
    assert any(c.state == "LISTEN" for c in net.scan(sim, include_listen=True, include_loopback=True).conns)


def test_connections_blocked(sim, phone: FakePhone) -> None:
    from droidforge.features.audit import net
    phone.proc_net = {k: [] for k in phone.proc_net}
    rep = net.scan(sim)
    assert rep.blocked and "SELinux" in rep.note


def test_cli_audit_json(monkeypatch, capsys, df_home) -> None:
    import json

    from droidforge import cli
    from droidforge.adb.sim import neo8_cn
    from droidforge.session import open_session
    phone = neo8_cn()
    monkeypatch.setattr(cli, "SESSION_FACTORY", lambda **kw: open_session(phone=phone, **kw))
    for what in ("perms", "signers", "net"):
        assert cli.main(["-q", "--simulate", "audit", what, "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data
    assert cli.main(["-q", "--simulate", "audit", "net"]) == 0
    assert "com.whatsapp" in capsys.readouterr().out
