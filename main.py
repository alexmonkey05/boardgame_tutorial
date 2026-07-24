from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from data_management import (
    ALLOWED_DIFFICULTIES,
    ALLOWED_GENRES,
    add_audit_event,
    aliases_csv,
    apply_games_import,
    audit_events,
    data_quality_report,
    games_csv,
    preview_games_csv,
    validate_game_values,
)
from recognition_service import match_vision_candidates
from storage import PostgresStorageRepository, SQLiteStorageRepository
from vision_client import VisionAPIError, is_vision_configured, recognize_boardgame_image

load_dotenv()

DATABASE_PATH = Path(os.getenv("BOARDGAME_DB_PATH") or "./boardgame_backend.sqlite3")
DATABASE_URL = os.getenv("DATABASE_URL") or ""
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN") or "dev-admin-token"
VISION_API_PROVIDER = os.getenv("VISION_API_PROVIDER") or "mock"
VISION_API_KEY = os.getenv("VISION_API_KEY") or ""
VISION_API_ENDPOINT = os.getenv("VISION_API_ENDPOINT") or ""
VISION_MODEL = os.getenv("VISION_MODEL") or ""
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in (os.getenv("CORS_ALLOWED_ORIGINS") or "*").split(",")
    if origin.strip()
]
KST = timezone(timedelta(hours=9))
MAX_IMAGE_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_RELATION_TYPES = {"similar", "heavier_alternative", "family_alternative"}
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_RULES = {
    "/recommendations": int(os.getenv("RECOMMENDATION_RATE_LIMIT_PER_MINUTE") or "30"),
    "/recognitions": int(os.getenv("RECOGNITION_RATE_LIMIT_PER_MINUTE") or "10"),
}
_rate_limit_buckets: dict[tuple[str, str, str], deque[float]] = defaultdict(deque)
_runtime_lock = threading.Lock()
_request_metrics: dict[str, Any] = {
    "requests": 0,
    "responsesByStatus": defaultdict(int),
    "rateLimited": 0,
    "visionAttempts": 0,
    "visionSuccesses": 0,
    "visionFailures": 0,
    "visionFallbacks": 0,
    "visionSkippedByHint": 0,
    "visionOcrRetries": 0,
}


def env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name) or default)
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


HINT_FAST_PATH_CONFIDENCE = env_float("RECOGNITION_HINT_FAST_PATH_CONFIDENCE", 0.84, 0.5, 0.98)

PRIVACY_POLICY = {
    "anonymousUsage": True,
    "optionalLoginReady": True,
    "dataDeletion": "DELETE /users/{userId}/data로 익명 세션 또는 선택 로그인 사용자 기록 삭제를 요청할 수 있습니다.",
    "minimalCollection": "추천과 최근 기록에 필요한 이벤트와 게임 ID 중심으로 저장합니다.",
}

IMAGE_RETENTION_POLICY = {
    "storeOriginalImage": False,
    "originalRetention": "MVP에서는 원본 이미지를 저장하지 않습니다.",
    "thumbnailRetention": "MVP에서는 썸네일을 생성하거나 저장하지 않습니다.",
    "processedImageRetention": "인식 작업에는 원본 이미지나 썸네일을 저장하지 않고 후보와 신뢰도만 저장합니다.",
    "externalApiTransmission": "이미지 업로드 인식 시 설정된 외부 Vision API로 원본 이미지 바이트를 전송할 수 있습니다.",
    "maxUploadMegabytes": 5,
    "allowedContentTypes": sorted(ALLOWED_IMAGE_CONTENT_TYPES),
    "consentRequiredForQualityImprovement": True,
    "recognitionLog": "인식 작업, 후보, 신뢰도, 사용자 확정 결과만 저장합니다.",
}


def image_recognition_config() -> dict[str, Any]:
    provider = (VISION_API_PROVIDER or "").lower()
    configured = provider == "nvidia" and bool(VISION_API_KEY and VISION_API_ENDPOINT and VISION_MODEL)
    return {
        "providerConfigured": bool(VISION_API_PROVIDER),
        "apiKeyConfigured": bool(VISION_API_KEY),
        "endpointConfigured": bool(VISION_API_ENDPOINT),
        "modelConfigured": bool(VISION_MODEL),
        "mode": "external-ready" if configured else "mock",
    }


def validate_uploaded_image(image_bytes: bytes, content_type: str) -> None:
    if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="지원하지 않는 이미지 형식입니다. JPG, PNG, WebP 파일을 업로드해 주세요.")
    if not image_bytes:
        raise HTTPException(status_code=400, detail="비어 있는 이미지 파일은 인식할 수 없습니다.")
    if len(image_bytes) > MAX_IMAGE_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="이미지 파일이 너무 큽니다. 5MB 이하 파일을 업로드해 주세요.")


def safe_hint_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return Path(value).name.strip()[:120]


def increment_metric(name: str, amount: int = 1) -> None:
    with _runtime_lock:
        _request_metrics[name] += amount


def rate_limit_check(path: str, key: str) -> tuple[bool, int]:
    limit = RATE_LIMIT_RULES.get(path, 0)
    if limit <= 0:
        return True, 0
    current = time.monotonic()
    bucket_key = (str(DATABASE_PATH), path, key)
    with _runtime_lock:
        bucket = _rate_limit_buckets[bucket_key]
        while bucket and current - bucket[0] >= RATE_LIMIT_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = max(1, int(RATE_LIMIT_WINDOW_SECONDS - (current - bucket[0])) + 1)
            return False, retry_after
        bucket.append(current)
    return True, 0


def rate_limit_strategy() -> dict[str, Any]:
    return {
        "backend": "memory",
        "multiReplicaSafe": False,
        "requiredBeforeScaling": "Redis shared atomic counter",
    }


def observability_snapshot() -> dict[str, Any]:
    with _runtime_lock:
        attempts = _request_metrics["visionAttempts"]
        failures = _request_metrics["visionFailures"]
        fallbacks = _request_metrics["visionFallbacks"]
        return {
            "requests": _request_metrics["requests"],
            "responsesByStatus": dict(_request_metrics["responsesByStatus"]),
            "rateLimited": _request_metrics["rateLimited"],
            "vision": {
                "attempts": attempts,
                "successes": _request_metrics["visionSuccesses"],
                "failures": failures,
                "fallbacks": fallbacks,
                "failureRate": round(failures / attempts, 4) if attempts else 0.0,
                "fallbackRate": round(fallbacks / attempts, 4) if attempts else 0.0,
            },
            "rateLimits": {
                "windowSeconds": RATE_LIMIT_WINDOW_SECONDS,
                "recommendations": RATE_LIMIT_RULES["/recommendations"],
                "recognitions": RATE_LIMIT_RULES["/recognitions"],
                "strategy": rate_limit_strategy(),
            },
        }

def now_iso() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def as_json(value: Any) -> str:
    return json.dumps(jsonable_encoder(value), ensure_ascii=False)


def from_json(value: Optional[str], fallback: Any = None) -> Any:
    if value is None or value == "":
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def normalize_text(value: str) -> str:
    return value.lower().replace(" ", "").replace("-", "")


def slugify(value: str) -> str:
    slug = value.lower().strip().replace(" ", "-")
    return "".join(ch for ch in slug if ch.isalnum() or ch == "-").strip("-") or str(uuid.uuid4())


@contextmanager
def db() -> Any:
    repository = PostgresStorageRepository(DATABASE_URL) if DATABASE_URL else SQLiteStorageRepository(DATABASE_PATH)
    with repository.connection() as conn:
        yield conn


def fetch_one(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> Optional[sqlite3.Row]:
    return conn.execute(query, params).fetchone()


def fetch_all(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    return conn.execute(query, params).fetchall()


def game_payload(row: sqlite3.Row) -> dict[str, Any]:
    row_keys = set(row.keys())
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
        "tags": from_json(row["tags"], []),
        "isBeginnerFriendly": bool(row["is_beginner_friendly"]),
        "isKidFriendly": bool(row["is_kid_friendly"]),
        "isPartyGame": bool(row["is_party_game"]),
        "isStrategyGame": bool(row["is_strategy_game"]),
        "playStyle": row["play_style"],
        "imageUrl": row["image_url"],
        "imageSource": row["image_source"] if "image_source" in row_keys else None,
        "imageLicense": row["image_license"] if "image_license" in row_keys else None,
        "imageAlt": row["image_alt"] if "image_alt" in row_keys else None,
        "dataSourceUrl": row["data_source_url"] if "data_source_url" in row_keys else None,
        "dataLicense": row["data_license"] if "data_license" in row_keys else None,
        "contentLicense": row["content_license"] if "content_license" in row_keys else None,
        "reviewedAt": row["reviewed_at"] if "reviewed_at" in row_keys else None,
        "reviewedBy": row["reviewed_by"] if "reviewed_by" in row_keys else None,
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def require_admin(x_admin_token: Optional[str] = Header(default=None)) -> None:
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="관리자 토큰이 필요합니다.")


class SessionCreate(BaseModel):
    deviceLabel: Optional[str] = None


class UserCreate(BaseModel):
    provider: Optional[str] = "local"
    displayName: Optional[str] = None
    sessionIdToLink: Optional[str] = None


class EventCreate(BaseModel):
    userId: Optional[str] = None
    sessionId: Optional[str] = None
    eventType: str = Field(..., examples=["game_search", "game_view", "recommendation_click"])
    gameId: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)


class PlayedGameCreate(BaseModel):
    gameId: str
    playedAt: Optional[str] = None
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    notes: Optional[str] = None


class HiddenGameCreate(BaseModel):
    gameId: str
    reason: Optional[str] = None


