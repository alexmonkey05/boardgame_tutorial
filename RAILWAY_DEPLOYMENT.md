# Railway 배포 절차

이 프로젝트는 사용자 웹앱, 관리자 콘솔과 FastAPI를 하나의 Railway 서비스로 배포합니다.

## 1. 로컬 검증

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m py_compile main.py recognition_service.py vision_client.py
.venv\Scripts\python.exe -m uvicorn main:app --reload
```

```powershell
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/meta/schema
curl http://127.0.0.1:8000/games
```

## 2. GitHub 배포 소스

```text
https://github.com/alexmonkey05/boardgame_tutorial
```

Railway 서비스는 `main` 브랜치를 사용합니다.

## 3. 시작 명령과 Healthcheck

Start Command:

```text
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Healthcheck path:

```text
/health
```

## 4. SQLite Volume

Volume mount:

```text
/app/data
```

서비스 변수:

```text
BOARDGAME_DB_PATH=/app/data/boardgame_backend.sqlite3
```

SQLite를 사용하는 동안 서비스 replica는 1개로 유지합니다. 다중 인스턴스가 필요하면 PostgreSQL로 전환합니다.

기존 Volume DB에는 이전 방향의 레거시 테이블과 열이 남아 있을 수 있습니다. 새 애플리케이션은 이를 사용하거나 노출하지 않지만 자동 삭제도 하지 않습니다. 물리적 정리는 Volume 백업과 복원 테스트가 준비된 뒤 별도 마이그레이션으로 진행합니다.

## 5. 서비스 변수

```text
BOARDGAME_DB_PATH=/app/data/boardgame_backend.sqlite3
ADMIN_TOKEN=<strong-production-secret>
CORS_ALLOWED_ORIGINS=https://boardgametutorial-production.up.railway.app
VISION_API_PROVIDER=nvidia
VISION_API_KEY=<provider-key>
VISION_API_ENDPOINT=<chat-completions-endpoint>
VISION_MODEL=<vision-model>
```

외부 이미지 인식 없이 동작을 확인하려면 다음 값을 사용합니다.

```text
VISION_API_PROVIDER=mock
```

`.env`, SQLite 파일, 토큰과 API 키를 Git에 커밋하지 않습니다.

## 6. 공개 주소

```text
https://boardgametutorial-production.up.railway.app
```

관리자 콘솔:

```text
https://boardgametutorial-production.up.railway.app/admin-ui
```

## 7. 배포 후 API 검증

```powershell
$base = 'https://boardgametutorial-production.up.railway.app'

Invoke-RestMethod "$base/health"
Invoke-RestMethod "$base/meta/schema"
Invoke-RestMethod "$base/games?peopleCount=4&maxPlayTime=45"

Invoke-RestMethod "$base/recommendations" `
  -Method Post `
  -ContentType 'application/json' `
  -Body '{"peopleCount":4,"remainingMinutes":45,"preferredGenres":["strategy"],"limit":4}'

Invoke-RestMethod "$base/recognitions?hint=splendor" -Method Post
```

확인할 계약:

- `/meta/schema`의 활성 테이블 목록은 게임 마스터와 사용자 신호 테이블만 포함합니다.
- `/recommendations` 요청에 위치 식별자가 필요하지 않습니다.
- `/recognitions` 요청에 위치 식별자가 필요하지 않습니다.
- 추천과 인식 응답에 보유 여부나 위치 필드가 없습니다.
- 제거된 레거시 공개·관리자 경로는 `404`입니다.

## 8. 브라우저 검증

- `/`에서 홈, 스캔, 추천, 게임 목록이 열립니다.
- 게임 목록의 검색과 필터가 동작합니다.
- 게임 상세에서 규칙 요약과 유사 게임을 확인할 수 있습니다.
- 이미지 또는 텍스트 힌트 인식 후 후보를 확정할 수 있습니다.
- `/admin-ui`에서 게임, 별칭, 관계와 로그를 관리할 수 있습니다.
- 모바일 폭에서 텍스트와 조작 요소가 겹치지 않습니다.

## 9. 운영 점검

- Volume 백업과 복원 가능 여부 확인
- `ADMIN_TOKEN` 강도와 노출 여부 확인
- CORS origin 제한 확인
- Vision 실패 시 fallback 확인
- 이미지 업로드 크기 제한 확인
- 공개 API rate limit 도입 검토
- PostgreSQL 전환 전 마이그레이션 리허설

## 10. 장애 확인

앱이 열리지 않으면 Start Command가 `0.0.0.0:$PORT`에 바인딩하는지 확인합니다.

DB 데이터가 유지되지 않으면 `/health`의 `database`가 `/app/data/boardgame_backend.sqlite3`인지 확인합니다.

이미지 인식이 fallback만 사용하면 `/health`의 `imageRecognition` 설정 여부와 Railway Variables를 확인합니다. API 응답은 실제 키나 endpoint 값을 노출하지 않습니다.
