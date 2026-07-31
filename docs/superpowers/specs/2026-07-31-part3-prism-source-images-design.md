# 파트 3 PRISM 원본 이미지 교체 설계

## 목적

파트 3 슬라이드에서 폐기하기로 한 과거 도식을 밝은 배경으로 재생성한
이미지를 제거한다. PRISM 설명 슬라이드는
`prism-insight/docs/PIPELINE_ARCHITECTURE_ko.md`가 참조하는 검증 이미지
14개를 진실 원천으로 사용하고, Lecture-prism을 설명하기 위해 새로 만든
보조 이미지만 함께 사용한다.

## 자산 원칙

1. `PIPELINE_ARCHITECTURE_ko.md`의 이미지 14개는 원본 파일과 SHA-256이
   같아야 한다.
2. PRISM의 기존 기능을 설명하는 슬라이드는 대응하는 원본 이미지를 직접
   참조한다.
3. 기존 도식을 재생성한 `*-light.png` 일곱 개는 슬라이드에서 사용하지 않고
   저장소에서도 삭제한다.
4. Lecture-prism 비교나 원본에 없는 세부 설명을 위해 새로 만든 다음 이미지는
   유지한다.
   - Lecture-prism 소스 맵
   - 분석 에이전트 지도
   - 정량 에이전트 핵심 프롬프트
   - 맥락 에이전트 핵심 프롬프트
   - 운영 보조 루프
   - 메모리 압축 구조

## 슬라이드 매핑

| 설명 | 사용할 PRISM 원본 이미지 |
|---|---|
| 전체 파이프라인 | `full-pipeline-overview.png` |
| 시장 상태와 배치 제어 | `market-pulse-batch-control-overview.png` |
| 분산일과 상태 전환 | `distribution-day-state-transitions.png` |
| 오전·오후 여섯 발견 조건 | `screening-six-triggers-overview.png` |
| 후보 재정렬 | `candidate-screening-reranking-overview.png` |
| 시장 체제와 진입 정책 | `trading-regime-entry-overview.png` |
| 여섯 방향 종목 분석 | `screening-analysis-deep-dive.png` |
| CAN SLIM C·A·N·S | `can-slim-company-supply-checks.png` |
| CAN SLIM L·I·M | `can-slim-leadership-market-checks.png` |
| 신규 진입 게이트 | `entry-gates-overview.png` |
| 피라미딩과 포트폴리오 | `pyramiding-portfolio-overview.png` |
| 매도 흐름 | `trading-exit-overview.png` |
| 독립 보호 도구 | `position-protection-loops.png` |
| 피드백과 재진입 | `feedback-reentry-overview.png` |

## 함께 고칠 자료

- 파트 3 슬라이드 조각과 최종 HTML
- 강사용 실습 진행 스크립트
- 수강생 붙여넣기 프롬프트

강사용·수강생 자료에서는 원본 그림의 범위와 Lecture-prism의 축소 구현을
혼동하지 않도록 출처와 대응 파일을 명시한다.

## 검증

- 원본 14개와 강의 저장소 사본의 SHA-256 일치
- 파트 3 최종 HTML에서 `*-light.png` 참조 0개
- 38장 전체 이미지 로드 실패 0개
- 38장 전체 가로·세로 오버플로 0개
- 변경 슬라이드 육안 검사
- PRISM 문서·코드와 강의 문구의 사실 관계 재대조