class RecommendationRequest(BaseModel):
    userId: Optional[str] = None
    sessionId: Optional[str] = None
    peopleCount: Optional[int] = Field(default=None, ge=1)
    remainingMinutes: Optional[int] = Field(default=None, ge=1)
    mood: Optional[str] = None
    preferredDifficulty: Optional[str] = None
    preferredGenres: list[str] = Field(default_factory=list)
    excludeGameIds: list[str] = Field(default_factory=list)
    previouslyPlayedGameIds: list[str] = Field(default_factory=list)
    limit: int = Field(default=5, ge=1, le=20)


class RecognitionConfirm(BaseModel):
    selectedGameId: str
    userId: Optional[str] = None
    sessionId: Optional[str] = None


class AdminGameCreate(BaseModel):
    id: Optional[str] = None
    nameKo: str
    nameEn: Optional[str] = None
    shortDescription: str
    rulesSummary: str
    minPlayers: int
    maxPlayers: int
    avgPlayTimeMinutes: int
    difficulty: str
    genre: str
    tags: list[str] = Field(default_factory=list)
    isBeginnerFriendly: bool = False
    isKidFriendly: bool = False
    isPartyGame: bool = False
    isStrategyGame: bool = False
    playStyle: str = "competitive"
    imageUrl: Optional[str] = None
    imageSource: Optional[str] = None
    imageLicense: Optional[str] = None
    imageAlt: Optional[str] = None
    dataSourceUrl: Optional[str] = None
    dataLicense: Optional[str] = None
    contentLicense: Optional[str] = None
    reviewedAt: Optional[str] = None
    reviewedBy: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)


class AdminGameAliasCreate(BaseModel):
    alias: str


class AdminGameRelationCreate(BaseModel):
    targetGameId: str
    relationType: str = "similar"


class AdminGamePatch(BaseModel):
    nameKo: Optional[str] = None
    nameEn: Optional[str] = None
    shortDescription: Optional[str] = None
    rulesSummary: Optional[str] = None
    minPlayers: Optional[int] = None
    maxPlayers: Optional[int] = None
    avgPlayTimeMinutes: Optional[int] = None
    difficulty: Optional[str] = None
    genre: Optional[str] = None
    tags: Optional[list[str]] = None
    isBeginnerFriendly: Optional[bool] = None
    isKidFriendly: Optional[bool] = None
    isPartyGame: Optional[bool] = None
    isStrategyGame: Optional[bool] = None
    playStyle: Optional[str] = None
    imageUrl: Optional[str] = None
    imageSource: Optional[str] = None
    imageLicense: Optional[str] = None
    imageAlt: Optional[str] = None
    dataSourceUrl: Optional[str] = None
    dataLicense: Optional[str] = None
    contentLicense: Optional[str] = None
    reviewedAt: Optional[str] = None
    reviewedBy: Optional[str] = None


class AdminImportApply(BaseModel):
    importId: str
    strategy: str = "all_or_nothing"


def model_to_json(model: BaseModel) -> str:
    if hasattr(model, "model_dump_json"):
        return model.model_dump_json()
    return model.json(ensure_ascii=False)


