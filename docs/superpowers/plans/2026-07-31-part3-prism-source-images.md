# Part 3 PRISM Source Images Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 파트 3의 PRISM 설명 슬라이드를 `PIPELINE_ARCHITECTURE_ko.md` 원본 이미지 14개로 교체하고, Lecture-prism 전용 신규 보조 이미지만 유지한다.

**Architecture:** `../prism-insight/prism-insight/docs/images/architecture/`를 PRISM 이미지의 단일 진실 원천으로 삼고 `docs/assets/prism-insight/`에 동일 파일을 동기화한다. 슬라이드 원본 조각은 PRISM 기능에는 동기화된 원본을, Lecture-prism 비교에는 강의용 신규 이미지를 참조하며, 빌더가 최종 HTML을 다시 생성한다.

**Tech Stack:** HTML/CSS, Node.js 표준 라이브러리 빌더, PNG/SVG 자산, SHA-256, Chrome DOM 렌더링 검사

## Global Constraints

- 원본 이미지 14개는 `PIPELINE_ARCHITECTURE_ko.md`가 참조하는 파일과 SHA-256이 같아야 한다.
- PRISM 기능 설명 슬라이드에서 `*-light.png`를 사용하지 않는다.
- Lecture-prism 소스 맵, 분석 에이전트·프롬프트, 운영 보조 루프, 메모리 압축 이미지는 유지한다.
- 파트 3은 38장 구성을 유지한다.
- 슬라이드, 강사용 진행 스크립트, 수강생 프롬프트를 함께 수정한다.
- API 키 없는 데모와 실거래 차단 코드는 변경하지 않는다.

---

### Task 1: PRISM 원본 이미지 동기화

**Files:**
- Modify: `docs/assets/prism-insight/full-pipeline-overview.png`
- Modify: `docs/assets/prism-insight/market-pulse-batch-control-overview.png`
- Modify: `docs/assets/prism-insight/candidate-screening-reranking-overview.png`
- Modify: `docs/assets/prism-insight/trading-regime-entry-overview.png`
- Modify: `docs/assets/prism-insight/screening-analysis-deep-dive.png`
- Modify: `docs/assets/prism-insight/entry-gates-overview.png`
- Modify: `docs/assets/prism-insight/pyramiding-portfolio-overview.png`
- Modify: `docs/assets/prism-insight/trading-exit-overview.png`
- Modify: `docs/assets/prism-insight/feedback-reentry-overview.png`
- Verify unchanged/equal: 나머지 원본 이미지 5개

**Interfaces:**
- Consumes: `../prism-insight/prism-insight/docs/PIPELINE_ARCHITECTURE_ko.md`의 이미지 경로 14개
- Produces: 원본과 SHA-256이 같은 `docs/assets/prism-insight/*.png` 14개

- [ ] **Step 1: 원본 문서의 이미지 목록을 추출한다**

Run:

```bash
rg -o 'images/architecture/[A-Za-z0-9._-]+\.png' ../prism-insight/prism-insight/docs/PIPELINE_ARCHITECTURE_ko.md
```

Expected: 중복 없는 이미지 경로 14개.

- [ ] **Step 2: 14개 원본 이미지를 강의 저장소에 동기화한다**

Run: 문서에서 추출한 파일명 각각을
`../prism-insight/prism-insight/docs/images/architecture/`에서
`docs/assets/prism-insight/`로 복사한다.

Expected: 대상 파일 14개가 모두 존재한다.

- [ ] **Step 3: 원본과 대상 해시를 검증한다**

Run: 파일명별 SHA-256을 계산해 원본과 대상이 같은지 비교한다.

Expected: `matched=14`, `mismatched=0`, `missing=0`.

### Task 2: 슬라이드 이미지 참조 교체

**Files:**
- Modify: `강의자료/deck-src/part3/01-first-success.html`
- Modify: `강의자료/deck-src/part3/02-context.html`
- Modify: `강의자료/deck-src/part3/03-system-map.html`
- Modify: `강의자료/deck-src/part3/04-guided-practice.html`
- Modify: `강의자료/deck-src/part3/05-bridge.html`

**Interfaces:**
- Consumes: Task 1의 `docs/assets/prism-insight/*.png`
- Produces: PRISM 기능 슬라이드의 원본 이미지 참조와 Lecture-prism 보조 이미지 참조

- [ ] **Step 1: 일곱 개 `*-light.png` 참조를 대응 원본으로 바꾼다**

Exact mapping:

