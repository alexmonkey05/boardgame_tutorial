# 다음 작업 프롬프트: 보드게임 카페 의존성 제거와 보드게임 DB 단순화

당신은 FastAPI 백엔드, 모바일 웹 프론트엔드, 데이터 모델을 함께 정리하는 풀스택 개발자입니다. 이 프로젝트는 처음에 "보드게임 카페에서 현재 매장에 있는 게임을 찾고 추천하는 앱"으로 시작했지만, 법적/운영 리스크를 줄이기 위해 방향성을 변경합니다.

이번 작업의 목표는 **보드게임 카페 관련 기능과 데이터를 제거하고, 앱을 일반 보드게임 식별/추천 서비스로 단순화**하는 것입니다.

## 방향 전환의 이유

보드게임 카페별 보유 게임 목록을 무단으로 구축하거나, 사용자가 현재 위치한 보드게임 카페에 특정 게임이 있는지 판단하는 기능은 법적/운영 리스크가 있을 수 있습니다.

따라서 앞으로 이 앱은 다음을 하지 않습니다.

- 특정 보드게임 카페의 보유 게임 목록을 저장하지 않습니다.
- 사용자가 현재 어떤 보드게임 카페에 있는지 묻거나 추정하지 않습니다.
- 특정 게임이 "현재 사용자가 있는 보드게임 카페에 있는지" 판단하지 않습니다.
- 카페별 선반 위치, 재고, 대여 가능 여부, 임시 품절 여부를 다루지 않습니다.
- 카페별 추천, 카페별 인기 게임, 카페별 재고 관리 기능을 제공하지 않습니다.

앞으로 DB에는 **보드게임 자체에 대한 정보만 저장**합니다.

## 새 서비스 목표

이 앱은 사용자가 보드게임을 잘 모를 때 다음을 도와주는 서비스입니다.

1. 보드게임 박스나 구성품 사진을 찍으면 어떤 보드게임인지 식별합니다.
2. 식별된 보드게임의 짧은 설명, 난이도, 인원수, 플레이 시간, 장르, 태그를 보여줍니다.
3. 사용자의 검색/조회/플레이/추천 클릭 기록을 바탕으로 다른 보드게임을 추천합니다.
4. 전체 보드게임 DB에서 검색, 필터, 정렬을 제공합니다.

앱의 핵심 질문은 더 이상 "이 카페에 있나요?"가 아닙니다.

새 핵심 질문은 다음입니다.

- "이 게임이 뭔가요?"
- "처음 해도 쉬운가요?"
- "몇 명이 하기 좋나요?"
- "비슷한 게임은 뭐가 있나요?"
- "내 취향에는 어떤 보드게임이 맞나요?"

## 현재 코드에서 제거해야 할 개념

아래 개념은 백엔드, 프론트엔드, 문서, 테스트, 관리자 페이지 프롬프트에서 제거하거나 일반화하세요.

- `cafe`
- `cafes`
- `cafeId`
- `currentCafe`
- `cafe_inventory`
- `inventory`
- `shelfLocation`
- `isAvailableInCafe`
- `temporaryUnavailable`
- `staffPick`가 카페 기준일 경우
- 카페별 인기/추천 점수
- 카페별 QR 코드
- 현재 위치/근처 매장
- 현재 카페 보유 여부
- 선반 위치
- 대여 가능 여부
- 보드게임 카페 재고 관리

단, 문서에서 "이전 방향성"을 설명하는 과거 기록은 필요하면 짧게 남길 수 있습니다. 하지만 사용자-facing 기능과 다음 작업 목표에서는 제거해야 합니다.

## 새 데이터 모델 방향

유지할 핵심 테이블:

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

제거하거나 더 이상 사용하지 않을 테이블:

- `cafes`
- `cafe_inventory`

SQLite 마이그레이션은 신중히 처리하세요.

MVP에서는 다음 중 하나를 선택할 수 있습니다.

1. 새 DB 스키마로 재생성하는 개발용 리셋 방식
2. 기존 DB에서 `cafes`, `cafe_inventory`를 남겨두되 API/프론트에서 더 이상 사용하지 않는 호환 방식
3. 명시적 마이그레이션으로 카페 테이블을 제거하는 방식

Railway Volume에 이미 운영 데이터가 있다면, 바로 삭제하지 말고 백업 후 진행하세요.

## 백엔드 API 변경 목표

### 제거할 API

다음 API는 제거하거나 deprecated 처리하세요.

- `GET /cafes/nearby`
- `GET /cafes/{cafeId}`
- `GET /cafes/by-qr/{qrCode}`
- `GET /cafes/{cafeId}/games`
- `POST /admin/cafes`
- `PATCH /admin/cafes/{cafeId}`
- `PUT /admin/cafes/{cafeId}/inventory`
- 카페/재고 관련 관리자 로그 또는 상태 API

