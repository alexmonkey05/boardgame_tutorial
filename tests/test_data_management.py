from __future__ import annotations

import csv
import io
import sqlite3

from fastapi.testclient import TestClient

import main
from data_management import GAME_CSV_FIELDS


ADMIN_TOKEN = "quality-test-token"


def make_client(tmp_path) -> TestClient:
    main.ADMIN_TOKEN = ADMIN_TOKEN
    main.DATABASE_PATH = tmp_path / "data-management.sqlite3"
    main.create_schema()
    main.seed_data()
    return TestClient(main.app)


def headers() -> dict[str, str]:
    return {"X-Admin-Token": ADMIN_TOKEN}


def csv_bytes(rows: list[dict[str, object]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=GAME_CSV_FIELDS)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue().encode("utf-8")


def valid_csv_row(game_id: str = "csv-new-game") -> dict[str, object]:
    return {
        "id": game_id,
        "nameKo": "CSV 새 게임",
        "nameEn": "CSV New Game",
        "shortDescription": "CSV 가져오기 테스트 게임입니다.",
        "rulesSummary": "차례마다 카드를 한 장 사용합니다.",
        "minPlayers": 2,
        "maxPlayers": 4,
        "avgPlayTimeMinutes": 30,
        "difficulty": "easy",
        "genre": "family",
        "tags": "test|cards",
        "isBeginnerFriendly": "true",
        "isKidFriendly": "true",
        "isPartyGame": "false",
        "isStrategyGame": "false",
        "playStyle": "competitive",
        "imageUrl": "",
        "imageSource": "",
        "imageLicense": "",
        "imageAlt": "",
        "aliases": "CSV 게임|CSV New Game",
    }


def test_csv_preview_apply_export_and_audit(tmp_path):
    client = make_client(tmp_path)
    invalid = valid_csv_row("csv-invalid-game")
    invalid["nameKo"] = "CSV 오류 게임"
    invalid["nameEn"] = "CSV Invalid Game"
    invalid["aliases"] = "CSV 오류"
    invalid["minPlayers"] = 5
    invalid["maxPlayers"] = 2
    preview = client.post(
        "/admin/imports/games/preview",
        headers=headers(),
        files={"file": ("games.csv", csv_bytes([valid_csv_row(), invalid]), "text/csv")},
    )

    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["summary"]["validRows"] == 1
    assert preview_body["summary"]["invalidRows"] == 1
    assert client.post(
        "/admin/imports/games/apply",
        headers=headers(),
        json={"importId": "missing", "strategy": "valid_only"},
    ).status_code == 404
    assert client.post(
        "/admin/imports/games/apply",
        headers=headers(),
        json={"importId": preview_body["importId"], "strategy": "all_or_nothing"},
    ).status_code == 400

    applied = client.post(
        "/admin/imports/games/apply",
        headers=headers(),
        json={"importId": preview_body["importId"], "strategy": "valid_only"},
    )
    assert applied.status_code == 200
    assert applied.json()["changedCount"] == 1
    assert client.get("/games/csv-new-game").status_code == 200
    assert client.post(
        "/admin/imports/games/apply",
        headers=headers(),
        json={"importId": preview_body["importId"], "strategy": "valid_only"},
    ).status_code == 409

    games_export = client.get("/admin/exports/games.csv", headers=headers())
    aliases_export = client.get("/admin/exports/aliases.csv", headers=headers())
    audits = client.get("/admin/audit-events", headers=headers())
    assert games_export.status_code == 200
    assert "csv-new-game" in games_export.text
    assert aliases_export.status_code == 200
    assert "CSV 게임" in aliases_export.text
    assert audits.json()["items"][0]["action"] == "games_csv_applied"
    for forbidden in [ADMIN_TOKEN, "CSV 가져오기 테스트 게임입니다.", "차례마다 카드를"]:
        assert forbidden not in audits.text


def test_csv_detects_alias_conflicts_and_quality_issues(tmp_path):
    client = make_client(tmp_path)
    conflicting = valid_csv_row("alias-conflict-game")
    conflicting["aliases"] = "splendor"
    preview = client.post(
        "/admin/imports/games/preview",
        headers=headers(),
        files={"file": ("games.csv", csv_bytes([conflicting]), "text/csv")},
    )
    assert preview.status_code == 200
    assert preview.json()["summary"]["invalidRows"] == 1

    with sqlite3.connect(main.DATABASE_PATH) as conn:
        conn.execute(
            "INSERT INTO game_aliases(game_id, alias, normalized_alias) VALUES (?, ?, ?)",
            ("codenames", "Splendor", "splendor"),
        )
        conn.execute(
            "INSERT INTO game_relations(source_game_id, target_game_id, relation_type) VALUES (?, ?, ?)",
            ("splendor", "splendor", "similar"),
        )
        conn.commit()
    quality = client.get("/admin/data-quality", headers=headers())
    issue_types = {issue["type"] for issue in quality.json()["issues"]}
    assert quality.status_code == 200
    assert "alias_conflict" in issue_types
    assert "self_relation" in issue_types


def test_image_metadata_and_global_alias_rules_are_enforced(tmp_path):
    client = make_client(tmp_path)
    payload = {
        "id": "image-rule-game",
        "nameKo": "이미지 규칙 게임",
        "nameEn": "Image Rule Game",
        "shortDescription": "이미지 규칙 테스트입니다.",
        "rulesSummary": "규칙 테스트입니다.",
        "minPlayers": 2,
        "maxPlayers": 4,
        "avgPlayTimeMinutes": 20,
        "difficulty": "easy",
        "genre": "family",
        "imageUrl": "https://example.com/game.jpg",
        "aliases": [],
    }
    assert client.post("/admin/games", headers=headers(), json=payload).status_code == 400
    payload.update({"imageSource": "Publisher", "imageLicense": "permission-granted", "imageAlt": "게임 상자"})
    assert client.post("/admin/games", headers=headers(), json=payload).status_code == 200
    assert client.post(
        "/admin/games/image-rule-game/aliases",
        headers=headers(),
        json={"alias": "splendor"},
    ).status_code == 409
