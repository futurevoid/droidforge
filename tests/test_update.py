"""P8.3: self-update (R-12.4) - version check, install-method detection, previewed host plan."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

from droidforge.adb.device import Device
from droidforge.adb.sim import FakePhone, SimBackend
from droidforge.engine import executor, guard
from droidforge.features import update
from droidforge.log import Logger
from tests.helpers import yes


class _Resp(io.BytesIO):
    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *a: object) -> None:
        self.close()


def _opener(answers: dict):
    seen = []

    def op(req, timeout: float = 0):
        url = req.full_url
        seen.append(url)
        ans = answers[url]
        if isinstance(ans, Exception):
            raise ans
        return _Resp(json.dumps(ans).encode())
    op.seen = seen  # type: ignore[attr-defined]
    return op


def test_versions() -> None:
    assert update.parse_version("v1.10.0") > update.parse_version("v1.9.3")
    assert update.parse_version("junk") == ()
    assert update.is_newer("v9.0.0") and not update.is_newer("v0.0.1")


def test_latest_release_and_tag_fallback() -> None:
    assert update.latest(_opener({update.RELEASES: {"tag_name": "v1.2.0"}})) == "v1.2.0"
    nf = urllib.error.HTTPError(update.RELEASES, 404, "Not Found", None, None)  # type: ignore[arg-type]
    op = _opener({update.RELEASES: nf, update.TAGS: [{"name": "v1.0.0"}, {"name": "v1.10.0"}, {"name": "x"}]})
    assert update.latest(op) == "v1.10.0" and op.seen == [update.RELEASES, update.TAGS]
    import pytest
    with pytest.raises(ValueError):
        update.latest(_opener({update.RELEASES: nf, update.TAGS: []}))
    with pytest.raises(OSError):
        update.latest(_opener({update.RELEASES: urllib.error.URLError("offline")}))


def test_install_method(tmp_path: Path) -> None:
    src = tmp_path / "checkout"
    (src / "droidforge").mkdir(parents=True)
    (src / "pyproject.toml").write_text("")
    assert update.install_method(src / "droidforge", "/usr") == "source"
    site = tmp_path / "site" / "droidforge"
    site.mkdir(parents=True)
    assert update.install_method(site, "/home/u/.local/share/pipx/venvs/droidforge") == "pipx"
    assert update.install_method(Path("/usr/lib/python3.12/site-packages/droidforge"), "/usr") == "aur"
    assert update.install_method(site, "/home/u/venv") == "pip"


def test_plans_are_guarded_host_steps() -> None:
    for method in ("pipx", "aur"):
        plan = update.upgrade_plan(method, "v9.0.0")
        (s,) = plan.steps
        v = guard.check_command(s.cmd, host=True)
        assert s.host and v.write and s.touches == ["host:droidforge"] and "sudo" not in s.cmd
    for method in ("source", "pip"):
        plan = update.upgrade_plan(method, "v9.0.0")
        assert not plan.steps and plan.notes


def test_upgrade_runs_on_host_only(phone: FakePhone) -> None:
    host = Device(SimBackend(phone), None, log=Logger(1))
    before = phone.state()
    rep = executor.run(update.upgrade_plan("pipx", "v9.0.0"), host, yes)
    assert rep.status == "done" and phone.host_log == ["pipx upgrade droidforge"] and phone.state() == before


def test_cli_update(phone: FakePhone, monkeypatch, capsys, df_home) -> None:
    from droidforge import cli
    host = Device(SimBackend(phone), None, log=Logger(1))
    monkeypatch.setattr(cli, "HOST_FACTORY", lambda simulate: host)
    monkeypatch.setattr(update, "latest", lambda: "v0.0.1")
    assert cli.main(["-q", "--simulate", "update"]) == 0
    assert "up to date" in capsys.readouterr().out
    monkeypatch.setattr(update, "latest", lambda: "v9.0.0")
    monkeypatch.setattr(update, "install_method", lambda: "pipx")
    assert cli.main(["-q", "--simulate", "update", "--check"]) == 0
    assert "v9.0.0 is available" in capsys.readouterr().out and phone.host_log == []
    assert cli.main(["-q", "--simulate", "--yes", "update"]) == 0
    assert phone.host_log == ["pipx upgrade droidforge"]
    monkeypatch.setattr(update, "install_method", lambda: "source")
    assert cli.main(["-q", "--simulate", "--yes", "update"]) == 0
    out = capsys.readouterr().out
    assert "git pull" in out and out.isascii() and len(phone.host_log) == 1

    def offline() -> str:
        raise OSError("offline")
    monkeypatch.setattr(update, "latest", offline)
    assert cli.main(["-q", "--simulate", "update"]) == 1
