# SUMMARY

## 관리자 페이지 최신 상태

- `admin.html`: FastAPI가 `/admin-ui`와 `/admin-ui/`에서 제공하는 운영자용 단일 파일 관리자 콘솔입니다. 관리자 토큰 입력, 로그아웃, 상태/게임/카페/재고/로그 탭, 게임 생성/수정, 별칭 추가/삭제, 카페 생성/수정, 카페별 재고 전체 교체 확인 모달을 포함합니다.
- `main.py`: `/admin-ui` 정적 라우트와 관리자 조회 API를 추가했습니다. 추가된 API는 `GET /admin/games`, `GET /admin/cafes`, `GET /admin/cafes/{cafeId}/inventory`, `POST /admin/games/{gameId}/aliases`, `DELETE /admin/games/{gameId}/aliases/{aliasId}`, `GET /admin/events`, `GET /admin/recognitions`, `GET /admin/recommendations`입니다.
- `tests/test_admin.py`: 관리자 토큰 누락/오류 401, 관리자 페이지 정적 라우트, 게임 생성/수정/별칭, 카페 생성/수정, 재고 전체 교체, 존재하지 않는 재고 게임 404, 로그 API 민감값 비노출을 검증합니다.
- 관리자 페이지는 `ADMIN_TOKEN`을 URL이나 코드에 넣지 않고 `sessionStorage`에만 보관하며, 요청마다 `X-Admin-Token` 헤더로 보냅니다. 관리자 로그 API는 토큰, NVIDIA API 키, 이미지 base64, 외부 Vision API 원문 응답을 반환하지 않는 요약 응답만 제공합니다.
- 최신 테스트 기준은 `.venv\Scripts\python.exe -m pytest -q` 21개 통과, Starlette TestClient/httpx deprecation 경고 1개입니다.

## 파일 맵

