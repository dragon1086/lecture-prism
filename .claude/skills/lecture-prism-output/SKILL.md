---
name: lecture-prism-output
description: Use when a lecture-prism task will produce a long report, comparison, plan, diagnostic result, or other output that is hard to read in chat.
---

# lecture-prism Readable Output

긴 결과를 채팅에 길게 늘어놓지 않고, 먼저 짧은 요약을 보여 준 뒤 다시 열어 볼 수 있는 독립 HTML로 남깁니다.

## 간결성 기준

- HTML 첫 화면에는 결론 세 가지와 다음 행동 하나만 보여 줍니다.
- 본문은 `핵심 한 문장 → 근거 세 가지 이내 → 다음 행동 한 줄`로 씁니다.
- 같은 내용을 요약·표·상세 영역에 반복하지 않습니다.
- 일반 HTML 본문은 1,500자 안팎으로 끝냅니다. 원문 로그처럼 꼭 보존할 내용만 접힌 상세 영역에 둡니다.
- 표는 기본 5열·8행 이내로 줄이고, 더 긴 목록은 `기타 N건`으로 묶습니다.
- 채팅에는 네 줄 안팎만 남깁니다. 결과, HTML 경로, 중요한 확인 사항, 다음 작업 순서입니다.
- 서론, 작업 과정 재설명, 의미 없는 마무리 문장은 넣지 않습니다.
- 핵심 세 가지를 고른 뒤 나머지는 생략합니다. 중요한 정보가 아니면 HTML에도 넣지 않습니다.

## 기준

- 결과가 800자 이상이거나 표가 두 개 이상이면 HTML을 우선합니다.
- HTML은 `reports/interactive/YYYYMMDD-HHMM-짧은-이름.html`에 저장합니다.
- 외부 CDN과 새 의존성 없이 한 파일로 열려야 합니다.
- 화면 문구에는 `fluent-korean`을 적용합니다.
- HTML의 디자인과 구조는 `docs/lecture-prism-output-style.md`와 `docs/lecture-prism-output-template.html`을 따릅니다.

## 기본 응답

채팅에는 결과 한 줄, HTML 경로, 중요한 확인 사항, 다음 한 가지만 남깁니다. 상세 표·코드 위치·전후 비교·실패 경로는 HTML에서 접었다 펼쳐 읽게 합니다.

## 금지

- 긴 Markdown 표를 채팅에 전부 출력하지 않습니다.
- 확인하지 않은 결과를 성공으로 꾸미지 않습니다.
- HTML에 시크릿, 계좌 정보, 웹후크, 개인 경로를 넣지 않습니다.
- HTML을 만들었다고만 말하고 파일을 저장하지 않습니다.
