# Slide 34 Plain Korean Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 슬라이드 34의 운영 통계 설명을 비개발자 투자자가 한 번에 이해하는 한국어로 바꾸고 강사 스크립트와 맞춘다.

**Architecture:** 기존 HTML 덱 구조와 수치는 유지하고, P3-S34의 정보 순서와 표현만 바꾸다. 같은 내용을 매니페스트·인덱스·강사 스크립트에 반영한 뒤 정적 HTML을 재생성한다.

**Tech Stack:** HTML, Markdown, JSON, Node.js 덱 빌더, Python unittest, Chrome headless

## Global Constraints

- 최근 90일과 한국·미국 거래 건수를 바꾸지 않는다.
- 과거 교훈이 손실의 원인이라고 단정하지 않는다.
- 새 외부 자산이나 의존성을 추가하지 않는다.
- 수강생에게 보이는 문장은 일상어와 투자자 용어를 우선한다.

---

### Task 1: 학습 문구 계약 고정

**Files:**
- Modify: `tests/test_part3_deck_contract.py`

**Interfaces:**
- Consumes: P3-S34 HTML 문구
- Produces: 쉬운 표현과 금지 용어를 고정하는 unittest

- [ ] **Step 1:** P3-S34에 `과거 매매 교훈을 읽고 판단한 거래`, `수익으로 끝난 거래의 비율`, `기억은 정답지가 아닙니다`가 있는지 검사한다.
- [ ] **Step 2:** `메모리 참조 거래`, `비참조 거래`, `관찰 상관관계`, `인과 증명`, `표본 선택`, `시장 국면`이 없는지 검사한다.
- [ ] **Step 3:** `python3 -m unittest tests.test_part3_deck_contract -v`를 실행해 실패를 확인한다.

### Task 2: 슬라이드와 강사 스크립트 교정

**Files:**
- Modify: `강의자료/deck-src/part3/05-bridge.html`
- Modify: `강의자료/deck-src/deck-manifest.json`
- Modify: `강의자료/deck-src/part3-index.md`
- Modify: `강의자료/강사용_실습진행_스크립트.md`

**Interfaces:**
- Consumes: 최근 90일 거래 건수와 원래 관찰 결과
- Produces: 학생용 P3-S34와 같은 뜻의 강사 발화문

- [ ] **Step 1:** 비교 대상과 승률을 한국어로 풀어 쓴다.
- [ ] **Step 2:** 결과를 단정할 수 없는 이유를 세 문장으로 줄인다.
- [ ] **Step 3:** 제목과 하단 교훈을 매니페스트·인덱스·강사 스크립트에 동기화한다.
- [ ] **Step 4:** `python3 -m unittest tests.test_part3_deck_contract -v`를 실행해 통과를 확인한다.

### Task 3: 생성본과 실제 화면 검증

**Files:**
- Modify: `강의자료/파트3_슬라이드.html`

**Interfaces:**
- Consumes: deck-src 원본
- Produces: 38장 정적 HTML 덱

- [ ] **Step 1:** `node 강의자료/deck-src/build-decks.mjs`로 덱을 재생성한다.
- [ ] **Step 2:** Chrome headless로 34쪽을 1600×900 크기로 렌더링한다.
- [ ] **Step 3:** 제목 줄바꿈, 본문 잘림, 하단 교훈 넘침이 없는지 `visual-verdict` 90점 이상으로 확인한다.
- [ ] **Step 4:** `python3 -m unittest tests.test_part3_deck_contract tests.test_part3_student_learning_contract -v`와 `git diff --check`를 실행한다.
