from __future__ import annotations

from scripts.migrate_sqlite_to_postgres import snapshot_sqlite
from scripts.rehearse_sqlite_backup import rehearse_backup

import main


def test_sqlite_backup_restore_rehearsal(tmp_path):
    main.DATABASE_PATH = tmp_path / "source.sqlite3"
    main.create_schema()
    main.seed_data()
    report = rehearse_backup(main.DATABASE_PATH, tmp_path / "backup.sqlite3", tmp_path / "restored.sqlite3")
    assert report["success"] is True
    assert report["tableCounts"]["source"] == report["tableCounts"]["restored"]


def test_postgres_dry_run_validates_active_rows(tmp_path):
    main.DATABASE_PATH = tmp_path / "migration-source.sqlite3"
    main.create_schema()
    main.seed_data()
    report = snapshot_sqlite(main.DATABASE_PATH)
    assert report["success"] is True
    assert report["tables"]["games"] == 7
    assert report["foreignKeyErrors"] == []
    assert report["jsonErrors"] == []
