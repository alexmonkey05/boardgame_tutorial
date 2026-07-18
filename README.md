# Boardgame Discovery

사진과 게임명 힌트로 보드게임을 식별하고, 전체 보드게임 DB에서 검색·필터·추천을 제공하는 FastAPI 기반 모바일 웹 서비스입니다.

## 핵심 기능

- 보드게임 박스 또는 구성품 이미지 식별
- 게임명, 별칭, 장르, 태그 검색
- 인원수, 플레이 시간, 난이도, 장르 필터
- 검색·조회·인식 확정·추천 클릭 이벤트 기반 개인화
- 게임 상세 정보와 유사 게임 조회
- 게임, 별칭, 관계, 운영 로그를 관리하는 관리자 콘솔
- 원본 이미지 미보관 및 사용자 기록 삭제 API

## 구성

- `main.py`: FastAPI 앱, SQLite 저장소, 추천·인식·관리자 API
- `index.html`: 모바일 사용자 앱
- `admin.html`: 보드게임 마스터 데이터 관리자 콘솔
- `vision_client.py`: 외부 Vision API 클라이언트
- `recognition_service.py`: Vision 후보와 내부 게임 DB 매칭
- `tests/`: API, 개인정보, 배포 계약 테스트
- `docs/index.html`: 정적 배포용 사용자 화면 사본

## 로컬 실행

```powershell
python -m venv .venv
.venv\Scripts\pip.exe install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn main:app --reload
```

접속 주소:

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/admin-ui
http://127.0.0.1:8000/docs
```

## 환경 변수

```text
BOARDGAME_DB_PATH=./boardgame_backend.sqlite3
ADMIN_TOKEN=<strong-secret>
VISION_API_PROVIDER=mock|nvidia
VISION_API_KEY=<provider-key>
VISION_API_ENDPOINT=<chat-completions-endpoint>
VISION_MODEL=<vision-model>
CORS_ALLOWED_ORIGINS=http://127.0.0.1:8000
```

운영 환경에서는 `ADMIN_TOKEN` 기본값을 사용하지 않습니다. 비밀 값은 `.env`나 Railway Variables에만 저장하고 Git에 커밋하지 않습니다.

## 주요 API

게임:

```text
GET /games
GET /games/search
GET /games/{gameId}
GET /games/{gameId}/similar
```

추천과 사용자 신호:

```text
POST /sessions
POST /users
POST /events
GET /users/{userId}/history
POST /users/{userId}/played-games
POST /users/{userId}/hidden-games
DELETE /users/{userId}/data
POST /recommendations
GET /users/{userId}/recommendation-profile
```

이미지 인식:

```text
POST /recognitions
GET /recognitions/{recognitionId}
POST /recognitions/{recognitionId}/confirm
```

관리자:

```text
GET /admin/games
POST /admin/games
PATCH /admin/games/{gameId}
POST /admin/games/{gameId}/aliases
DELETE /admin/games/{gameId}/aliases/{aliasId}
POST /admin/games/{gameId}/relations
DELETE /admin/games/{gameId}/relations/{relationId}
GET /admin/events
GET /admin/recognitions
GET /admin/recommendations
```

모든 관리자 API는 `X-Admin-Token` 헤더가 필요합니다.

## 요청 예시

```powershell
curl "http://127.0.0.1:8000/games?peopleCount=4&maxPlayTime=45&difficulty=easy"

curl -X POST "http://127.0.0.1:8000/recommendations" `
  -H "Content-Type: application/json" `
  -d '{"peopleCount":4,"remainingMinutes":45,"preferredGenres":["strategy"],"limit":5}'

curl -X POST "http://127.0.0.1:8000/recognitions?hint=splendor"
```

이미지 업로드 예시:

```powershell
curl -X POST "http://127.0.0.1:8000/recognitions" `
  -F "image=@box.jpg"
```

지원 형식은 JPEG, PNG, WebP이며 최대 크기는 5MB입니다. 원본 이미지와 썸네일은 로컬 DB에 저장하지 않습니다.

## 관리자 페이지

배포된 관리자 콘솔:

```text
https://boardgametutorial-production.up.railway.app/admin-ui
```

Railway Variables의 `ADMIN_TOKEN`을 입력하면 게임 생성·수정, 별칭·관계 관리, 최근 인식·추천·이벤트 로그 조회가 가능합니다. 토큰은 URL이나 화면 로그에 포함하지 않고 브라우저 `sessionStorage`에만 보관합니다.

## 데이터 호환 정책

새 DB에는 게임 마스터와 사용자 신호 관련 테이블만 생성합니다. 이전 운영 DB에 남아 있는 `cafes`, `cafe_inventory` 및 레거시 열은 배포 과정에서 자동 삭제하지 않습니다. 데이터 백업 전까지 물리적으로 보존하되 활성 API, 추천, 인식, 사용자 화면, 관리자 화면에서는 읽거나 노출하지 않습니다.

## 테스트

```powershell
.venv\Scripts\python.exe -m pytest -q
```

현재 기준: `22 passed`.

## Railway

- 시작 명령: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Healthcheck: `/health`
- Volume mount: `/app/data`
- DB 경로: `/app/data/boardgame_backend.sqlite3`
- 공개 URL: `https://boardgametutorial-production.up.railway.app`

배포 절차와 검증 명령은 `RAILWAY_DEPLOYMENT.md`를 참고합니다.