def create_schema() -> None:
    with db() as conn:
        if DATABASE_URL:
            schema_path = Path(__file__).with_name("docs") / "postgresql_target_schema.sql"
            conn.executescript(schema_path.read_text(encoding="utf-8"))
            return
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS games (
                id TEXT PRIMARY KEY,
                name_ko TEXT NOT NULL,
                name_en TEXT,
                short_description TEXT NOT NULL,
                rules_summary TEXT NOT NULL,
                min_players INTEGER NOT NULL,
                max_players INTEGER NOT NULL,
                avg_play_time_minutes INTEGER NOT NULL,
                difficulty TEXT NOT NULL,
                genre TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                is_beginner_friendly INTEGER NOT NULL DEFAULT 0,
                is_kid_friendly INTEGER NOT NULL DEFAULT 0,
                is_party_game INTEGER NOT NULL DEFAULT 0,
                is_strategy_game INTEGER NOT NULL DEFAULT 0,
                play_style TEXT NOT NULL DEFAULT 'competitive',
                image_url TEXT,
                image_source TEXT,
                image_license TEXT,
                image_alt TEXT,
                data_source_url TEXT,
                data_license TEXT,
                content_license TEXT,
                reviewed_at TEXT,
                reviewed_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS game_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                alias TEXT NOT NULL,
                normalized_alias TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS game_relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                target_game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                relation_type TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                provider TEXT,
                display_name TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS anonymous_sessions (
                id TEXT PRIMARY KEY,
                device_label TEXT,
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_events (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                session_id TEXT,
                event_type TEXT NOT NULL,
                game_id TEXT,
                payload TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS played_games (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                played_at TEXT NOT NULL,
                rating INTEGER,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS hidden_games (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                reason TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, game_id)
            );

            CREATE TABLE IF NOT EXISTS recognition_jobs (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                session_id TEXT,
                status TEXT NOT NULL,
                image_original_stored INTEGER NOT NULL DEFAULT 0,
                hint_text TEXT,
                top_game_id TEXT,
                confidence REAL,
                needs_retake INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL,
                confirmed_game_id TEXT,
                created_at TEXT NOT NULL,
                confirmed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS recognition_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recognition_id TEXT NOT NULL REFERENCES recognition_jobs(id) ON DELETE CASCADE,
                game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                confidence REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS recommendation_logs (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                session_id TEXT,
                request_payload TEXT NOT NULL,
                response_payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS admin_users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                token_hint TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS admin_imports (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                preview_payload TEXT NOT NULL,
                summary TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                applied_at TEXT
            );

            CREATE TABLE IF NOT EXISTS admin_audit_events (
                id TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                summary TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_game_aliases_normalized ON game_aliases(normalized_alias);
            CREATE INDEX IF NOT EXISTS idx_game_relations_source ON game_relations(source_game_id, relation_type);
            CREATE INDEX IF NOT EXISTS idx_games_filter ON games(min_players, max_players, avg_play_time_minutes, difficulty, genre);
            CREATE INDEX IF NOT EXISTS idx_games_genre_difficulty ON games(genre, difficulty, avg_play_time_minutes);
            CREATE INDEX IF NOT EXISTS idx_user_events_recent ON user_events(user_id, session_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_user_events_game_recent ON user_events(user_id, session_id, game_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_user_events_type_recent ON user_events(event_type, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_played_games_user_recent ON played_games(user_id, played_at DESC);
            CREATE INDEX IF NOT EXISTS idx_hidden_games_user ON hidden_games(user_id, game_id);
            CREATE INDEX IF NOT EXISTS idx_recognition_jobs_user_recent ON recognition_jobs(user_id, session_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_recognition_candidates_job ON recognition_candidates(recognition_id, confidence DESC);
            CREATE INDEX IF NOT EXISTS idx_recommendation_logs_user ON recommendation_logs(user_id, session_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_admin_imports_expiry ON admin_imports(expires_at, status);
            CREATE INDEX IF NOT EXISTS idx_admin_audit_recent ON admin_audit_events(created_at DESC);
            """
        )
        game_columns = SQLiteStorageRepository(DATABASE_PATH).table_columns(conn, "games")
        for column_name in ("image_source", "image_license", "image_alt", "data_source_url", "data_license", "content_license", "reviewed_at", "reviewed_by"):
            if column_name not in game_columns:
                conn.execute(f"ALTER TABLE games ADD COLUMN {column_name} TEXT")
        conn.execute(
            """
            UPDATE games
            SET image_url = NULL, image_source = NULL, image_license = NULL, image_alt = NULL
            WHERE image_url LIKE 'https://example.com/%'
            """
        )
        source_ids = {
            "splendor": "Q20037103", "codenames": "Q25203543", "azul": "Q44367843",
            "dixit": "Q906623", "pandemic": "Q531592", "ticket-to-ride": "Q228308",
            "terraforming-mars": "Q36718832",
        }
        for game_id, entity_id in source_ids.items():
            conn.execute(
                """
                UPDATE games SET data_source_url = COALESCE(data_source_url, ?),
                    data_license = COALESCE(data_license, 'CC0-1.0'),
                    content_license = COALESCE(content_license, 'project-authored'),
                    reviewed_at = COALESCE(reviewed_at, '2026-07-18'),
                    reviewed_by = COALESCE(reviewed_by, 'project-curation')
                WHERE id = ?
                """,
                (f"https://www.wikidata.org/wiki/Special:EntityData/{entity_id}.json", game_id),
            )


def seed_data() -> None:
    games = [
        ("splendor", "스플렌더", "Splendor", "보석 토큰을 모아 카드를 사고 점수를 만드는 입문 전략 게임입니다.", "토큰을 가져가거나 카드를 구매해 귀족과 점수를 얻습니다.", 2, 4, 30, "easy", "strategy", ["입문", "엔진빌딩", "카드"], 1, 0, 0, 1, "competitive", None, "Q20037103"),
        ("codenames", "코드네임", "Codenames", "힌트 한 단어로 팀원이 정답 카드를 맞히는 파티 추리 게임입니다.", "팀장은 단어 힌트와 숫자를 말하고 팀원은 관련 카드를 고릅니다.", 4, 8, 20, "easy", "party", ["단어", "팀전", "대화"], 1, 1, 1, 0, "team", None, "Q25203543"),
        ("azul", "아줄", "Azul", "타일을 골라 개인 보드에 배치하는 아름다운 퍼즐 전략 게임입니다.", "공용 타일을 가져와 줄을 채우고 벽에 배치해 점수를 얻습니다.", 2, 4, 35, "medium", "puzzle", ["퍼즐", "타일", "가족"], 1, 1, 0, 1, "competitive", None, "Q44367843"),
        ("dixit", "딕싯", "Dixit", "그림 카드와 상상력으로 힌트를 맞히는 감성 파티 게임입니다.", "출제자의 문장에 어울리는 그림을 내고 누가 낸 카드인지 맞힙니다.", 3, 8, 30, "easy", "party", ["그림", "상상", "가족"], 1, 1, 1, 0, "competitive", None, "Q906623"),
        ("pandemic", "팬데믹", "Pandemic", "전 세계 질병 확산을 함께 막는 협력 전략 게임입니다.", "역할 능력을 활용해 도시를 이동하고 치료제를 개발합니다.", 2, 4, 45, "medium", "cooperative", ["협력", "전략", "테마"], 0, 0, 0, 1, "cooperative", None, "Q531592"),
        ("ticket-to-ride", "티켓 투 라이드", "Ticket to Ride", "기차 노선을 연결해 목적지를 완성하는 가족 전략 게임입니다.", "카드를 모아 노선을 점유하고 목적지 티켓을 완성합니다.", 2, 5, 45, "easy", "family", ["가족", "기차", "루트빌딩"], 1, 1, 0, 1, "competitive", None, "Q228308"),
        ("terraforming-mars", "테라포밍 마스", "Terraforming Mars", "화성 개발 기업이 되어 장기 엔진을 만드는 고난도 전략 게임입니다.", "프로젝트 카드를 내고 산소, 온도, 바다를 올려 점수를 얻습니다.", 1, 5, 120, "hard", "strategy", ["고난도", "엔진빌딩", "SF"], 0, 0, 0, 1, "competitive", None, "Q36718832"),
    ]
    aliases = {
        "splendor": ["스플랜더", "스플렌더", "스플렌더 보석", "splendor", "splender", "splendor board game"],
        "codenames": ["코드 네임", "코드네임", "코드네임즈", "codenames", "code names", "code name"],
        "azul": ["아줄", "아쥴", "azul", "azule"],
        "dixit": ["딕싯", "딕시트", "dixit"],
        "pandemic": ["팬데믹", "판데믹", "pandemic"],
        "ticket-to-ride": ["티켓투라이드", "티켓 투 라이드", "티투라", "ticket to ride", "ticket ride"],
        "terraforming-mars": ["테라포밍마스", "테라포밍 마스", "테포마", "terraforming mars", "tmars"],
    }
    relations = [
        ("splendor", "azul", "similar"),
        ("azul", "splendor", "similar"),
        ("codenames", "dixit", "similar"),
        ("dixit", "codenames", "similar"),
        ("splendor", "terraforming-mars", "heavier_alternative"),
        ("pandemic", "ticket-to-ride", "family_alternative"),
    ]
    with db() as conn:
        existing = fetch_one(conn, "SELECT COUNT(*) AS count FROM games")
        if existing and existing["count"] > 0:
            return
        t = now_iso()
        conn.executemany(
            """
            INSERT INTO games(
                id, name_ko, name_en, short_description, rules_summary,
                min_players, max_players, avg_play_time_minutes, difficulty, genre,
                tags, is_beginner_friendly, is_kid_friendly, is_party_game,
                is_strategy_game, play_style, image_url, image_source, image_license,
                image_alt, created_at, updated_at
                , data_source_url, data_license, content_license, reviewed_at, reviewed_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    gid, ko, en, desc, rules, minp, maxp, time_min, diff, genre,
                    as_json(tags), beginner, kid, party, strategy, style, image,
                    None, None, None, t, t,
                    f"https://www.wikidata.org/wiki/Special:EntityData/{entity_id}.json",
                    "CC0-1.0", "project-authored", "2026-07-18", "project-curation",
                )
                for gid, ko, en, desc, rules, minp, maxp, time_min, diff, genre, tags,
                beginner, kid, party, strategy, style, image, entity_id in games
            ],
        )
        for game_id, names in aliases.items():
            for alias in names:
                conn.execute("INSERT INTO game_aliases(game_id, alias, normalized_alias) VALUES (?, ?, ?)", (game_id, alias, normalize_text(alias)))
        conn.executemany("INSERT INTO game_relations(source_game_id, target_game_id, relation_type) VALUES (?, ?, ?)", relations)
        conn.execute("INSERT INTO admin_users VALUES (?, ?, ?, ?, ?)", ("admin-dev", "Development Admin", ADMIN_TOKEN[:4] + "...", "owner", t))


def startup() -> None:
    if not DATABASE_URL:
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    create_schema()
    seed_data()


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    startup()
    yield


app = FastAPI(
    title="Boardgame Discovery API",
    version="0.3.0",
    description="보드게임 식별, 검색, 추천과 마스터 데이터 관리를 제공하는 FastAPI 서비스",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def operational_protection(request: Request, call_next: Any) -> Response:
    request_id = str(uuid.uuid4())
    started = time.perf_counter()
    path = request.url.path
    if request.method == "POST" and path in RATE_LIMIT_RULES:
        client_key = (
            request.query_params.get("sessionId")
            or request.query_params.get("userId")
            or (request.client.host if request.client else "anonymous")
        )
        allowed, retry_after = rate_limit_check(path, client_key)
        if not allowed:
            increment_metric("rateLimited")
            increment_metric("requests")
            with _runtime_lock:
                _request_metrics["responsesByStatus"]["429"] += 1
            response = JSONResponse(
                status_code=429,
                content={"detail": "요청이 잠시 많습니다. 잠시 후 다시 시도해 주세요.", "requestId": request_id},
                headers={"Retry-After": str(retry_after)},
            )
            response.headers["X-Request-ID"] = request_id
            return response
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
    finally:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        increment_metric("requests")
        with _runtime_lock:
            _request_metrics["responsesByStatus"][str(status_code)] += 1
        print(
            as_json({
                "event": "http_request",
                "requestId": request_id,
                "method": request.method,
                "path": path,
                "statusCode": status_code,
                "durationMs": duration_ms,
            }),
            flush=True,
        )
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-Ms"] = str(duration_ms)
    return response


@app.get("/", include_in_schema=False)
def web_app() -> FileResponse:
    return FileResponse(Path(__file__).with_name("index.html"))


@app.get("/admin-ui", include_in_schema=False)
@app.get("/admin-ui/", include_in_schema=False)
def admin_web_app() -> FileResponse:
    return FileResponse(Path(__file__).with_name("admin.html"))


@app.get("/health")
def health() -> dict[str, Any]:
    with db() as conn:
        repository = PostgresStorageRepository(DATABASE_URL) if DATABASE_URL else SQLiteStorageRepository(DATABASE_PATH)
        table_count = len(repository.table_names(conn))
        game_count = fetch_one(conn, "SELECT COUNT(*) AS count FROM games")["count"]
    database_label = "postgresql" if DATABASE_URL else str(DATABASE_PATH)
    return {"status": "ok", "time": now_iso(), "database": database_label, "tables": table_count, "seedGames": game_count, "privacy": PRIVACY_POLICY, "imageRetention": IMAGE_RETENTION_POLICY, "imageRecognition": image_recognition_config()}


@app.get("/ready")
def readiness() -> dict[str, Any]:
    try:
        with db() as conn:
            conn.execute("SELECT 1").fetchone()
            game_count = conn.execute("SELECT COUNT(*) AS count FROM games").fetchone()["count"]
    except Exception as exc:
        raise HTTPException(status_code=503, detail="데이터베이스 준비 상태를 확인할 수 없습니다.") from exc
    if game_count <= 0:
        raise HTTPException(status_code=503, detail="게임 마스터 데이터가 준비되지 않았습니다.")
    return {"status": "ready", "database": "available", "games": game_count, "time": now_iso()}


@app.get("/meta/schema")
def schema_metadata() -> dict[str, Any]:
    return {
        "tables": ["games", "game_aliases", "game_relations", "users", "anonymous_sessions", "user_events", "played_games", "hidden_games", "recognition_jobs", "recognition_candidates", "recommendation_logs", "admin_users", "admin_imports", "admin_audit_events"],
        "fastQueries": ["전체 게임 조건 필터링", "게임명/별칭 검색", "유사 게임 조회", "사용자 최근 기록 조회", "취향 기반 추천 후보 조회", "이미지 인식 후보 저장 및 확인"],
        "privacy": PRIVACY_POLICY,
        "imageRetention": IMAGE_RETENTION_POLICY,
        "imageRecognition": image_recognition_config(),
    }


@app.get("/games")
def list_games(q: Optional[str] = None, peopleCount: Optional[int] = Query(default=None, ge=1), maxPlayTime: Optional[int] = Query(default=None, ge=1), difficulty: Optional[str] = None, genre: Optional[str] = None, tag: Optional[str] = None, limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0)) -> dict[str, Any]:
    sql = "SELECT DISTINCT g.* FROM games g LEFT JOIN game_aliases a ON a.game_id = g.id WHERE 1=1"
    params: list[Any] = []
    if q:
        normalized = f"%{normalize_text(q)}%"
        like = f"%{q.lower()}%"
        sql += " AND (lower(g.name_ko) LIKE ? OR lower(g.name_en) LIKE ? OR a.normalized_alias LIKE ?)"
        params.extend([like, like, normalized])
    if peopleCount:
        sql += " AND g.min_players <= ? AND g.max_players >= ?"
        params.extend([peopleCount, peopleCount])
    if maxPlayTime:
        sql += " AND g.avg_play_time_minutes <= ?"
        params.append(maxPlayTime)
    if difficulty:
        sql += " AND g.difficulty = ?"
        params.append(difficulty)
    if genre:
        sql += " AND g.genre = ?"
        params.append(genre)
    if tag:
        sql += " AND CAST(g.tags AS TEXT) LIKE ?"
        params.append(f"%{tag}%")
    sql += " ORDER BY g.name_ko LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    with db() as conn:
        rows = fetch_all(conn, sql, tuple(params))
    return {"items": [game_payload(row) for row in rows], "limit": limit, "offset": offset}


@app.get("/games/search")
def search_games(q: str = Query(..., min_length=1), limit: int = Query(default=20, ge=1, le=50)) -> dict[str, Any]:
    normalized = normalize_text(q)
    with db() as conn:
        rows = fetch_all(conn, """
            SELECT DISTINCT g.*
            FROM games g
            LEFT JOIN game_aliases a ON a.game_id = g.id
            WHERE lower(g.name_ko) LIKE ? OR lower(g.name_en) LIKE ? OR a.normalized_alias LIKE ?
            ORDER BY CASE WHEN a.normalized_alias = ? THEN 0 ELSE 1 END, g.name_ko
            LIMIT ?
            """, (f"%{q.lower()}%", f"%{q.lower()}%", f"%{normalized}%", normalized, limit))
    return {"query": q, "items": [game_payload(row) for row in rows]}


@app.get("/games/{game_id}")
def get_game(game_id: str) -> dict[str, Any]:
    with db() as conn:
        row = fetch_one(conn, "SELECT * FROM games WHERE id = ?", (game_id,))
        if not row:
            raise HTTPException(status_code=404, detail="게임을 찾을 수 없습니다.")
        aliases = [r["alias"] for r in fetch_all(conn, "SELECT alias FROM game_aliases WHERE game_id = ? ORDER BY alias", (game_id,))]
    payload = game_payload(row)
    payload["aliases"] = aliases
    return payload


@app.get("/games/{game_id}/similar")
def similar_games(game_id: str) -> dict[str, Any]:
    with db() as conn:
        if not fetch_one(conn, "SELECT id FROM games WHERE id = ?", (game_id,)):
            raise HTTPException(status_code=404, detail="게임을 찾을 수 없습니다.")
        rows = fetch_all(conn, """
            SELECT g.*, r.relation_type
            FROM game_relations r
            JOIN games g ON g.id = r.target_game_id
            WHERE r.source_game_id = ?
            ORDER BY r.relation_type, g.name_ko
            """, (game_id,))
    return {"gameId": game_id, "items": [{"relationType": row["relation_type"], "game": game_payload(row)} for row in rows]}


@app.post("/sessions")
def create_session(payload: SessionCreate) -> dict[str, Any]:
    session_id = f"anon_{secrets.token_urlsafe(18)}"
    t = now_iso()
    with db() as conn:
        conn.execute("INSERT INTO anonymous_sessions VALUES (?, ?, ?, ?)", (session_id, payload.deviceLabel, t, t))
    return {"sessionId": session_id, "createdAt": t, "privacy": PRIVACY_POLICY}


@app.post("/users")
def create_user(payload: UserCreate) -> dict[str, Any]:
    user_id = f"user_{secrets.token_urlsafe(16)}"
    t = now_iso()
    with db() as conn:
        conn.execute("INSERT INTO users VALUES (?, ?, ?, ?)", (user_id, payload.provider, payload.displayName, t))
        if payload.sessionIdToLink:
            conn.execute("UPDATE user_events SET user_id = ? WHERE session_id = ? AND user_id IS NULL", (user_id, payload.sessionIdToLink))
            conn.execute("UPDATE recognition_jobs SET user_id = ? WHERE session_id = ? AND user_id IS NULL", (user_id, payload.sessionIdToLink))
            conn.execute("UPDATE recommendation_logs SET user_id = ? WHERE session_id = ? AND user_id IS NULL", (user_id, payload.sessionIdToLink))
    return {"userId": user_id, "createdAt": t, "linkedSessionId": payload.sessionIdToLink, "privacy": PRIVACY_POLICY}


@app.post("/events")
def create_event(payload: EventCreate) -> dict[str, Any]:
    event_id = str(uuid.uuid4())
    t = now_iso()
    with db() as conn:
        if payload.gameId and not fetch_one(conn, "SELECT id FROM games WHERE id = ?", (payload.gameId,)):
            raise HTTPException(status_code=404, detail="게임을 찾을 수 없습니다.")
        conn.execute(
            "INSERT INTO user_events(id, user_id, session_id, event_type, game_id, payload, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event_id, payload.userId, payload.sessionId, payload.eventType, payload.gameId, as_json(payload.payload), t),
        )
        if payload.sessionId:
            conn.execute("UPDATE anonymous_sessions SET last_seen_at = ? WHERE id = ?", (t, payload.sessionId))
    return {"eventId": event_id, "createdAt": t}


@app.get("/users/{user_id}/history")
def user_history(user_id: str, limit: int = Query(default=30, ge=1, le=100)) -> dict[str, Any]:
    with db() as conn:
        events = fetch_all(conn, "SELECT * FROM user_events WHERE user_id = ? OR session_id = ? ORDER BY created_at DESC LIMIT ?", (user_id, user_id, limit))
        played = fetch_all(conn, "SELECT p.*, g.name_ko FROM played_games p JOIN games g ON g.id = p.game_id WHERE p.user_id = ? ORDER BY p.played_at DESC LIMIT ?", (user_id, limit))
        hidden = fetch_all(conn, "SELECT h.*, g.name_ko FROM hidden_games h JOIN games g ON g.id = h.game_id WHERE h.user_id = ? ORDER BY h.created_at DESC LIMIT ?", (user_id, limit))
    return {
        "userId": user_id,
        "events": [{"id": r["id"], "eventType": r["event_type"], "gameId": r["game_id"], "payload": from_json(r["payload"], {}), "createdAt": r["created_at"]} for r in events],
        "playedGames": [{"id": r["id"], "gameId": r["game_id"], "nameKo": r["name_ko"], "playedAt": r["played_at"], "rating": r["rating"], "notes": r["notes"]} for r in played],
        "hiddenGames": [{"id": r["id"], "gameId": r["game_id"], "nameKo": r["name_ko"], "reason": r["reason"], "createdAt": r["created_at"]} for r in hidden],
    }


@app.post("/users/{user_id}/played-games")
def add_played_game(user_id: str, payload: PlayedGameCreate) -> dict[str, Any]:
    record_id = str(uuid.uuid4())
    played_at = payload.playedAt or now_iso()
    with db() as conn:
        if not fetch_one(conn, "SELECT id FROM games WHERE id = ?", (payload.gameId,)):
            raise HTTPException(status_code=404, detail="게임을 찾을 수 없습니다.")
        conn.execute(
            "INSERT INTO played_games(id, user_id, game_id, played_at, rating, notes) VALUES (?, ?, ?, ?, ?, ?)",
            (record_id, user_id, payload.gameId, played_at, payload.rating, payload.notes),
        )
    return {"id": record_id, "userId": user_id, "gameId": payload.gameId, "playedAt": played_at}


@app.post("/users/{user_id}/hidden-games")
def add_hidden_game(user_id: str, payload: HiddenGameCreate) -> dict[str, Any]:
    record_id = str(uuid.uuid4())
    t = now_iso()
    with db() as conn:
        if not fetch_one(conn, "SELECT id FROM games WHERE id = ?", (payload.gameId,)):
            raise HTTPException(status_code=404, detail="게임을 찾을 수 없습니다.")
        conn.execute(
            """INSERT INTO hidden_games(id, user_id, game_id, reason, created_at) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET user_id=excluded.user_id, game_id=excluded.game_id, reason=excluded.reason, created_at=excluded.created_at""",
            (record_id, user_id, payload.gameId, payload.reason, t),
        )
    return {"id": record_id, "userId": user_id, "gameId": payload.gameId, "createdAt": t}


@app.delete("/users/{user_id}/data")
def delete_user_data(user_id: str) -> dict[str, Any]:
    with db() as conn:
        counts = {
            "userEvents": conn.execute("DELETE FROM user_events WHERE user_id = ? OR session_id = ?", (user_id, user_id)).rowcount,
            "playedGames": conn.execute("DELETE FROM played_games WHERE user_id = ?", (user_id,)).rowcount,
            "hiddenGames": conn.execute("DELETE FROM hidden_games WHERE user_id = ?", (user_id,)).rowcount,
            "recognitionJobs": conn.execute("DELETE FROM recognition_jobs WHERE user_id = ? OR session_id = ?", (user_id, user_id)).rowcount,
            "recommendationLogs": conn.execute("DELETE FROM recommendation_logs WHERE user_id = ? OR session_id = ?", (user_id, user_id)).rowcount,
            "anonymousSessions": conn.execute("DELETE FROM anonymous_sessions WHERE id = ?", (user_id,)).rowcount,
            "users": conn.execute("DELETE FROM users WHERE id = ?", (user_id,)).rowcount,
        }
    return {"userId": user_id, "deleted": counts, "imageRetention": IMAGE_RETENTION_POLICY}


def mood_bonus(game: dict[str, Any], mood: Optional[str]) -> tuple[int, list[str]]:
    if not mood:
        return 0, []
    text = mood.lower()
    tags = set(game["tags"])
    bonus = 0
    reasons: list[str] = []
    if any(word in text for word in ["파티", "대화", "웃", "가볍"]):
        if game["isPartyGame"] or "대화" in tags:
            bonus += 18
            reasons.append("대화하면서 가볍게 즐기기 좋아요")
    if any(word in text for word in ["전략", "머리", "깊"]):
        if game["isStrategyGame"]:
            bonus += 18
            reasons.append("전략적인 선택지가 많은 편이에요")
    if any(word in text for word in ["협력", "같이", "팀"]):
        if game["playStyle"] in ["cooperative", "team"]:
            bonus += 16
            reasons.append("함께 목표를 맞추는 흐름에 잘 맞아요")
    return bonus, reasons


def load_user_recommendation_signals(conn: sqlite3.Connection, user_id: Optional[str], session_id: Optional[str]) -> dict[str, Any]:
    identifiers = [value for value in [user_id, session_id] if value]
    if not identifiers:
        return {"eventGameWeights": {}, "genreWeights": {}, "difficultyWeights": {}, "tagWeights": {}}
    event_game_weights: dict[str, float] = {}
    genre_weights: dict[str, float] = {}
    difficulty_weights: dict[str, float] = {}
    tag_weights: dict[str, float] = {}
    event_weight_by_type = {"game_search": 1.5, "game_view": 3.0, "recognition_confirm": 4.0, "recommendation_click": 5.0}
    placeholders = ",".join("?" for _ in identifiers)
    rows = fetch_all(conn, f"""
        SELECT e.event_type, e.game_id, e.payload, g.genre, g.difficulty, g.tags
        FROM user_events e
        LEFT JOIN games g ON g.id = e.game_id
        WHERE (e.user_id IN ({placeholders}) OR e.session_id IN ({placeholders}))
        ORDER BY e.created_at DESC
        LIMIT 120
        """, tuple(identifiers + identifiers))
    for index, row in enumerate(rows):
        recency_multiplier = max(0.35, 1 - (index * 0.015))
        weight = event_weight_by_type.get(row["event_type"], 0.5) * recency_multiplier
        payload = from_json(row["payload"], {})
        game_id = row["game_id"] or payload.get("gameId") or payload.get("selectedGameId")
        if game_id:
            event_game_weights[game_id] = event_game_weights.get(game_id, 0) + weight
        if row["genre"]:
            genre_weights[row["genre"]] = genre_weights.get(row["genre"], 0) + weight
        if row["difficulty"]:
            difficulty_weights[row["difficulty"]] = difficulty_weights.get(row["difficulty"], 0) + weight
        for tag in from_json(row["tags"], []):
            tag_weights[tag] = tag_weights.get(tag, 0) + weight
    return {"eventGameWeights": event_game_weights, "genreWeights": genre_weights, "difficultyWeights": difficulty_weights, "tagWeights": tag_weights}


def event_preference_bonus(game: dict[str, Any], signals: dict[str, Any]) -> tuple[float, list[str]]:
    bonus = 0.0
    reasons: list[str] = []
    if game["id"] in signals["eventGameWeights"]:
        direct = min(16.0, signals["eventGameWeights"][game["id"]] * 1.8)
        bonus += direct
        reasons.append("최근 검색하거나 살펴본 게임이라 우선순위를 높였어요")
    genre_weight = signals["genreWeights"].get(game["genre"], 0)
    if genre_weight:
        bonus += min(12.0, genre_weight * 1.2)
        reasons.append("최근 관심을 보인 장르와 비슷해요")
    difficulty_weight = signals["difficultyWeights"].get(game["difficulty"], 0)
    if difficulty_weight:
        bonus += min(8.0, difficulty_weight)
        reasons.append("최근 본 게임들의 난이도와 가까워요")
    matched_tags = [tag for tag in game["tags"] if signals["tagWeights"].get(tag, 0) > 0]
    if matched_tags:
        bonus += min(10.0, sum(signals["tagWeights"][tag] for tag in matched_tags) * 0.8)
        reasons.append(f"최근 관심 태그({matched_tags[0]})와 맞아요")
    return bonus, reasons[:2]


def build_recommendations(payload: RecommendationRequest) -> dict[str, Any]:
    with db() as conn:
        rows = fetch_all(conn, "SELECT * FROM games ORDER BY name_ko")
        hidden = set()
        played = set(payload.previouslyPlayedGameIds)
        signals = load_user_recommendation_signals(conn, payload.userId, payload.sessionId)
        if payload.userId or payload.sessionId:
            uid = payload.userId or payload.sessionId
            hidden = {r["game_id"] for r in fetch_all(conn, "SELECT game_id FROM hidden_games WHERE user_id = ?", (uid,))}
            played.update({r["game_id"] for r in fetch_all(conn, "SELECT game_id FROM played_games WHERE user_id = ?", (uid,))})
    excluded = set(payload.excludeGameIds) | hidden
    items: list[dict[str, Any]] = []
    for row in rows:
        game = game_payload(row)
        if game["id"] in excluded:
            continue
        score = 40.0
        reasons: list[str] = []
        if payload.peopleCount:
            if game["minPlayers"] <= payload.peopleCount <= game["maxPlayers"]:
                score += 20
                reasons.append(f"{payload.peopleCount}명이 하기 좋아요")
            else:
                score -= 25
        if payload.remainingMinutes:
            if game["avgPlayTimeMinutes"] <= payload.remainingMinutes:
                score += 18
                reasons.append(f"{payload.remainingMinutes}분 안에 끝내기 쉬워요")
            else:
                over = game["avgPlayTimeMinutes"] - payload.remainingMinutes
                score -= min(25, over / 2)
        if payload.preferredDifficulty:
            if game["difficulty"] == payload.preferredDifficulty:
                score += 15
                reasons.append("선호한 난이도와 맞아요")
            elif game["difficulty"] == "easy" and payload.preferredDifficulty == "medium":
                score += 5
        if payload.preferredGenres and game["genre"] in payload.preferredGenres:
            score += 16
            reasons.append("선호한 장르와 잘 맞아요")
        bonus, mood_reasons = mood_bonus(game, payload.mood)
        score += bonus
        reasons.extend(mood_reasons)
        event_bonus, event_reasons = event_preference_bonus(game, signals)
        score += event_bonus
        reasons.extend(event_reasons)
        if game["id"] in played:
            score -= 12
            reasons.append("이미 플레이한 기록이 있어 우선순위를 조금 낮췄어요")
        if not reasons:
            reasons.append("게임의 난이도, 장르와 최근 관심 기록을 함께 반영했어요")
        items.append({"game": game, "score": round(score, 1), "priority": 0, "reasons": reasons[:4]})
    items.sort(key=lambda x: x["score"], reverse=True)
    for index, item in enumerate(items, start=1):
        item["priority"] = index
    return {
        "items": items[: payload.limit],
        "alternatives": items[payload.limit : payload.limit + 3],
        "signalsUsed": {
            "eventGameCount": len(signals["eventGameWeights"]),
            "genreCount": len(signals["genreWeights"]),
            "tagCount": len(signals["tagWeights"]),
        },
    }


@app.post("/recommendations")
def recommendations(payload: RecommendationRequest) -> dict[str, Any]:
    result = build_recommendations(payload)
    log_id = str(uuid.uuid4())
    t = now_iso()
    response = {"recommendationId": log_id, "items": result["items"], "alternatives": result["alternatives"], "signalsUsed": result["signalsUsed"], "generatedAt": t}
    with db() as conn:
        repository = PostgresStorageRepository(DATABASE_URL) if DATABASE_URL else SQLiteStorageRepository(DATABASE_PATH)
        legacy_columns = repository.table_columns(conn, "recommendation_logs")
        if "cafe_id" in legacy_columns:
            conn.execute(
                "INSERT INTO recommendation_logs(id, user_id, session_id, cafe_id, request_payload, response_payload, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (log_id, payload.userId, payload.sessionId, "", model_to_json(payload), as_json(response), t),
            )
        else:
            conn.execute(
                "INSERT INTO recommendation_logs(id, user_id, session_id, request_payload, response_payload, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (log_id, payload.userId, payload.sessionId, model_to_json(payload), as_json(response), t),
            )
    return response


@app.get("/users/{user_id}/recommendation-profile")
def recommendation_profile(user_id: str) -> dict[str, Any]:
    with db() as conn:
        events = fetch_all(conn, "SELECT event_type, game_id, payload FROM user_events WHERE user_id = ? OR session_id = ? ORDER BY created_at DESC LIMIT 100", (user_id, user_id))
        played = fetch_all(conn, "SELECT p.game_id, g.genre, g.difficulty, g.tags FROM played_games p JOIN games g ON g.id = p.game_id WHERE p.user_id = ?", (user_id,))
        hidden = fetch_all(conn, "SELECT game_id, reason FROM hidden_games WHERE user_id = ?", (user_id,))
        signals = load_user_recommendation_signals(conn, user_id, user_id)
    genres: dict[str, int] = {}
    difficulties: dict[str, int] = {}
    tags: dict[str, int] = {}
    for row in played:
        genres[row["genre"]] = genres.get(row["genre"], 0) + 1
        difficulties[row["difficulty"]] = difficulties.get(row["difficulty"], 0) + 1
        for tag in from_json(row["tags"], []):
            tags[tag] = tags.get(tag, 0) + 1
    return {"userId": user_id, "signals": {"recentEventCount": len(events), "playedCount": len(played), "hiddenCount": len(hidden)}, "eventBasedPreferences": {"gameWeights": signals["eventGameWeights"], "genreWeights": signals["genreWeights"], "difficultyWeights": signals["difficultyWeights"], "tagWeights": signals["tagWeights"]}, "preferredGenres": genres, "preferredDifficulties": difficulties, "preferredTags": tags, "hiddenGames": [dict(row) for row in hidden], "privacy": PRIVACY_POLICY}


def recognition_candidates_for_hint(conn: sqlite3.Connection, hint: str) -> list[dict[str, Any]]:
    normalized = normalize_text(hint)
    rows = fetch_all(conn, """
        SELECT DISTINCT g.*
        FROM games g
        LEFT JOIN game_aliases a ON a.game_id = g.id
        WHERE lower(g.name_ko) LIKE ? OR lower(g.name_en) LIKE ? OR a.normalized_alias LIKE ? OR CAST(g.tags AS TEXT) LIKE ?
        LIMIT 5
        """, (f"%{hint.lower()}%", f"%{hint.lower()}%", f"%{normalized}%", f"%{hint}%"))
    if not rows:
        rows = fetch_all(conn, "SELECT * FROM games ORDER BY is_beginner_friendly DESC, name_ko LIMIT 4")
    candidates = []
    for index, row in enumerate(rows):
        matched_name = normalized and (normalized in normalize_text(row["name_ko"]) or (row["name_en"] and normalized in normalize_text(row["name_en"])))
        base = 0.88 - (index * 0.12) if matched_name else 0.52 - (index * 0.07)
        candidates.append({"game": game_payload(row), "confidence": round(max(0.2, min(base, 0.96)), 2)})
    return candidates


def confident_hint_candidates(conn: sqlite3.Connection, hint: str) -> list[dict[str, Any]]:
    if not hint:
        return []
    candidates = recognition_candidates_for_hint(conn, hint)
    top = candidates[0] if candidates else None
    if top and top["confidence"] >= HINT_FAST_PATH_CONFIDENCE:
        return candidates
    return []


def vision_catalog_options(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    games = fetch_all(conn, "SELECT id, name_ko, name_en FROM games ORDER BY name_ko")
    alias_rows = fetch_all(conn, "SELECT game_id, alias FROM game_aliases ORDER BY game_id, alias")
    aliases_by_game: dict[str, list[str]] = defaultdict(list)
    for row in alias_rows:
        if len(aliases_by_game[row["game_id"]]) < 4:
            aliases_by_game[row["game_id"]].append(row["alias"])
    return [
        {
            "id": row["id"],
            "nameKo": row["name_ko"],
            "nameEn": row["name_en"],
            "aliases": aliases_by_game.get(row["id"], []),
        }
        for row in games
    ]


def recognition_needs_ocr_retry(result: Optional[dict[str, Any]]) -> bool:
    if not result:
        return False
    candidates = result.get("candidates") or []
    if not candidates:
        return True
    top = candidates[0]
    return bool(result.get("needsRetake")) or float(top.get("confidence") or 0.0) < 0.72


@app.post("/recognitions")
async def create_recognition(userId: Optional[str] = Query(default=None), sessionId: Optional[str] = Query(default=None), hint: Optional[str] = Query(default=None), image: Optional[UploadFile] = File(default=None)) -> dict[str, Any]:
    recognition_id = str(uuid.uuid4())
    hint_text = safe_hint_text(hint)
    filename_hint = safe_hint_text(image.filename if image else None)
    fallback_hint = hint_text or filename_hint
    image_bytes = await image.read() if image else b""
    content_type = image.content_type or "application/octet-stream" if image else "application/octet-stream"
    t = now_iso()
    external_processing = {
        "provider": "nvidia",
        "used": False,
        "skippedByHint": False,
        "ocrRetryUsed": False,
        "storesOriginalImageLocally": False,
    }
    if image:
        validate_uploaded_image(image_bytes, content_type)
    if not image_bytes and not fallback_hint:
        message = "이미지나 텍스트 힌트가 없어 인식 후보를 만들 수 없어요. 박스 사진을 업로드하거나 게임명 힌트를 입력해 주세요."
        with db() as conn:
            conn.execute(
                "INSERT INTO recognition_jobs(id, user_id, session_id, status, image_original_stored, hint_text, top_game_id, confidence, needs_retake, message, confirmed_game_id, created_at, confirmed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (recognition_id, userId, sessionId, "input_required", 0, None, None, 0.0, 1, message, None, t, None),
            )
        return {"recognitionId": recognition_id, "topCandidate": None, "candidates": [], "unmatchedCandidates": [], "needsRetake": True, "message": message, "imageRetention": IMAGE_RETENTION_POLICY, "externalProcessing": external_processing}

    recognition_result: Optional[dict[str, Any]] = None
    hint_fast_candidates: Optional[list[dict[str, Any]]] = None
    status = "completed"
    if image_bytes and hint_text:
        with db() as conn:
            hint_fast_candidates = confident_hint_candidates(conn, hint_text)
        if hint_fast_candidates:
            status = "hint_fast_path"
            external_processing["skippedByHint"] = True
            increment_metric("visionSkippedByHint")

    if image_bytes and is_vision_configured() and hint_fast_candidates is None:
        increment_metric("visionAttempts")
        try:
            with db() as conn:
                catalog_options = vision_catalog_options(conn)
            vision_response = await recognize_boardgame_image(image_bytes, content_type, hint_text or None, catalog_options)
            external_processing["used"] = True
            with db() as conn:
                recognition_result = match_vision_candidates(conn, vision_response)
            if recognition_needs_ocr_retry(recognition_result):
                increment_metric("visionOcrRetries")
                external_processing["ocrRetryUsed"] = True
                ocr_response = await recognize_boardgame_image(image_bytes, content_type, hint_text or None, None, mode="ocr")
                with db() as conn:
                    ocr_result = match_vision_candidates(conn, ocr_response)
                if (ocr_result.get("candidates") or []) and (
                    not (recognition_result.get("candidates") or [])
                    or ocr_result["candidates"][0]["confidence"] > recognition_result["candidates"][0]["confidence"]
                ):
                    recognition_result = ocr_result
            increment_metric("visionSuccesses")
        except VisionAPIError:
            status = "fallback"
            increment_metric("visionFailures")
            increment_metric("visionFallbacks")

    with db() as conn:
        if hint_fast_candidates is not None:
            candidates = hint_fast_candidates
            unmatched_candidates = []
            top = candidates[0] if candidates else None
            confidence = top["confidence"] if top else 0
            needs_retake = confidence < 0.55 or len(candidates) == 0
            message = "입력한 힌트와 DB가 충분히 일치해 빠르게 후보를 만들었어요."
            if len(candidates) > 1 and candidates[0]["confidence"] - candidates[1]["confidence"] < 0.15:
                message = "비슷한 후보가 있어요. 맞는 게임을 선택해 주세요."
        elif recognition_result is None:
            candidates = recognition_candidates_for_hint(conn, fallback_hint or hint_text)
            unmatched_candidates: list[dict[str, Any]] = []
            top = candidates[0] if candidates else None
            confidence = top["confidence"] if top else 0
            needs_retake = confidence < 0.55 or len(candidates) == 0
            message = "사진을 저장하지 않고 후보를 만들었어요."
            if image_bytes and is_vision_configured() and status == "fallback":
                message = "이미지 인식 서비스가 잠시 불안정해 텍스트 힌트 기반으로 후보를 만들었어요."
            if needs_retake:
                message = "신뢰도가 낮아요. 박스 앞면이 더 잘 보이게 다시 촬영하거나 게임명 힌트를 입력해 주세요."
            elif len(candidates) > 1 and candidates[0]["confidence"] - candidates[1]["confidence"] < 0.15:
                message = "비슷한 후보가 있어요. 맞는 게임을 선택해 주세요."
        else:
            candidates = recognition_result["candidates"]
            unmatched_candidates = recognition_result["unmatchedCandidates"]
            top = candidates[0] if candidates else None
            confidence = top["confidence"] if top else 0
            needs_retake = bool(recognition_result["needsRetake"])
            message = recognition_result["message"]
        top = candidates[0] if candidates else None
        conn.execute(
            "INSERT INTO recognition_jobs(id, user_id, session_id, status, image_original_stored, hint_text, top_game_id, confidence, needs_retake, message, confirmed_game_id, created_at, confirmed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (recognition_id, userId, sessionId, status, 0, fallback_hint or None, top["game"]["id"] if top else None, confidence, int(needs_retake), message, None, t, None),
        )
        for candidate in candidates:
            conn.execute(
                "INSERT INTO recognition_candidates(recognition_id, game_id, confidence) VALUES (?, ?, ?)",
                (recognition_id, candidate["game"]["id"], candidate["confidence"]),
            )
    return {"recognitionId": recognition_id, "topCandidate": top, "candidates": candidates, "unmatchedCandidates": unmatched_candidates, "needsRetake": needs_retake, "message": message, "imageRetention": IMAGE_RETENTION_POLICY, "externalProcessing": external_processing}


@app.get("/recognitions/{recognition_id}")
def get_recognition(recognition_id: str) -> dict[str, Any]:
    with db() as conn:
        job = fetch_one(conn, "SELECT * FROM recognition_jobs WHERE id = ?", (recognition_id,))
        if not job:
            raise HTTPException(status_code=404, detail="인식 작업을 찾을 수 없습니다.")
        rows = fetch_all(conn, """
            SELECT c.confidence, g.*
            FROM recognition_candidates c
            JOIN games g ON g.id = c.game_id
            WHERE c.recognition_id = ?
            ORDER BY c.confidence DESC
            """, (recognition_id,))
    candidates = [{"game": game_payload(row), "confidence": row["confidence"]} for row in rows]
    return {"recognitionId": job["id"], "status": job["status"], "topCandidate": candidates[0] if candidates else None, "candidates": candidates, "needsRetake": bool(job["needs_retake"]), "message": job["message"], "confirmedGameId": job["confirmed_game_id"], "imageRetention": IMAGE_RETENTION_POLICY}


@app.post("/recognitions/{recognition_id}/confirm")
def confirm_recognition(recognition_id: str, payload: RecognitionConfirm) -> dict[str, Any]:
    t = now_iso()
    with db() as conn:
        job = fetch_one(conn, "SELECT id FROM recognition_jobs WHERE id = ?", (recognition_id,))
        if not job:
            raise HTTPException(status_code=404, detail="인식 작업을 찾을 수 없습니다.")
        if not fetch_one(conn, "SELECT id FROM games WHERE id = ?", (payload.selectedGameId,)):
            raise HTTPException(status_code=404, detail="선택한 게임을 찾을 수 없습니다.")
        conn.execute("UPDATE recognition_jobs SET confirmed_game_id = ?, confirmed_at = ? WHERE id = ?", (payload.selectedGameId, t, recognition_id))
        conn.execute(
            "INSERT INTO user_events(id, user_id, session_id, event_type, game_id, payload, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), payload.userId, payload.sessionId, "recognition_confirm", payload.selectedGameId, as_json({"recognitionId": recognition_id}), t),
        )
    return {"recognitionId": recognition_id, "confirmedGameId": payload.selectedGameId, "confirmedAt": t}


def admin_game_payload(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    payload = game_payload(row)
    payload["aliases"] = [
        {"id": alias["id"], "alias": alias["alias"]}
        for alias in fetch_all(conn, "SELECT id, alias FROM game_aliases WHERE game_id = ? ORDER BY alias", (row["id"],))
    ]
    payload["relations"] = [
        {
            "id": relation["id"],
            "targetGameId": relation["target_game_id"],
            "targetNameKo": relation["target_name_ko"],
            "relationType": relation["relation_type"],
        }
        for relation in fetch_all(
            conn,
            """
            SELECT r.id, r.target_game_id, r.relation_type, g.name_ko AS target_name_ko
            FROM game_relations r
            JOIN games g ON g.id = r.target_game_id
            WHERE r.source_game_id = ?
            ORDER BY r.relation_type, g.name_ko
            """,
            (row["id"],),
        )
    ]
    return payload


def ensure_game_quality(conn: sqlite3.Connection, payload: dict[str, Any], game_id: str) -> None:
    candidate = dict(payload)
    candidate["id"] = game_id
    errors = validate_game_values(candidate)
    for row in fetch_all(conn, "SELECT id, name_ko, name_en FROM games WHERE id != ?", (game_id,)):
        existing_names = {normalize_text(row["name_ko"])}
        if row["name_en"]:
            existing_names.add(normalize_text(row["name_en"]))
        for name in (candidate.get("nameKo"), candidate.get("nameEn")):
            if name and normalize_text(name) in existing_names:
                errors.append(f"name: 동일하게 정규화된 이름이 게임 {row['id']}에 있습니다.")
    if errors:
        raise HTTPException(status_code=400, detail={"message": "게임 데이터 품질 규칙을 확인해 주세요.", "errors": sorted(set(errors))})


def ensure_alias_available(conn: sqlite3.Connection, game_id: str, alias: str) -> str:
    normalized = normalize_text(alias)
    owners = {row["game_id"] for row in fetch_all(conn, "SELECT game_id FROM game_aliases WHERE normalized_alias = ?", (normalized,))}
    other_owners = owners - {game_id}
    if other_owners:
        raise HTTPException(status_code=409, detail=f"별칭이 다른 게임({', '.join(sorted(other_owners))})에 이미 연결돼 있습니다.")
    return normalized


@app.get("/admin/games", dependencies=[Depends(require_admin)])
def admin_list_games(q: Optional[str] = None, limit: int = Query(default=200, ge=1, le=500), offset: int = Query(default=0, ge=0)) -> dict[str, Any]:
    sql = """
        SELECT DISTINCT g.*
        FROM games g
        LEFT JOIN game_aliases a ON a.game_id = g.id
        WHERE 1 = 1
    """
    params: list[Any] = []
    if q:
        normalized = f"%{normalize_text(q)}%"
        like = f"%{q.lower()}%"
        sql += " AND (lower(g.id) LIKE ? OR lower(g.name_ko) LIKE ? OR lower(g.name_en) LIKE ? OR a.normalized_alias LIKE ?)"
        params.extend([like, like, like, normalized])
    sql += " ORDER BY g.name_ko LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    with db() as conn:
        rows = fetch_all(conn, sql, tuple(params))
        items = [admin_game_payload(conn, row) for row in rows]
    return {"items": items, "limit": limit, "offset": offset}


@app.post("/admin/games/{game_id}/aliases", dependencies=[Depends(require_admin)])
def admin_create_game_alias(game_id: str, payload: AdminGameAliasCreate) -> dict[str, Any]:
    alias = payload.alias.strip()
    if not alias:
        raise HTTPException(status_code=400, detail="Alias is required.")
    normalized = normalize_text(alias)
    with db() as conn:
        if not fetch_one(conn, "SELECT id FROM games WHERE id = ?", (game_id,)):
            raise HTTPException(status_code=404, detail="Game not found.")
        normalized = ensure_alias_available(conn, game_id, alias)
        existing = fetch_one(conn, "SELECT id FROM game_aliases WHERE game_id = ? AND normalized_alias = ?", (game_id, normalized))
        if existing:
            raise HTTPException(status_code=409, detail="Alias already exists for this game.")
        alias_id = conn.execute(
            "INSERT INTO game_aliases(game_id, alias, normalized_alias) VALUES (?, ?, ?) RETURNING id",
            (game_id, alias, normalized),
        ).fetchone()["id"]
        add_audit_event(conn, "alias_created", "game_alias", str(alias_id), {"gameId": game_id}, now_iso())
    return {"id": alias_id, "gameId": game_id, "alias": alias}


@app.delete("/admin/games/{game_id}/aliases/{alias_id}", dependencies=[Depends(require_admin)])
def admin_delete_game_alias(game_id: str, alias_id: int) -> dict[str, Any]:
    with db() as conn:
        cur = conn.execute("DELETE FROM game_aliases WHERE game_id = ? AND id = ?", (game_id, alias_id))
        if cur.rowcount:
            add_audit_event(conn, "alias_deleted", "game_alias", str(alias_id), {"gameId": game_id}, now_iso())
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Alias not found.")
    return {"gameId": game_id, "aliasId": alias_id, "deleted": True}


@app.post("/admin/games/{game_id}/relations", dependencies=[Depends(require_admin)])
def admin_create_game_relation(game_id: str, payload: AdminGameRelationCreate) -> dict[str, Any]:
    relation_type = payload.relationType.strip()
    if not relation_type:
        raise HTTPException(status_code=400, detail="Relation type is required.")
    if relation_type not in ALLOWED_RELATION_TYPES:
        raise HTTPException(status_code=400, detail="지원하지 않는 관계 유형입니다.")
    if game_id == payload.targetGameId:
        raise HTTPException(status_code=400, detail="A game cannot relate to itself.")
    with db() as conn:
        known_ids = {
            row["id"]
            for row in fetch_all(conn, "SELECT id FROM games WHERE id IN (?, ?)", (game_id, payload.targetGameId))
        }
        if {game_id, payload.targetGameId} != known_ids:
            raise HTTPException(status_code=404, detail="Game not found.")
        existing = fetch_one(
            conn,
            "SELECT id FROM game_relations WHERE source_game_id = ? AND target_game_id = ? AND relation_type = ?",
            (game_id, payload.targetGameId, relation_type),
        )
        if existing:
            raise HTTPException(status_code=409, detail="Relation already exists.")
        relation_id = conn.execute(
            "INSERT INTO game_relations(source_game_id, target_game_id, relation_type) VALUES (?, ?, ?) RETURNING id",
            (game_id, payload.targetGameId, relation_type),
        ).fetchone()["id"]
        add_audit_event(conn, "relation_created", "game_relation", str(relation_id), {"sourceGameId": game_id, "targetGameId": payload.targetGameId, "relationType": relation_type}, now_iso())
    return {"id": relation_id, "sourceGameId": game_id, "targetGameId": payload.targetGameId, "relationType": relation_type}


@app.delete("/admin/games/{game_id}/relations/{relation_id}", dependencies=[Depends(require_admin)])
def admin_delete_game_relation(game_id: str, relation_id: int) -> dict[str, Any]:
    with db() as conn:
        cur = conn.execute("DELETE FROM game_relations WHERE source_game_id = ? AND id = ?", (game_id, relation_id))
        if cur.rowcount:
            add_audit_event(conn, "relation_deleted", "game_relation", str(relation_id), {"gameId": game_id}, now_iso())
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Relation not found.")
    return {"gameId": game_id, "relationId": relation_id, "deleted": True}


@app.get("/admin/data-quality", dependencies=[Depends(require_admin)])
def admin_data_quality() -> dict[str, Any]:
    with db() as conn:
        return data_quality_report(conn)


@app.delete("/admin/data-quality/aliases/{alias_id}", dependencies=[Depends(require_admin)])
def admin_resolve_alias_issue(alias_id: int) -> dict[str, Any]:
    with db() as conn:
        row = fetch_one(conn, "SELECT game_id FROM game_aliases WHERE id = ?", (alias_id,))
        if not row:
            raise HTTPException(status_code=404, detail="별칭을 찾을 수 없습니다.")
        conn.execute("DELETE FROM game_aliases WHERE id = ?", (alias_id,))
        add_audit_event(conn, "quality_alias_removed", "game_alias", str(alias_id), {"gameId": row["game_id"]}, now_iso())
    return {"aliasId": alias_id, "deleted": True}


@app.delete("/admin/data-quality/relations/{relation_id}", dependencies=[Depends(require_admin)])
def admin_resolve_relation_issue(relation_id: int) -> dict[str, Any]:
    with db() as conn:
        row = fetch_one(conn, "SELECT source_game_id FROM game_relations WHERE id = ?", (relation_id,))
        if not row:
            raise HTTPException(status_code=404, detail="관계를 찾을 수 없습니다.")
        conn.execute("DELETE FROM game_relations WHERE id = ?", (relation_id,))
        add_audit_event(conn, "quality_relation_removed", "game_relation", str(relation_id), {"sourceGameId": row["source_game_id"]}, now_iso())
    return {"relationId": relation_id, "deleted": True}


@app.post("/admin/imports/games/preview", dependencies=[Depends(require_admin)])
async def admin_preview_games_import(file: UploadFile = File(...)) -> dict[str, Any]:
    if file.content_type not in {"text/csv", "application/csv", "application/vnd.ms-excel", "text/plain", "application/octet-stream"}:
        raise HTTPException(status_code=400, detail="CSV 파일만 미리보기 할 수 있습니다.")
    content = await file.read()
    try:
        with db() as conn:
            return preview_games_csv(conn, content, datetime.now(KST))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/admin/imports/games/apply", dependencies=[Depends(require_admin)])
def admin_apply_games_import(payload: AdminImportApply) -> dict[str, Any]:
    try:
        with db() as conn:
            result = apply_games_import(conn, payload.importId, payload.strategy, datetime.now(KST))
            add_audit_event(
                conn,
                "games_csv_applied",
                "admin_import",
                payload.importId,
                {"strategy": payload.strategy, **result["result"], "changedCount": len(result["changedGameIds"])},
                now_iso(),
            )
            result["changedCount"] = len(result.pop("changedGameIds"))
            return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/admin/exports/games.csv", dependencies=[Depends(require_admin)])
def admin_export_games() -> Response:
    with db() as conn:
        content = games_csv(conn)
    return Response(
        content="\ufeff" + content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="boardgames.csv"'},
    )


@app.get("/admin/exports/aliases.csv", dependencies=[Depends(require_admin)])
def admin_export_aliases() -> Response:
    with db() as conn:
        content = aliases_csv(conn)
    return Response(
        content="\ufeff" + content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="boardgame-aliases.csv"'},
    )


@app.get("/admin/audit-events", dependencies=[Depends(require_admin)])
def admin_audit_events(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    with db() as conn:
        return {"items": audit_events(conn, limit)}


@app.get("/admin/observability", dependencies=[Depends(require_admin)])
def admin_observability() -> dict[str, Any]:
    return observability_snapshot()


@app.get("/admin/events", dependencies=[Depends(require_admin)])
def admin_events(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    with db() as conn:
        rows = fetch_all(conn, "SELECT * FROM user_events ORDER BY created_at DESC LIMIT ?", (limit,))
    return {
        "items": [
            {
                "id": row["id"],
                "eventType": row["event_type"],
                "userPresent": bool(row["user_id"]),
                "sessionPresent": bool(row["session_id"]),
                "gameId": row["game_id"],
                "payloadKeys": sorted(from_json(row["payload"], {}).keys()),
                "createdAt": row["created_at"],
            }
            for row in rows
        ]
    }


@app.get("/admin/recognitions", dependencies=[Depends(require_admin)])
def admin_recognitions(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    with db() as conn:
        rows = fetch_all(conn, """
            SELECT r.*, COUNT(c.id) AS candidate_count
            FROM recognition_jobs r
            LEFT JOIN recognition_candidates c ON c.recognition_id = r.id
            GROUP BY r.id
            ORDER BY r.created_at DESC
            LIMIT ?
            """, (limit,))
    return {
        "items": [
            {
                "id": row["id"],
                "status": row["status"],
                "userPresent": bool(row["user_id"]),
                "sessionPresent": bool(row["session_id"]),
                "hintPresent": bool(row["hint_text"]),
                "topGameId": row["top_game_id"],
                "confidence": row["confidence"],
                "needsRetake": bool(row["needs_retake"]),
                "confirmedGameId": row["confirmed_game_id"],
                "candidateCount": row["candidate_count"],
                "createdAt": row["created_at"],
                "confirmedAt": row["confirmed_at"],
            }
            for row in rows
        ]
    }


@app.get("/admin/recommendations", dependencies=[Depends(require_admin)])
def admin_recommendations(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    with db() as conn:
        rows = fetch_all(conn, "SELECT * FROM recommendation_logs ORDER BY created_at DESC LIMIT ?", (limit,))
    items = []
    for row in rows:
        request_payload = from_json(row["request_payload"], {})
        response_payload = from_json(row["response_payload"], {})
        items.append(
            {
                "id": row["id"],
                "userPresent": bool(row["user_id"]),
                "sessionPresent": bool(row["session_id"]),
                "request": {
                    "peopleCount": request_payload.get("peopleCount"),
                    "remainingMinutes": request_payload.get("remainingMinutes"),
                    "mood": request_payload.get("mood"),
                    "preferredDifficulty": request_payload.get("preferredDifficulty"),
                    "preferredGenres": request_payload.get("preferredGenres") or [],
                    "limit": request_payload.get("limit"),
                    "excludeCount": len(request_payload.get("excludeGameIds") or []),
                    "previouslyPlayedCount": len(request_payload.get("previouslyPlayedGameIds") or []),
                },
                "itemCount": len(response_payload.get("items") or []),
                "alternativeCount": len(response_payload.get("alternatives") or []),
                "createdAt": row["created_at"],
            }
        )
    return {"items": items}


@app.post("/admin/games", dependencies=[Depends(require_admin)])
def admin_create_game(payload: AdminGameCreate) -> dict[str, Any]:
    game_id = payload.id or slugify(payload.nameEn or payload.nameKo)
    t = now_iso()
    data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
    with db() as conn:
        ensure_game_quality(conn, data, game_id)
        if fetch_one(conn, "SELECT id FROM games WHERE id = ?", (game_id,)):
            raise HTTPException(status_code=409, detail="같은 ID의 게임이 이미 있습니다.")
        aliases = payload.aliases + [payload.nameKo] + ([payload.nameEn] if payload.nameEn else [])
        for alias in aliases:
            ensure_alias_available(conn, game_id, alias)
        conn.execute("""
            INSERT INTO games(
                id, name_ko, name_en, short_description, rules_summary,
                min_players, max_players, avg_play_time_minutes, difficulty, genre,
                tags, is_beginner_friendly, is_kid_friendly, is_party_game,
                is_strategy_game, play_style, image_url, image_source, image_license,
                image_alt, created_at, updated_at, data_source_url, data_license,
                content_license, reviewed_at, reviewed_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (game_id, payload.nameKo, payload.nameEn, payload.shortDescription, payload.rulesSummary, payload.minPlayers, payload.maxPlayers, payload.avgPlayTimeMinutes, payload.difficulty, payload.genre, as_json(payload.tags), int(payload.isBeginnerFriendly), int(payload.isKidFriendly), int(payload.isPartyGame), int(payload.isStrategyGame), payload.playStyle, payload.imageUrl, payload.imageSource, payload.imageLicense, payload.imageAlt, t, t, payload.dataSourceUrl, payload.dataLicense, payload.contentLicense, payload.reviewedAt, payload.reviewedBy))
        seen_aliases = set()
        for alias in aliases:
            normalized = normalize_text(alias)
            if normalized in seen_aliases:
                continue
            seen_aliases.add(normalized)
            conn.execute("INSERT INTO game_aliases(game_id, alias, normalized_alias) VALUES (?, ?, ?)", (game_id, alias, normalized))
        add_audit_event(conn, "game_created", "game", game_id, {"aliasCount": len(seen_aliases)}, t)
    return {"id": game_id, "createdAt": t}


@app.patch("/admin/games/{game_id}", dependencies=[Depends(require_admin)])
def admin_patch_game(game_id: str, payload: AdminGamePatch) -> dict[str, Any]:
    data = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else payload.dict(exclude_unset=True)
    if not data:
        return {"id": game_id, "updated": False}
    mapping = {"nameKo": "name_ko", "nameEn": "name_en", "shortDescription": "short_description", "rulesSummary": "rules_summary", "minPlayers": "min_players", "maxPlayers": "max_players", "avgPlayTimeMinutes": "avg_play_time_minutes", "difficulty": "difficulty", "genre": "genre", "tags": "tags", "isBeginnerFriendly": "is_beginner_friendly", "isKidFriendly": "is_kid_friendly", "isPartyGame": "is_party_game", "isStrategyGame": "is_strategy_game", "playStyle": "play_style", "imageUrl": "image_url", "imageSource": "image_source", "imageLicense": "image_license", "imageAlt": "image_alt", "dataSourceUrl": "data_source_url", "dataLicense": "data_license", "contentLicense": "content_license", "reviewedAt": "reviewed_at", "reviewedBy": "reviewed_by"}
    sets = []
    params = []
    for key, value in data.items():
        sets.append(f"{mapping[key]} = ?")
        params.append(as_json(value) if key == "tags" else int(value) if isinstance(value, bool) else value)
    sets.append("updated_at = ?")
    params.append(now_iso())
    params.append(game_id)
    with db() as conn:
        existing = fetch_one(conn, "SELECT * FROM games WHERE id = ?", (game_id,))
        if not existing:
            raise HTTPException(status_code=404, detail="게임을 찾을 수 없습니다.")
        merged = game_payload(existing)
        merged.update(data)
        ensure_game_quality(conn, merged, game_id)
        cur = conn.execute(f"UPDATE games SET {', '.join(sets)} WHERE id = ?", tuple(params))
        add_audit_event(conn, "game_updated", "game", game_id, {"changedFields": sorted(data.keys())}, now_iso())
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="게임을 찾을 수 없습니다.")
    return {"id": game_id, "updated": True}
