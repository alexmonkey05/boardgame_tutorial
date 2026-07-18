from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


def table_counts(path: Path) -> dict[str, int]:
    with sqlite3.connect(path) as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        return {table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables}


def integrity_check(path: Path) -> str:
    with sqlite3.connect(path) as conn:
        return conn.execute("PRAGMA integrity_check").fetchone()[0]


def rehearse_backup(source: Path, backup: Path, restored: Path) -> dict[str, Any]:
    source = source.resolve()
    backup = backup.resolve()
    restored = restored.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"SQLite source not found: {source}")
    for target in (backup, restored):
        if target.exists():
            raise FileExistsError(f"Refusing to overwrite rehearsal target: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(source) as source_conn, sqlite3.connect(backup) as backup_conn:
        source_conn.backup(backup_conn)
    with sqlite3.connect(backup) as backup_conn, sqlite3.connect(restored) as restored_conn:
        backup_conn.backup(restored_conn)

    source_counts = table_counts(source)
    backup_counts = table_counts(backup)
    restored_counts = table_counts(restored)
    report = {
        "source": str(source),
        "backup": str(backup),
        "restored": str(restored),
        "integrity": {
            "source": integrity_check(source),
            "backup": integrity_check(backup),
            "restored": integrity_check(restored),
        },
        "tableCounts": {
            "source": source_counts,
            "backup": backup_counts,
            "restored": restored_counts,
        },
        "countsMatch": source_counts == backup_counts == restored_counts,
    }
    report["success"] = report["countsMatch"] and all(value == "ok" for value in report["integrity"].values())
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Create and restore a non-destructive SQLite backup rehearsal.")
    parser.add_argument("source", type=Path)
    parser.add_argument("backup", type=Path)
    parser.add_argument("restored", type=Path)
    args = parser.parse_args()
    report = rehearse_backup(args.source, args.backup, args.restored)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
