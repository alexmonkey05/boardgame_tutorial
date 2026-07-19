# 데이터 운영 가이드

## 데이터 품질 규칙

- 게임 ID는 `^[a-z0-9]+(?:-[a-z0-9]+)*$` 형식의 고정 slug입니다.
- 한국어 이름, 설명, 규칙 요약, 인원, 시간, 난이도와 장르는 필수입니다.
- 난이도는 `easy`, `medium`, `hard`만 허용합니다.
- 장르는 `cooperative`, `family`, `party`, `puzzle`, `strategy`만 허용합니다.
- 별칭은 공백과 하이픈을 제거하고 소문자로 정규화한 뒤 전체 게임에서 충돌을 검사합니다.
- 자기 관계와 동일한 출발·대상·유형의 중복 관계를 허용하지 않습니다.
- 이미지가 있으면 URL, 출처, 라이선스와 대체 텍스트를 모두 기록합니다.
- 데이터 출처 URL, 데이터 라이선스, 문구 라이선스, 검토일과 검토자를 기록합니다.

관리자 페이지의 `품질` 탭과 `GET /admin/data-quality`에서 현재 오류와 경고를 조회합니다. `unverified` 이미지 라이선스는 경고로 표시됩니다.

## CSV 가져오기

게임 CSV 열 순서:

```text
id,nameKo,nameEn,shortDescription,rulesSummary,minPlayers,maxPlayers,avgPlayTimeMinutes,difficulty,genre,tags,isBeginnerFriendly,isKidFriendly,isPartyGame,isStrategyGame,playStyle,imageUrl,imageSource,imageLicense,imageAlt,dataSourceUrl,dataLicense,contentLicense,reviewedAt,reviewedBy,aliases
```

`tags`와 `aliases`의 여러 값은 `|`로 구분합니다. 파일은 UTF-8, 2MB 이하, 최대 2,000행이어야 합니다.

검토 완료된 51개 파일은 `data/boardgames_wikidata_cc0.csv`입니다. 이미지 권리가 별도로 확인되지 않아 이미지 열은 비어 있습니다. 2026-07-18 운영 관리자 API에서 `all_or_nothing` 미리보기 결과 51개 전체가 유효하고 오류가 없음을 확인한 뒤 적용했으며, 생성 44개·수정 7개로 완료됐습니다.

1. `POST /admin/imports/games/preview`에 multipart `file`을 전송합니다.
2. 오류 행과 생성·수정 diff를 확인합니다.
3. 15분 안에 `POST /admin/imports/games/apply`를 호출합니다.
4. `all_or_nothing`은 오류 행이 하나라도 있으면 전체를 취소합니다.
5. `valid_only`는 검증된 행만 적용하고 오류 행은 건너뜁니다.

원본 CSV와 관리자 토큰은 저장하지 않습니다. 미리보기에는 정규화된 행 데이터만 저장하며, 적용 결과는 변경 ID가 아닌 건수와 필드명 중심으로 감사 로그에 남깁니다.

내보내기:

```text
GET /admin/exports/games.csv
GET /admin/exports/aliases.csv
```

## SQLite 백업 리허설

운영 Volume 파일을 먼저 복사한 안전한 작업 사본에서 실행합니다.

```powershell
.venv\Scripts\python.exe scripts\rehearse_sqlite_backup.py `
  source.sqlite3 backup.sqlite3 restored.sqlite3
