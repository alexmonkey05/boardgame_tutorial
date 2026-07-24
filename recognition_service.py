from __future__ import annotations

import json
import sqlite3
from difflib import SequenceMatcher
from typing import Any, Optional


def _from_json(value: Optional[str], fallback: Any = None) -> Any:
    if value is None or value == "":
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def normalize_game_name(value: Optional[str]) -> str:
    if not value:
        return ""
    return "".join(ch.lower() for ch in value if ch.isalnum())


def _game_payload(row: sqlite3.Row) -> dict[str, Any]:
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
        "tags": _from_json(row["tags"], []),
        "isBeginnerFriendly": bool(row["is_beginner_friendly"]),
        "isKidFriendly": bool(row["is_kid_friendly"]),
        "isPartyGame": bool(row["is_party_game"]),
        "isStrategyGame": bool(row["is_strategy_game"]),
        "playStyle": row["play_style"],
        "imageUrl": row["image_url"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        return {}
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(stripped[start : end + 1])
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def parse_vision_response(response: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {"candidates": [], "needsRetake": True, "message": "이미지 인식 응답을 해석하지 못했어요."}

    if "candidates" in response:
        parsed = response
    else:
        content = response.get("content")
        if not content:
            raw = response.get("raw")
            choices = raw.get("choices") if isinstance(raw, dict) else None
            if choices and isinstance(choices, list):
                message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
                content = message.get("content") if isinstance(message, dict) else ""
        parsed = _extract_json_object(content or "")

    raw_candidates = parsed.get("candidates") if isinstance(parsed, dict) else []
    candidates: list[dict[str, Any]] = []
    if isinstance(raw_candidates, list):
        for item in raw_candidates[:5]:
            if not isinstance(item, dict):
                continue
            game_id = str(item.get("gameId") or item.get("game_id") or "").strip()
            confidence = item.get("confidence", 0)
            try:
                confidence_float = float(confidence)
            except (TypeError, ValueError):
                confidence_float = 0.72 if game_id else 0.0
            confidence_float = max(0.0, min(confidence_float, 1.0))
            candidates.append(
                {
                    "gameId": game_id,
                    "visibleText": str(item.get("visibleText") or item.get("visible_text") or "").strip(),
                    "name": str(item.get("name") or "").strip(),
                    "nameKo": str(item.get("nameKo") or item.get("name_ko") or "").strip(),
                    "confidence": confidence_float,
                    "evidence": str(item.get("evidence") or "").strip(),
                }
            )

    message = parsed.get("message") if isinstance(parsed, dict) else None
    needs_retake = bool(parsed.get("needsRetake", len(candidates) == 0)) if isinstance(parsed, dict) else True
    return {
        "candidates": candidates,
        "needsRetake": needs_retake,
        "message": message or ("후보를 찾았어요." if candidates else "사진에서 보드게임 후보를 찾지 못했어요."),
    }


def _match_score(candidate_names: list[str], db_names: list[str]) -> float:
    best = 0.0
    for candidate in candidate_names:
        if not candidate:
            continue
        for db_name in db_names:
            if not db_name:
                continue
            if candidate == db_name:
                best = max(best, 1.0)
            elif candidate in db_name or db_name in candidate:
                best = max(best, 0.78)
            else:
                ratio = SequenceMatcher(None, candidate, db_name).ratio()
                if ratio >= 0.82:
                    best = max(best, 0.68 + (ratio - 0.82) * 0.5)
    return round(min(best, 1.0), 3)


def _game_aliases(conn: sqlite3.Connection, game_id: str) -> list[str]:
    rows = conn.execute("SELECT alias FROM game_aliases WHERE game_id = ?", (game_id,)).fetchall()
    return [row["alias"] for row in rows]


def _aliases_by_game(conn: sqlite3.Connection) -> dict[str, list[str]]:
    rows = conn.execute("SELECT game_id, alias FROM game_aliases").fetchall()
    aliases: dict[str, list[str]] = {}
    for row in rows:
        aliases.setdefault(row["game_id"], []).append(row["alias"])
    return aliases


def _normalized_db_names(row: sqlite3.Row, aliases: list[str]) -> list[str]:
    return [
        normalize_game_name(row["name_ko"]),
        normalize_game_name(row["name_en"]),
        *[normalize_game_name(alias) for alias in aliases],
    ]


def match_vision_candidates(
    conn: sqlite3.Connection,
    vision_response: dict[str, Any],
) -> dict[str, Any]:
    parsed = parse_vision_response(vision_response)
    games = conn.execute("SELECT * FROM games").fetchall()
    games_by_id = {row["id"]: row for row in games}
    aliases_by_game = _aliases_by_game(conn)
    matched_by_game_id: dict[str, dict[str, Any]] = {}
    unmatched: list[dict[str, Any]] = []

    for raw_candidate in parsed["candidates"]:
        candidate_game_id = str(raw_candidate.get("gameId") or "").strip()
        candidate_names = [
            normalize_game_name(raw_candidate.get("visibleText")),
            normalize_game_name(raw_candidate.get("name")),
            normalize_game_name(raw_candidate.get("nameKo")),
        ]
        title_names = [
            normalize_game_name(raw_candidate.get("visibleText")),
            normalize_game_name(raw_candidate.get("nameKo")),
        ]
        best_row: Optional[sqlite3.Row] = None
        best_score = 0.0
        if candidate_game_id in games_by_id:
            id_row = games_by_id[candidate_game_id]
            id_title_score = _match_score(title_names, _normalized_db_names(id_row, aliases_by_game.get(id_row["id"], [])))
            best_title_row: Optional[sqlite3.Row] = None
            best_title_score = 0.0
            for row in games:
                score = _match_score(candidate_names, _normalized_db_names(row, aliases_by_game.get(row["id"], [])))
                if score > best_score:
                    best_score = score
                    best_row = row
                title_score = _match_score(title_names, _normalized_db_names(row, aliases_by_game.get(row["id"], [])))
                if title_score > best_title_score:
                    best_title_score = title_score
                    best_title_row = row
            if best_title_row and best_title_score >= 0.9 and id_title_score < 0.78:
                best_row = best_title_row
                best_score = best_title_score
            elif not best_row or best_score < 0.9:
                best_row = id_row
                best_score = 1.0
        else:
            for row in games:
                score = _match_score(candidate_names, _normalized_db_names(row, aliases_by_game.get(row["id"], [])))
                if score > best_score:
                    best_score = score
                    best_row = row

        nvidia_confidence = float(raw_candidate.get("confidence") or 0.0)
        if not best_row or best_score < 0.6:
            unmatched.append(raw_candidate)
            continue

        final_confidence = round((nvidia_confidence * 0.68) + (best_score * 0.32), 3)
        game_id = best_row["id"]
        candidate = {
            "game": _game_payload(best_row),
            "nvidiaConfidence": round(nvidia_confidence, 3),
            "matchScore": best_score,
            "confidence": final_confidence,
            "needsRetake": final_confidence < 0.58,
            "message": "보드게임 DB와 일치하는 후보를 찾았어요.",
            "evidence": raw_candidate.get("evidence") or "",
        }
        existing = matched_by_game_id.get(game_id)
        if not existing or candidate["confidence"] > existing["confidence"]:
            matched_by_game_id[game_id] = candidate

    candidates = sorted(matched_by_game_id.values(), key=lambda item: item["confidence"], reverse=True)[:5]
    needs_retake = parsed["needsRetake"] or not candidates or (candidates[0]["confidence"] < 0.58)
    message = parsed["message"]
    if not candidates:
        message = "사진과 일치하는 보드게임을 찾지 못했어요. 박스 제목이 보이게 다시 촬영해 주세요."
    elif needs_retake:
        message = "신뢰도가 낮아요. 후보를 확인하거나 박스 앞면을 더 선명하게 촬영해 주세요."
    elif len(candidates) > 1 and candidates[0]["confidence"] - candidates[1]["confidence"] < 0.12:
        message = "비슷한 후보가 있어요. 맞는 게임을 선택해 주세요."

    return {
        "candidates": candidates,
        "unmatchedCandidates": unmatched[:5],
        "needsRetake": needs_retake,
        "message": message,
    }
