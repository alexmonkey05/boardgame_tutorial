from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any


TABLE_COLUMNS = {
    "games": ["id", "name_ko", "name_en", "short_description", "rules_summary", "min_players", "max_players", "avg_play_time_minutes", "difficulty", "genre", "tags", "is_beginner_friendly", "is_kid_friendly", "is_party_game", "is_strategy_game", "play_style", "image_url", "image_source", "image_license", "image_alt", "data_source_url", "data_license", "content_license", "reviewed_at", "reviewed_by", "created_at", "updated_at"],
    "game_aliases": ["id", "game_id", "alias", "normalized_alias"],
    "game_relations": ["id", "source_game_id", "target_game_id", "relation_type"],
    "users": ["id", "provider", "display_name", "created_at"],
    "anonymous_sessions": ["id", "device_label", "created_at", "last_seen_at"],
    "user_events": ["id", "user_id", "session_id", "event_type", "game_id", "payload", "created_at"],
    "played_games": ["id", "user_id", "game_id", "played_at", "rating", "notes"],
    "hidden_games": ["id", "user_id", "game_id", "reason", "created_at"],
    "recognition_jobs": ["id", "user_id", "session_id", "status", "image_original_stored", "hint_text", "top_game_id", "confidence", "needs_retake", "message", "confirmed_game_id", "created_at", "confirmed_at"],
    "recognition_candidates": ["id", "recognition_id", "game_id", "confidence"],
    "recommendation_logs": ["id", "user_id", "session_id", "request_payload", "response_payload", "created_at"],
    "admin_users": ["id", "name", "token_hint", "role", "created_at"],
    "admin_imports": ["id", "kind", "status", "preview_payload", "summary", "created_at", "expires_at", "applied_at"],
    "admin_audit_events": ["id", "action", "entity_type", "entity_id", "summary", "created_at"],
}

JSON_COLUMNS = {
    ("games", "tags"),
    ("user_events", "payload"),
    ("recommendation_logs", "request_payload"),
    ("recommendation_logs", "response_payload"),
    ("admin_imports", "preview_payload"),
    ("admin_imports", "summary"),
    ("admin_audit_events", "summary"),
}

DELETE_ORDER = [
    "admin_audit_events",
    "admin_imports",
    "admin_users",
    "recommendation_logs",
    "recognition_candidates",
    "recognition_jobs",
    "hidden_games",
    "played_games",
    "user_events",
    "anonymous_sessions",
    "users",
    "game_relations",
    "game_aliases",
    "games",
]


