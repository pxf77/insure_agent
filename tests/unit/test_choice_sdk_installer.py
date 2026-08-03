from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path("scripts/install_choice_sdk.sh")


def run_installer(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def test_choice_sdk_installer_help_is_non_mutating() -> None:
    result = run_installer("--help")

    assert result.returncode == 0
    assert "official Choice Python V2.7.5.0" in result.stdout
    assert "pinned SHA-256" in result.stdout


def test_choice_sdk_installer_rejects_relative_destination() -> None:
    result = run_installer("vendor/choice", sys.executable)

    assert result.returncode == 2
    assert "absolute, non-root path" in result.stderr


def test_choice_sdk_installer_refuses_to_overwrite(tmp_path: Path) -> None:
    destination = tmp_path / "choice"
    destination.mkdir()

    result = run_installer(str(destination), sys.executable)

    assert result.returncode == 2
    assert "refusing to overwrite" in result.stderr
