from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

import main


def make_client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("VISION_API_PROVIDER", "mock")
    monkeypatch.setenv("VISION_API_KEY", "")
    monkeypatch.setenv("VISION_API_ENDPOINT", "")
    monkeypatch.setenv("VISION_MODEL", "")
    main.DATABASE_PATH = tmp_path / "privacy.sqlite3"
    main.create_schema()
    main.seed_data()
    return TestClient(main.app)


def test_recognition_does_not_store_original_image(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    response = client.post(
        "/recognitions?userId=user-1",
        files={"image": ("splendor.jpg", b"image-bytes", "image/jpeg")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["imageRetention"]["storeOriginalImage"] is False
    assert body["externalProcessing"]["storesOriginalImageLocally"] is False

    with sqlite3.connect(main.DATABASE_PATH) as conn:
        stored = conn.execute("SELECT image_original_stored FROM recognition_jobs").fetchone()[0]
    assert stored == 0


def test_delete_user_data_cleans_recognition_logs(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    client.post("/recognitions?userId=user-1&hint=splendor")

    response = client.delete("/users/user-1/data")

    assert response.status_code == 200
    body = response.json()
    assert body["deleted"]["recognitionJobs"] == 1
    assert body["imageRetention"]["storeOriginalImage"] is False


def test_health_and_schema_do_not_expose_secret_values(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    main.VISION_API_PROVIDER = "nvidia"
    main.VISION_API_KEY = "fake-secret-key"
    main.VISION_API_ENDPOINT = "https://example.invalid/v1/chat/completions"
    main.VISION_MODEL = "secret-model-name"

    health = client.get("/health").text
    schema = client.get("/meta/schema").text

    assert "fake-secret-key" not in health
    assert "fake-secret-key" not in schema
    assert "https://example.invalid" not in health
    assert "https://example.invalid" not in schema
    assert "secret-model-name" not in health
    assert "secret-model-name" not in schema