```

도구는 기존 대상 파일을 덮어쓰지 않습니다. SQLite backup API로 백업과 복원을 수행한 뒤 세 파일의 `PRAGMA integrity_check`와 모든 테이블의 행 수를 비교합니다.

2026-07-18 로컬 운영 DB 사본 리허설 결과:

- 원본·백업·복원본 무결성: 모두 `ok`
- 모든 테이블 행 수: 일치
- 활성 게임: 7개
- 레거시 테이블: 백업과 복원본에 그대로 보존
- 결과: 성공

2026-07-18 Railway Volume에서도 운영 SQLite 파일을 실제 백업하고 복원 리허설을 완료했습니다.

- 적용 전 백업: `/app/data/backups/boardgame-20260718T1955KST.sqlite3`, 활성 게임 7개
- 적용 후 백업: `/app/data/backups/boardgame-postimport-20260718T2015KST.sqlite3`, 활성 게임 51개
- 두 리허설 모두 원본·백업·복원본 무결성 `ok`
- 모든 테이블 행 수 일치 및 레거시 테이블 보존 확인

2026-07-19 운영 SQLite 원본과 Volume 백업 4개를 `backups/railway-20260719`로 외부 반출했습니다. 모든 파일의 무결성은 `ok`이며 SHA-256은 같은 디렉터리의 `MANIFEST.json`에 기록했습니다. 반출 검증 후 Railway Volume의 `/app/data/backups`는 삭제했습니다.

## 운영 보호

- `POST /recommendations`: 기본 분당 30회
- `POST /recognitions`: 기본 분당 10회
- 초과 시 `429`, `Retry-After`, `X-Request-ID`를 반환합니다.
- 모든 요청에 요청 ID와 처리 시간 헤더가 포함됩니다.
- 구조화 로그에는 메서드, 경로, 상태 코드, 처리 시간만 기록합니다.
- 쿼리 문자열, 본문, 토큰, API 키와 이미지 바이트는 로그에 기록하지 않습니다.
- `/health`는 프로세스 생존, `/ready`는 DB와 게임 데이터 준비 상태를 확인합니다.
- `GET /admin/observability`에서 상태 코드, rate limit, Vision 실패와 fallback 비율을 확인합니다.

## 다중 replica rate limit 결정

현재 배포는 단일 replica를 유지하고 인메모리 sliding window를 사용합니다. 이 방식은 프로세스마다 카운터가 달라지므로 다중 replica에는 안전하지 않습니다.

- replica를 늘리기 전 Redis 공유 저장소와 원자적 Lua 연산 기반 제한으로 교체합니다.
- Redis 장애 정책은 짧은 타임아웃 후 fail-open으로 두고 관측성 경고를 남깁니다.
- 키에는 제한 대상 경로와 비식별 클라이언트 키 해시만 사용하며 원문 토큰과 요청 본문은 저장하지 않습니다.
- 공유 저장소가 준비되기 전에는 `WEB_CONCURRENCY=1`과 Railway replica 1개를 유지합니다.

## PostgreSQL 계약 테스트

`storage.py`는 SQLite와 PostgreSQL의 테이블·열 조회를 같은 저장소 계약으로 제공합니다. 테스트 전용 PostgreSQL URL이 있을 때 다음 명령으로 실제 스키마 계약을 확인합니다.

```powershell
$env:TEST_POSTGRES_URL='postgresql://...'
.venv\Scripts\pip.exe install -r requirements-postgres.txt
.venv\Scripts\python.exe -m pytest tests/test_storage.py -q
```

`TEST_POSTGRES_URL`이 없으면 PostgreSQL 테스트만 명시적으로 skip합니다.

2026-07-18 임시 Railway PostgreSQL에서 다음을 확인했습니다.

- 실제 PostgreSQL API 계약 테스트 단독 실행: `1 passed`
- SQLite 스냅샷을 두 번 적재해 행 수와 주요 ID가 변하지 않는 idempotency 확인
- 외래키 오류 0개와 JSONB 열 형식 확인
- 시간대 포함 값과 identity sequence 정상 확인
- API 응답의 PostgreSQL 날짜 직렬화 회귀 수정 및 재검증

2026-07-19 새 Railway PostgreSQL에 최신 SQLite를 정확히 동기화하고 운영 `DATABASE_URL`을 전환했습니다. 운영 품질은 게임 51개·별칭 118개·관계 6개·오류 0개·경고 0개·점수 100입니다. 기존 시험 PostgreSQL 서비스는 삭제했고 연결 Volume은 Railway `pending deletion` 상태입니다. 비활성 SQLite에서는 외부 원본 백업을 확보한 뒤 레거시 테이블과 열을 제거했습니다.
