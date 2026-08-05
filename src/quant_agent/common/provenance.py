from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from quant_agent.common.io import content_sha256


def configuration_hash(resolved_config: dict[str, Any]) -> str:
    return content_sha256(resolved_config)


def code_version(project_root: str | Path = ".") -> str:
    root = Path(project_root)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    revision = result.stdout.strip()
    if not revision:
        return "unknown"
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        if not status:
            return revision
        digest = hashlib.sha256(status.encode("utf-8"))
        tracked_diff = subprocess.run(
            ["git", "diff", "--binary", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
        ).stdout
        digest.update(tracked_diff)
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=root,
            check=True,
            capture_output=True,
        ).stdout.split(b"\0")
        for raw_path in sorted(value for value in untracked if value):
            path = root / raw_path.decode("utf-8")
            if path.is_file():
                digest.update(raw_path)
                digest.update(path.read_bytes())
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError):
        return f"{revision}-dirty"
    return f"{revision}-dirty-{digest.hexdigest()[:12]}"
