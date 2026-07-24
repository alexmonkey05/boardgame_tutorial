from __future__ import annotations

import pytest

from scripts.migrate_sqlite_to_postgres import (
    apply_postgres,
    snapshot_sqlite,
    validate_apply_options,
)
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


def test_postgres_apply_is_upsert_only_without_prune_confirmation():
    validate_apply_options(
        apply=True,
        confirm="APPLY_POSTGRES",
        prune_target=False,
        prune_confirm="",
    )


@pytest.mark.parametrize(
    ("apply", "confirm", "prune_target", "prune_confirm", "message"),
    [
        (False, "", True, "", "--prune-target requires --apply"),
        (True, "", False, "", "--apply requires --confirm APPLY_POSTGRES"),
        (
            True,
            "APPLY_POSTGRES",
            True,
            "",
            "--prune-target requires --prune-confirm DELETE_POSTGRES_ROWS_NOT_IN_SQLITE",
        ),
    ],
)
def test_postgres_prune_requires_independent_confirmation(
    apply, confirm, prune_target, prune_confirm, message
):
    with pytest.raises(RuntimeError, match=message):
        validate_apply_options(
            apply=apply,
            confirm=confirm,
            prune_target=prune_target,
            prune_confirm=prune_confirm,
        )


def test_postgres_prune_requires_environment_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLOW_POSTGRES_APPLY", "1")
    monkeypatch.delenv("ALLOW_POSTGRES_PRUNE", raising=False)

    with pytest.raises(RuntimeError, match="Set ALLOW_POSTGRES_PRUNE=1"):
        apply_postgres(
            tmp_path / "source.sqlite3",
            "postgresql://unused",
            tmp_path / "schema.sql",
            prune_target=True,
        )
