from __future__ import annotations

from fastapi.testclient import TestClient

import main


def test_root_serves_frontend(tmp_path, monkeypatch):
    monkeypatch.setenv("VISION_API_PROVIDER", "mock")
    main.DATABASE_PATH = tmp_path / "deployment.sqlite3"
    main.create_schema()
    main.seed_data()
    client = TestClient(main.app)

    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "보드게임 탐색기" in response.text
    for forbidden in ["카페", "매장", "선반", "재고", "대여 가능"]:
        assert forbidden not in response.text


def test_startup_creates_database_parent_directory(tmp_path, monkeypatch):
    nested_db = tmp_path / "data" / "boardgame_backend.sqlite3"
    main.DATABASE_PATH = nested_db

    main.startup()

    assert nested_db.parent.exists()
    assert nested_db.exists()
