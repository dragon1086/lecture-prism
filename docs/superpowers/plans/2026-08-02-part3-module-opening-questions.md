# Part 3 Module Opening Questions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 파트 3의 네 모듈을 실제 투자 상황 질문으로 열고, 수강생의 준비 수준에 맞는 서로 다른 참여 활동으로 바꾼다.

**Architecture:** 슬라이드 원본의 네 시작 질문을 교체하고, 모듈 3에는 결정론적 HTML 사례 슬라이드를 넣는다. 기존 P3-S21~P3-S29를 한 장씩 이동하고 중복 전환 P3-S30을 제거해 총 38장을 유지한다. 강사용 스크립트와 계약 테스트가 질문·활동·슬라이드 순서를 함께 고정한다.

**Tech Stack:** HTML/CSS 슬라이드 조각, Markdown 강사용 스크립트, Node.js 덱 조합기, Python unittest 계약 테스트, Headless Chrome PDF 렌더링

## Global Constraints

- 파트 3은 정확히 38장을 유지한다.
- 실제 주문·브로커·계좌·시크릿을 사용하지 않는다.
- 모듈 3 사례의 숫자는 교육용 고정값이며 HTML 텍스트로 표시한다.
- 수강생 프롬프트의 마지막 세 질문은 에이전트가 답하지 않는다.
- 기존 PRISM 매매 이미지를 삭제하지 않는다.
- 4·5쪽 이미지 개편은 이 계획의 범위 밖이다.

---

### Task 1: 질문·활동·사례 계약을 먼저 실패시킨다

**Files:**
- Modify: `tests/test_part3_student_learning_contract.py`
- Modify: `tests/test_part3_deck_contract.py`

**Interfaces:**
- Consumes: `PART3_SOURCE`, `INSTRUCTOR_SCRIPT`, `_slide()` 기존 테스트 도우미
- Produces: 네 질문, 네 활동, P3-S21 사례, 38장 순서를 고정하는 회귀 계약

- [ ] **Step 1: 네 확정 질문과 활동 방식 테스트를 추가한다**

`test_instructor_uses_varied_learner_actions_for_each_module()`에서 네 질문을 확인하고 `60초 짝 대화`, `정보 세 가지`, `A/B 투표`, `바로 다시 산다 / 하루 더 본다 / 조건을 다시 확인한다`를 각각 확인한다. 기존 `60초 짝 대화` 4회 조건은 제거한다.

- [ ] **Step 2: P3-S21 판단 사례와 38장 순서 테스트를 추가한다**

P3-S21에서 `BUY 8점`, 네 가격·손익비 기준, 두 선택지, 교육용 사례 표기를 확인한다. P3-S22~P3-S30에 기존 매매 이미지·비교·주문 수명주기·P3-M3 프롬프트가 남는지 확인한다.

- [ ] **Step 3: 테스트가 현재 문구와 구조 때문에 실패하는지 확인한다**

Run: `python3 -m unittest tests.test_part3_student_learning_contract tests.test_part3_deck_contract -v`

Expected: 새 질문·다양한 활동·P3-S21 사례가 없어 FAIL.

### Task 2: 슬라이드 질문과 모듈 3 사례를 구현한다

**Files:**
- Modify: `강의자료/deck-src/part3/02-context.html`
- Modify: `강의자료/deck-src/part3/03-system-map.html`
- Modify: `강의자료/deck-src/part3/04-guided-practice.html`
- Modify: `강의자료/deck-src/part3/05-bridge.html`
- Modify: `강의자료/deck-src/deck-manifest.json`
- Modify: `강의자료/deck-src/part3-index.md`

**Interfaces:**
- Consumes: 기존 `.slide`, `.flow`, `.step`, `.takeaway` 공통 CSS
- Produces: P3-S07·14·21·31 확정 질문과 P3-S21 교육용 판단표

- [ ] **Step 1: P3-S07·14·31 제목을 확정 질문으로 바꾼다**

manifest와 index도 같은 문장으로 맞춘다.

- [ ] **Step 2: P3-S21을 교육용 판단 사례로 교체한다**

한 화면에서 AI 의견, 현재가·목표가·손절가, 계산된 손익비와 코드 기준, `주문한다 / 보류한다` 선택지를 큰 글자로 보여 준다. 하단에는 `실제 종목 추천이 아닌 연습 사례`라고 표시한다.

- [ ] **Step 3: 기존 P3-S21~P3-S29를 P3-S22~P3-S30으로 이동한다**

HTML 주석 ID, `.pagenum`, manifest, index를 함께 갱신한다. 기존 P3-S30 전환 슬라이드는 제거한다.

- [ ] **Step 4: 덱을 재생성한다**

Run: `node 강의자료/deck-src/build-decks.mjs`

Expected: `part3: 38 slides`, `part4: 40 slides`.

### Task 3: 강사용 진행을 활동별로 바꾼다

**Files:**
- Modify: `강의자료/강사용_실습진행_스크립트.md`
- Test: `tests/test_part3_student_learning_contract.py`

**Interfaces:**
- Consumes: Task 2의 네 질문과 P3-S21 사례 값
- Produces: 경험 대화, 정보 비교, 사례 투표, 재진입 선택의 네 진행 방식

- [ ] **Step 1: 모듈 1은 20초 판단과 60초 짝 대화를 유지한다**

- [ ] **Step 2: 모듈 2를 정보 세 가지 적기와 옆 사람 비교로 바꾼다**

- [ ] **Step 3: 모듈 3을 P3-S21 사례 확인, A/B 투표, 주문 0건 공개, 내 안전선 한 문장으로 바꾼다**

- [ ] **Step 4: 모듈 4를 세 재진입 선택지와 이유 한 문장으로 바꾼다**

- [ ] **Step 5: 기준선 제목과 모듈 4 구현 한계를 맞춘다**

네 기준선 제목을 `수강생 판단 뒤 lecture-prism 기준선`으로 바꾸고, 다음 날 자동 재진입 금지가 없다는 문장을 추가한다.

### Task 4: 렌더링과 전체 회귀를 검증한다

**Files:**
- Verify: `강의자료/파트3_슬라이드.html`
- Verify: `tests/test_part3_student_learning_contract.py`
- Verify: `tests/test_part3_deck_contract.py`

**Interfaces:**
- Consumes: Tasks 1~3의 생성본
- Produces: 38장 덱과 회귀 검증 증거

- [ ] **Step 1: 관련 계약 테스트를 통과시킨다**

Run: `python3 -m unittest tests.test_part3_student_learning_contract tests.test_part3_deck_contract -v`

Expected: PASS.

- [ ] **Step 2: API 키 없는 데모를 완주한다**

Run: `LECTURE_PROFILE=mock LECTURE_NOTIFY_DISCORD=0 LECTURE_SAVE_REPORTS=0 python3 main.py`

Expected: simulation 파이프라인 완료.

- [ ] **Step 3: PDF로 렌더링해 P3-S07·14·21·31을 원본 크기로 확인한다**

Expected: 제목·숫자·선택지의 잘림과 겹침 0건.

- [ ] **Step 4: 전체 테스트와 diff 검사를 통과시킨다**

Run: `python3 -m unittest discover -s tests -q`

Expected: 0 failures.

Run: `git diff --check`

Expected: 출력 없음.

- [ ] **Step 5: Lore 형식으로 커밋한다**

변경 파일과 테스트 결과를 확인한 뒤 질문·활동·덱 순서 변경을 한 커밋에 기록한다.

