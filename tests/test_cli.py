"""P4.10: the CLI reaches every plan (sim, --yes)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from droidforge import cli
from droidforge.adb.sim import FakePhone, neo8_cn
from droidforge.session import open_session
from tests.helpers import UAD_SAMPLE, make_apk


@pytest.fixture
def ph(monkeypatch: pytest.MonkeyPatch, df_home: Path) -> FakePhone:
    from droidforge.data import uad
    uad.cache_file().write_text(json.dumps(UAD_SAMPLE))
    phone = neo8_cn()
    monkeypatch.setattr(cli, "SESSION_FACTORY", lambda **kw: open_session(phone=phone, **kw))
    return phone


def run(*argv: str) -> int:
    return cli.main(["-q", "--simulate", "--yes", *argv])


def test_every_command(ph: FakePhone, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    assert run("debloat", "disable", "com.heytap.market") == 0 and not ph.packages["com.heytap.market"].enabled
    assert run("debloat", "enable", "com.heytap.market") == 0 and ph.packages["com.heytap.market"].enabled
    assert run("telemetry", "--force") == 0 and ph.packages["com.oplus.sauhelper"].suspended
    assert run("ads", "feed") == 0 and not ph.packages["com.coloros.assistantscreen"].enabled
    assert run("hijack") == 0 and not ph.packages["com.oplus.appdetail"].enabled
    assert run("dns", "quad9") == 0 and ph.settings["global"]["private_dns_specifier"] == "dns.quad9.net"
    assert run("firewall", "block", "com.whatsapp") == 0 and "com.whatsapp" in ph.firewall_blocked
    assert run("firewall", "unblock", "com.whatsapp") == 0 and not ph.firewall_blocked
    assert run("swap", "browser") == 0 and ph.roles["android.app.role.BROWSER"] == ["org.mozilla.fenix"]
    assert run("keepalive", "com.whatsapp") == 0 and "com.whatsapp" in ph.deviceidle
    assert run("language", "apps", "com.whatsapp", "--locales", "en-US,ar-EG") == 0
    assert ph.packages["com.whatsapp"].locales == "en-US,ar-EG"
    assert run("keyboard", "gboard") == 0
    assert run("region", "datetime") == 0 and ph.started[-1] == "android.settings.DATE_SETTINGS"
    make_apk(tmp_path / "keep.apk", "com.google.android.keep")
    assert run("install", str(tmp_path / "keep.apk")) == 0 and "com.google.android.keep" in ph.packages
    assert run("install", "--play", "org.mozilla.fenix") == 0
    ph.add("net.dinglisch.android.taskerm", system=False, perms={"android.permission.WRITE_SECURE_SETTINGS": False})
    assert run("powerperms", "--preset", "tasker") == 0
    capsys.readouterr()
    assert run("history") == 0
    out = capsys.readouterr().out
    first = out.splitlines()[0].split()[0]
    assert run("rollback", first) == 0 and ph.packages["com.heytap.market"].enabled
    assert out.isascii()


def test_refused_and_nothing_to_do(ph: FakePhone, capsys: pytest.CaptureFixture) -> None:
    assert run("debloat", "disable", "com.android.systemui") == 1        # locked: nothing to do
    assert "--expert" in capsys.readouterr().out
    assert run("dns", "nextdns") == 2                                   # missing ID


def test_refused_disable_suggests_force(ph: FakePhone, capsys: pytest.CaptureFixture) -> None:
    assert run("debloat", "disable", "com.oplus.sauhelper") == 0
    assert "droidforge debloat force" in capsys.readouterr().out


def test_prompt_no_cancels(ph: FakePhone, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda q: "n")
    before = ph.state()
    assert cli.main(["-q", "--simulate", "debloat", "disable", "com.heytap.market"]) == 1
    assert ph.state() == before


def test_reapply_after_ota(ph: FakePhone) -> None:
    assert run("debloat", "disable", "com.heytap.mcs") == 0
    ph.packages["com.heytap.mcs"].enabled = True
    ph.props["ro.build.fingerprint"] = "realme/RMX8899/new:16/NEW/9:user/release-keys"
    assert run("reapply") == 0 and not ph.packages["com.heytap.mcs"].enabled


# ---------------------------------------------------------------- P8.1
def test_allow_locked_with_expert(ph: FakePhone) -> None:
    p = "com.android.ims.rcsservice"
    assert run("debloat", "disable", p) == 1                                  # not even selectable without --expert
    assert cli.main(["-q", "--simulate", "--yes", "--expert", "--allow-locked", p, "debloat", "disable", p]) == 0
    assert not ph.packages[p].enabled


def test_allow_locked_does_not_answer_other_typed_strings(ph: FakePhone, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_tty(q: str) -> str:
        raise EOFError
    monkeypatch.setattr("builtins.input", no_tty)
    assert cli.main(["-q", "--simulate", "--yes", "--allow-locked", "I UNDERSTAND", "debloat", "disable",
                     "com.oplus.camera"]) == 1                                # guarded: typed string not given
    assert ph.packages["com.oplus.camera"].enabled


def test_export_apply_import_legacy(ph: FakePhone, tmp_path: Path) -> None:
    assert run("debloat", "disable", "com.heytap.market") == 0
    out = tmp_path / "neo8.json"
    assert run("export", "--profile", str(out)) == 0
    data = json.loads(out.read_text())
    assert data["disabled"] == ["com.heytap.market"] and "serial" not in data
    assert run("debloat", "enable", "com.heytap.market") == 0
    assert run("apply", "--profile", str(out)) == 0 and not ph.packages["com.heytap.market"].enabled
    legacy = tmp_path / "cnrom_state.json"
    legacy.write_text(json.dumps({"removed": ["com.opos.cs"], "english": ["com.android.settings"]}))
    assert run("import-legacy", str(legacy)) == 0 and not ph.packages["com.opos.cs"].user0
    assert ph.packages["com.android.settings"].locales == ""
    assert run("apply", "--profile", str(tmp_path / "missing.json")) == 2
