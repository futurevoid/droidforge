"""Package-wide structure rules from CLAUDE.md (code rules)."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import droidforge
from droidforge import cli

PKG = Path(droidforge.__file__).parent
MODULES = sorted(PKG.rglob("*.py"))


def test_version_string() -> None:
    assert droidforge.__version__


def test_cli_version(capsys: pytest.CaptureFixture) -> None:
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0
    assert droidforge.__version__ in capsys.readouterr().out


def test_python_m_version() -> None:
    r = subprocess.run([sys.executable, "-m", "droidforge", "--version"], capture_output=True, text=True)
    assert r.returncode == 0
    assert droidforge.__version__ in r.stdout


@pytest.mark.parametrize("path", MODULES, ids=lambda p: str(p.relative_to(PKG)))
def test_future_annotations_everywhere(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    ok = any(isinstance(n, ast.ImportFrom) and n.module == "__future__" and any(a.name == "annotations" for a in n.names)
             for n in tree.body)
    assert ok, f"{path} lacks `from __future__ import annotations`"


def _imports(path: Path) -> set:
    names = set()
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Import):
            names.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            names.add(n.module.split(".")[0])
    return names


@pytest.mark.parametrize("sub", ["engine", "features", "adb", "data"])
def test_core_never_imports_textual(sub: str) -> None:
    for path in (PKG / sub).rglob("*.py"):
        assert "textual" not in _imports(path), f"{path} imports textual (P4)"


def test_no_match_statements() -> None:
    for path in MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not any(type(n).__name__ == "Match" for n in ast.walk(tree)), f"{path} uses `match` (py3.9)"


def test_no_device_side_binaries() -> None:
    bad = [p for p in PKG.rglob("*") if p.suffix in (".dex", ".jar", ".apk", ".smali", ".so")]
    assert not bad, f"device-side binaries are forbidden (P9): {bad}"


WRITE_PATH_OWNERS = {PKG / "engine" / "executor.py", PKG / "adb" / "device.py"}


def test_only_executor_calls_device_sh() -> None:
    """CLAUDE.md: nothing reaches the device except through engine/executor.py."""
    for path in MODULES:
        if path in WRITE_PATH_OWNERS:
            continue
        for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "sh":
                raise AssertionError(f"{path}:{n.lineno} calls .sh() - writes go through engine/executor.py")
