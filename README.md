# Boardgame Cafe Tutorial MVP

FastAPI 백엔드와 모바일 우선 `index.html` 프로토타입으로 구성된 보드게임 카페 도우미 MVP입니다.

## 실행

```bash
pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn main:app --reload
```

Windows에서 이 작업 환경은 로컬 `python` 명령이 PATH에 없을 수 있으므로 프로젝트 `.venv`의 Python을 기준으로 확인했습니다.

FastAPI가 `index.html`도 함께 서빙하므로 로컬에서는 아래 주소로 앱과 API를 한 번에 확인할 수 있습니다.

```text
http://127.0.0.1:8000/
```

## GitHub Pages 배포

GitHub Pages는 정적 파일만 실행할 수 있으므로 FastAPI 백엔드는 Pages에서 실행되지 않습니다. Pages에는 프론트엔드만 배포하고, 실제 NVIDIA 인식/추천 API를 휴대폰에서 쓰려면 백엔드는 별도 HTTPS 주소로 배포해야 합니다.

현재 Pages용 정적 파일은 `docs/`에 둡니다.

```text
docs/
  index.html
  .nojekyll
```

GitHub 저장소 설정에서 다음처럼 지정하세요.

1. `Settings` > `Pages`
2. `Build and deployment`에서 `Deploy from a branch`
3. Branch는 `main`
4. Folder는 `/docs`
5. 저장 후 Pages URL 접속

GitHub Pages의 메인 파일은 `docs/index.html`입니다. 루트의 `index.html`은 로컬 개발용 원본으로 두고, Pages는 `/docs/index.html`을 엽니다.

백엔드가 별도 HTTPS 주소에 배포되어 있다면 Pages URL 뒤에 `apiBase`를 붙여 테스트할 수 있습니다.

```text
https://사용자명.github.io/저장소명/?apiBase=https://백엔드주소
```

백엔드가 아직 배포되지 않은 상태라면 휴대폰에서는 샘플 fallback UI만 확인할 수 있습니다. `http://127.0.0.1:8000`은 휴대폰 자기 자신을 가리키므로 PC에서 실행 중인 로컬 FastAPI 서버에 연결되지 않습니다.

## 내 PC를 백엔드 서버로 쓰기

현재 PC의 `25565` 포트가 외부에서 접근 가능하다면 FastAPI를 해당 포트로 실행할 수 있습니다.

```bash
.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 25565
```

로컬에서 먼저 확인합니다.

```bash
curl http://127.0.0.1:25565/health
```

휴대폰이 같은 Wi-Fi에 있다면 PC의 내부 IP로 확인할 수 있습니다.

```text
http://PC내부IP:25565/health
```

외부망에서 확인하려면 공유기 포트포워딩, Windows 방화벽 인바운드 허용, 공인 IP 또는 도메인 연결이 필요합니다.

중요: GitHub Pages는 HTTPS로 열리므로 Pages 프론트에서 `http://공인IP:25565` 백엔드를 호출하면 브라우저 mixed content 정책으로 막힐 수 있습니다. Pages와 함께 실제 API를 쓰려면 다음 중 하나가 필요합니다.

- 유효한 인증서가 붙은 `https://도메인:25565`
- Cloudflare Tunnel, ngrok 같은 HTTPS 터널
- 별도 HTTPS 백엔드 배포

HTTPS 백엔드가 준비되면 Pages URL에 다음처럼 붙입니다.

```text
https://사용자명.github.io/저장소명/?apiBase=https://도메인:25565
```

`http://공인IP:25565`는 API 직접 확인에는 쓸 수 있지만, GitHub Pages HTTPS 프론트와 연결하는 최종 주소로는 권장하지 않습니다.

## 환경 변수

`.env`에 다음 값을 설정합니다. 실제 값은 문서, 로그, 테스트 출력에 남기지 않습니다.

- `VISION_API_PROVIDER`
- `VISION_API_KEY`
- `VISION_API_ENDPOINT`
- `VISION_MODEL`

선택 값:

- `ADMIN_TOKEN`
- `BOARDGAME_DB_PATH`

## 테스트

```bash
.venv\Scripts\python.exe -m pytest
```

