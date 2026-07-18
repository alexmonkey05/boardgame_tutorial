from __future__ import annotations

from fastapi.testclient import TestClient

import main


def make_client(tmp_path) -> TestClient:
    main.DATABASE_PATH = tmp_path / "recommendations.sqlite3"
    main.create_schema()
    main.seed_data()
    return TestClient(main.app)


def test_recommendations_work_without_cafe_context(tmp_path):
    client = make_client(tmp_path)

    response = client.post(
        "/recommendations",
        json={
            "peopleCount": 4,
            "remainingMinutes": 45,
            "preferredDifficulty": "easy",
            "preferredGenres": ["strategy"],
            "limit": 4,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 4
    assert "cafeId" not in body
    combined = response.text
    for forbidden in ["isAvailableInCafe", "shelfLocation", "매장", "선반", "대여 가능"]:
        assert forbidden not in combined


def test_recommendation_openapi_has_no_cafe_field(tmp_path):
    client = make_client(tmp_path)
    schema = client.get("/openapi.json").json()
    request_schema = schema["components"]["schemas"]["RecommendationRequest"]

    assert "cafeId" not in request_schema["properties"]
    assert "preferredGenres" in request_schema["properties"]


def test_games_filter_the_full_database(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/games?peopleCount=4&maxPlayTime=30&difficulty=easy&genre=party")

    assert response.status_code == 200
    items = response.json()["items"]
    assert {item["id"] for item in items} == {"codenames", "dixit"}
