"""P4.5: install sources (R-6.1)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from droidforge.adb.apk import ApkError, package_name
from droidforge.adb.sim import FakePhone
from droidforge.engine import executor
from droidforge.features import apps
from tests.helpers import make_apk, yes


def test_apk_reader(tmp_path: Path) -> None:
    make_apk(tmp_path / "a.apk", "org.mozilla.fenix")
    assert package_name(tmp_path / "a.apk") == "org.mozilla.fenix"
    (tmp_path / "bad.apk").write_bytes(b"nope")
    with pytest.raises(ApkError):
        package_name(tmp_path / "bad.apk")


def test_install_and_undo(sim, phone: FakePhone, tmp_path: Path) -> None:
    initial = phone.clone().state()
    make_apk(tmp_path / "Keep 1.0.apk", "com.google.android.keep")      # space in the name: quoted
    plan = apps.install_plan(sim, [tmp_path / "Keep 1.0.apk"])
    st = plan.steps[0]
    assert st.host and st.cmd.startswith(f"adb -s {phone.serial} install -r '") and st.undo == [
        "pm uninstall com.google.android.keep"]
    rep = executor.run(plan, sim, yes)
    assert rep.status == "done", (rep.error, [str(c) for c in rep.undeclared])
    assert "com.google.android.keep" in sim.packages("-3")
    from droidforge.engine import undo
    assert executor.run(undo.undo_plan(rep.results, "u"), sim, yes).status == "done"
    assert phone.state() == initial


def test_already_installed_is_left_to_play(sim, tmp_path: Path) -> None:
    make_apk(tmp_path / "wa.apk", "com.whatsapp")
    plan = apps.install_plan(sim, [tmp_path / "wa.apk"])
    assert plan.steps == [] and "Play Store" in plan.notes[0]


def test_folder_with_splits(sim, phone: FakePhone, tmp_path: Path) -> None:
    make_apk(tmp_path / "base.apk", "com.example.one")
    make_apk(tmp_path / "split_config.en.apk", "com.example.one")
    make_apk(tmp_path / "two.apk", "com.example.two")
    (tmp_path / "junk.apk").write_bytes(b"x")
    plan = apps.folder_plan(sim, tmp_path)
    cmds = [s.cmd for s in plan.steps]
    assert any("install-multiple -r" in c and c.index("base.apk") < c.index("split_config") for c in cmds)
    assert any(c.endswith("two.apk") for c in cmds) and any("Skipped" in n for n in plan.notes)
    assert executor.run(plan, sim, yes).status == "done"
    assert {"com.example.one", "com.example.two"} <= sim.packages("-3")


def test_play_page(sim, phone: FakePhone) -> None:
    assert executor.run(apps.play_plan(sim, "org.mozilla.fenix"), sim, yes).status == "done"
    assert phone.started[-1].endswith("market://details?id=org.mozilla.fenix")


class FakeHTTP:
    def __init__(self, routes):
        self.routes = routes

    def __call__(self, req, timeout=0):
        return io.BytesIO(self.routes[req.full_url])


def test_download_github_checks_package(tmp_path: Path) -> None:
    make_apk(tmp_path / "src.apk", "moe.shizuku.privileged.api")
    rel = {"assets": [{"name": "shizuku-v13.apk", "browser_download_url": "https://github.com/x/shizuku-v13.apk"}]}
    http = FakeHTTP({"https://api.github.com/repos/RikkaApps/Shizuku/releases/latest": json.dumps(rel).encode(),
                     "https://github.com/x/shizuku-v13.apk": (tmp_path / "src.apk").read_bytes()})
    out = apps.download("shizuku", tmp_path / "dl", http)
    assert out.name == "shizuku-v13.apk" and package_name(out) == "moe.shizuku.privileged.api"
    make_apk(tmp_path / "evil.apk", "com.evil")
    http.routes["https://github.com/x/shizuku-v13.apk"] = (tmp_path / "evil.apk").read_bytes()
    with pytest.raises(ValueError, match="expected moe.shizuku"):
        apps.download("shizuku", tmp_path / "dl2", http)


def test_download_play_only_app(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Play Store"):
        apps.download("gboard", tmp_path)