def snapshot_sqlite(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        available = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        missing = sorted(set(TABLE_COLUMNS) - available)
        if missing:
            raise RuntimeError(f"Active tables missing: {', '.join(missing)}")
        foreign_key_errors = [dict(row) for row in conn.execute("PRAGMA foreign_key_check")]
        counts: dict[str, int] = {}
        ids: dict[str, list[str]] = {}
        json_errors: list[dict[str, str]] = []
        digest = hashlib.sha256()
        for table, columns in TABLE_COLUMNS.items():
            existing_columns = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
            missing_columns = [column for column in columns if column not in existing_columns]
            if missing_columns:
                raise RuntimeError(f"{table} columns missing: {', '.join(missing_columns)}")
            rows = conn.execute(f'SELECT {", ".join(columns)} FROM "{table}" ORDER BY id').fetchall()
            counts[table] = len(rows)
            ids[table] = [str(row["id"]) for row in rows[:20]]
            for row in rows:
                digest.update(json.dumps(dict(row), ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"))
                for column in columns:
                    if (table, column) in JSON_COLUMNS and row[column] not in (None, ""):
                        try:
                            json.loads(row[column])
                        except (TypeError, json.JSONDecodeError):
                            json_errors.append({"table": table, "id": str(row["id"]), "column": column})
        return {
            "database": str(path),
            "tables": counts,
            "sampleIds": ids,
            "foreignKeyErrors": foreign_key_errors,
            "jsonErrors": json_errors,
            "contentSha256": digest.hexdigest(),
            "success": not foreign_key_errors and not json_errors,
        }


def apply_postgres(
    snapshot_path: Path,
    database_url: str,
    schema_path: Path,
    *,
    prune_target: bool = False,
) -> dict[str, Any]:
    if os.getenv("ALLOW_POSTGRES_APPLY") != "1":
        raise RuntimeError("Set ALLOW_POSTGRES_APPLY=1 only after backup rehearsal and explicit approval.")
    if prune_target and os.getenv("ALLOW_POSTGRES_PRUNE") != "1":
        raise RuntimeError("Set ALLOW_POSTGRES_PRUNE=1 only for an approved, backed-up replacement migration.")
    try:
        import psycopg
        from psycopg import sql
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise RuntimeError("Install requirements-postgres.txt before --apply.") from exc

    with sqlite3.connect(snapshot_path) as source, psycopg.connect(database_url) as target:
        source.row_factory = sqlite3.Row
        target.execute(schema_path.read_text(encoding="utf-8"))
        applied: dict[str, int] = {}
        source_ids: dict[str, list[Any]] = {}
        for table, columns in TABLE_COLUMNS.items():
            rows = source.execute(f'SELECT {", ".join(columns)} FROM "{table}" ORDER BY id').fetchall()
            if prune_target:
                source_ids[table] = [row["id"] for row in rows]
            update_columns = [column for column in columns if column != "id"]
            statement = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT (id) DO UPDATE SET {}").format(
                sql.Identifier(table),
                sql.SQL(", ").join(map(sql.Identifier, columns)),
                sql.SQL(", ").join(sql.Placeholder() for _ in columns),
                sql.SQL(", ").join(
                    sql.SQL("{} = EXCLUDED.{}").format(sql.Identifier(column), sql.Identifier(column))
                    for column in update_columns
                ),
            )
            batch = []
            for row in rows:
                values = []
                for column in columns:
                    value = row[column]
                    if (table, column) in JSON_COLUMNS and value not in (None, ""):
                        value = Jsonb(json.loads(value))
                    values.append(value)
                batch.append(values)
            if batch:
                with target.cursor() as cursor:
                    cursor.executemany(statement, batch)
            applied[table] = len(rows)
        deleted: dict[str, int] = {}
        if prune_target:
            for table in DELETE_ORDER:
                ids = source_ids[table]
                if ids:
                    result = target.execute(
                        sql.SQL("DELETE FROM {} WHERE NOT (id = ANY(%s))").format(sql.Identifier(table)),
                        (ids,),
                    )
                else:
                    result = target.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(table)))
                deleted[table] = result.rowcount
        for table in ("game_aliases", "game_relations", "recognition_candidates"):
            target.execute(
                sql.SQL(
                    "SELECT setval(pg_get_serial_sequence({}, 'id'), COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {}"
                ).format(sql.Literal(table), sql.Identifier(table))
            )
        target.commit()
    return {
        "appliedRows": applied,
        "deletedRows": deleted,
        "prunedTarget": prune_target,
        "success": True,
    }


def validate_apply_options(
    *,
    apply: bool,
    confirm: str,
    prune_target: bool,
    prune_confirm: str,
) -> None:
    if prune_target and not apply:
        raise RuntimeError("--prune-target requires --apply.")
    if not apply:
        return
    if confirm != "APPLY_POSTGRES":
        raise RuntimeError("--apply requires --confirm APPLY_POSTGRES.")
    if prune_target and prune_confirm != "DELETE_POSTGRES_ROWS_NOT_IN_SQLITE":
        raise RuntimeError(
            "--prune-target requires --prune-confirm DELETE_POSTGRES_ROWS_NOT_IN_SQLITE."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate SQLite data and optionally upsert it into PostgreSQL.")
    parser.add_argument("sqlite", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument(
        "--prune-target",
        action="store_true",
        help="Delete PostgreSQL rows that are absent from SQLite. Never use during normal production sync.",
    )
    parser.add_argument("--prune-confirm", default="")
    parser.add_argument("--schema", type=Path, default=Path(__file__).resolve().parents[1] / "docs" / "postgresql_target_schema.sql")
    args = parser.parse_args()
    validate_apply_options(
        apply=args.apply,
        confirm=args.confirm,
        prune_target=args.prune_target,
        prune_confirm=args.prune_confirm,
    )
    snapshot = snapshot_sqlite(args.sqlite)
    result: dict[str, Any] = {"mode": "dry-run", "validation": snapshot}
    if args.apply:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL is required for --apply.")
        result = {
            "mode": "apply",
            "validation": snapshot,
            "apply": apply_postgres(
                args.sqlite,
                database_url,
                args.schema,
                prune_target=args.prune_target,
            ),
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if snapshot["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
