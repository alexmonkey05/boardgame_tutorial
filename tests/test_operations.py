from __future__ import annotations

from fastapi.testclient import TestClient

import main


def make_client(tmp_path) -> TestClient:
    main.DATABASE_PATH = tmp_path / "operations.sqlite3"
    main.create_schema()
    main.seed_data()
    return TestClient(main.app)


def test_readiness_request_ids_and_rate_limit_boundary(tmp_path):
    client = make_client(tmp_path)
    original_limit = main.RATE_LIMIT_RULES["/recommendations"]
    with main._runtime_lock:
        main._rate_limit_buckets.clear()
    main.RATE_LIMIT_RULES["/recommendations"] = 2
    try:
        ready = client.get("/ready")
        first = client.post("/recommendations", json={"peopleCount": 2})
        second = client.post("/recommendations", json={"peopleCount": 2})
        limited = client.post("/recommendations", json={"peopleCount": 2})
    finally:
        main.RATE_LIMIT_RULES["/recommendations"] = original_limit
        with main._runtime_lock:
            main._rate_limit_buckets.clear()

    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert first.status_code == 200
    assert second.status_code == 200
    assert limited.status_code == 429
    assert limited.headers["retry-after"]
    for response in (ready, first, second, limited):
        assert response.headers["x-request-id"]


def test_admin_observability_requires_token(tmp_path):
    client = make_client(tmp_path)
    main.ADMIN_TOKEN = "operations-token"
    assert client.get("/admin/observability").status_code == 401
    response = client.get("/admin/observability", headers={"X-Admin-Token": "operations-token"})
    assert response.status_code == 200
    assert "vision" in response.json()
    strategy = response.json()["rateLimits"]["strategy"]
    assert strategy["backend"] == "memory"
    assert strategy["multiReplicaSafe"] is False
