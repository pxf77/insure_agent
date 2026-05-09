import os
import subprocess
import sys
from pathlib import Path


def test_create_db_and_tables_registers_models_from_database_import(tmp_path: Path) -> None:
    db_path = tmp_path / "hermes.db"
    script = f"""
import sqlite3

from backend.app.database import create_db_and_tables

create_db_and_tables()

with sqlite3.connect({str(db_path)!r}) as connection:
    tables = {{
        row[0]
        for row in connection.execute(
            "select name from sqlite_master where type = 'table'"
        )
    }}

expected = {{"watchlist", "signal", "riskcheck", "manualreview"}}
missing = expected - tables
if missing:
    raise SystemExit(f"missing tables: {{sorted(missing)}}")
"""
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr + result.stdout
