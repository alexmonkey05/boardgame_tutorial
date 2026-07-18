from __future__ import annotations

from fastapi.testclient import TestClient

import main


ADMIN_TOKEN = "test-admin-token"


def make_client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("VISION_API_PROVIDER", "mock")
    main.ADMIN_TOKEN = ADMIN_TOKEN
    main.DATABASE_PATH = tmp_path / "admin.sqlite3"
    main.create_schema()
    main.seed_data()
    return TestClient(main.app)


def admin_headers() -> dict[str, str]:
    return {"X-Admin-Token": ADMIN_TOKEN}


def game_payload(game_id: str = "admin-test-game") -> dict[str, object]:
    return {
        "id": game_id,
        "nameKo": "관리자 테스트 게임",
        "nameEn": "Admin Test Game",
        "shortDescription": "관리자 화면 테스트용 게임입니다.",
        "rulesSummary": "테스트용 규칙 요약입니다.",
        "minPlayers": 2,
        "maxPlayers": 4,
        "avgPlayTimeMinutes": 30,
        "difficulty": "easy",
        "genre": "family",
        "tags": ["test", "admin"],
        "isBeginnerFriendly": True,
        "isKidFriendly": True,
        "isPartyGame": False,
        "isStrategyGame": False,
        "playStyle": "competitive",
        "imageUrl": None,
        "aliases": ["관리자 별칭"],
    }


def test_admin_ui_route_serves_game_data_console(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    response = client.get("/admin-ui")

    assert response.status_code == 200
    assert "Boardgame Data Admin" in response.text
    for forbidden in ["카페", "재고", "선반", "대여 가능"]:
        assert forbidden not in response.text


def test_admin_token_required_for_admin_reads(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    assert client.get("/admin/games").status_code == 401
    assert client.get("/admin/games", headers={"X-Admin-Token": "wrong"}).status_code == 401


def test_admin_game_alias_and_relation_management(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    created = client.post("/admin/games", json=game_payload(), headers=admin_headers())
    patched = client.patch(
        "/admin/games/admin-test-game",
        json={"avgPlayTimeMinutes": 45, "isStrategyGame": True},
        headers=admin_headers(),
    )
    alias = client.post(
        "/admin/games/admin-test-game/aliases",
        json={"alias": "새 테스트 별칭"},
        headers=admin_headers(),
    )
    relation = client.post(
        "/admin/games/admin-test-game/relations",
        json={"targetGameId": "splendor", "relationType": "similar"},
        headers=admin_headers(),
    )
    listed = client.get("/admin/games?q=admin-test-game", headers=admin_headers())
    game = listed.json()["items"][0]

    assert created.status_code == 200
    assert patched.status_code == 200
    assert alias.status_code == 200
    assert relation.status_code == 200
    assert any(item["alias"] == "새 테스트 별칭" for item in game["aliases"])
    assert any(item["targetGameId"] == "splendor" for item in game["relations"])

    assert client.delete(
        f"/admin/games/admin-test-game/aliases/{alias.json()['id']}", headers=admin_headers()
    ).status_code == 200
    assert client.delete(
        f"/admin/games/admin-test-game/relations/{relation.json()['id']}", headers=admin_headers()
    ).status_code == 200


def test_removed_admin_routes_are_not_exposed(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    paths = client.get("/openapi.json").json()["paths"]

    assert not any(path.startswith("/admin/cafes") for path in paths)
    assert not any(path.startswith("/cafes") for path in paths)
    assert client.get("/admin/cafes", headers=admin_headers()).status_code == 404


def test_admin_logs_do_not_expose_sensitive_or_removed_context(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    client.post(
        "/events",
        json={"eventType": "admin_safety_test", "payload": {"secret": "fake-secret-key", "image": "data:image/png;base64,abc"}},
    )
    client.post("/recognitions?hint=splendor")
    client.post("/recommendations", json={"peopleCount": 2})

    events = client.get("/admin/events", headers=admin_headers())
    recognitions = client.get("/admin/recognitions", headers=admin_headers())
    recommendations = client.get("/admin/recommendations", headers=admin_headers())
    combined = events.text + recognitions.text + recommendations.text

    assert events.status_code == 200
    assert recognitions.status_code == 200
    assert recommendations.status_code == 200
    for forbidden in ["fake-secret-key", "data:image", "base64", ADMIN_TOKEN, "cafeId", "shelfLocation"]:
        assert forbidden not in combined