```text
prism-market-pulse-batch-control-light.png -> market-pulse-batch-control-overview.png
prism-trading-regime-entry-light.png -> trading-regime-entry-overview.png
prism-candidate-screening-reranking-light.png -> candidate-screening-reranking-overview.png
prism-entry-gates-light.png -> entry-gates-overview.png
prism-pyramiding-portfolio-light.png -> pyramiding-portfolio-overview.png
prism-trading-exit-light.png -> trading-exit-overview.png
prism-feedback-reentry-light.png -> feedback-reentry-overview.png
```

각 대상은 `../docs/assets/prism-insight/<filename>`을 참조한다.

- [ ] **Step 2: 모든 PRISM 원본 슬라이드의 alt 문구를 원본 그림 의미에 맞춘다**

Expected: “밝은 배경으로 재구성한 강의용 그림” 문구 0개.

- [ ] **Step 3: 신규 보조 이미지 참조가 유지되는지 확인한다**

Expected retained references:

```text
assets/lecture-prism-source-map.svg
assets/prism-analysis-agent-map.png
assets/prism-analysis-prompt-quant.png
assets/prism-analysis-prompt-context.png
assets/prism-auxiliary-operations-loop.png
assets/prism-memory-compression-operations.png
```

### Task 3: 강사용·수강생 자료의 출처 경계 수정

**Files:**
- Modify: `강의자료/강사용_실습진행_스크립트.md`
- Modify: `lecture/exercises/수강생_붙여넣기_프롬프트_파트3.md`

**Interfaces:**
- Consumes: 설계 문서의 원본/보조 이미지 구분
- Produces: 강사가 출처를 설명하고 수강생이 PRISM과 Lecture-prism의 구현 범위를 구분하는 문구

- [ ] **Step 1: 강사용 스크립트에서 모듈 1–4 이미지 출처를 명시한다**

각 모듈 시작 부분에 다음 구분을 자연어로 반영한다.

```text
PRISM 기능 그림: PIPELINE_ARCHITECTURE_ko.md 원본
Lecture-prism 비교 그림: 강의용 신규 보조 자료
```

- [ ] **Step 2: 수강생 프롬프트의 사실 확인 기준을 명시한다**

수강생이 구조를 물을 때 `PIPELINE_ARCHITECTURE_ko.md`와 PRISM 코드,
Lecture-prism 대응 파일을 함께 대조하도록 기존 프롬프트를 보강한다.

- [ ] **Step 3: 폐기 대상 표현을 검색한다**

Run:

```bash
rg -n '밝은 배경으로 재구성|prism-.*-light\.png' 강의자료 lecture/exercises/수강생_붙여넣기_프롬프트_파트3.md
```

Expected: 사용 중인 파트 3 자료에서 결과 0개.

### Task 4: 최종 HTML 재생성과 자동 검증

**Files:**
- Modify (generated): `강의자료/파트3_슬라이드.html`
- Verify: `강의자료/deck-src/part3-index.md`

**Interfaces:**
- Consumes: Task 2의 슬라이드 조각
- Produces: 38장 최종 HTML

- [ ] **Step 1: 덱을 다시 빌드한다**

Run:

```bash
node 강의자료/deck-src/build-decks.mjs
```

Expected: `part3: 38 slides`.

- [ ] **Step 2: 생성 결과의 슬라이드·자산 계약을 검사한다**

Expected:

```text
section[data-slide-id] = 38
*-light.png references = 0
PRISM source image references = 14
```

- [ ] **Step 3: Chrome에서 전체 덱을 렌더링한다**

검사 항목:

```text
brokenImages = 0
horizontalOverflow = 0
verticalOverflow = 0
```

- [ ] **Step 4: 변경 슬라이드를 육안 검사한다**

Inspect: P3-S06, S07, S09, S11, S14, S23, S24, S25, S31.

Expected: 원본 이미지가 왜곡 없이 크게 보이고 제목·캡션과 일치한다.

### Task 5: 최종 계약 검사와 커밋

**Files:**
- Verify: 모든 변경 파일

**Interfaces:**
- Consumes: Tasks 1–4의 결과
- Produces: 리뷰 가능한 단일 구현 커밋

- [ ] **Step 1: 문서와 자산 계약을 검사한다**

Run:

```bash
git diff --check
git status --short
```

Expected: 공백 오류 0개, `_workspace/`는 스테이징하지 않는다.

- [ ] **Step 2: 민감정보와 로컬 절대 경로를 검사한다**

Expected: API 키·토큰·계좌정보·`/Users/` 경로 0개.

- [ ] **Step 3: 구현 파일을 Lore 형식으로 커밋한다**

Commit intent: 검증된 PRISM 원본 그림만 강의의 기능 설명에 사용한다.

