# 보드게임 식별·추천 백엔드 구축 프롬프트

당신은 FastAPI, SQLite 또는 PostgreSQL, 이미지 인식 API와 추천 시스템을 설계하는 백엔드 개발자입니다.

## 목표

보드게임 마스터 DB를 기반으로 검색, 필터, 상세, 유사 게임, 이미지 식별, 사용자 신호 기반 추천과 관리자 품질 관리를 제공합니다.

## 핵심 테이블

- `games`: 이름, 설명, 규칙, 인원, 시간, 난이도, 장르, 태그, 특성과 이미지 권리 메타데이터
- `game_aliases`: 한글·영문·통칭·오탈자 별칭
- `game_relations`: 유사 게임과 대안 관계
- `users`, `anonymous_sessions`
- `user_events`, `played_games`, `hidden_games`
- `recognition_jobs`, `recognition_candidates`
- `recommendation_logs`
- `admin_users`
- `admin_imports`, `admin_audit_events`

## 공개 API

```text
GET /health
GET /ready
GET /meta/schema
GET /games
GET /games/search
GET /games/{gameId}
GET /games/{gameId}/similar
POST /sessions
POST /users
POST /events
GET /users/{userId}/history
POST /users/{userId}/played-games
POST /users/{userId}/hidden-games
DELETE /users/{userId}/data
POST /recommendations
GET /users/{userId}/recommendation-profile
POST /recognitions
GET /recognitions/{recognitionId}
POST /recognitions/{recognitionId}/confirm
```

## 관리자 API

모든 요청은 `X-Admin-Token` 헤더를 요구합니다.

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
GET /admin/data-quality
POST /admin/imports/games/preview
POST /admin/imports/games/apply
GET /admin/exports/games.csv
GET /admin/exports/aliases.csv
GET /admin/audit-events
GET /admin/observability
```

## 추천 계약

입력은 `userId`, `sessionId`, `peopleCount`, `remainingMinutes`, `mood`, `preferredDifficulty`, `preferredGenres`, `excludeGameIds`, `previouslyPlayedGameIds`, `limit`을 중심으로 구성합니다.

점수에는 인원, 시간, 난이도, 장르, 분위기, 사용자 이벤트, 플레이·숨김 기록을 반영합니다. 각 결과는 `game`, `score`, `priority`, `reasons`를 제공합니다.

## 인식 계약

이미지와 선택적 `hint`, `userId`, `sessionId`를 받습니다. 응답은 `recognitionId`, `topCandidate`, `candidates`, `unmatchedCandidates`, `needsRetake`, `message`, `imageRetention`, `externalProcessing`으로 구성합니다.

후보에는 `game`, `nvidiaConfidence`, `matchScore`, `confidence`, `needsRetake`, `message`, `evidence`를 사용할 수 있습니다.

## 보안과 개인정보

- 비밀 값은 환경 변수로만 주입합니다.
- 원본 이미지와 base64를 로그나 DB에 저장하지 않습니다.
- 관리자 로그는 외부 API 원문과 토큰을 반환하지 않습니다.
- 업로드 형식과 5MB 크기 제한을 검증합니다.
- 사용자 기록 삭제를 트랜잭션으로 처리합니다.
- 추천과 인식에 사용자 친화적인 rate limit을 적용합니다.
- 요청 ID, 처리 시간, 상태 코드와 Vision 결과를 구조화하되 입력 원문은 로그에 남기지 않습니다.
- CSV 원본은 저장하지 않고 짧은 수명의 검증 결과만 한 번 적용합니다.

## 테스트

- 게임 검색·필터와 유사 게임
- 추천 입력과 결과 필드
- Vision 성공, fallback, 미매칭, 파일 검증
- 관리자 토큰과 게임·별칭·관계 CRUD
- 민감값 비노출과 사용자 기록 삭제
- CSV 정상·오류·중복·충돌, preview 없는 적용 거부
- 품질 규칙, 감사 로그, rate limit 경계와 readiness
- SQLite 백업 복원과 PostgreSQL dry-run 행 수·외래키·JSON 검증
- 제거된 레거시 경로의 OpenAPI 비노출
