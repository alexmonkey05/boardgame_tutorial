from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from storage import PostgresStorageRepository, SQLiteStorageRepository


def test_sqlite_storage_contract_and_schema_idempotency(tmp_path):
    main.DATABASE_PATH = tmp_path / "storage.sqlite3"
    main.create_schema()
    main.seed_data()
    repository = SQLiteStorageRepository(main.DATABASE_PATH)
    with repository.connection() as conn:
        ids_before = [row[0] for row in conn.execute("SELECT id FROM games ORDER BY id")]
        assert "games" in repository.table_names(conn)
        assert {"data_source_url", "content_license", "reviewed_at"} <= repository.table_columns(conn, "games")
    main.create_schema()
    main.seed_data()
    with repository.connection() as conn:
        ids_after = [row[0] for row in conn.execute("SELECT id FROM games ORDER BY id")]
        assert ids_after == ids_before
        assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 7


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"), reason="TEST_POSTGRES_URL is not configured")
def test_postgres_storage_schema_contract():
    previous_url = main.DATABASE_URL
    main.DATABASE_URL = os.environ["TEST_POSTGRES_URL"]
    try:
        main.create_schema()
        main.create_schema()
        main.seed_data()
        repository = PostgresStorageRepository(main.DATABASE_URL)
        with repository.connection() as conn:
            assert "games" in repository.table_names(conn)
            assert {"data_source_url", "content_license", "reviewed_at"} <= repository.table_columns(conn, "games")
        client = TestClient(main.app)
        assert client.get("/health").json()["database"] == "postgresql"
        assert client.get("/ready").status_code == 200
        assert client.get("/games?limit=3").status_code == 200
        assert client.post("/recommendations", json={"peopleCount": 2, "limit": 2}).status_code == 200
        main.ADMIN_TOKEN = "postgres-contract-token"
        quality = client.get("/admin/data-quality", headers={"X-Admin-Token": main.ADMIN_TOKEN})
        assert quality.status_code == 200
        assert quality.json()["summary"]["errors"] == 0
        dataset = Path(__file__).resolve().parents[1] / "data" / "boardgames_wikidata_cc0.csv"
        preview = client.post(
            "/admin/imports/games/preview",
            headers={"X-Admin-Token": main.ADMIN_TOKEN},
            files={"file": (dataset.name, dataset.read_bytes(), "text/csv")},
        )
        assert preview.status_code == 200
        assert preview.json()["summary"]["invalidRows"] == 0
    finally:
        main.DATABASE_URL = previous_url
