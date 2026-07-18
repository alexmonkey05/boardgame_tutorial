from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any


ALLOWED_DIFFICULTIES = {"easy", "medium", "hard"}
ALLOWED_GENRES = {"strategy", "party", "puzzle", "family", "cooperative"}
IMPORT_TTL_MINUTES = 15
MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_IMPORT_ROWS = 2000
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

GAME_CSV_FIELDS = [
    "id",
    "nameKo",
    "nameEn",
    "shortDescription",
    "rulesSummary",
    "minPlayers",
    "maxPlayers",
    "avgPlayTimeMinutes",
    "difficulty",
    "genre",
    "tags",
    "isBeginnerFriendly",
    "isKidFriendly",
    "isPartyGame",
    "isStrategyGame",
    "playStyle",
    "imageUrl",
    "imageSource",
    "imageLicense",
    "imageAlt",
    "dataSourceUrl",
    "dataLicense",
    "contentLicense",
    "reviewedAt",
    "reviewedBy",
    "aliases",
]

REQUIRED_CSV_FIELDS = {
    "id",
    "nameKo",
    "shortDescription",
    "rulesSummary",
    "minPlayers",
    "maxPlayers",
    "avgPlayTimeMinutes",
    "difficulty",
    "genre",
    "dataSourceUrl",
    "dataLicense",
    "contentLicense",
    "reviewedAt",
    "reviewedBy",
}

GAME_DB_COLUMNS = {
    "nameKo": "name_ko",
    "nameEn": "name_en",
    "shortDescription": "short_description",
    "rulesSummary": "rules_summary",
    "minPlayers": "min_players",
    "maxPlayers": "max_players",
    "avgPlayTimeMinutes": "avg_play_time_minutes",
    "difficulty": "difficulty",
    "genre": "genre",
    "tags": "tags",
    "isBeginnerFriendly": "is_beginner_friendly",
    "isKidFriendly": "is_kid_friendly",
    "isPartyGame": "is_party_game",
    "isStrategyGame": "is_strategy_game",
    "playStyle": "play_style",
    "imageUrl": "image_url",
    "imageSource": "image_source",
    "imageLicense": "image_license",
    "imageAlt": "image_alt",
    "dataSourceUrl": "data_source_url",
    "dataLicense": "data_license",
    "contentLicense": "content_license",
    "reviewedAt": "reviewed_at",
    "reviewedBy": "reviewed_by",
}


def normalize_text(value: str) -> str:
    return value.lower().replace(" ", "").replace("-", "")


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def decoded_json(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def split_list(value: str | None) -> list[str]:
    if not value:
        return []
    separator = "|" if "|" in value else ";"
    return [item.strip() for item in value.split(separator) if item.strip()]


def parse_bool(value: str | None, field: str, errors: list[str]) -> bool:
    normalized = (value or "").strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"", "0", "false", "no", "n"}:
        return False
    errors.append(f"{field}: true/false 값이어야 합니다.")
    return False


def parse_positive_int(value: str | None, field: str, errors: list[str]) -> int:
    try:
        parsed = int((value or "").strip())
    except ValueError:
        errors.append(f"{field}: 정수여야 합니다.")
        return 0
    if parsed <= 0:
        errors.append(f"{field}: 1 이상이어야 합니다.")
    return parsed