### 유지/강화할 API

다음 API는 유지하고 카페 의존성을 제거하세요.

- `GET /health`
- `GET /meta/schema`
- `GET /games`
- `GET /games/search`
- `GET /games/{gameId}`
- `GET /games/{gameId}/similar`
- `POST /sessions`
- `POST /users`
- `POST /events`
- `GET /users/{userId}/history`
- `POST /users/{userId}/played-games`
- `POST /users/{userId}/hidden-games`
- `DELETE /users/{userId}/data`
- `POST /recommendations`
- `GET /users/{userId}/recommendation-profile`
- `POST /recognitions`
- `GET /recognitions/{recognitionId}`
- `POST /recognitions/{recognitionId}/confirm`
- `POST /admin/games`
- `PATCH /admin/games/{gameId}`

### 새로 고려할 API

필요하다면 다음 API를 추가하세요.

- `GET /admin/games`
- `POST /admin/games/{gameId}/aliases`
- `DELETE /admin/games/{gameId}/aliases/{aliasId}`
- `GET /admin/events`
- `GET /admin/recognitions`
- `GET /admin/recommendations`

관리자 API도 이제 카페/재고 관리가 아니라 **보드게임 DB 품질 관리**에 집중해야 합니다.

## 인식 API 변경

`POST /recognitions`에서 `cafeId` 파라미터를 제거하세요.

기존 응답에서 제거할 필드:

- `isAvailableInCafe`
- `shelfLocation`
- 카페 보유 여부 관련 메시지

새 응답은 다음에 집중합니다.

- `recognitionId`
- `topCandidate`
- `candidates`
- `unmatchedCandidates`
- `needsRetake`
- `message`
- `imageRetention`
- `externalProcessing`

각 candidate에는 다음이 있으면 충분합니다.

- `game`
- `nvidiaConfidence`
- `matchScore`
- `confidence`
- `needsRetake`
- `message`
- `evidence`

## 추천 API 변경

`POST /recommendations`에서 `cafeId`를 제거하세요.

추천 입력은 다음 중심으로 재설계합니다.

- `userId`
- `sessionId`
- `peopleCount`
- `remainingMinutes`
- `mood`
- `preferredDifficulty`
- `preferredGenres`
- `excludeGameIds`
- `previouslyPlayedGameIds`
- `limit`

추천 점수에서 제거할 요소:

- 현재 카페 보유 여부 가중치
- 카페별 대여 가능 여부
- 카페별 인기 점수
- 매장 추천 여부
- 선반 위치

추천 점수에서 유지/강화할 요소:

- 인원수 적합성
- 플레이 시간 적합성
- 난이도 적합성
- 분위기/태그 적합성
- 사용자 이벤트 기반 취향
- 플레이 기록
- 숨김 게임 제외
- 비슷한 장르/태그

추천 이유 예시:

- "4명이 하기 좋아요"
- "30분 안에 끝내기 쉬워요"
- "이전에 본 전략 게임과 비슷해요"
- "처음 해도 쉬운 게임이에요"
- "협력 게임을 자주 봐서 추천했어요"

절대 사용하지 말아야 할 추천 이유:

- "지금 이 카페에 있어요"
- "현재 매장에 바로 대여 가능해요"
- "선반 A-3에 있어요"
- "이 매장의 추천 게임이에요"

## 프론트엔드 변경 목표

사용자 화면에서 보드게임 카페 관련 문구와 UI를 제거하세요.

제거할 화면/문구:

- 현재 매장
- 카페 선택
- QR로 매장 인식
- 근처 매장
- 카페 게임
- 이 카페에 있는 게임
- 선반 위치
- 직원에게 위치 묻기
- 현재 매장 없음
- 매장 보유 우선
- 카페별 보유 게임 필터

새 화면 구조 제안:

- `홈`
- `스캔`
- `추천`
- `게임 목록`
- `상세`

`카페 게임` 탭은 `게임 목록` 또는 `보드게임 DB`로 바꾸세요.

홈 화면 문구 예시:

- "사진으로 보드게임을 찾고, 내 취향에 맞는 다음 게임을 추천받아요."
- "카페 보유 여부가 아니라 보드게임 자체의 특징과 취향을 기준으로 도와줍니다."

게임 목록 화면:

- 전체 보드게임 DB 검색
- 인원수 필터
- 플레이 시간 필터
- 난이도 필터
- 장르 필터
- 태그 필터
- 초보자 추천
- 아이와 가능
- 파티 게임
- 전략 게임