- `AI_APP_GOAL_PROMPT.md`: 보드게임 카페 모바일 앱을 기획하기 위해 AI에게 전달할 목표 중심 프롬프트 문서입니다.
- `.env`: 외부 이미지 인식/AI API 연동을 위한 환경 변수 설정 파일입니다. `VISION_API_KEY` 등 실제 키 값은 비워두고 사용자가 직접 채웁니다.
- `.gitignore`: `.env`, SQLite DB 파일, Python 캐시 파일, 로컬 `.venv`, pytest 캐시, 로그 파일이 저장소에 섞이지 않도록 제외합니다.
- `ADMIN_PAGE_PROMPT.md`: 운영자가 DB 데이터를 안전하게 관리할 수 있는 관리자 페이지를 만들기 위한 목표, 화면 구성, 인증, API, 테스트 전략 프롬프트 문서입니다.
- `BACKEND_BUILD_PROMPT.md`: 보드게임 카페 앱의 백엔드 구축을 위해 AI에게 전달할 데이터 모델, API, 이미지 인식, 추천, 관리자 기능 중심 프롬프트 문서입니다.
- `docs/index.html`: GitHub Pages 배포용 정적 프론트엔드 진입 파일입니다. GitHub Pages 설정에서 `/docs` 폴더를 선택하면 이 파일이 메인으로 열립니다.
- `docs/.nojekyll`: GitHub Pages가 Jekyll 처리를 하지 않고 정적 파일을 그대로 제공하도록 하는 빈 파일입니다.
- `index.html`: 보드게임 카페 현장에서 바로 쓰는 모바일 우선 웹앱 프로토타입입니다. 스캔 탭, 카페 목록, 카페 보유 게임 검색/필터, 추천 탭, 게임 상세 화면이 백엔드 API를 우선 사용하고 실패 시 샘플 데이터로 fallback합니다. 익명 세션을 생성해 추천/상세/인식 확정 이벤트에 전달하고, 카메라 인식 시뮬레이션 fallback과 제품 기획 요약 모달도 유지합니다.
- `main.py`: FastAPI 기반 백엔드 MVP 진입점입니다. `.env` 로드, CORS, 헬스체크, SQLite 스키마 생성, 샘플 데이터 시드, 게임/카페/검색/정렬/추천/사용자 이벤트/익명 세션/선택 사용자 생성/기록 삭제/이미지 인식 API/관리자 API를 제공합니다.
- `vision_client.py`: NVIDIA/OpenAI-compatible Vision API 요청 payload 생성, 이미지 base64 변환, HTTP 호출, 타임아웃 및 오류 분류를 담당합니다.
- `recognition_service.py`: 외부 Vision 응답 JSON 파싱, 비정상 응답 fallback, 내부 `games`/`game_aliases` 매칭, 최종 confidence 계산을 담당합니다.
- `NEXT_WORK_PROMPT.md`: 현재 진행도 기준으로 GitHub Pages 배포 확인, 휴대폰 브라우저 테스트, 백엔드 HTTPS 연결 전략, Pages용 프론트 설정 정리를 다음 작업으로 넘기기 위한 프롬프트 문서입니다.
- `requirements.txt`: FastAPI, Uvicorn, 파일 업로드 처리용 python-multipart, `.env` 로드용 python-dotenv, NVIDIA 호출용 httpx, 테스트용 pytest 등 백엔드 실행과 검증에 필요한 Python 의존성 목록입니다.
- `tests/test_recognition.py`: 인식 fallback, NVIDIA payload, 응답 파싱, 내부 DB 매칭, 카페 404, 이미지 기반 NVIDIA 호출 경로를 검증합니다.
- `tests/test_privacy.py`: 원본 이미지 미저장, 사용자 데이터 삭제 시 인식 로그 정리, health/schema의 비밀 값 비노출을 검증합니다.
- `tests/test_recommendations.py`: 존재하지 않는 카페에 대한 추천 API 404를 검증합니다.
- `scripts/smoke_nvidia_recognition.py`: 개인정보가 없는 임시 테스트 이미지를 생성해 실제 NVIDIA Vision 호출과 `POST /recognitions` 경유 처리를 확인하고, 키/원본 응답 없이 요약만 출력하는 수동 스모크 테스트 스크립트입니다.
- `README.md`: 실행 방법, GitHub Pages 배포 방법, 환경 변수, 테스트 방법, 이미지 업로드 제한, 주요 API 예시, 운영 전 보안 체크리스트를 정리한 빠른 시작 문서입니다.
- `RAILWAY_DEPLOYMENT.md`: Railway 단일 FastAPI 서비스 배포, Volume 기반 SQLite, 서비스 변수, 헬스체크, 배포 검증 절차를 정리한 매뉴얼입니다.
- `SUMMARY.md`: 프로젝트 파일 구조와 각 파일의 책임, 실행 방법, 데이터 흐름을 요약합니다.

## 프로젝트 요약

이 프로젝트는 보드게임 카페에서 사용자가 게임 선택, 보드게임 식별, 매장 보유 게임 확인을 쉽게 할 수 있는 모바일 앱을 기획하고 실행 가능한 프로토타입과 백엔드 MVP로 확인하기 위한 작업입니다.

현재 핵심 아이디어는 다음과 같습니다.