def validate_game_values(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    game_id = str(payload.get("id") or "").strip()
    if not game_id or not SLUG_PATTERN.fullmatch(game_id):
        errors.append("id: 소문자 영문, 숫자와 하이픈으로 된 안정적인 slug여야 합니다.")
    for field in ("nameKo", "shortDescription", "rulesSummary", "genre"):
        if not str(payload.get(field) or "").strip():
            errors.append(f"{field}: 필수입니다.")
    min_players = int(payload.get("minPlayers") or 0)
    max_players = int(payload.get("maxPlayers") or 0)
    play_time = int(payload.get("avgPlayTimeMinutes") or 0)
    if min_players <= 0 or max_players <= 0:
        errors.append("players: 최소/최대 인원은 1 이상이어야 합니다.")
    if min_players > max_players:
        errors.append("players: 최소 인원은 최대 인원보다 클 수 없습니다.")
    if play_time <= 0:
        errors.append("avgPlayTimeMinutes: 1 이상이어야 합니다.")
    if payload.get("difficulty") not in ALLOWED_DIFFICULTIES:
        errors.append("difficulty: easy, medium, hard 중 하나여야 합니다.")
    if payload.get("genre") not in ALLOWED_GENRES:
        errors.append(f"genre: {', '.join(sorted(ALLOWED_GENRES))} 중 하나여야 합니다.")

    image_url = str(payload.get("imageUrl") or "").strip()
    image_metadata = [str(payload.get(key) or "").strip() for key in ("imageSource", "imageLicense", "imageAlt")]
    if image_url and not all(image_metadata):
        errors.append("image: URL, 출처, 라이선스, 대체 텍스트를 모두 입력해야 합니다.")
    if not image_url and any(image_metadata):
        errors.append("image: 이미지 메타데이터를 입력하려면 URL도 필요합니다.")
    return errors


def _row_to_payload(row: sqlite3.Row) -> dict[str, Any]:
    keys = set(row.keys())
    return {
        "id": row["id"],
        "nameKo": row["name_ko"],
        "nameEn": row["name_en"],
        "shortDescription": row["short_description"],
        "rulesSummary": row["rules_summary"],
        "minPlayers": row["min_players"],
        "maxPlayers": row["max_players"],
        "avgPlayTimeMinutes": row["avg_play_time_minutes"],
        "difficulty": row["difficulty"],
        "genre": row["genre"],
        "tags": decoded_json(row["tags"], []),
        "isBeginnerFriendly": bool(row["is_beginner_friendly"]),
        "isKidFriendly": bool(row["is_kid_friendly"]),
        "isPartyGame": bool(row["is_party_game"]),
        "isStrategyGame": bool(row["is_strategy_game"]),
        "playStyle": row["play_style"],
        "imageUrl": row["image_url"],
        "imageSource": row["image_source"] if "image_source" in keys else None,
        "imageLicense": row["image_license"] if "image_license" in keys else None,
        "imageAlt": row["image_alt"] if "image_alt" in keys else None,
        "dataSourceUrl": row["data_source_url"] if "data_source_url" in keys else None,
        "dataLicense": row["data_license"] if "data_license" in keys else None,
        "contentLicense": row["content_license"] if "content_license" in keys else None,
        "reviewedAt": row["reviewed_at"] if "reviewed_at" in keys else None,
        "reviewedBy": row["reviewed_by"] if "reviewed_by" in keys else None,
    }


def _csv_row_payload(row: dict[str, str], errors: list[str]) -> dict[str, Any]:
    payload = {
        "id": (row.get("id") or "").strip(),
        "nameKo": (row.get("nameKo") or "").strip(),
        "nameEn": (row.get("nameEn") or "").strip() or None,
        "shortDescription": (row.get("shortDescription") or "").strip(),
        "rulesSummary": (row.get("rulesSummary") or "").strip(),
        "minPlayers": parse_positive_int(row.get("minPlayers"), "minPlayers", errors),
        "maxPlayers": parse_positive_int(row.get("maxPlayers"), "maxPlayers", errors),
        "avgPlayTimeMinutes": parse_positive_int(row.get("avgPlayTimeMinutes"), "avgPlayTimeMinutes", errors),
        "difficulty": (row.get("difficulty") or "").strip().lower(),
        "genre": (row.get("genre") or "").strip().lower(),
        "tags": split_list(row.get("tags")),
        "isBeginnerFriendly": parse_bool(row.get("isBeginnerFriendly"), "isBeginnerFriendly", errors),
        "isKidFriendly": parse_bool(row.get("isKidFriendly"), "isKidFriendly", errors),
        "isPartyGame": parse_bool(row.get("isPartyGame"), "isPartyGame", errors),
        "isStrategyGame": parse_bool(row.get("isStrategyGame"), "isStrategyGame", errors),
        "playStyle": (row.get("playStyle") or "competitive").strip() or "competitive",
        "imageUrl": (row.get("imageUrl") or "").strip() or None,
        "imageSource": (row.get("imageSource") or "").strip() or None,
        "imageLicense": (row.get("imageLicense") or "").strip() or None,
        "imageAlt": (row.get("imageAlt") or "").strip() or None,
        "dataSourceUrl": (row.get("dataSourceUrl") or "").strip() or None,
        "dataLicense": (row.get("dataLicense") or "").strip() or None,
        "contentLicense": (row.get("contentLicense") or "").strip() or None,
        "reviewedAt": (row.get("reviewedAt") or "").strip() or None,
        "reviewedBy": (row.get("reviewedBy") or "").strip() or None,
        "aliases": split_list(row.get("aliases")),
    }
    for field in ("dataSourceUrl", "dataLicense", "contentLicense", "reviewedAt", "reviewedBy"):
        if not payload[field]:
            errors.append(f"{field}: 출처 검토를 위해 필수입니다.")
    if payload["dataSourceUrl"] and not payload["dataSourceUrl"].startswith("https://www.wikidata.org/wiki/Special:EntityData/Q"):
        errors.append("dataSourceUrl: Wikidata EntityData HTTPS URL이어야 합니다.")
    if payload["dataLicense"] and payload["dataLicense"] != "CC0-1.0":
        errors.append("dataLicense: 현재 수집 정책에서는 CC0-1.0만 허용합니다.")
    if payload["contentLicense"] and payload["contentLicense"] != "project-authored":
        errors.append("contentLicense: 현재 문구 정책에서는 project-authored여야 합니다.")
    if payload["reviewedAt"]:
        try:
            datetime.fromisoformat(payload["reviewedAt"])
        except ValueError:
            errors.append("reviewedAt: ISO 8601 날짜여야 합니다.")
    errors.extend(validate_game_values(payload))
    return payload


def _diff(existing: dict[str, Any] | None, payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if existing is None:
        return {"id": {"before": None, "after": payload["id"]}}
    changes: dict[str, dict[str, Any]] = {}
    for field in GAME_DB_COLUMNS:
        if existing.get(field) != payload.get(field):
            changes[field] = {"before": existing.get(field), "after": payload.get(field)}
    return changes


def preview_games_csv(
    conn: sqlite3.Connection,
    csv_bytes: bytes,
    now: datetime,
) -> dict[str, Any]:
    if not csv_bytes:
        raise ValueError("CSV 파일이 비어 있습니다.")
    if len(csv_bytes) > MAX_IMPORT_BYTES:
        raise ValueError("CSV 파일은 2MB 이하여야 합니다.")
    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV 파일은 UTF-8 인코딩이어야 합니다.") from exc

    reader = csv.DictReader(io.StringIO(text))
    headers = set(reader.fieldnames or [])
    missing = sorted(REQUIRED_CSV_FIELDS - headers)
    if missing:
        raise ValueError(f"필수 CSV 열이 없습니다: {', '.join(missing)}")
    raw_rows = list(reader)
    if len(raw_rows) > MAX_IMPORT_ROWS:
        raise ValueError(f"한 번에 최대 {MAX_IMPORT_ROWS}행까지 가져올 수 있습니다.")

    existing_rows = conn.execute("SELECT * FROM games").fetchall()
    existing_games = {row["id"]: _row_to_payload(row) for row in existing_rows}
    existing_name_owners: dict[str, str] = {}
    for game in existing_games.values():
        for name in (game["nameKo"], game.get("nameEn")):
            if name:
                existing_name_owners[normalize_text(name)] = game["id"]
    existing_alias_owners: dict[str, set[str]] = {}
    for alias in conn.execute("SELECT game_id, normalized_alias FROM game_aliases"):
        existing_alias_owners.setdefault(alias["normalized_alias"], set()).add(alias["game_id"])

    rows: list[dict[str, Any]] = []
    id_rows: dict[str, list[int]] = {}
    alias_rows: dict[str, list[tuple[int, str]]] = {}
    for index, raw in enumerate(raw_rows, start=2):
        errors: list[str] = []
        payload = _csv_row_payload(raw, errors)
        game_id = payload["id"]
        id_rows.setdefault(game_id, []).append(len(rows))
        aliases = payload["aliases"] + [payload["nameKo"]] + ([payload["nameEn"]] if payload["nameEn"] else [])
        for alias in aliases:
            normalized = normalize_text(alias)
            alias_rows.setdefault(normalized, []).append((len(rows), game_id))
            owners = existing_alias_owners.get(normalized, set()) - {game_id}
            if owners:
                errors.append(f"aliases: '{alias}' 별칭이 다른 게임({', '.join(sorted(owners))})에 연결돼 있습니다.")
        for name in (payload["nameKo"], payload.get("nameEn")):
            if name:
                owner = existing_name_owners.get(normalize_text(name))
                if owner and owner != game_id:
                    errors.append(f"name: 동일하게 정규화된 이름이 기존 게임 {owner}에 있습니다.")
        existing = existing_games.get(game_id)
        changes = _diff(existing, payload)
        action = "create" if existing is None else "update" if changes else "no_change"
        rows.append({
            "rowNumber": index,
            "gameId": game_id,
            "nameKo": payload["nameKo"],
            "action": action,
            "errors": errors,
            "diff": changes,
            "payload": payload,
        })

    for game_id, indexes in id_rows.items():
        if game_id and len(indexes) > 1:
            for index in indexes:
                rows[index]["errors"].append(f"id: CSV 안에서 '{game_id}'가 중복됐습니다.")
    for normalized, occurrences in alias_rows.items():
        owners = {owner for _, owner in occurrences}
        if normalized and len(owners) > 1:
            for index, _ in occurrences:
                rows[index]["errors"].append("aliases: CSV 안에서 하나의 별칭이 여러 게임에 연결됩니다.")

    for row in rows:
        row["errors"] = sorted(set(row["errors"]))
        row["valid"] = not row["errors"]

    created_at = now.isoformat(timespec="seconds")
    expires_at = (now + timedelta(minutes=IMPORT_TTL_MINUTES)).isoformat(timespec="seconds")
    conn.execute("DELETE FROM admin_imports WHERE status = 'previewed' AND expires_at < ?", (created_at,))
    import_id = str(uuid.uuid4())
    valid_count = sum(1 for row in rows if row["valid"])
    summary = {
        "totalRows": len(rows),
        "validRows": valid_count,
        "invalidRows": len(rows) - valid_count,
        "creates": sum(1 for row in rows if row["valid"] and row["action"] == "create"),
        "updates": sum(1 for row in rows if row["valid"] and row["action"] == "update"),
        "unchanged": sum(1 for row in rows if row["valid"] and row["action"] == "no_change"),
    }
    conn.execute(
        "INSERT INTO admin_imports(id, kind, status, preview_payload, summary, created_at, expires_at, applied_at) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
        (import_id, "games_csv", "previewed", json_text(rows), json_text(summary), created_at, expires_at),
    )
    return {
        "importId": import_id,
        "expiresAt": expires_at,
        "summary": summary,
        "rows": [{key: value for key, value in row.items() if key != "payload"} for row in rows],
    }


def _upsert_game(conn: sqlite3.Connection, payload: dict[str, Any], now_iso: str) -> str:
    existing = conn.execute("SELECT id, created_at FROM games WHERE id = ?", (payload["id"],)).fetchone()
    action = "update" if existing else "create"
    created_at = existing["created_at"] if existing else now_iso
    conn.execute(
        """
        INSERT INTO games(
            id, name_ko, name_en, short_description, rules_summary,
            min_players, max_players, avg_play_time_minutes, difficulty, genre,
            tags, is_beginner_friendly, is_kid_friendly, is_party_game,
            is_strategy_game, play_style, image_url, image_source, image_license,
            image_alt, created_at, updated_at
            , data_source_url, data_license, content_license, reviewed_at, reviewed_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name_ko=excluded.name_ko, name_en=excluded.name_en,
            short_description=excluded.short_description, rules_summary=excluded.rules_summary,
            min_players=excluded.min_players, max_players=excluded.max_players,
            avg_play_time_minutes=excluded.avg_play_time_minutes,
            difficulty=excluded.difficulty, genre=excluded.genre, tags=excluded.tags,
            is_beginner_friendly=excluded.is_beginner_friendly,
            is_kid_friendly=excluded.is_kid_friendly,
            is_party_game=excluded.is_party_game,
            is_strategy_game=excluded.is_strategy_game, play_style=excluded.play_style,
            image_url=excluded.image_url, image_source=excluded.image_source,
            image_license=excluded.image_license, image_alt=excluded.image_alt,
            data_source_url=excluded.data_source_url, data_license=excluded.data_license,
            content_license=excluded.content_license, reviewed_at=excluded.reviewed_at,
            reviewed_by=excluded.reviewed_by,
            updated_at=excluded.updated_at
        """,
        (
            payload["id"], payload["nameKo"], payload.get("nameEn"),
            payload["shortDescription"], payload["rulesSummary"], payload["minPlayers"],
            payload["maxPlayers"], payload["avgPlayTimeMinutes"], payload["difficulty"],
            payload["genre"], json_text(payload.get("tags") or []),
            int(bool(payload.get("isBeginnerFriendly"))), int(bool(payload.get("isKidFriendly"))),
            int(bool(payload.get("isPartyGame"))), int(bool(payload.get("isStrategyGame"))),
            payload.get("playStyle") or "competitive", payload.get("imageUrl"),
            payload.get("imageSource"), payload.get("imageLicense"), payload.get("imageAlt"),
            created_at, now_iso, payload.get("dataSourceUrl"), payload.get("dataLicense"),
            payload.get("contentLicense"), payload.get("reviewedAt"), payload.get("reviewedBy"),
        ),
    )
    conn.execute("DELETE FROM game_aliases WHERE game_id = ?", (payload["id"],))
    seen: set[str] = set()
    aliases = payload.get("aliases") or []
    aliases = aliases + [payload["nameKo"]] + ([payload["nameEn"]] if payload.get("nameEn") else [])
    for alias in aliases:
        normalized = normalize_text(alias)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        conn.execute(
            "INSERT INTO game_aliases(game_id, alias, normalized_alias) VALUES (?, ?, ?)",
            (payload["id"], alias, normalized),
        )
    return action


def apply_games_import(
    conn: sqlite3.Connection,
    import_id: str,
    strategy: str,
    now: datetime,
) -> dict[str, Any]:
    if strategy not in {"valid_only", "all_or_nothing"}:
        raise ValueError("strategy는 valid_only 또는 all_or_nothing이어야 합니다.")
    preview = conn.execute("SELECT * FROM admin_imports WHERE id = ?", (import_id,)).fetchone()
    if not preview:
        raise LookupError("가져오기 미리보기를 찾을 수 없습니다.")
    if preview["applied_at"]:
        raise RuntimeError("이미 적용된 가져오기입니다.")
    expires_at = preview["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at < now:
        raise RuntimeError("가져오기 미리보기 유효 시간이 지났습니다. 다시 미리보기 하세요.")
    rows = decoded_json(preview["preview_payload"], [])
    invalid_count = sum(1 for row in rows if row["errors"])
    if strategy == "all_or_nothing" and invalid_count:
        raise ValueError("오류 행이 있어 전체 적용을 취소했습니다.")
    applied = {"created": 0, "updated": 0, "unchanged": 0, "skipped": invalid_count}
    timestamp = now.isoformat(timespec="seconds")
    changed_game_ids: list[str] = []
    for row in rows:
        if row["errors"]:
            continue
        if row["action"] == "no_change":
            applied["unchanged"] += 1
            continue
        action = _upsert_game(conn, row["payload"], timestamp)
        applied["created" if action == "create" else "updated"] += 1
        changed_game_ids.append(row["gameId"])
    conn.execute(
        "UPDATE admin_imports SET status = 'applied', preview_payload = '[]', applied_at = ? WHERE id = ?",
        (timestamp, import_id),
    )
    return {"importId": import_id, "strategy": strategy, "result": applied, "changedGameIds": changed_game_ids}


def add_audit_event(
    conn: sqlite3.Connection,
    action: str,
    entity_type: str,
    entity_id: str | None,
    summary: dict[str, Any],
    created_at: str,
) -> str:
    event_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO admin_audit_events(id, action, entity_type, entity_id, summary, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (event_id, action, entity_type, entity_id, json_text(summary), created_at),
    )
    return event_id


def data_quality_report(conn: sqlite3.Connection) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    games = conn.execute("SELECT * FROM games ORDER BY id").fetchall()
    normalized_names: dict[str, list[str]] = {}
    for row in games:
        payload = _row_to_payload(row)
        for message in validate_game_values(payload):
            issues.append({"type": "invalid_game", "severity": "error", "entityType": "game", "entityId": row["id"], "message": message})
        for name in (row["name_ko"], row["name_en"]):
            if name:
                normalized_names.setdefault(normalize_text(name), []).append(row["id"])
        if row["image_url"] and row["image_license"] == "unverified":
            issues.append({"type": "unverified_image_license", "severity": "warning", "entityType": "game", "entityId": row["id"], "message": "이미지 라이선스가 아직 검증되지 않았습니다."})
        missing_provenance = [
            field for field in ("data_source_url", "data_license", "content_license", "reviewed_at", "reviewed_by")
            if field not in row.keys() or not row[field]
        ]
        if missing_provenance:
            issues.append({"type": "missing_provenance", "severity": "warning", "entityType": "game", "entityId": row["id"], "message": "출처 검토 정보가 비어 있습니다: " + ", ".join(missing_provenance)})

    for game_ids in normalized_names.values():
        unique_ids = sorted(set(game_ids))
        if len(unique_ids) > 1:
            issues.append({"type": "duplicate_game_name", "severity": "error", "entityType": "game", "entityId": unique_ids[0], "relatedIds": unique_ids, "message": "정규화된 게임 이름이 중복됩니다."})

    aliases_by_value: dict[str, list[dict[str, Any]]] = {}
    for row in conn.execute("SELECT id, game_id, alias, normalized_alias FROM game_aliases ORDER BY id"):
        aliases_by_value.setdefault(row["normalized_alias"], []).append(dict(row))
    for normalized_alias, alias_rows in aliases_by_value.items():
        game_ids = sorted({row["game_id"] for row in alias_rows})
        if len(game_ids) > 1:
            actions = [
                {"kind": "delete_alias", "id": str(row["id"]), "label": f"{row['game_id']}의 '{row['alias']}' 삭제"}
                for row in alias_rows
            ]
            issues.append({"type": "alias_conflict", "severity": "error", "entityType": "alias", "entityId": normalized_alias, "relatedIds": game_ids, "message": "하나의 별칭이 여러 게임에 연결돼 있습니다.", "resolutionActions": actions})

    broken_relations = conn.execute(
        """
        SELECT r.id, r.source_game_id, r.target_game_id
        FROM game_relations r
        LEFT JOIN games source ON source.id = r.source_game_id
        LEFT JOIN games target ON target.id = r.target_game_id
        WHERE source.id IS NULL OR target.id IS NULL
        """
    ).fetchall()
    for row in broken_relations:
        issues.append({"type": "broken_relation", "severity": "error", "entityType": "relation", "entityId": str(row["id"]), "relatedIds": [row["source_game_id"], row["target_game_id"]], "message": "존재하지 않는 게임을 참조하는 관계입니다."})

    relation_rows = conn.execute(
        "SELECT id, source_game_id, target_game_id, relation_type FROM game_relations"
    ).fetchall()
    seen_relations: dict[tuple[str, str, str], list[int]] = {}
    for row in relation_rows:
        if row["source_game_id"] == row["target_game_id"]:
            issues.append({"type": "self_relation", "severity": "error", "entityType": "relation", "entityId": str(row["id"]), "relatedIds": [row["source_game_id"]], "message": "게임이 자기 자신을 참조합니다.", "resolutionActions": [{"kind": "delete_relation", "id": str(row["id"]), "label": "잘못된 관계 삭제"}]})
        key = (row["source_game_id"], row["target_game_id"], row["relation_type"])
        seen_relations.setdefault(key, []).append(row["id"])
    for relation_ids in seen_relations.values():
        if len(relation_ids) > 1:
            issues.append({"type": "duplicate_relation", "severity": "error", "entityType": "relation", "entityId": str(relation_ids[0]), "relatedIds": [str(value) for value in relation_ids], "message": "동일한 게임 관계가 중복돼 있습니다.", "resolutionActions": [{"kind": "delete_relation", "id": str(value), "label": "중복 관계 삭제"} for value in relation_ids[1:]]})

    errors = sum(1 for issue in issues if issue["severity"] == "error")
    warnings = sum(1 for issue in issues if issue["severity"] == "warning")
    return {
        "summary": {
            "games": len(games),
            "aliases": conn.execute("SELECT COUNT(*) AS count FROM game_aliases").fetchone()["count"],
            "relations": len(relation_rows),
            "errors": errors,
            "warnings": warnings,
            "score": max(0, 100 - errors * 10 - warnings * 2),
        },
        "allowedValues": {"difficulty": sorted(ALLOWED_DIFFICULTIES), "genre": sorted(ALLOWED_GENRES)},
        "issues": issues,
    }


def games_csv(conn: sqlite3.Connection) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=GAME_CSV_FIELDS)
    writer.writeheader()
    aliases_by_game: dict[str, list[str]] = {}
    for alias in conn.execute("SELECT game_id, alias FROM game_aliases ORDER BY game_id, alias"):
        aliases_by_game.setdefault(alias["game_id"], []).append(alias["alias"])
    for row in conn.execute("SELECT * FROM games ORDER BY id"):
        payload = _row_to_payload(row)
        payload["tags"] = "|".join(payload["tags"])
        payload["aliases"] = "|".join(aliases_by_game.get(row["id"], []))
        for field in ("isBeginnerFriendly", "isKidFriendly", "isPartyGame", "isStrategyGame"):
            payload[field] = "true" if payload[field] else "false"
        writer.writerow({field: payload.get(field) for field in GAME_CSV_FIELDS})
    return output.getvalue()


def aliases_csv(conn: sqlite3.Connection) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["id", "gameId", "alias", "normalizedAlias"])
    for row in conn.execute("SELECT id, game_id, alias, normalized_alias FROM game_aliases ORDER BY game_id, alias"):
        writer.writerow([row["id"], row["game_id"], row["alias"], row["normalized_alias"]])
    return output.getvalue()


def audit_events(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, action, entity_type, entity_id, summary, created_at FROM admin_audit_events ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "action": row["action"],
            "entityType": row["entity_type"],
            "entityId": row["entity_id"],
            "summary": decoded_json(row["summary"], {}),
            "createdAt": row["created_at"],
        }
        for row in rows
    ]
