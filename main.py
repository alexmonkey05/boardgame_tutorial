from __future__ import annotations

import json
import math
import os
import secrets
import sqlite3
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from recognition_service import match_vision_candidates
from vision_client import VisionAPIError, is_vision_configured, recognize_boardgame_image

load_dotenv()

DATABASE_PATH = Path(os.getenv("BOARDGAME_DB_PATH") or "./boardgame_backend.sqlite3")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN") or "dev-admin-token"
VISION_API_PROVIDER = os.getenv("VISION_API_PROVIDER") or "mock"
VISION_API_KEY = os.getenv("VISION_API_KEY") or ""
VISION_API_ENDPOINT = os.getenv("VISION_API_ENDPOINT") or ""
VISION_MODEL = os.getenv("VISION_MODEL") or ""
KST = timezone(timedelta(hours=9))
MAX_IMAGE_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}

PRIVACY_POLICY = {
    "anonymousUsage": True,
    "optionalLoginReady": True,
    "locationFallback": "위치 권한을 거부하면 QR 코드 또는 수동 카페 선택으로 이용합니다.",
    "dataDeletion": "DELETE /users/{userId}/data로 익명 세션 또는 선택 로그인 사용자 기록 삭제를 요청할 수 있습니다.",
    "minimalCollection": "추천과 최근 기록에 필요한 이벤트, 카페 ID, 게임 ID 중심으로 저장합니다.",
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

def now_iso() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def as_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def from_json(value: Optional[str], fallback: Any = None) -> Any:
    if value is None or value == "":
        return fallback
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
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def fetch_one(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> Optional[sqlite3.Row]:
    return conn.execute(query, params).fetchone()


def fetch_all(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    return conn.execute(query, params).fetchall()


def game_payload(row: sqlite3.Row) -> dict[str, Any]:
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
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def cafe_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "branchName": row["branch_name"],
        "address": row["address"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "qrCode": row["qr_code"],
        "status": row["status"],
        "metadata": from_json(row["metadata"], {}),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def inventory_game_payload(row: sqlite3.Row) -> dict[str, Any]:
    game = game_payload(row)
    return {
        "game": game,
        "inventory": {
            "cafeId": row["cafe_id"],
            "shelfLocation": row["shelf_location"],
            "isAvailable": bool(row["is_available"]),
            "temporaryUnavailable": bool(row["temporary_unavailable"]),
            "popularityScore": row["popularity_score"],
            "staffPick": bool(row["staff_pick"]),
        },
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
    cafeId: Optional[str] = None
    gameId: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)


class PlayedGameCreate(BaseModel):
    gameId: str
    cafeId: Optional[str] = None
    playedAt: Optional[str] = None
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    notes: Optional[str] = None


class HiddenGameCreate(BaseModel):
    gameId: str
    reason: Optional[str] = None


class RecommendationRequest(BaseModel):
    userId: Optional[str] = None
    sessionId: Optional[str] = None
    cafeId: str
    peopleCount: Optional[int] = Field(default=None, ge=1)
    remainingMinutes: Optional[int] = Field(default=None, ge=1)
    mood: Optional[str] = None
    preferredDifficulty: Optional[str] = None
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
    aliases: list[str] = Field(default_factory=list)


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


class AdminCafeCreate(BaseModel):
    id: Optional[str] = None
    name: str
    branchName: str
    address: str
    latitude: float
    longitude: float
    qrCode: str
    status: str = "open"
    metadata: dict[str, Any] = Field(default_factory=dict)


class AdminCafePatch(BaseModel):
    name: Optional[str] = None
    branchName: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    qrCode: Optional[str] = None
    status: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class InventoryItem(BaseModel):
    gameId: str
    shelfLocation: Optional[str] = None
    isAvailable: bool = True
    temporaryUnavailable: bool = False
    popularityScore: int = 0
    staffPick: bool = False


class InventoryReplace(BaseModel):
    items: list[InventoryItem]


def model_to_json(model: BaseModel) -> str:
    if hasattr(model, "model_dump_json"):
        return model.model_dump_json()
    return model.json(ensure_ascii=False)


def create_schema() -> None:
    with db() as conn:
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

            CREATE TABLE IF NOT EXISTS cafes (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                branch_name TEXT NOT NULL,
                address TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                qr_code TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cafe_inventory (
                cafe_id TEXT NOT NULL REFERENCES cafes(id) ON DELETE CASCADE,
                game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                shelf_location TEXT,
                is_available INTEGER NOT NULL DEFAULT 1,
                temporary_unavailable INTEGER NOT NULL DEFAULT 0,
                popularity_score INTEGER NOT NULL DEFAULT 0,
                staff_pick INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (cafe_id, game_id)
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
                cafe_id TEXT,
                game_id TEXT,
                payload TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS played_games (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                cafe_id TEXT,
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
                cafe_id TEXT,
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
                confidence REAL NOT NULL,
                is_available_in_cafe INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS recommendation_logs (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                session_id TEXT,
                cafe_id TEXT NOT NULL,
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

            CREATE INDEX IF NOT EXISTS idx_game_aliases_normalized ON game_aliases(normalized_alias);
            CREATE INDEX IF NOT EXISTS idx_game_relations_source ON game_relations(source_game_id, relation_type);
            CREATE INDEX IF NOT EXISTS idx_games_filter ON games(min_players, max_players, avg_play_time_minutes, difficulty, genre);
            CREATE INDEX IF NOT EXISTS idx_games_genre_difficulty ON games(genre, difficulty, avg_play_time_minutes);
            CREATE INDEX IF NOT EXISTS idx_cafes_qr_code ON cafes(qr_code);
            CREATE INDEX IF NOT EXISTS idx_cafe_inventory_lookup ON cafe_inventory(cafe_id, is_available, temporary_unavailable, game_id);
            CREATE INDEX IF NOT EXISTS idx_cafe_inventory_game_lookup ON cafe_inventory(game_id, cafe_id);
            CREATE INDEX IF NOT EXISTS idx_cafe_inventory_popularity ON cafe_inventory(cafe_id, popularity_score DESC);
            CREATE INDEX IF NOT EXISTS idx_user_events_recent ON user_events(user_id, session_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_user_events_game_recent ON user_events(user_id, session_id, game_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_user_events_type_recent ON user_events(event_type, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_played_games_user_recent ON played_games(user_id, played_at DESC);
            CREATE INDEX IF NOT EXISTS idx_hidden_games_user ON hidden_games(user_id, game_id);
            CREATE INDEX IF NOT EXISTS idx_recognition_jobs_user_recent ON recognition_jobs(user_id, session_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_recognition_candidates_job ON recognition_candidates(recognition_id, confidence DESC);
            CREATE INDEX IF NOT EXISTS idx_recommendation_logs_user ON recommendation_logs(user_id, session_id, created_at DESC);
            """
        )


def seed_data() -> None:
    games = [
        ("splendor", "스플렌더", "Splendor", "보석 토큰을 모아 카드를 사고 점수를 만드는 입문 전략 게임입니다.", "토큰을 가져가거나 카드를 구매해 귀족과 점수를 얻습니다.", 2, 4, 30, "easy", "strategy", ["입문", "엔진빌딩", "카드"], 1, 0, 0, 1, "competitive", "https://example.com/images/splendor.jpg"),
        ("codenames", "코드네임", "Codenames", "힌트 한 단어로 팀원이 정답 카드를 맞히는 파티 추리 게임입니다.", "팀장은 단어 힌트와 숫자를 말하고 팀원은 관련 카드를 고릅니다.", 4, 8, 20, "easy", "party", ["단어", "팀전", "대화"], 1, 1, 1, 0, "team", "https://example.com/images/codenames.jpg"),
        ("azul", "아줄", "Azul", "타일을 골라 개인 보드에 배치하는 아름다운 퍼즐 전략 게임입니다.", "공용 타일을 가져와 줄을 채우고 벽에 배치해 점수를 얻습니다.", 2, 4, 35, "medium", "puzzle", ["퍼즐", "타일", "가족"], 1, 1, 0, 1, "competitive", "https://example.com/images/azul.jpg"),
        ("dixit", "딕싯", "Dixit", "그림 카드와 상상력으로 힌트를 맞히는 감성 파티 게임입니다.", "출제자의 문장에 어울리는 그림을 내고 누가 낸 카드인지 맞힙니다.", 3, 6, 30, "easy", "party", ["그림", "상상", "가족"], 1, 1, 1, 0, "competitive", "https://example.com/images/dixit.jpg"),
        ("pandemic", "팬데믹", "Pandemic", "전 세계 질병 확산을 함께 막는 협력 전략 게임입니다.", "역할 능력을 활용해 도시를 이동하고 치료제를 개발합니다.", 2, 4, 45, "medium", "cooperative", ["협력", "전략", "테마"], 0, 0, 0, 1, "cooperative", "https://example.com/images/pandemic.jpg"),
        ("ticket-to-ride", "티켓 투 라이드", "Ticket to Ride", "기차 노선을 연결해 목적지를 완성하는 가족 전략 게임입니다.", "카드를 모아 노선을 점유하고 목적지 티켓을 완성합니다.", 2, 5, 45, "easy", "family", ["가족", "기차", "루트빌딩"], 1, 1, 0, 1, "competitive", "https://example.com/images/ticket-to-ride.jpg"),
        ("terraforming-mars", "테라포밍 마스", "Terraforming Mars", "화성 개발 기업이 되어 장기 엔진을 만드는 고난도 전략 게임입니다.", "프로젝트 카드를 내고 산소, 온도, 바다를 올려 점수를 얻습니다.", 1, 5, 120, "hard", "strategy", ["고난도", "엔진빌딩", "SF"], 0, 0, 0, 1, "competitive", "https://example.com/images/terraforming-mars.jpg"),
    ]
    cafes = [
        ("cafe-hongdae", "보드라운지", "홍대점", "서울 마포구 와우산로 21", 37.5519, 126.9223, "QR-HONGDAE-001", "open", {"popularMood": "친구 모임", "tables": 18}),
        ("cafe-gangnam", "플레이박스", "강남점", "서울 강남구 강남대로 396", 37.4979, 127.0276, "QR-GANGNAM-001", "open", {"popularMood": "퇴근 후 모임", "tables": 22}),
    ]
    inventory = [
        ("cafe-hongdae", "splendor", "A-03", 1, 0, 94, 1),
        ("cafe-hongdae", "codenames", "B-01", 1, 0, 89, 1),
        ("cafe-hongdae", "azul", "A-07", 1, 0, 82, 0),
        ("cafe-hongdae", "dixit", "B-04", 1, 0, 78, 0),
        ("cafe-hongdae", "pandemic", "C-02", 0, 1, 73, 0),
        ("cafe-gangnam", "splendor", "S-10", 1, 0, 90, 0),
        ("cafe-gangnam", "pandemic", "C-08", 1, 0, 86, 1),
        ("cafe-gangnam", "ticket-to-ride", "F-02", 1, 0, 84, 1),
        ("cafe-gangnam", "terraforming-mars", "H-01", 1, 0, 65, 0),
        ("cafe-gangnam", "azul", "S-03", 1, 0, 80, 0),
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
            "INSERT INTO games VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(gid, ko, en, desc, rules, minp, maxp, time_min, diff, genre, as_json(tags), beginner, kid, party, strategy, style, image, t, t) for gid, ko, en, desc, rules, minp, maxp, time_min, diff, genre, tags, beginner, kid, party, strategy, style, image in games],
        )
        conn.executemany(
            "INSERT INTO cafes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(cid, name, branch, addr, lat, lng, qr, status, as_json(meta), t, t) for cid, name, branch, addr, lat, lng, qr, status, meta in cafes],
        )
        conn.executemany(
            "INSERT INTO cafe_inventory VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(cid, gid, shelf, available, unavailable, popularity, staff, t) for cid, gid, shelf, available, unavailable, popularity, staff in inventory],
        )
        for game_id, names in aliases.items():
            for alias in names:
                conn.execute("INSERT INTO game_aliases(game_id, alias, normalized_alias) VALUES (?, ?, ?)", (game_id, alias, normalize_text(alias)))
        conn.executemany("INSERT INTO game_relations(source_game_id, target_game_id, relation_type) VALUES (?, ?, ?)", relations)
        conn.execute("INSERT INTO admin_users VALUES (?, ?, ?, ?, ?)", ("admin-dev", "Development Admin", ADMIN_TOKEN[:4] + "...", "owner", t))


def startup() -> None:
    create_schema()
    seed_data()


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    startup()
    yield


app = FastAPI(
    title="Boardgame Cafe Backend MVP",
    version="0.1.2",
    description="보드게임 카페 앱 프로토타입의 하드코딩 데이터를 서버 API로 분리한 FastAPI MVP",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, Any]:
    with db() as conn:
        table_count = fetch_one(conn, "SELECT COUNT(*) AS count FROM sqlite_master WHERE type='table'")["count"]
        game_count = fetch_one(conn, "SELECT COUNT(*) AS count FROM games")["count"]
    return {"status": "ok", "time": now_iso(), "database": str(DATABASE_PATH), "tables": table_count, "seedGames": game_count, "privacy": PRIVACY_POLICY, "imageRetention": IMAGE_RETENTION_POLICY, "imageRecognition": image_recognition_config()}


@app.get("/meta/schema")
def schema_metadata() -> dict[str, Any]:
    return {
        "tables": ["games", "game_aliases", "game_relations", "cafes", "cafe_inventory", "users", "anonymous_sessions", "user_events", "played_games", "hidden_games", "recognition_jobs", "recognition_candidates", "recommendation_logs", "admin_users"],
        "fastQueries": ["카페별 보유 게임 조회", "조건 기반 보유 게임 필터링", "게임명/별칭 검색", "사용자 최근 기록 조회", "현재 카페 기준 추천 후보 조회", "이미지 인식 후보 저장 및 확인"],
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
        sql += " AND g.tags LIKE ?"
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


@app.get("/cafes/nearby")
def nearby_cafes(lat: Optional[float] = None, lng: Optional[float] = None, limit: int = Query(default=20, ge=1, le=50)) -> dict[str, Any]:
    with db() as conn:
        rows = fetch_all(conn, "SELECT * FROM cafes ORDER BY name LIMIT ?", (limit,))
    items = []
    for row in rows:
        cafe = cafe_payload(row)
        if lat is not None and lng is not None:
            cafe["distanceKm"] = round(math.sqrt((row["latitude"] - lat) ** 2 + (row["longitude"] - lng) ** 2) * 111, 2)
        items.append(cafe)
    if lat is not None and lng is not None:
        items.sort(key=lambda item: item.get("distanceKm", 999999))
    return {"items": items[:limit], "locationFallback": PRIVACY_POLICY["locationFallback"]}


@app.get("/cafes/by-qr/{qr_code}")
def cafe_by_qr(qr_code: str) -> dict[str, Any]:
    with db() as conn:
        row = fetch_one(conn, "SELECT * FROM cafes WHERE qr_code = ?", (qr_code,))
    if not row:
        raise HTTPException(status_code=404, detail="QR 코드에 해당하는 카페를 찾을 수 없습니다.")
    return cafe_payload(row)


@app.get("/cafes/{cafe_id}")
def get_cafe(cafe_id: str) -> dict[str, Any]:
    with db() as conn:
        row = fetch_one(conn, "SELECT * FROM cafes WHERE id = ?", (cafe_id,))
    if not row:
        raise HTTPException(status_code=404, detail="카페를 찾을 수 없습니다.")
    return cafe_payload(row)


@app.get("/cafes/{cafe_id}/games")
def cafe_games(cafe_id: str, peopleCount: Optional[int] = Query(default=None, ge=1), maxPlayTime: Optional[int] = Query(default=None, ge=1), difficulty: Optional[str] = None, genre: Optional[str] = None, tag: Optional[str] = None, availableOnly: bool = False, q: Optional[str] = None, sort: str = Query(default="popularity", pattern="^(popularity|name|playTime|difficulty|availability)$"), limit: int = Query(default=100, ge=1, le=200)) -> dict[str, Any]:
    sql = """
        SELECT g.*, i.cafe_id, i.shelf_location, i.is_available, i.temporary_unavailable, i.popularity_score, i.staff_pick
        FROM cafe_inventory i
        JOIN games g ON g.id = i.game_id
        LEFT JOIN game_aliases a ON a.game_id = g.id
        WHERE i.cafe_id = ?
    """
    params: list[Any] = [cafe_id]
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
        sql += " AND g.tags LIKE ?"
        params.append(f"%{tag}%")
    if availableOnly:
        sql += " AND i.is_available = 1 AND i.temporary_unavailable = 0"
    if q:
        normalized = f"%{normalize_text(q)}%"
        like = f"%{q.lower()}%"
        sql += " AND (lower(g.name_ko) LIKE ? OR lower(g.name_en) LIKE ? OR a.normalized_alias LIKE ?)"
        params.extend([like, like, normalized])
    order_by = {
        "popularity": "i.is_available DESC, i.temporary_unavailable ASC, i.popularity_score DESC, g.name_ko",
        "name": "g.name_ko ASC, i.is_available DESC",
        "playTime": "g.avg_play_time_minutes ASC, i.is_available DESC, i.popularity_score DESC",
        "difficulty": "CASE g.difficulty WHEN 'easy' THEN 1 WHEN 'medium' THEN 2 WHEN 'hard' THEN 3 ELSE 9 END, i.is_available DESC, g.name_ko",
        "availability": "i.is_available DESC, i.temporary_unavailable ASC, i.popularity_score DESC, g.name_ko",
    }[sort]
    sql += f" GROUP BY g.id ORDER BY {order_by} LIMIT ?"
    params.append(limit)
    with db() as conn:
        cafe = fetch_one(conn, "SELECT * FROM cafes WHERE id = ?", (cafe_id,))
        if not cafe:
            raise HTTPException(status_code=404, detail="카페를 찾을 수 없습니다.")
        rows = fetch_all(conn, sql, tuple(params))
    return {"cafe": cafe_payload(cafe), "items": [inventory_game_payload(row) for row in rows], "sort": sort, "sortOptions": ["popularity", "name", "playTime", "difficulty", "availability"]}


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
        if payload.cafeId and not fetch_one(conn, "SELECT id FROM cafes WHERE id = ?", (payload.cafeId,)):
            raise HTTPException(status_code=404, detail="카페를 찾을 수 없습니다.")
        conn.execute("INSERT INTO user_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (event_id, payload.userId, payload.sessionId, payload.eventType, payload.cafeId, payload.gameId, as_json(payload.payload), t))
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
        "events": [{"id": r["id"], "eventType": r["event_type"], "cafeId": r["cafe_id"], "gameId": r["game_id"], "payload": from_json(r["payload"], {}), "createdAt": r["created_at"]} for r in events],
        "playedGames": [{"id": r["id"], "gameId": r["game_id"], "nameKo": r["name_ko"], "cafeId": r["cafe_id"], "playedAt": r["played_at"], "rating": r["rating"], "notes": r["notes"]} for r in played],
        "hiddenGames": [{"id": r["id"], "gameId": r["game_id"], "nameKo": r["name_ko"], "reason": r["reason"], "createdAt": r["created_at"]} for r in hidden],
    }


@app.post("/users/{user_id}/played-games")
def add_played_game(user_id: str, payload: PlayedGameCreate) -> dict[str, Any]:
    record_id = str(uuid.uuid4())
    played_at = payload.playedAt or now_iso()
    with db() as conn:
        if not fetch_one(conn, "SELECT id FROM games WHERE id = ?", (payload.gameId,)):
            raise HTTPException(status_code=404, detail="게임을 찾을 수 없습니다.")
        conn.execute("INSERT INTO played_games VALUES (?, ?, ?, ?, ?, ?, ?)", (record_id, user_id, payload.gameId, payload.cafeId, played_at, payload.rating, payload.notes))
    return {"id": record_id, "userId": user_id, "gameId": payload.gameId, "playedAt": played_at}


@app.post("/users/{user_id}/hidden-games")
def add_hidden_game(user_id: str, payload: HiddenGameCreate) -> dict[str, Any]:
    record_id = str(uuid.uuid4())
    t = now_iso()
    with db() as conn:
        if not fetch_one(conn, "SELECT id FROM games WHERE id = ?", (payload.gameId,)):
            raise HTTPException(status_code=404, detail="게임을 찾을 수 없습니다.")
        conn.execute("INSERT OR REPLACE INTO hidden_games VALUES (?, ?, ?, ?, ?)", (record_id, user_id, payload.gameId, payload.reason, t))
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
        cafe = fetch_one(conn, "SELECT id FROM cafes WHERE id = ?", (payload.cafeId,))
        if not cafe:
            raise HTTPException(status_code=404, detail="카페를 찾을 수 없습니다.")
        rows = fetch_all(conn, """
            SELECT g.*, i.cafe_id, i.shelf_location, i.is_available, i.temporary_unavailable, i.popularity_score, i.staff_pick
            FROM cafe_inventory i
            JOIN games g ON g.id = i.game_id
            WHERE i.cafe_id = ?
            ORDER BY i.is_available DESC, i.popularity_score DESC
            """, (payload.cafeId,))
        hidden = set()
        played = set(payload.previouslyPlayedGameIds)
        signals = load_user_recommendation_signals(conn, payload.userId, payload.sessionId)
        if payload.userId or payload.sessionId:
            uid = payload.userId or payload.sessionId
            hidden = {r["game_id"] for r in fetch_all(conn, "SELECT game_id FROM hidden_games WHERE user_id = ?", (uid,))}
            played.update({r["game_id"] for r in fetch_all(conn, "SELECT game_id FROM played_games WHERE user_id = ?", (uid,))})
    excluded = set(payload.excludeGameIds) | hidden
    items: list[dict[str, Any]] = []
    alternatives: list[dict[str, Any]] = []
    for row in rows:
        game = game_payload(row)
        if game["id"] in excluded:
            continue
        score = 40 + int(row["popularity_score"] or 0) / 2
        reasons: list[str] = []
        available = bool(row["is_available"]) and not bool(row["temporary_unavailable"])
        if available:
            score += 35
            reasons.append("지금 이 카페에 바로 대여 가능해요")
        else:
            score -= 35
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
        bonus, mood_reasons = mood_bonus(game, payload.mood)
        score += bonus
        reasons.extend(mood_reasons)
        event_bonus, event_reasons = event_preference_bonus(game, signals)
        score += event_bonus
        reasons.extend(event_reasons)
        if row["staff_pick"]:
            score += 8
            reasons.append("이 매장의 추천 게임이에요")
        if game["id"] in played:
            score -= 12
            reasons.append("이미 플레이한 기록이 있어 우선순위를 조금 낮췄어요")
        if not reasons:
            reasons.append("현재 조건과 매장 인기 데이터를 함께 반영했어요")
        result = {"game": game, "score": round(score, 1), "priority": 0, "reasons": reasons[:4], "isAvailableInCafe": available, "shelfLocation": row["shelf_location"]}
        if available and score >= 50:
            items.append(result)
        else:
            alternatives.append(result)
    items.sort(key=lambda x: x["score"], reverse=True)
    alternatives.sort(key=lambda x: x["score"], reverse=True)
    for index, item in enumerate(items, start=1):
        item["priority"] = index
    return {"items": items[: payload.limit], "alternatives": alternatives[:3], "signalsUsed": {"eventGameCount": len(signals["eventGameWeights"]), "genreCount": len(signals["genreWeights"]), "tagCount": len(signals["tagWeights"])}}


@app.post("/recommendations")
def recommendations(payload: RecommendationRequest) -> dict[str, Any]:
    result = build_recommendations(payload)
    log_id = str(uuid.uuid4())
    t = now_iso()
    response = {"recommendationId": log_id, "cafeId": payload.cafeId, "items": result["items"], "alternatives": result["alternatives"], "signalsUsed": result["signalsUsed"], "generatedAt": t}
    with db() as conn:
        conn.execute("INSERT INTO recommendation_logs VALUES (?, ?, ?, ?, ?, ?, ?)", (log_id, payload.userId, payload.sessionId, payload.cafeId, model_to_json(payload), as_json(response), t))
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


def recognition_candidates_for_hint(conn: sqlite3.Connection, hint: str, cafe_id: Optional[str]) -> list[dict[str, Any]]:
    normalized = normalize_text(hint)
    rows = fetch_all(conn, """
        SELECT DISTINCT g.*
        FROM games g
        LEFT JOIN game_aliases a ON a.game_id = g.id
        WHERE lower(g.name_ko) LIKE ? OR lower(g.name_en) LIKE ? OR a.normalized_alias LIKE ? OR g.tags LIKE ?
        LIMIT 5
        """, (f"%{hint.lower()}%", f"%{hint.lower()}%", f"%{normalized}%", f"%{hint}%"))
    if not rows:
        rows = fetch_all(conn, "SELECT * FROM games ORDER BY is_beginner_friendly DESC, name_ko LIMIT 4")
    candidates = []
    for index, row in enumerate(rows):
        available = False
        if cafe_id:
            inv = fetch_one(conn, "SELECT is_available, temporary_unavailable FROM cafe_inventory WHERE cafe_id = ? AND game_id = ?", (cafe_id, row["id"]))
            available = bool(inv and inv["is_available"] and not inv["temporary_unavailable"])
        matched_name = normalized and (normalized in normalize_text(row["name_ko"]) or (row["name_en"] and normalized in normalize_text(row["name_en"])))
        base = 0.88 - (index * 0.12) if matched_name else 0.52 - (index * 0.07)
        candidates.append({"game": game_payload(row), "confidence": round(max(0.2, min(base, 0.96)), 2), "isAvailableInCafe": available})
    return candidates


@app.post("/recognitions")
async def create_recognition(cafeId: Optional[str] = Query(default=None), userId: Optional[str] = Query(default=None), sessionId: Optional[str] = Query(default=None), hint: Optional[str] = Query(default=None), image: Optional[UploadFile] = File(default=None)) -> dict[str, Any]:
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
        "storesOriginalImageLocally": False,
    }
    if image:
        validate_uploaded_image(image_bytes, content_type)
    if not image_bytes and not fallback_hint:
        message = "이미지나 텍스트 힌트가 없어 인식 후보를 만들 수 없어요. 박스 사진을 업로드하거나 게임명 힌트를 입력해 주세요."
        with db() as conn:
            conn.execute("INSERT INTO recognition_jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (recognition_id, userId, sessionId, cafeId, "input_required", 0, None, None, 0.0, 1, message, None, t, None))
        return {"recognitionId": recognition_id, "topCandidate": None, "candidates": [], "needsRetake": True, "message": message, "imageRetention": IMAGE_RETENTION_POLICY, "externalProcessing": external_processing}

    with db() as conn:
        if cafeId and not fetch_one(conn, "SELECT id FROM cafes WHERE id = ?", (cafeId,)):
            prefixed_cafe_id = f"cafe-{cafeId}"
            if fetch_one(conn, "SELECT id FROM cafes WHERE id = ?", (prefixed_cafe_id,)):
                cafeId = prefixed_cafe_id
            else:
                raise HTTPException(status_code=404, detail="카페를 찾을 수 없습니다.")

    recognition_result: Optional[dict[str, Any]] = None
    status = "completed"
    if image_bytes and is_vision_configured():
        try:
            vision_response = await recognize_boardgame_image(image_bytes, content_type, hint_text or None)
            external_processing["used"] = True
            with db() as conn:
                recognition_result = match_vision_candidates(conn, vision_response, cafeId)
        except VisionAPIError:
            status = "fallback"

    with db() as conn:
        if recognition_result is None:
            candidates = recognition_candidates_for_hint(conn, fallback_hint or hint_text, cafeId)
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
        conn.execute("INSERT INTO recognition_jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (recognition_id, userId, sessionId, cafeId, status, 0, fallback_hint or None, top["game"]["id"] if top else None, confidence, int(needs_retake), message, None, t, None))
        for candidate in candidates:
            conn.execute("INSERT INTO recognition_candidates(recognition_id, game_id, confidence, is_available_in_cafe) VALUES (?, ?, ?, ?)", (recognition_id, candidate["game"]["id"], candidate["confidence"], int(candidate["isAvailableInCafe"])))
    return {"recognitionId": recognition_id, "topCandidate": top, "candidates": candidates, "unmatchedCandidates": unmatched_candidates, "needsRetake": needs_retake, "message": message, "imageRetention": IMAGE_RETENTION_POLICY, "externalProcessing": external_processing}


@app.get("/recognitions/{recognition_id}")
def get_recognition(recognition_id: str) -> dict[str, Any]:
    with db() as conn:
        job = fetch_one(conn, "SELECT * FROM recognition_jobs WHERE id = ?", (recognition_id,))
        if not job:
            raise HTTPException(status_code=404, detail="인식 작업을 찾을 수 없습니다.")
        rows = fetch_all(conn, """
            SELECT c.confidence, c.is_available_in_cafe, g.*
            FROM recognition_candidates c
            JOIN games g ON g.id = c.game_id
            WHERE c.recognition_id = ?
            ORDER BY c.confidence DESC
            """, (recognition_id,))
    candidates = [{"game": game_payload(row), "confidence": row["confidence"], "isAvailableInCafe": bool(row["is_available_in_cafe"])} for row in rows]
    return {"recognitionId": job["id"], "status": job["status"], "topCandidate": candidates[0] if candidates else None, "candidates": candidates, "needsRetake": bool(job["needs_retake"]), "message": job["message"], "confirmedGameId": job["confirmed_game_id"], "imageRetention": IMAGE_RETENTION_POLICY}


@app.post("/recognitions/{recognition_id}/confirm")
def confirm_recognition(recognition_id: str, payload: RecognitionConfirm) -> dict[str, Any]:
    t = now_iso()
    with db() as conn:
        job = fetch_one(conn, "SELECT cafe_id FROM recognition_jobs WHERE id = ?", (recognition_id,))
        if not job:
            raise HTTPException(status_code=404, detail="인식 작업을 찾을 수 없습니다.")
        if not fetch_one(conn, "SELECT id FROM games WHERE id = ?", (payload.selectedGameId,)):
            raise HTTPException(status_code=404, detail="선택한 게임을 찾을 수 없습니다.")
        conn.execute("UPDATE recognition_jobs SET confirmed_game_id = ?, confirmed_at = ? WHERE id = ?", (payload.selectedGameId, t, recognition_id))
        conn.execute("INSERT INTO user_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (str(uuid.uuid4()), payload.userId, payload.sessionId, "recognition_confirm", job["cafe_id"], payload.selectedGameId, as_json({"recognitionId": recognition_id}), t))
    return {"recognitionId": recognition_id, "confirmedGameId": payload.selectedGameId, "confirmedAt": t}


@app.post("/admin/games", dependencies=[Depends(require_admin)])
def admin_create_game(payload: AdminGameCreate) -> dict[str, Any]:
    game_id = payload.id or slugify(payload.nameEn or payload.nameKo)
    t = now_iso()
    with db() as conn:
        conn.execute("""
            INSERT INTO games VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (game_id, payload.nameKo, payload.nameEn, payload.shortDescription, payload.rulesSummary, payload.minPlayers, payload.maxPlayers, payload.avgPlayTimeMinutes, payload.difficulty, payload.genre, as_json(payload.tags), int(payload.isBeginnerFriendly), int(payload.isKidFriendly), int(payload.isPartyGame), int(payload.isStrategyGame), payload.playStyle, payload.imageUrl, t, t))
        seen_aliases = set()
        for alias in payload.aliases + [payload.nameKo] + ([payload.nameEn] if payload.nameEn else []):
            normalized = normalize_text(alias)
            if normalized in seen_aliases:
                continue
            seen_aliases.add(normalized)
            conn.execute("INSERT INTO game_aliases(game_id, alias, normalized_alias) VALUES (?, ?, ?)", (game_id, alias, normalized))
    return {"id": game_id, "createdAt": t}


@app.patch("/admin/games/{game_id}", dependencies=[Depends(require_admin)])
def admin_patch_game(game_id: str, payload: AdminGamePatch) -> dict[str, Any]:
    data = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else payload.dict(exclude_unset=True)
    if not data:
        return {"id": game_id, "updated": False}
    mapping = {"nameKo": "name_ko", "nameEn": "name_en", "shortDescription": "short_description", "rulesSummary": "rules_summary", "minPlayers": "min_players", "maxPlayers": "max_players", "avgPlayTimeMinutes": "avg_play_time_minutes", "difficulty": "difficulty", "genre": "genre", "tags": "tags", "isBeginnerFriendly": "is_beginner_friendly", "isKidFriendly": "is_kid_friendly", "isPartyGame": "is_party_game", "isStrategyGame": "is_strategy_game", "playStyle": "play_style", "imageUrl": "image_url"}
    sets = []
    params = []
    for key, value in data.items():
        sets.append(f"{mapping[key]} = ?")
        params.append(as_json(value) if key == "tags" else int(value) if isinstance(value, bool) else value)
    sets.append("updated_at = ?")
    params.append(now_iso())
    params.append(game_id)
    with db() as conn:
        cur = conn.execute(f"UPDATE games SET {', '.join(sets)} WHERE id = ?", tuple(params))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="게임을 찾을 수 없습니다.")
    return {"id": game_id, "updated": True}


@app.post("/admin/cafes", dependencies=[Depends(require_admin)])
def admin_create_cafe(payload: AdminCafeCreate) -> dict[str, Any]:
    cafe_id = payload.id or str(uuid.uuid4())
    t = now_iso()
    with db() as conn:
        conn.execute("INSERT INTO cafes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (cafe_id, payload.name, payload.branchName, payload.address, payload.latitude, payload.longitude, payload.qrCode, payload.status, as_json(payload.metadata), t, t))
    return {"id": cafe_id, "createdAt": t}


@app.patch("/admin/cafes/{cafe_id}", dependencies=[Depends(require_admin)])
def admin_patch_cafe(cafe_id: str, payload: AdminCafePatch) -> dict[str, Any]:
    data = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else payload.dict(exclude_unset=True)
    if not data:
        return {"id": cafe_id, "updated": False}
    mapping = {"name": "name", "branchName": "branch_name", "address": "address", "latitude": "latitude", "longitude": "longitude", "qrCode": "qr_code", "status": "status", "metadata": "metadata"}
    sets = []
    params = []
    for key, value in data.items():
        sets.append(f"{mapping[key]} = ?")
        params.append(as_json(value) if key == "metadata" else value)
    sets.append("updated_at = ?")
    params.append(now_iso())
    params.append(cafe_id)
    with db() as conn:
        cur = conn.execute(f"UPDATE cafes SET {', '.join(sets)} WHERE id = ?", tuple(params))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="카페를 찾을 수 없습니다.")
    return {"id": cafe_id, "updated": True}


@app.put("/admin/cafes/{cafe_id}/inventory", dependencies=[Depends(require_admin)])
def admin_replace_inventory(cafe_id: str, payload: InventoryReplace) -> dict[str, Any]:
    t = now_iso()
    with db() as conn:
        if not fetch_one(conn, "SELECT id FROM cafes WHERE id = ?", (cafe_id,)):
            raise HTTPException(status_code=404, detail="카페를 찾을 수 없습니다.")
        conn.execute("DELETE FROM cafe_inventory WHERE cafe_id = ?", (cafe_id,))
        for item in payload.items:
            if not fetch_one(conn, "SELECT id FROM games WHERE id = ?", (item.gameId,)):
                raise HTTPException(status_code=404, detail=f"게임을 찾을 수 없습니다: {item.gameId}")
            conn.execute("INSERT INTO cafe_inventory VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (cafe_id, item.gameId, item.shelfLocation, int(item.isAvailable), int(item.temporaryUnavailable), item.popularityScore, int(item.staffPick), t))
    return {"cafeId": cafe_id, "itemCount": len(payload.items), "updatedAt": t}
