from __future__ import annotations

import sqlite3
import json
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ContextManager, Iterator, Protocol


class StorageRepository(Protocol):
    def connection(self) -> ContextManager[Any]: ...

    def table_names(self, conn: Any) -> set[str]: ...

    def table_columns(self, conn: Any, table: str) -> set[str]: ...


class SQLiteStorageRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def table_names(self, conn: sqlite3.Connection) -> set[str]:
        return {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
        }

    def table_columns(self, conn: sqlite3.Connection, table: str) -> set[str]:
        if not table.replace("_", "").isalnum():
            raise ValueError("Invalid table name.")
        return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}


class PostgresConnectionAdapter:
    JSON_COLUMNS = {
        ("games", "tags"),
        ("user_events", "payload"),
        ("recommendation_logs", "request_payload"),
        ("recommendation_logs", "response_payload"),
        ("admin_imports", "preview_payload"),
        ("admin_imports", "summary"),
        ("admin_audit_events", "summary"),
    }

    def __init__(self, connection: Any, jsonb_type: Any) -> None:
        self._connection = connection
        self._jsonb_type = jsonb_type

    @staticmethod
    def _query(query: str) -> str:
        return query.replace("?", "%s")

    def _jsonb(self, value: Any) -> Any:
        if isinstance(value, str):
            value = json.loads(value)
        return self._jsonb_type(value)

    def _params(self, query: str, params: tuple[Any, ...] | list[Any]) -> tuple[Any, ...]:
        values = list(params)
        insert = re.search(r"INSERT\s+INTO\s+([a-z_]+)\s*\((.*?)\)\s*VALUES", query, re.IGNORECASE | re.DOTALL)
        if insert:
            table = insert.group(1).lower()
            columns = [column.strip().lower() for column in insert.group(2).split(",")]
            for index, column in enumerate(columns):
                if index < len(values) and (table, column) in self.JSON_COLUMNS:
                    values[index] = self._jsonb(values[index])
            return tuple(values)
        update = re.search(r"UPDATE\s+([a-z_]+)\s+SET\s+(.*?)(?:\s+WHERE\s+|$)", query, re.IGNORECASE | re.DOTALL)
        if update:
            table = update.group(1).lower()
            parameter_index = 0
            for assignment in update.group(2).split(","):
                placeholder_count = assignment.count("?")
                column = assignment.split("=", 1)[0].strip().lower()
                if placeholder_count and parameter_index < len(values) and (table, column) in self.JSON_COLUMNS:
                    values[parameter_index] = self._jsonb(values[parameter_index])
                parameter_index += placeholder_count
        return tuple(values)

    def execute(self, query: str, params: tuple[Any, ...] | list[Any] = ()) -> Any:
        return self._connection.execute(self._query(query), self._params(query, params))

    def executemany(self, query: str, params: list[tuple[Any, ...]]) -> Any:
        with self._connection.cursor() as cursor:
            cursor.executemany(self._query(query), [self._params(query, row) for row in params])
            return cursor

    def executescript(self, script: str) -> Any:
        return self._connection.execute(script)


class PostgresStorageRepository:
    """PostgreSQL implementation of the application storage boundary."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    @contextmanager
    def connection(self) -> Iterator[Any]:
        try:
            import psycopg
            from psycopg.rows import dict_row
            from psycopg.types.json import Jsonb
        except ImportError as exc:
            raise RuntimeError("Install requirements-postgres.txt for PostgreSQL tests.") from exc
        with psycopg.connect(self.database_url, row_factory=dict_row) as raw_conn:
            yield PostgresConnectionAdapter(raw_conn, Jsonb)

    def table_names(self, conn: Any) -> set[str]:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        ).fetchall()
        return {row["table_name"] for row in rows}

    def table_columns(self, conn: Any, table: str) -> set[str]:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = ?",
            (table,),
        ).fetchall()
        return {row["column_name"] for row in rows}