상세 화면:

- 규칙 요약
- 인원수
- 플레이 시간
- 난이도
- 장르/태그
- 추천 이유
- 비슷한 게임

상세 화면에서 선반 위치나 대여 가능 여부는 제거하세요.

## 관리자 페이지 방향 변경

관리자 페이지는 카페/재고 관리가 아니라 보드게임 DB 관리에 집중합니다.

관리자 페이지에서 유지할 기능:

- 게임 목록 조회
- 게임 생성
- 게임 수정
- 게임 별칭 관리
- 게임 관계 관리
- 최근 인식 로그 조회
- 최근 추천 로그 조회
- 사용자 이벤트 요약

관리자 페이지에서 제거할 기능:

- 카페 생성/수정
- 카페별 재고 관리
- 선반 위치 수정
- 대여 가능 여부 수정
- 임시 품절 여부 수정
- 매장 추천 여부 수정

## 문서 변경 목표

다음 문서에서 보드게임 카페별 보유 목록, 현재 카페 판단, 재고 관리, 선반 위치 관련 내용을 제거하거나 과거 기록으로만 정리하세요.

- `README.md`
- `SUMMARY.md`
- `AI_APP_GOAL_PROMPT.md`
- `BACKEND_BUILD_PROMPT.md`
- `ADMIN_PAGE_PROMPT.md`
- `RAILWAY_DEPLOYMENT.md`

`NEXT_WORK_PROMPT.md`는 이 방향 전환 작업이 완료된 뒤 다시 최신 다음 작업으로 갱신하세요.

## 테스트 변경 목표

기존 테스트 중 카페 관련 테스트는 삭제하거나 일반 게임 DB 기준으로 바꾸세요.

추가/수정할 테스트:

- 추천 API가 `cafeId` 없이 동작합니다.
- 인식 API가 `cafeId` 없이 동작합니다.
- 인식 후보 응답에 `isAvailableInCafe`가 없습니다.
- 추천 응답에 선반 위치나 카페 보유 여부가 없습니다.
- 게임 목록 API가 전체 DB 기준 필터링을 제공합니다.
- 프론트 문구에 "카페", "매장", "선반", "대여 가능" 같은 제거 대상 문구가 남아 있지 않은지 확인합니다.
- 관리자 API가 카페/재고 관리 기능을 노출하지 않습니다.
- 데이터 삭제와 개인정보 정책 테스트는 계속 통과합니다.

## 구현 순서

1. 현재 카페 관련 코드 사용처를 전부 검색합니다.
2. 제거할 항목과 유지할 항목을 목록화합니다.
3. 백엔드 모델과 API에서 카페 의존성을 제거합니다.
4. 추천 로직에서 카페/재고 가중치를 제거합니다.
5. 인식 로직에서 카페 보유 여부 계산을 제거합니다.
6. 프론트 탭과 문구를 일반 보드게임 DB 기준으로 바꿉니다.
7. 관리자 페이지/프롬프트에서 카페/재고 관리 방향을 제거합니다.
8. 테스트를 수정하고 새 테스트를 추가합니다.
9. README/SUMMARY 등 문서를 새 방향성으로 갱신합니다.
10. Railway 환경에서 `/health`, `/games`, `/recommendations`, `/recognitions`를 다시 검증합니다.

## 완료 기준

이번 방향 전환은 다음 조건을 만족하면 완료입니다.

- 사용자-facing UI에서 보드게임 카페/현재 매장/선반/재고/대여 가능 여부가 사라집니다.
- 백엔드 추천과 인식 API가 `cafeId` 없이 동작합니다.
- DB 운영 목표가 카페별 보유 목록이 아니라 보드게임 마스터 DB 관리로 바뀝니다.
- 카페/재고 관련 관리자 기능이 제거되거나 비활성화됩니다.
- 자동 테스트가 통과합니다.
- Railway 배포 후 모바일에서 스캔, 추천, 게임 목록, 상세 조회가 정상 동작합니다.
- 문서가 새 방향성과 일치합니다.

## 중요한 주의사항

- 기존 Railway Volume의 DB를 바로 파괴하지 마세요.
- 마이그레이션 전 백업 또는 새 DB 경로 테스트를 먼저 고려하세요.
- 법적 리스크 회피가 방향 전환의 핵심이므로, 카페별 보유 게임을 암시하는 문구도 제거하세요.
- "보드게임 카페에서 쓸 수 있는 앱"이라는 사용 상황 자체는 남길 수 있지만, 특정 카페의 보유 여부를 판단하는 기능은 제거해야 합니다.
- 사용자가 직접 게임명을 검색하거나 사진으로 식별하는 흐름은 유지합니다.