- 카메라로 보드게임을 촬영해 어떤 게임인지 식별합니다.
- 보드게임 상세 설명 데이터는 서버에 저장하고, 앱은 식별 결과를 기반으로 서버 데이터를 불러옵니다.
- 사용자의 이전 플레이, 검색, 조회, 추천 클릭 기록을 바탕으로 새로운 보드게임을 추천합니다.
- 현재 사용자가 있는 보드게임 카페의 보유 게임 목록을 확인하고 필터링 및 정렬할 수 있습니다.
- 프로토타입은 샘플 서버 데이터를 내장해 빌드 과정 없이 `index.html`을 브라우저에서 직접 열어 실행할 수 있습니다.
- 백엔드 MVP는 `main.py`를 진입점으로 실행되며 SQLite 로컬 데이터베이스에 게임, 별칭, 관계, 카페, 보유 목록, 익명 세션, 선택 사용자, 이벤트, 플레이/숨김 기록, 인식 작업, 추천 로그, 관리자 계정을 저장합니다.
- `.env`에는 NVIDIA API 연동에 필요한 `VISION_API_PROVIDER`, `VISION_API_KEY`, `VISION_API_ENDPOINT`, `VISION_MODEL` 값이 사용자가 채운 상태입니다.
- 프로젝트 `.venv` 기준으로 `pytest` 테스트 13개가 재통과했으며, Starlette TestClient/httpx deprecation 경고 1개가 남아 있습니다.
- 실제 NVIDIA Vision 스모크 테스트는 1회 성공했습니다. 임시 테스트 이미지 기준으로 `externalProcessing.used=true`, provider `nvidia`, top candidate `splendor`, 후보 1개, 미매칭 0개, `needsRetake=false`를 확인했습니다.
- 브라우저 검증에서 홈 API 연결, 익명 세션 상태 표시, 스캔 힌트 인식, 후보 확정, 추천 탭, 카페 게임 검색, 상세 화면이 정상 동작하고 콘솔 에러가 없음을 확인했습니다. 추천 클릭과 상세 조회 이벤트가 같은 익명 세션으로 저장되는 것도 DB에서 확인했습니다.
- GitHub Pages 배포 소스는 `/docs` 폴더이며, 메인 파일은 `docs/index.html`입니다. Pages는 정적 파일만 제공하므로 휴대폰에서 실제 API 기능을 쓰려면 FastAPI 백엔드를 별도 HTTPS 주소로 배포하거나 HTTPS 터널로 노출해야 합니다.
- 사용자의 PC에서 `25565` 포트가 열려 있으므로 FastAPI를 `--host 0.0.0.0 --port 25565`로 실행해 PC를 백엔드 서버처럼 사용할 수 있습니다. 다만 GitHub Pages 프론트와 연결하려면 mixed content 차단을 피하기 위해 `https://도메인:25565` 또는 HTTPS 터널이 필요합니다.
- Railway 단일 서비스 배포를 위해 FastAPI가 `/`에서 `index.html`을 서빙하고, 프론트 기본 API URL은 같은 origin을 사용하도록 준비되었습니다.

## 백엔드 실행 방법

1. 의존성을 설치합니다.

```bash
pip install -r requirements.txt
```

2. 개발 서버를 실행합니다.

```bash
uvicorn main:app --reload
```

3. 상태를 확인합니다.

```bash
curl http://127.0.0.1:8000/health
```

FastAPI가 프론트도 함께 서빙하므로 Railway 방식의 단일 앱은 `http://127.0.0.1:8000/`에서 확인할 수 있습니다.

테스트는 다음 명령으로 실행합니다.

```bash
.venv\Scripts\python.exe -m pytest
```

실제 NVIDIA 스모크 테스트는 기본 자동 테스트에 포함하지 않고 필요 시 수동 실행합니다.

```bash
.venv\Scripts\python.exe scripts\smoke_nvidia_recognition.py
```

기본 SQLite 파일은 `./boardgame_backend.sqlite3`에 생성됩니다. 경로를 바꾸려면 `BOARDGAME_DB_PATH` 환경 변수를 사용합니다. 관리자 API 기본 토큰은 `dev-admin-token`이며, 운영 환경에서는 `ADMIN_TOKEN` 환경 변수로 변경해야 합니다.
외부 이미지 인식 또는 AI API를 연결하려면 `.env`의 `VISION_API_PROVIDER`, `VISION_API_KEY`, `VISION_API_ENDPOINT`, `VISION_MODEL` 값을 사용합니다. 현재 이 NVIDIA API 관련 값들은 사용자가 채운 상태이며, `main.py`와 `vision_client.py`는 python-dotenv로 이를 로드합니다. health/schema 응답은 실제 값이 아니라 설정 여부만 반환하고, 실제 키 값은 문서나 로그에 기록하지 않습니다.

