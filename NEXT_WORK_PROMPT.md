# 다음 작업 프롬프트: PostgreSQL 운영 관찰과 백업 자동화

## 현재 완료 상태

운영 PostgreSQL 전환과 승인된 정리 작업이 모두 완료됐습니다.

- 운영 `/health`의 database는 `postgresql`
- 게임 51개, 별칭 118개, 관계 6개, 품질 점수 100
- SQLite 외부 백업과 SHA-256 매니페스트 확보
- PostgreSQL API 계약과 주요 운영 API 검증 완료
- 레거시 테이블·열 제거 완료
- 기존 시험 PostgreSQL 서비스 제거 완료, Volume 삭제는 Railway `pending deletion`
- Railway 원격 논리 백업과 임시 SSH 키 제거 완료

## 다음 목표

1. Railway PostgreSQL의 자동 백업 또는 외부 정기 백업 정책을 설정합니다.
2. 기존 시험 Volume `8a683b39-993b-44b0-a8fe-83c4899a2249`의 `pending deletion` 완료를 확인합니다.
3. `/admin/observability`에서 오류율, rate limit과 Vision fallback 비율을 관찰합니다.
4. PostgreSQL 연결 수와 쿼리 지연을 관찰하고 필요할 때 pool 설정을 조정합니다.
5. 다중 replica가 필요해지기 전에 Redis 공유 rate limit을 도입합니다.
6. 이미지 출처와 라이선스가 검증된 게임만 단계적으로 확장합니다.

## 운영 보호

- `DATABASE_URL`은 Railway service reference로만 관리하고 원문을 문서나 로그에 남기지 않습니다.
- `backups/`와 SQLite 파일은 Git에 커밋하지 않습니다.
- 데이터 변경 전 관리자 CSV `all_or_nothing` 미리보기를 사용합니다.
- PostgreSQL migration은 dry-run과 외부 백업 후에만 실제 적용합니다.
- app SQLite Volume을 제거하려면 PostgreSQL 복원 리허설과 별도 승인을 먼저 받습니다.

## 완료 기준

- PostgreSQL 자동 백업의 보존 기간과 복원 절차가 문서화됩니다.
- 운영 오류율과 DB 지연 기준선이 확보됩니다.
- 게임 51개와 품질 점수 100을 유지합니다.
