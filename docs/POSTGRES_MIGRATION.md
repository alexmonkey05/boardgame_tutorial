# PostgreSQL 전환 리허설

## 범위

`postgresql_target_schema.sql`은 활성 14개 테이블만 정의합니다. 운영 SQLite에 남은 레거시 테이블과 열은 전환 대상에서 제외하지만 원본 Volume에서는 삭제하지 않습니다.

주요 차이:

- JSON 문자열 열은 PostgreSQL `JSONB`로 전환합니다.
- 시간 문자열은 `TIMESTAMPTZ`로 전환합니다.
- SQLite 자동 증가 ID는 PostgreSQL identity 열로 전환합니다.
- 게임 인원, 시간, 난이도, 장르와 관계 무결성을 DB 제약으로도 확인합니다.

## Dry-run

```powershell
.venv\Scripts\python.exe scripts\migrate_sqlite_to_postgres.py source.sqlite3
```

Dry-run은 네트워크 연결 없이 다음 항목을 검사합니다.

- 활성 테이블과 필요한 열
- 테이블별 행 수와 주요 ID 표본
- SQLite 외래키 오류
- JSON 파싱 오류
- 전체 활성 데이터 SHA-256

2026-07-18 로컬 운영 DB 사본 결과는 활성 14개 테이블, 게임 7개, 외래키 오류 0개, JSON 오류 0개로 통과했습니다.

## 실제 적용 잠금

실제 PostgreSQL 적재는 사용자 승인, Railway Volume 백업과 복원 리허설 완료 후에만 수행합니다.

```powershell
.venv\Scripts\pip.exe install -r requirements-postgres.txt
$env:DATABASE_URL='<postgres-connection-string>'
$env:ALLOW_POSTGRES_APPLY='1'
.venv\Scripts\python.exe scripts\migrate_sqlite_to_postgres.py source.sqlite3 `
  --apply --confirm APPLY_POSTGRES
```

스크립트는 기본키 기준 upsert를 사용하므로 동일 사본을 반복 적용해도 중복 행을 만들지 않습니다. identity sequence도 적재한 최대 ID 이후로 조정합니다. 연결 문자열은 출력하지 않습니다.

## 전환과 복귀

1. 기존 Railway SQLite 서비스를 계속 실행한 상태에서 별도 PostgreSQL에 dry-run과 시험 적재를 수행합니다.
2. 테이블별 행 수, 게임 ID, 외래키와 JSON 필드를 재검증합니다.
3. 애플리케이션의 PostgreSQL 저장소 지원을 별도 변경으로 배포합니다.
4. 승인된 점검 창에 연결 대상만 전환합니다.
5. 문제가 있으면 기존 SQLite 환경변수와 Volume으로 즉시 복귀합니다.

현재 애플리케이션 런타임은 계속 SQLite를 사용합니다. 이 문서와 도구는 전환 준비물이며 실제 전환을 수행하지 않습니다.
