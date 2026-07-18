# 보드게임 데이터 출처 정책

## 허용 범위

- 게임의 식별자와 이름 같은 구조화 메타데이터는 Wikidata EntityData를 사용합니다.
- `dataSourceUrl`에는 `https://www.wikidata.org/wiki/Special:EntityData/Q....json` 형식의 엔터티 URL을 기록합니다.
- Wikidata 구조화 데이터의 라이선스는 `CC0-1.0`으로 기록합니다.
- 한국어 소개와 규칙 요약은 외부 설명을 복사하지 않고 프로젝트에서 새로 작성하며 `contentLicense=project-authored`로 기록합니다.
- 모든 행에 `reviewedAt`과 `reviewedBy`를 기록합니다.

Wikidata의 메인·Property·Lexeme 구조화 데이터는 CC0입니다. 정책과 다운로드 안내는 다음 공식 문서를 기준으로 합니다.

- https://www.wikidata.org/wiki/Wikidata:Licensing
- https://www.wikidata.org/wiki/Wikidata:Data_access

## 이미지 정책

- 이미지 URL은 파일 페이지에서 라이선스와 저작자와 원본 출처를 각각 확인한 경우에만 등록합니다.
- URL만 발견했거나 상품 이미지 사용 권한이 불명확하면 이미지 관련 네 열을 모두 비웁니다.
- 이미지를 등록할 때 `imageUrl`, `imageSource`, `imageLicense`, `imageAlt`를 함께 입력합니다.
- `unverified` 라이선스는 운영 데이터로 승인하지 않습니다.

현재 51개 준비 데이터셋은 이미지 권리를 별도로 확보하지 않았으므로 이미지 열을 비웠습니다.

## 사용하지 않는 출처

BoardGameGeek XML API는 현재 비상업적 사용 제한과 앱 등록·토큰 승인이 적용되므로 기본 데이터 수집 출처로 사용하지 않습니다. 상업적 이용은 별도 라이선스 계약 전에는 허용하지 않습니다.

- https://boardgamegeek.com/wiki/page/XML_API_Terms_of_Use
- https://boardgamegeek.com/using_the_xml_api
- https://boardgamegeek.com/wiki/page/BGG_XML_API_Commercial_Use

## 검토 절차

1. 고정 slug와 Wikidata Q ID가 같은 게임을 가리키는지 확인합니다.
2. 인원·시간·난이도·장르를 사람이 검토합니다.
3. 한국어 소개와 규칙 요약을 프로젝트 문장으로 작성합니다.
4. 별칭 충돌과 중복 ID가 없는지 CSV 전체 미리보기를 실행합니다.
5. 이미지 권리가 확인되지 않았다면 이미지 열을 비웁니다.
6. `all_or_nothing` 방식으로만 최초 적용합니다.