## 주요 API 책임

- `GET /health`: 서버, DB, 시드 데이터, 개인정보 및 이미지 보관 정책 메타데이터와 이미지 인식 API 설정 여부를 반환합니다.
- `GET /meta/schema`: 구현된 테이블, 빠른 조회 대상, 개인정보/이미지 보관 정책, 이미지 인식 API 설정 상태를 반환합니다.
- `GET /games`, `GET /games/search`, `GET /games/{gameId}`, `GET /games/{gameId}/similar`: 게임 목록, 검색, 상세, 유사 게임을 제공합니다.
- `GET /cafes/nearby`, `GET /cafes/{cafeId}`, `GET /cafes/by-qr/{qrCode}`, `GET /cafes/{cafeId}/games`: 카페 탐색, QR 기반 카페 식별, 카페별 보유 게임 목록을 제공합니다.
- `GET /cafes/{cafeId}/games`: 인원수, 최대 플레이 시간, 난이도, 장르, 태그, 대여 가능 여부, 검색어 필터를 지원하며 `sort=popularity|name|playTime|difficulty|availability` 정렬 옵션을 제공합니다.
- `POST /sessions`: 로그인 없이 사용할 수 있는 익명 세션을 생성합니다.
- `POST /users`: 선택 로그인 또는 기기 변경 이전을 위한 사용자 레코드를 만들고, 필요하면 기존 익명 세션 이벤트/인식/추천 로그를 사용자에 연결합니다.
- `POST /events`, `GET /users/{userId}/history`, `POST /users/{userId}/played-games`, `POST /users/{userId}/hidden-games`: 검색, 조회, 추천 클릭, 플레이 완료, 관심 없음 같은 사용자 행동 기록을 저장하고 조회합니다.
- `DELETE /users/{userId}/data`: 익명 세션 ID 또는 사용자 ID 기준으로 이벤트, 플레이/숨김 기록, 인식 작업, 추천 로그, 세션, 사용자 레코드를 삭제합니다.
- `POST /recommendations`, `GET /users/{userId}/recommendation-profile`: 현재 카페 보유 게임을 우선으로 추천 점수를 계산하고, 저장된 검색/조회/추천 클릭/인식 확정 이벤트와 플레이/숨김 기록을 반영해 사람이 이해하기 쉬운 한국어 추천 이유를 반환합니다.
- `POST /recognitions`, `GET /recognitions/{recognitionId}`, `POST /recognitions/{recognitionId}/confirm`: 원본 이미지를 저장하지 않고, 이미지가 있고 NVIDIA 설정이 준비된 경우 외부 Vision API 호출을 시도합니다. 성공하면 외부 후보를 내부 게임 DB와 매칭해 저장하고, 실패하거나 설정이 없으면 기존 힌트/파일명 기반 fallback 후보를 저장합니다. 이미지와 힌트가 모두 없으면 후보를 임의 생성하지 않고 재촬영 또는 입력 필요 상태를 반환합니다.
- `POST /admin/games`, `PATCH /admin/games/{gameId}`, `POST /admin/cafes`, `PATCH /admin/cafes/{cafeId}`, `PUT /admin/cafes/{cafeId}/inventory`: 관리자 토큰 기반으로 게임, 카페, 카페별 보유 목록을 관리합니다.

## 데이터 흐름

