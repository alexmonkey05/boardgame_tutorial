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


def cafe_payload(cafe_id: str = "cafe-admin-test") -> dict[str, object]:
    return {
        "id": cafe_id,
        "name": "관리자 카페",
        "branchName": "테스트점",
        "address": "서울 테스트로 1",
        "latitude": 37.5,
        "longitude": 127.0,
        "qrCode": "QR-ADMIN-TEST",
        "status": "open",
        "metadata": {"note": "admin"},
    }


def test_admin_ui_route_serves_page(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    response = client.get("/admin-ui")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Boardgame Cafe Admin" in response.text


def test_admin_token_required_for_admin_reads(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    missing = client.get("/admin/games")
    wrong = client.get("/admin/games", headers={"X-Admin-Token": "wrong"})

    assert missing.status_code == 401
    assert wrong.status_code == 401


def test_admin_game_create_patch_and_aliases(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    created = client.post("/admin/games", json=game_payload(), headers=admin_headers())
    listed = client.get("/admin/games?q=admin-test-game", headers=admin_headers())
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
    after_alias = client.get("/admin/games?q=새 테스트 별칭", headers=admin_headers())
    deleted = client.delete(
        f"/admin/games/admin-test-game/aliases/{alias.json()['id']}",
        headers=admin_headers(),
    )

    assert created.status_code == 200
    assert listed.status_code == 200
    assert listed.json()["items"][0]["aliases"]
    assert patched.status_code == 200
    assert alias.status_code == 200
    assert after_alias.status_code == 200
    assert after_alias.json()["items"][0]["id"] == "admin-test-game"
    assert deleted.status_code == 200


def test_admin_cafe_create_and_patch(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    created = client.post("/admin/cafes", json=cafe_payload(), headers=admin_headers())
    patched = client.patch(
        "/admin/cafes/cafe-admin-test",
        json={"status": "maintenance", "metadata": {"note": "patched"}},
        headers=admin_headers(),
    )
    listed = client.get("/admin/cafes", headers=admin_headers())

    cafe = next(item for item in listed.json()["items"] if item["id"] == "cafe-admin-test")
    assert created.status_code == 200
    assert patched.status_code == 200
    assert cafe["status"] == "maintenance"
    assert cafe["metadata"]["note"] == "patched"


def test_admin_inventory_replace_and_unknown_game_404(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    client.post("/admin/cafes", json=cafe_payload(), headers=admin_headers())
    client.post("/admin/games", json=game_payload(), headers=admin_headers())

    replaced = client.put(
        "/admin/cafes/cafe-admin-test/inventory",
        json={
            "items": [
                {
                    "gameId": "admin-test-game",
                    "shelfLocation": "A-1",
                    "isAvailable": True,
                    "temporaryUnavailable": False,
                    "popularityScore": 77,
                    "staffPick": True,
                }
            ]
        },
        headers=admin_headers(),
    )
    inventory = client.get("/admin/cafes/cafe-admin-test/inventory", headers=admin_headers())
    missing_game = client.put(
        "/admin/cafes/cafe-admin-test/inventory",
        json={"items": [{"gameId": "no-such-game"}]},
        headers=admin_headers(),
    )

    assert replaced.status_code == 200
    assert inventory.status_code == 200
    assert inventory.json()["items"][0]["game"]["id"] == "admin-test-game"
    assert inventory.json()["items"][0]["inventory"]["staffPick"] is True
    assert missing_game.status_code == 404


def test_admin_logs_do_not_expose_sensitive_values(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    client.post(
        "/events",
        json={
            "eventType": "admin_safety_test",
            "payload": {"secret": "fake-secret-key", "image": "data:image/png;base64,abc"},
        },
    )
    client.post("/recognitions?cafeId=cafe-hongdae&hint=splendor")
    client.post("/recommendations", json={"cafeId": "cafe-hongdae", "peopleCount": 2})

    events = client.get("/admin/events", headers=admin_headers())
    recognitions = client.get("/admin/recognitions", headers=admin_headers())
    recommendations = client.get("/admin/recommendations", headers=admin_headers())
    combined = events.text + recognitions.text + recommendations.text

    assert events.status_code == 200
    assert recognitions.status_code == 200
    assert recommendations.status_code == 200
    assert "fake-secret-key" not in combined
    assert "data:image" not in combined
    assert "base64" not in combined.lower()
    assert ADMIN_TOKEN not in combined
