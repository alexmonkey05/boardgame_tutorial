from __future__ import annotations

from fastapi.testclient import TestClient

import main


def make_client(tmp_path) -> TestClient:
    main.DATABASE_PATH = tmp_path / "recommendations.sqlite3"
    main.create_schema()
    main.seed_data()
    return TestClient(main.app)


def test_recommendations_unknown_cafe_returns_404(tmp_path):
    client = make_client(tmp_path)

    response = client.post("/recommendations", json={"cafeId": "no-such-cafe"})

    assert response.status_code == 404