1. 서버 시작 시 `main.py`가 SQLite 스키마와 인덱스를 생성합니다.
2. 게임, 별칭, 유사 관계, 카페, 카페별 보유 목록, 관리자 계정 샘플 데이터가 비어 있는 DB에 시드됩니다.
3. 앱은 시작 시 `GET /cafes/nearby`로 카페 목록을 불러오고, 선택된 카페의 보유 게임을 `GET /cafes/{cafeId}/games`로 가져옵니다.
4. 카페 보유 게임 목록은 검색어, 인원, 시간, 장르, 정렬 조건을 서버 API 파라미터로 전달하고, 입문/아이/파티/전략 토글은 클라이언트에서 추가 필터링합니다.
5. 사용자의 검색, 조회, 추천 클릭, 플레이 완료, 숨김 처리는 이벤트와 사용자 기록 테이블에 저장됩니다.
6. 선택 로그인 또는 기기 변경 이전이 필요하면 `POST /users`로 사용자 레코드를 만들고 기존 익명 세션 기록을 연결할 수 있습니다.
7. 추천 탭은 `POST /recommendations`를 호출하고, 백엔드 추천 점수와 추천 이유를 카드에 표시합니다.
8. 추천 API는 `POST /events`로 저장된 검색/조회/추천 클릭/인식 확정 이벤트에서 직접 게임, 장르, 난이도, 태그 선호 신호를 계산해 추천 점수와 추천 이유에 반영합니다.
9. 앱은 `POST /sessions`로 익명 세션을 생성하고 브라우저 저장소에 보관합니다. 추천, 상세 조회, 추천 클릭, 인식 확정 흐름은 이 세션 ID를 API에 전달합니다.
10. 게임 상세 화면은 `GET /games/{gameId}`로 최신 상세를 불러오고, 상세 조회 이벤트를 `POST /events`로 기록합니다.
11. 스캔 탭은 파일 업로드와 텍스트 힌트를 `POST /recognitions`로 전송하고, 후보 확정 시 `POST /recognitions/{recognitionId}/confirm`을 호출합니다. 백엔드 연결 실패 시 화면 안에서 오류 상태를 보여주며 기존 샘플 시뮬레이션 버튼도 유지합니다.
12. 이미지 인식 API는 업로드 원본을 로컬 DB나 디스크에 저장하지 않습니다. 업로드는 5MB 이하 `image/jpeg`, `image/png`, `image/webp`만 허용하고, 빈 파일과 지원하지 않는 MIME은 400 응답으로 거부합니다.
13. 이미지가 있고 NVIDIA 설정이 준비되어 있으면 `vision_client.py`가 OpenAI-compatible chat completions payload를 만들어 외부 Vision API로 전송합니다.
14. `recognition_service.py`는 외부 응답에서 최대 5개 후보를 파싱하고, 내부 `games`와 `game_aliases`에 매칭되는 후보만 최종 후보로 우선 반환합니다. 내부 DB에 없는 후보는 `unmatchedCandidates`로만 응답합니다.
15. 외부 호출 실패, 설정 누락, 낮은 신뢰도 상황에서는 기존 힌트/파일명 기반 fallback 흐름으로 후보를 만들고 사용자에게는 짧은 안내만 반환합니다.
16. 이미지와 힌트가 모두 없는 인식 요청은 `needsRetake=true`, 빈 후보 목록, 입력 부족 안내 메시지로 응답합니다.
17. 사용자 데이터 삭제 요청은 원본 이미지가 저장되지 않았다는 보관 정책과 함께 사용자/세션 기준 기록 테이블을 정리합니다.
18. 관리자 API는 일반 사용자 API와 분리되어 `X-Admin-Token` 헤더가 올바를 때만 데이터를 생성하거나 수정합니다.

## 개인정보 및 이미지 보관 원칙

