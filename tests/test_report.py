"""P8.2: HTML session report (R-11.4)."""

from __future__ import annotations

from pathlib import Path

from droidforge.adb.sim import FakePhone
from droidforge.engine import executor, report
from droidforge.engine.history import History
from tests.helpers import TELEMETRY, disable_plan, force_step, yes


def test_report_contents(sim, phone: FakePhone, tmp_path: Path) -> None:
    from droidforge.engine.plan import Plan
    h = History(phone.serial)
    executor.run(disable_plan(TELEMETRY[:2]), sim, yes, history=h)
    phone.packages["com.opos.cs"].refuse = {"disable", "suspend", "uninstall"}
    phone.firewall_supported = False
    executor.run(Plan("force", [force_step("com.opos.cs")]), sim, yes, history=h)
    before = phone.state()
    path = report.write(sim, h, "", with_audit=True, directory=tmp_path)
    assert phone.state() == before
    text = path.read_text()
    assert text.startswith("<!doctype html>") and "realme RMX8899" in text
    assert "What changed (2)" in text and f"pm enable --user 0 {TELEMETRY[0]}" in text
    assert "What failed (1)" in text and "com.opos.cs" in text
    assert "Audit: signers" in text and "droidforge rollback" in text and "Reset all settings" in text


def test_report_escapes_and_shows_breakage(sim, phone: FakePhone, tmp_path: Path) -> None:
    phone.break_ui()
    phone.props["ro.build.fingerprint"] = "x<script>alert(1)</script>"
    sim.forget_props()
    text = report.build(sim, History(phone.serial))
    assert "<script>" not in text and "&lt;script&gt;" in text
    assert "Something is wrong" in text and "Disable permission monitoring" in text


def test_cli_report(monkeypatch, capsys, df_home) -> None:
    from droidforge import cli
    from droidforge.adb.sim import neo8_cn
    from droidforge.session import open_session
    phone = neo8_cn()
    monkeypatch.setattr(cli, "SESSION_FACTORY", lambda **kw: open_session(phone=phone, **kw))
    assert cli.main(["-q", "--simulate", "report", "--audit"]) == 0
    path = capsys.readouterr().out.split("Report written: ")[1].strip()
    assert Path(path).exists() and "reports" in path
