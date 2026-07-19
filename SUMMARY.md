# 프로젝트 상태 요약

## 현재 상태

보드게임 식별·검색·추천 서비스의 운영 전환이 완료됐습니다. 운영 앱은 Railway PostgreSQL을 사용하며 사용자·관리자 기능과 데이터 품질이 정상입니다.

## 운영 기준선

- 서비스: `https://boardgametutorial-production.up.railway.app`
- 관리자: `https://boardgametutorial-production.up.railway.app/admin-ui`
- 운영 DB: Railway PostgreSQL `Postgres-bWm0`
- 게임 51개, 별칭 118개, 관계 6개
- 품질 오류 0개, 경고 0개, 점수 100
- `/health` database: `postgresql`
- `/ready`: 게임 51개, ready

## 완료된 운영 작업

- 운영 SQLite와 Volume 백업 4개를 `backups/railway-20260719`로 반출
- 모든 SQLite 파일 무결성 `ok` 및 SHA-256 매니페스트 생성
- 최신 SQLite 14개 활성 테이블을 새 PostgreSQL에 정확히 동기화
- 실제 PostgreSQL API 계약 테스트 통과
- 운영 `DATABASE_URL`을 새 PostgreSQL private reference로 전환
- `/health`, `/ready`, `/games`, `/recommendations`, `/recognitions`, `/admin-ui` 검증
- OpenAPI에서 `/cafes`, `/admin/cafes`, `cafeId` 비노출 확인
- PostgreSQL 레거시 테이블·열 없음 확인
- 비활성 SQLite의 `cafes`, `cafe_inventory`, `cafe_id` 제거
- Railway Volume의 `/app/data/backups` 삭제
- 기존 시험 PostgreSQL 서비스 삭제 및 Volume 삭제 요청 완료 (`pending deletion`)
- 작업용 Railway SSH 키 제거

## 코드 검증

- 로컬 테스트: `33 passed, 1 skipped`
- 실제 PostgreSQL 계약 테스트: `1 passed`
- migration은 배치 upsert와 원본에 없는 행 삭제를 수행해 반복 실행 시 정확한 동기화를 보장
- JSONB, 시간대, identity sequence와 외래키 검증 통과

## 유지 사항

- app SQLite Volume은 즉시 복귀용 fallback으로 유지합니다.
- 외부 백업은 Git에서 제외되며 로컬 `backups/railway-20260719`에 보관합니다.
- 다중 replica 전환 전 Redis 공유 rate limit을 도입합니다.