- MVP는 로그인 없이 익명 세션 ID로 사용할 수 있습니다.
- 선택 로그인 또는 기기 변경 이전을 위해 `POST /users`를 제공하지만 필수 로그인은 요구하지 않습니다.
- 추천과 최근 기록에 필요한 이벤트, 카페 ID, 게임 ID 중심으로 저장하고 과도한 개인정보를 수집하지 않습니다.
- 위치 권한을 거부하면 QR 코드 또는 수동 카페 선택으로 대체합니다.
- 사용자는 `DELETE /users/{userId}/data`로 익명 세션 또는 사용자 기록 삭제를 요청할 수 있습니다.
- 이미지 인식 원본 파일은 기본적으로 저장하지 않습니다.
- 이미지 업로드는 5MB 이하의 JPG/PNG/WebP만 허용하며, 비어 있거나 허용되지 않은 파일은 400 응답으로 거부합니다.
- 이미지 업로드 인식 시 원본 이미지 바이트는 설정된 외부 Vision API로 전송될 수 있으며, 응답에는 `externalProcessing`으로 외부 처리 사용 여부를 표시합니다.
- 품질 개선 목적으로 이미지를 장기 보관하려면 별도 동의와 원본/썸네일/전처리 이미지별 보관 기간이 필요합니다.
- 인식 로그에는 원본 이미지가 아니라 인식 작업, 후보 게임, 신뢰도, 사용자 확정 결과만 저장합니다.
- 운영 환경에서는 기본 관리자 토큰 사용 금지, CORS 도메인 제한, SQLite 백업 정책, 외부 Vision 장애 fallback, rate limit 도입 여부를 별도로 점검해야 합니다.

## 변경 기록

