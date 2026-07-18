# 프로젝트 상태 요약

## 현재 목표

이 서비스는 특정 장소의 보유 목록을 판단하는 도구가 아니라, 보드게임 자체를 식별하고 검색·추천하는 서비스입니다.

사용자는 다음 흐름을 이용합니다.

1. 사진 또는 게임명 힌트로 보드게임을 식별합니다.
2. 게임의 설명, 규칙 요약, 인원수, 시간, 난이도, 장르와 태그를 확인합니다.
3. 전체 보드게임 DB를 검색하고 조건으로 필터링합니다.
4. 최근 검색·조회·인식·추천 반응과 플레이 기록을 바탕으로 다음 게임을 추천받습니다.
5. 유사 게임 관계를 따라 다른 게임을 탐색합니다.

## 구현 상태

### 백엔드

- `main.py`가 FastAPI 앱과 SQLite 저장소를 제공합니다.
- 게임 목록, 검색, 상세, 유사 게임 API가 전체 게임 DB를 기준으로 동작합니다.
- 추천 API는 인원, 시간, 난이도, 분위기, 선호 장르와 사용자 이벤트 신호를 반영합니다.
- 인식 API는 외부 Vision 결과를 게임명·별칭과 매칭하며 위치 기반 입력이나 응답 필드가 없습니다.
- 사용자 이벤트, 플레이 기록, 숨김 게임, 추천 로그, 인식 로그와 데이터 삭제를 지원합니다.
- 관리자 API는 게임, 별칭, 게임 관계, 이미지 권리 메타데이터, 데이터 품질과 운영 로그를 관리합니다.
- 추천과 인식 공개 API에는 메모리 기반 분당 rate limit이 적용됩니다.
- 모든 HTTP 응답에 요청 ID와 처리 시간이 포함되고 `/ready`가 DB 준비 상태를 확인합니다.

### 사용자 화면

- `index.html`과 `docs/index.html`은 홈, 스캔, 추천, 게임 목록, 상세 화면을 제공합니다.
- 게임 목록은 검색, 인원수, 플레이 시간, 난이도, 장르와 특성 토글을 지원합니다.
- 상세 화면은 규칙 요약과 유사 게임을 보여줍니다.
- API 연결 상태와 익명 세션을 같은 origin에서 관리합니다.

### 관리자 화면

- `/admin-ui`에서 `admin.html`을 제공합니다.
- `ADMIN_TOKEN` 기반 인증을 사용합니다.
- 게임 생성·수정, 별칭 추가·삭제, 게임 관계 추가·삭제를 지원합니다.
- 이미지 URL, 출처, 라이선스와 대체 텍스트를 함께 관리합니다.
- CSV 미리보기·오류 행·diff 확인, 전체 검증 적용 또는 유효 행 적용과 CSV 내보내기를 지원합니다.
- 중복 이름, 별칭 충돌, 관계 오류와 이미지 라이선스 경고를 품질 탭에서 확인합니다.
- 최근 인식, 추천, 사용자 이벤트와 관리자 감사 로그의 민감값 없는 요약을 조회합니다.

### 개인정보와 이미지

- 원본 이미지와 썸네일을 SQLite에 저장하지 않습니다.
- 인식 후보, 신뢰도, 확정 결과만 보관합니다.
- 외부 Vision 공급자를 사용할 때만 업로드 이미지를 공급자 API로 전송합니다.
- `DELETE /users/{userId}/data`로 사용자 또는 익명 세션 관련 기록을 삭제할 수 있습니다.
- 관리자 응답에는 토큰, Vision API 키, 이미지 base64, 외부 API 원문 응답이 포함되지 않습니다.

## 데이터 모델

활성 테이블:

- `games`
- `game_aliases`
- `game_relations`
- `users`
- `anonymous_sessions`
- `user_events`
- `played_games`
- `hidden_games`
- `recognition_jobs`
- `recognition_candidates`
- `recommendation_logs`
- `admin_users`
- `admin_imports`
- `admin_audit_events`

이전 운영 DB의 `cafes`, `cafe_inventory`와 관련 레거시 열은 안전한 백업 전까지 자동 삭제하지 않습니다. 새 코드에서는 해당 데이터를 읽거나 노출하지 않습니다.

## 검증 상태

- Python 컴파일 검사 통과
- 자동 테스트 `.venv\Scripts\python.exe -m pytest -q` 기준 `29 passed`, Starlette TestClient/httpx deprecation 경고 1개
- 관리자 인증 누락·오류 `401` 검증
- 제거된 공개·관리자 경로 `404` 및 OpenAPI 비노출 검증
- 추천과 인식 요청이 `cafeId` 없이 동작함을 검증
- 추천·인식 응답에서 위치·보유 관련 필드가 제거됐음을 검증
- 사용자 화면과 관리자 화면에 제거 대상 문구가 없음을 검증
- 전체 게임 DB 필터와 게임 관계 관리 API를 검증
- CSV 정상·오류·별칭 충돌, preview 없는 적용 거부와 재적용 거부 검증
- 이미지 메타데이터 동시 관리와 전역 별칭 충돌 거부 검증
- rate limit 경계, 요청 ID, readiness와 관측성 인증 검증
- SQLite 백업·복원 리허설과 PostgreSQL dry-run 행 수·외래키·JSON 검증
- 코드에 남은 카페 관련 문자열은 레거시 DB 호환, 제거 검증 테스트, 과거 방향 문서에 한정됨을 확인

## 데이터 운영 리허설

- SQLite 운영 DB의 로컬 사본을 backup API로 백업·복원했습니다.
- 원본, 백업, 복원본의 무결성과 모든 테이블 행 수가 일치했습니다.
- 레거시 테이블은 복원본에도 그대로 보존됐습니다.
- PostgreSQL dry-run에서 활성 14개 테이블, 외래키 오류 0개, JSON 오류 0개를 확인했습니다.
- 실제 Railway Volume 백업, PostgreSQL 적용과 레거시 데이터 삭제는 수행하지 않았습니다.

## 배포

- Railway 서비스 URL: `https://boardgametutorial-production.up.railway.app`
- 관리자 URL: `https://boardgametutorial-production.up.railway.app/admin-ui`
- Healthcheck: `/health`
- Readiness: `/ready`
- Volume DB: `/app/data/boardgame_backend.sqlite3`
- CORS는 Railway origin으로 제한합니다.

배포 후 `/health`, `/ready`, `/games`, `/recommendations`, `/recognitions`, `/admin-ui`, 데이터 품질과 OpenAPI 계약을 다시 확인해야 합니다.
