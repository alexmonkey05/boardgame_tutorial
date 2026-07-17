# 다음 작업 프롬프트: GitHub Pages 휴대폰 테스트와 백엔드 연결

당신은 정적 프론트엔드 배포와 FastAPI 백엔드 연결을 함께 다루는 풀스택 개발자입니다. 이 프로젝트는 보드게임 카페에서 사용자가 보드게임을 빠르게 찾고, 사진으로 식별하고, 현재 카페에 있는 게임을 추천받는 앱입니다.

이번 단계의 목표는 GitHub Pages로 프론트엔드를 공개하고, 휴대폰 브라우저에서 실제 사용 흐름을 테스트할 수 있게 만드는 것입니다.

## 현재 진행도 판단

전체 서비스 기준 진행도는 약 88%입니다.

- 기획 문서와 목표 프롬프트: 완료
- FastAPI 백엔드 MVP: 약 88%
- NVIDIA Vision API 호출 코드: 구현 및 실제 스모크 성공
- 이미지 업로드 안전장치: 5MB 제한, MIME 제한, 빈 파일 거부 구현
- 스캔 탭 백엔드 연결: 구현 및 브라우저 검증 완료
- 카페 목록/보유 게임/추천/상세 화면 API화: 1차 구현 및 브라우저 검증 완료
- 익명 세션/추천 클릭/상세 조회 이벤트: 브라우저 시나리오에서 확인 완료
- 자동 테스트: `.venv\Scripts\python.exe -m pytest -q` 기준 13개 통과, Starlette TestClient/httpx deprecation 경고 1개 남음
- GitHub Pages 구조: `docs/index.html`과 `docs/.nojekyll` 준비 완료
- 남은 핵심 작업: GitHub Pages 실제 배포, 휴대폰 브라우저 테스트, PC의 25565 포트 백엔드 HTTPS 연결

## 현재 파일 구조

GitHub Pages용 공개 파일은 `docs/`에 있습니다.

```text
docs/
  index.html
  .nojekyll
```

중요한 파일 책임:

- `docs/index.html`: GitHub Pages가 열 메인 파일입니다.
- `index.html`: 로컬 개발용 원본 프론트 파일입니다. 현재 `docs/index.html`과 같은 내용입니다.
- `main.py`: FastAPI 백엔드입니다. GitHub Pages에서는 실행되지 않습니다.
- `.env`: NVIDIA API 키와 백엔드 환경 변수입니다. 절대 커밋하거나 Pages에 포함하지 않습니다.
- `README.md`: 실행 방법과 GitHub Pages 설정 방법을 설명합니다.

## GitHub Pages 설정

GitHub 저장소에서 다음처럼 설정하세요.

1. `Settings` > `Pages`
2. `Build and deployment`: `Deploy from a branch`
3. Branch: `main`
4. Folder: `/docs`
5. 저장

메인 파일은 `docs/index.html`입니다.

루트 `index.html`을 메인으로 설정하려면 Pages source를 repository root로 바꿔야 하지만, 이 프로젝트는 백엔드 파일과 테스트 파일도 루트에 있으므로 `/docs` 배포를 권장합니다.

## 중요한 제약

GitHub Pages는 정적 호스팅입니다.

따라서 다음은 Pages에서 실행되지 않습니다.

- `main.py`
- `vision_client.py`
- `recognition_service.py`
- SQLite DB
- NVIDIA API 키가 필요한 서버 처리

휴대폰에서 실제 NVIDIA 인식, 추천, 카페 게임 API를 쓰려면 FastAPI 백엔드를 별도 HTTPS 주소로 배포해야 합니다.

이번 프로젝트에서는 사용자의 PC를 백엔드 서버처럼 사용할 예정이며, 현재 `25565` 포트가 외부 접근 가능하다고 가정합니다. FastAPI는 다음처럼 실행할 수 있습니다.

```bash
.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 25565
```

단, GitHub Pages 프론트는 HTTPS로 열리므로 `http://공인IP:25565`를 직접 호출하면 mixed content 정책으로 막힐 수 있습니다. Pages와 연결하려면 `https://도메인:25565`처럼 유효한 HTTPS가 붙은 백엔드 주소 또는 HTTPS 터널이 필요합니다.

## 휴대폰 테스트 전략

### 1단계: Pages 정적 화면 테스트

백엔드가 아직 공개 HTTPS로 배포되지 않았다면 먼저 정적 화면만 확인하세요.

확인할 것:

- Pages URL이 열리는지
- 모바일 레이아웃이 깨지지 않는지
- 하단 탭이 잘 눌리는지
- 샘플 fallback UI가 동작하는지
- API 연결 실패 메시지가 친절한지

### 2단계: 백엔드 HTTPS 연결 테스트

백엔드를 별도 HTTPS 주소로 배포하거나 HTTPS 터널을 사용한 뒤, Pages URL에 `apiBase`를 붙여 테스트하세요.

```text
https://사용자명.github.io/저장소명/?apiBase=https://백엔드주소
```

PC의 25565 포트를 그대로 쓸 경우 최종 형태는 다음과 같습니다.

```text
https://사용자명.github.io/저장소명/?apiBase=https://도메인:25565
```

주의:

