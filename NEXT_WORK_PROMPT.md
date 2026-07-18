# 다음 작업 프롬프트: 승인 기반 PostgreSQL 시험과 운영 데이터 반영

당신은 보드게임 데이터 큐레이션, 이미지 권리 검증, FastAPI 저장소 추상화와 Railway 운영을 함께 설계하는 시니어 개발자입니다.

## 현재 완료 상태

서비스는 일반 보드게임 식별·검색·추천 제품으로 전환됐으며 다음 운영 기반이 구현됐습니다.

- 카페·매장·재고·선반 의존성 제거와 Railway 운영 배포 검증
- 게임 ID, 필수 필드, 인원·시간, 난이도·장르 품질 규칙
- 전역 별칭 충돌, 중복 이름, 자기·중복·끊어진 관계 탐지
- 이미지 URL, 출처, 라이선스와 대체 텍스트 동시 관리
- 관리자 CSV 미리보기, 오류 행, 생성·수정 diff, 전체 또는 유효 행 적용
- 게임·별칭 CSV 내보내기와 민감값 없는 관리자 감사 로그
- 요청 ID, 처리 시간, readiness, 추천·인식 rate limit과 Vision 관측성
- SQLite 로컬 사본 백업·복원 리허설 성공
- 활성 14개 테이블의 PostgreSQL dry-run 성공
- Wikidata CC0 식별 메타데이터와 프로젝트 작성 문구 정책 확정
- 이미지 URL 없이 권리 경고를 제거한 51개 게임 CSV 준비 및 전체 미리보기 통과
- 출처·라이선스·검토 메타데이터와 품질 이슈 전용 해결 작업 구현
- SQLite·PostgreSQL 선택형 저장소 런타임과 조건부 API 계약 테스트 구현
- 단일 replica 유지 및 확장 전 Redis 공유 rate limit 도입 결정
- 자동 테스트 31개 통과 및 PostgreSQL 환경 의존 테스트 1개 skip

운영 SQLite의 레거시 테이블과 열은 계속 물리 보존하며 활성 API와 UI에서는 읽거나 노출하지 않습니다.

## 다음 목표

승인을 받은 시험 환경에서 PostgreSQL API 계약을 실행하고 검증된 51개 데이터의 운영 반영 여부를 결정합니다.

1. Railway Volume의 SQLite 파일을 실제 백업하고 복원 리허설용 사본을 확보합니다.
2. 임시 Railway PostgreSQL 서비스 또는 사용자가 제공한 `TEST_POSTGRES_URL`에서 API 계약 테스트를 실행합니다.
3. SQLite 스냅샷을 PostgreSQL에 반복 적재해 행 수·ID·JSONB·시간대·identity sequence의 idempotency를 확인합니다.
4. PostgreSQL 시험이 성공해도 운영 `DATABASE_URL` 전환은 별도로 승인받습니다.
5. `data/boardgames_wikidata_cc0.csv`를 운영에 적용하기 전 관리자 미리보기 결과를 다시 확인하고 승인을 받습니다.
6. 적용 후 게임 51개와 품질 점수 100을 확인합니다.

## 데이터 확장 원칙

- 출처와 라이선스를 확인하지 않은 이미지 URL은 추가하지 않습니다.
- 설명과 규칙 요약을 외부 문서에서 장문 복제하지 않습니다.
- 게임 ID는 최초 생성 후 변경하지 않습니다.
- CSV 적용 전 `all_or_nothing` 검증을 우선 사용합니다.
- 별칭은 여러 언어, 통칭과 흔한 오탈자를 포함하되 다른 게임과 충돌하지 않아야 합니다.
- 확장 데이터는 생성 출처, 검토일과 검토자를 추적할 수 있어야 합니다.

## PostgreSQL 준비

- `docs/postgresql_target_schema.sql`과 SQLite 활성 스키마의 차이를 자동 검사합니다.
- 저장소 인터페이스는 SQLite와 PostgreSQL에서 동일한 응답 계약을 유지합니다.
- JSONB, identity sequence, 시간대와 트랜잭션 동작을 통합 테스트합니다.
- `scripts/migrate_sqlite_to_postgres.py`는 dry-run을 기본값으로 유지합니다.
- 실제 적재는 `--apply --confirm APPLY_POSTGRES`와 `ALLOW_POSTGRES_APPLY=1`을 모두 요구합니다.
- 실패 시 기존 SQLite Railway 서비스를 계속 사용할 수 있어야 합니다.

## 테스트

- 50개 이상 CSV의 전체 검증과 적용 성능
- 정규화 이름·별칭의 다국어 충돌
- 이미지 라이선스 누락과 미검증 상태
- SQLite와 PostgreSQL API 계약 동등성
- PostgreSQL migration 재실행의 idempotency
- 다중 프로세스 rate limit 전략
- 관리자 품질 해결 흐름의 모바일·데스크톱 회귀

## 승인 필요 작업

다음 작업은 사용자 승인 없이 수행하지 마세요.

- Railway Volume 실제 백업 파일 생성·다운로드·삭제
- PostgreSQL 서비스 생성, 비용 발생 설정과 실제 데이터 적재
- 운영 `DATABASE_URL` 전환
- 레거시 테이블·열 삭제
- 검증된 CSV의 대규모 운영 적용

## 완료 기준

- 검증된 출처와 권리 메타데이터를 가진 실제 게임 데이터셋이 준비됩니다.
- 전체 CSV가 오류 없이 미리보기를 통과합니다.
- SQLite와 PostgreSQL에서 자동 API 계약 테스트가 통과합니다.
- migration을 반복 실행해도 행 수와 주요 ID가 변하지 않습니다.
- 승인 전에는 운영 DB와 Railway Volume에 파괴적 변경이 없습니다.