- `AI_APP_GOAL_PROMPT.md`를 추가해 AI에게 전달할 앱 목표 설명 프롬프트를 작성했습니다.
- 프로젝트 관리 규칙에 맞춰 `SUMMARY.md`를 새로 생성했습니다.
- `index.html`을 추가해 모바일 하단 탭 구조의 보드게임 카페 도우미 실행 프로토타입을 구현했습니다.
- `SUMMARY.md`에 새 실행 파일과 프로젝트 책임 변화를 반영했습니다.
- `BACKEND_BUILD_PROMPT.md`를 추가해 백엔드 구축을 위한 목표, 데이터 모델, API, 추천, 이미지 인식, 개인정보 정책 요구사항을 정리했습니다.
- `main.py`를 추가해 FastAPI 백엔드 MVP, SQLite 저장소, 시드 데이터, 공개 API, 추천 로직, 이미지 인식 시뮬레이션, 관리자 토큰 인증을 구현했습니다.
- `requirements.txt`를 추가해 FastAPI, Uvicorn, python-multipart 실행 의존성을 명시했습니다.
- `GET /cafes/{cafeId}/games`에 사용자 지정 정렬 옵션을 추가했습니다.
- 추천 로직이 저장된 검색/조회/추천 클릭/인식 확정 이벤트를 선호 신호로 반영하도록 개선했습니다.
- 이미지와 힌트가 모두 없는 인식 요청은 고신뢰도 fallback 후보를 반환하지 않고 입력 부족 응답을 반환하도록 수정했습니다.
- 관리자 게임 생성 시 명시된 `id`를 항상 우선 존중하도록 game_id 생성 흐름을 명확히 했습니다.
- `POST /users`를 추가해 선택 사용자 생성과 익명 세션 기록 연결 흐름을 제공했습니다.
- `DELETE /users/{userId}/data`를 추가해 개인정보 삭제 요청의 MVP 동작을 구현했습니다.
- `GET /meta/schema`를 추가해 구현된 테이블과 빠른 조회 책임을 API로 확인할 수 있게 했습니다.
- 이미지 인식 시뮬레이션의 무작위 파일명 fallback 신뢰도를 낮춰 불명확한 사진은 재촬영 흐름으로 연결되도록 조정했습니다.
- 추천 요청의 존재하지 않는 카페, 이벤트의 존재하지 않는 카페/게임, 숨김 게임의 존재하지 않는 게임에 대한 검증을 추가했습니다.
- Pydantic v1/v2 호환 직렬화 보조 함수를 추가했습니다.
- `.env`를 추가해 외부 이미지 인식/AI API 키 설정 자리를 만들고 실제 값은 비워두었습니다.
- `.gitignore`를 추가해 `.env`, SQLite DB, Python 캐시 파일을 제외했습니다.
- `python-dotenv` 의존성과 `.env` 로드를 추가하고, `GET /health`와 `GET /meta/schema`에서 이미지 인식 API 설정 여부를 확인할 수 있게 했습니다.
- `NEXT_WORK_PROMPT.md`를 현재 진행도 기준으로 다시 갱신해 이미 구현된 NVIDIA Vision 연동 코드와 스캔 탭 연결을 검증하고, 의존성 설치, 테스트 실행, 서버 기동, 실제 NVIDIA 스모크 테스트, 나머지 프론트 API화를 다음 단계 작업으로 정리했습니다.
- `.venv\Scripts\python.exe -m pytest`로 테스트를 실행해 `tests/test_privacy.py`, `tests/test_recognition.py`, `tests/test_recommendations.py`의 10개 테스트가 모두 통과함을 확인했습니다.
- `vision_client.py`를 추가해 NVIDIA/OpenAI-compatible Vision API payload 생성, 이미지 base64 변환, HTTP 호출, 오류 분류를 분리했습니다.
- `recognition_service.py`를 추가해 Vision 응답 JSON 파싱, 내부 게임/별칭 매칭, 최종 confidence 계산, 미매칭 후보 분리를 구현했습니다.
- `POST /recognitions`가 이미지 입력 시 NVIDIA 호출을 시도하고, 실패 또는 설정 누락 시 기존 힌트 기반 fallback으로 동작하도록 교체했습니다.
- `POST /recognitions` 응답에 `externalProcessing`, `unmatchedCandidates`, NVIDIA confidence, 내부 매칭 점수, 최종 confidence, 카페 보유 여부를 포함하도록 확장했습니다.
- 이미지 보관 정책에 외부 API 전송 가능성과 원본 이미지 미저장 원칙을 명시하고, `GET /health`와 `GET /meta/schema`가 실제 설정 값이 아닌 설정 여부만 반환하도록 조정했습니다.
- `tests/test_recognition.py`, `tests/test_privacy.py`, `tests/test_recommendations.py`를 추가해 인식, 개인정보, 추천 검증을 시작했습니다.
- `index.html`의 스캔 탭에 파일 업로드, 힌트 입력, 백엔드 인식 요청, 후보 표시, 후보 확정, API 연결 실패 상태를 추가했습니다.
- `.gitignore`에 `.venv/`를 추가해 로컬 테스트 환경이 저장소에 섞이지 않도록 했습니다.
- `vision_client.py` payload에서 일부 NVIDIA NIM 모델과 호환성이 낮은 `response_format` 필드를 제거하고, 시스템 프롬프트의 JSON 요구와 서버 파싱 fallback으로 안정성을 유지했습니다.
- `scripts/smoke_nvidia_recognition.py`를 추가해 실제 NVIDIA Vision 호출과 서버 경유 인식 흐름을 안전하게 스모크 테스트할 수 있게 했습니다.
- 실제 NVIDIA 스모크 테스트에서 외부 처리 사용, 내부 DB 매칭, top candidate `splendor`, 미매칭 0개를 확인했습니다.
- `index.html`의 카페 목록, 카페 보유 게임 검색/필터/정렬, 추천 탭, 게임 상세 화면을 백엔드 API 우선 흐름으로 연결했습니다.
- 브라우저에서 홈 API 연결, 스캔 힌트 인식, 후보 확정, 추천, 카페 검색, 상세 조회를 확인했고 콘솔 에러 0개를 확인했습니다.
- `README.md`를 추가해 실행, 환경 변수, 테스트, 주요 API 확인 명령을 정리했습니다.
- `NEXT_WORK_PROMPT.md`를 최신 진행도 기준으로 갱신해 MVP 안정화, 이미지 업로드 안전장치, 프론트 API 실패 상태 개선, 익명 세션/이벤트 기록, 운영 전 보안 기본값 점검을 다음 작업으로 정리했습니다.
- `.venv\Scripts\python.exe -m pytest`를 다시 실행해 10개 테스트 통과와 deprecation 경고 3개를 확인했습니다.
- FastAPI startup을 `@app.on_event`에서 lifespan으로 전환해 startup deprecation 경고를 제거했습니다.
- `POST /recognitions`에 5MB 크기 제한, 허용 MIME 검증, 빈 파일 거부, 안전한 파일명 힌트 처리를 추가했습니다.
- 이미지 업로드 검증 테스트를 추가해 빈 파일, 지원하지 않는 MIME, 5MB 초과 파일이 400 응답을 반환하고 민감 정보가 노출되지 않음을 확인했습니다.
- `game_aliases` 시드 데이터에 한국어/영어 오타, 약칭, 확장 검색용 별칭을 일부 추가했습니다.
- `index.html`이 익명 세션을 생성해 브라우저 저장소에 보관하고 추천, 상세 조회, 추천 클릭, 인식 확정 API에 전달하도록 개선했습니다.
- 추천 입력 변경 시 API 요청을 짧게 debounce하고, 카페 게임 화면에는 서버 필터와 클라이언트 토글 필터의 책임을 안내하도록 개선했습니다.
- 브라우저 시나리오에서 추천 클릭과 상세 조회 이벤트가 같은 익명 세션으로 저장되는 것을 확인했습니다.
- `README.md`에 이미지 업로드 제한, NVIDIA 스모크 주의, 테스트 경고 현황, 운영 전 보안 체크리스트를 추가했습니다.
- `.gitignore`에 `.pytest_cache/`와 `*.log`를 추가했습니다.
- `.venv\Scripts\python.exe -m pytest -q`를 다시 실행해 13개 테스트 통과와 deprecation 경고 1개를 확인했습니다.
- `docs/index.html`과 `docs/.nojekyll`을 추가해 GitHub Pages에서 `/docs` 폴더를 정적 배포 소스로 사용할 수 있게 했습니다.
- `README.md`에 GitHub Pages 설정 방법, 메인 파일, 휴대폰 테스트 시 백엔드 별도 HTTPS 배포 필요성을 추가했습니다.
- `README.md`에 PC를 25565 포트 백엔드 서버로 사용하는 실행 명령, 로컬/휴대폰 확인 방법, GitHub Pages HTTPS mixed content 주의사항, `apiBase=https://도메인:25565` 연결 방식을 추가했습니다.
- `RAILWAY_DEPLOYMENT.md` 절차에 맞춰 FastAPI 루트 `/`가 `index.html`을 반환하도록 추가하고, 프론트 기본 API URL을 `location.origin`으로 바꿨습니다.
- Railway Volume용 `BOARDGAME_DB_PATH=/app/data/boardgame_backend.sqlite3` 같은 중첩 경로를 위해 startup에서 DB 부모 디렉터리를 생성하도록 보강했습니다.
- `tests/test_deployment.py`를 추가해 루트 프론트 서빙과 DB 부모 디렉터리 생성을 검증했습니다.
- 로컬 Uvicorn 서버에서 `/`, `/health`, `/meta/schema`, `/games`, `/cafes/cafe-hongdae/games`, 힌트 기반 `/recognitions`가 정상 응답함을 확인했습니다.
- `.venv\Scripts\python.exe -m pytest -q`를 실행해 15개 테스트 통과와 deprecation 경고 1개를 확인했습니다.
- `ADMIN_PAGE_PROMPT.md`를 추가해 Railway 운영 환경에서 사용할 관리자 페이지의 인증, 게임/카페/재고 관리, 로그/상태 탭, 관리자 API 보강, 테스트 전략을 정리했습니다.