- GitHub Pages는 HTTPS입니다.
- HTTPS 페이지에서 `http://` 백엔드를 호출하면 브라우저 mixed content 정책으로 막힐 수 있습니다.
- 휴대폰에서 `http://127.0.0.1:8000`은 PC가 아니라 휴대폰 자기 자신입니다.
- 휴대폰에서 `http://공인IP:25565/health`가 열리더라도 GitHub Pages에서 `http://공인IP:25565` API를 호출하는 것은 HTTPS mixed content 때문에 실패할 수 있습니다.
- 따라서 실제 휴대폰 테스트에는 HTTPS 백엔드 주소가 필요합니다.

### 3단계: 휴대폰 실사용 시나리오

휴대폰에서 다음을 확인하세요.

- 홈 화면 API 연결 상태
- 익명 세션 생성
- 카페 목록 로드
- 카페 게임 검색/필터
- 추천 탭 조건 변경과 추천 결과
- 상세 화면 조회
- 추천 클릭 이벤트 기록
- 스캔 탭 힌트 인식
- 가능하면 사진 업로드 인식
- 후보 확정
- API 실패 시 fallback 안내

## 다음 구현 작업

### 1. Pages용 API 설정 UX 개선

현재 프론트는 다음 순서로 API 주소를 읽습니다.

- `window.BOARDGAME_API_BASE_URL`
- URL query의 `apiBase`
- `localStorage`의 `boardgameApiBaseUrl`
- 기본값 `http://127.0.0.1:8000`

휴대폰 테스트 편의를 위해 다음 중 하나를 추가하세요.

- 설정 모달에서 API 주소 입력/저장
- `apiBase` query가 들어오면 localStorage에 저장
- 현재 연결 중인 API 주소를 홈 화면에 표시

### 2. 백엔드 배포 후보 정리

GitHub Pages와 함께 쓸 백엔드 연결 방식을 하나 선택해 문서화하세요.

후보:

- PC 직접 서버: `0.0.0.0:25565`로 FastAPI 실행 후 `https://도메인:25565` 구성
- PC 직접 서버 + HTTPS 터널: Cloudflare Tunnel 또는 ngrok으로 로컬 `25565`를 HTTPS URL에 연결
- Render
- Fly.io
- Railway
- Cloud Run
- Cloudflare Tunnel 또는 ngrok 임시 터널

MVP 휴대폰 테스트만 목적이라면 PC의 25565 포트를 직접 쓰되 HTTPS 터널을 붙이는 방식이 가장 빠릅니다. 장기 운영이면 도메인과 인증서를 붙인 PC 서버 또는 Render/Fly/Cloud Run 같은 배포가 낫습니다.

### 3. CORS 설정 정리

현재 개발 편의를 위해 CORS가 넓게 열려 있을 수 있습니다.

Pages URL이 확정되면 백엔드 CORS 허용 origin에 다음을 명시하세요.

```text
https://사용자명.github.io
```

또는 프로젝트 페이지 URL 구조에 맞춰 정확한 origin만 허용하세요.

### 4. 배포 전 보안 확인

- `.env`가 커밋되지 않는지 확인
- `boardgame_backend.sqlite3`가 커밋되지 않는지 확인
- `ADMIN_TOKEN` 기본값을 운영에서 사용하지 않기
- NVIDIA API 키가 프론트 코드에 절대 들어가지 않기
- Pages에는 정적 프론트 파일만 포함하기
- 25565 포트에 다른 서버가 이미 떠 있지 않은지 확인
- Windows 방화벽과 공유기 포트포워딩이 FastAPI 실행 PC로 향하는지 확인
- HTTPS 인증서 또는 HTTPS 터널 없이 Pages에서 `http://...:25565`를 호출하지 않기

## 커밋 전 확인

커밋 전에 다음을 확인하세요.

```bash
git status --short
.venv\Scripts\python.exe -m pytest -q
```

확인할 파일:

- `docs/index.html`
- `docs/.nojekyll`
- `README.md`
- `SUMMARY.md`
- `NEXT_WORK_PROMPT.md`

`.env`, `.venv/`, `boardgame_backend.sqlite3`, `__pycache__/`, `.pytest_cache/`는 커밋하지 않습니다.

## 완료 기준

이번 단계는 다음 조건을 만족하면 완료입니다.

- GitHub Pages source가 `/docs`로 설정됩니다.
- Pages URL에서 `docs/index.html`이 정상 표시됩니다.
- 휴대폰에서 Pages URL 접속이 됩니다.
- 백엔드 미연결 상태에서 fallback 안내가 자연스럽습니다.
- PC의 25565 백엔드를 HTTPS 주소 또는 임시 HTTPS 터널로 노출하고 `apiBase` 연결 테스트를 수행합니다.
- 휴대폰에서 최소 1개 실제 API 시나리오가 성공합니다.
- `README.md`와 `SUMMARY.md`가 실제 Pages URL, 백엔드 연결 방식, 남은 작업에 맞게 갱신됩니다.

## 다음 단계 후보

- 관리자 데이터 관리 화면 추가
- 백엔드 정식 배포
- PostgreSQL 전환 준비
- 보드게임 데이터 대량 확장
- API rate limit과 관측성 로깅 구현
