from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

import main
from recognition_service import match_vision_candidates, parse_vision_response
from vision_client import build_nvidia_payload


def make_client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("VISION_API_PROVIDER", "mock")
    monkeypatch.setenv("VISION_API_KEY", "")
    monkeypatch.setenv("VISION_API_ENDPOINT", "")
    monkeypatch.setenv("VISION_MODEL", "")
    main.DATABASE_PATH = tmp_path / "recognition.sqlite3"
    main.create_schema()
    main.seed_data()
    return TestClient(main.app)


def test_fallback_recognition_works_without_nvidia_settings(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    response = client.post("/recognitions?cafeId=cafe-hongdae&hint=splendor")

    assert response.status_code == 200
    body = response.json()
    assert body["externalProcessing"]["used"] is False
    assert body["topCandidate"]["game"]["id"] == "splendor"
    assert body["topCandidate"]["isAvailableInCafe"] is True


def test_nvidia_payload_contains_image_and_no_api_key():
    payload = build_nvidia_payload(b"fake-image", "image/png", "splendor", "vision-model")
    payload_text = str(payload)

    assert payload["model"] == "vision-model"
    assert "data:image/png;base64," in payload_text
    assert "fake-secret-key" not in payload_text
    assert "candidates" in payload_text


def test_parse_vision_response_handles_json_and_malformed_text():
    parsed = parse_vision_response(
        {
            "content": '{"candidates":[{"name":"Splendor","nameKo":"스플렌더","confidence":0.86}],"needsRetake":false}'
        }
    )
    malformed = parse_vision_response({"content": "not json"})

    assert parsed["candidates"][0]["name"] == "Splendor"
    assert parsed["needsRetake"] is False
    assert malformed["candidates"] == []
    assert malformed["needsRetake"] is True


def test_unknown_vision_candidate_is_not_returned_as_final_candidate(tmp_path, monkeypatch):
    make_client(tmp_path, monkeypatch)
    with sqlite3.connect(main.DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        result = match_vision_candidates(
            conn,
            {"candidates": [{"name": "Unknown Prototype", "nameKo": "없는 게임", "confidence": 0.99}]},
            "cafe-hongdae",
        )

    assert result["candidates"] == []
    assert result["unmatchedCandidates"][0]["name"] == "Unknown Prototype"


def test_missing_cafe_returns_404(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    response = client.post("/recognitions?cafeId=no-such-cafe&hint=splendor")

    assert response.status_code == 404


def test_post_recognitions_uses_nvidia_when_image_and_settings_exist(tmp_path, monkeypatch):
    monkeypatch.setenv("VISION_API_PROVIDER", "nvidia")
    monkeypatch.setenv("VISION_API_KEY", "fake-secret-key")
    monkeypatch.setenv("VISION_API_ENDPOINT", "https://example.invalid/v1/chat/completions")
    monkeypatch.setenv("VISION_MODEL", "vision-model")
    main.DATABASE_PATH = tmp_path / "nvidia.sqlite3"
    main.create_schema()
    main.seed_data()

    async def fake_recognize(image_bytes, content_type, hint=None):
        assert image_bytes == b"image-bytes"
        assert content_type == "image/jpeg"
        assert hint == "splendor"
        return {
            "content": '{"candidates":[{"name":"Splendor","nameKo":"스플렌더","confidence":0.91,"evidence":"title"}],"needsRetake":false}'
        }

    monkeypatch.setattr(main, "recognize_boardgame_image", fake_recognize)
    client = TestClient(main.app)

    response = client.post(
        "/recognitions?cafeId=cafe-hongdae&hint=splendor",
        files={"image": ("box.jpg", b"image-bytes", "image/jpeg")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["externalProcessing"]["used"] is True
    assert body["topCandidate"]["game"]["id"] == "splendor"
    assert body["topCandidate"]["nvidiaConfidence"] == 0.91


def test_recognition_rejects_empty_image(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    response = client.post(
        "/recognitions?cafeId=cafe-hongdae",
        files={"image": ("empty.jpg", b"", "image/jpeg")},
    )

    assert response.status_code == 400
    assert "base64" not in response.text.lower()
    assert "fake-secret-key" not in response.text


def test_recognition_rejects_unsupported_mime_type(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    response = client.post(
        "/recognitions?cafeId=cafe-hongdae",
        files={"image": ("note.txt", b"not-an-image", "text/plain")},
    )

    assert response.status_code == 400
    assert "base64" not in response.text.lower()
    assert "note.txt" not in response.text


def test_recognition_rejects_large_image(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    oversized = b"x" * (main.MAX_IMAGE_UPLOAD_BYTES + 1)

    response = client.post(
        "/recognitions?cafeId=cafe-hongdae",
        files={"image": ("large.png", oversized, "image/png")},
    )

    assert response.status_code == 400
    assert "5MB" in response.text
    assert "base64" not in response.text.lower()