현재 자동 테스트는 통과하며, Starlette/FastAPI TestClient의 `httpx` 관련 deprecation 경고가 남아 있습니다. 앱 동작에는 영향을 주지 않는 경고로 문서화하고 추후 의존성 업데이트 때 정리합니다.

실제 NVIDIA Vision 스모크 테스트는 기본 테스트에 포함하지 않습니다. 필요한 경우 아래 스크립트를 수동으로 실행합니다.

```bash
.venv\Scripts\python.exe scripts\smoke_nvidia_recognition.py
```

이 스크립트는 개인정보가 없는 임시 테스트 이미지를 만들고 삭제하며, API 키나 원본 응답 대신 요약만 출력합니다.

## 이미지 업로드 제한

- 최대 크기: 5MB
- 허용 MIME: `image/jpeg`, `image/png`, `image/webp`
- 빈 파일과 허용되지 않은 MIME은 400 응답으로 거부합니다.
- 원본 이미지는 로컬 디스크나 DB에 저장하지 않습니다.

## 주요 확인 API

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/meta/schema
curl http://127.0.0.1:8000/games
curl http://127.0.0.1:8000/cafes/cafe-hongdae/games
curl -X POST "http://127.0.0.1:8000/recognitions?cafeId=cafe-hongdae&hint=splendor"
```

## 운영 전 보안 체크리스트

- 운영 환경에서는 `ADMIN_TOKEN=dev-admin-token` 기본값을 사용하지 않습니다.
- CORS `allow_origins=["*"]`는 배포 도메인이 정해진 뒤 명시 도메인으로 제한합니다.
- `BOARDGAME_DB_PATH`와 SQLite 백업 위치를 운영 환경에 맞게 분리합니다.
- 외부 Vision API 장애 시에는 기존 힌트 기반 fallback과 사용자 친화적 안내를 유지합니다.
- `.env`, SQLite DB, 원본 이미지, 로그 파일은 저장소에 포함하지 않습니다.
- 트래픽이 늘어나면 API rate limit과 요청 크기 제한을 프록시 또는 ASGI 미들웨어에서 추가합니다.

## Railway 배포

자세한 절차는 `RAILWAY_DEPLOYMENT.md`를 따릅니다.

핵심 설정:

- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Volume mount path: `/app/data`
- Service variable: `BOARDGAME_DB_PATH=/app/data/boardgame_backend.sqlite3`
- Healthcheck path: `/health`

## 관리자 페이지

FastAPI 서버가 같은 origin에서 관리자 콘솔을 제공합니다.

```text
http://127.0.0.1:8000/admin-ui
https://boardgametutorial-production.up.railway.app/admin-ui
```

관리자 페이지는 `ADMIN_TOKEN` 값을 직접 입력해 사용합니다. 토큰은 URL, 코드, 콘솔 출력에 넣지 않고 브라우저 `sessionStorage`에만 보관하며, 관리자 API 요청에는 `X-Admin-Token` 헤더로만 전송합니다. 로그아웃을 누르면 저장된 토큰이 지워집니다.

관리자 콘솔에서 가능한 작업:

- 상태 확인: `/health`, `/meta/schema`, 이미지 인식 설정 여부, DB 경로, 테이블 목록 확인
- 게임 관리: 게임 목록 조회, 검색, 생성, 수정, 별칭 추가 및 삭제
- 카페 관리: 카페 목록 조회, 생성, 수정
- 재고 관리: 카페별 보유 게임 조회, 선반 위치/대여 가능/일시 제외/직원 추천/인기도 수정, 전체 교체 저장 전 확인 모달
- 로그 확인: 최근 이벤트, 인식, 추천 로그 요약 확인

추가된 관리자 API:

```text
GET /admin/games
GET /admin/cafes
GET /admin/cafes/{cafeId}/inventory
POST /admin/games/{gameId}/aliases
DELETE /admin/games/{gameId}/aliases/{aliasId}
GET /admin/events
GET /admin/recognitions
GET /admin/recommendations
```

관리자 로그 API는 관리자 토큰, NVIDIA API 키, 이미지 base64, 외부 Vision API 원문 응답을 반환하지 않습니다.
