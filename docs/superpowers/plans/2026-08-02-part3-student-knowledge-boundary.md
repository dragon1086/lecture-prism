# Part 3 Student Knowledge Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 파트 3 수강생이 원본 PRISM 저장소나 아직 배우지 않은 뒤 모듈을 전제로 하지 않고, 현재 진도에 맞는 `lecture-prism` 프롬프트만 복사해 실행하게 한다.

**Architecture:** 원본 PRISM 비교는 슬라이드의 강사 설명 영역에 유지하고 수강생 실행 계약에서는 제거한다. 붙여넣기 프롬프트 파일을 유일한 프롬프트 원문으로 삼고, P3-S13과 강사용 스크립트는 해당 블록 번호와 현재 실습 목적만 안내한다.

**Tech Stack:** 정적 HTML 슬라이드, Markdown 수업 문서, Node.js 덱 조합기, Python `unittest`

## Global Constraints

- 파트 3 수강생은 원본 PRISM 저장소를 설치하거나 코드를 읽지 않는다.
- 프롬프트에는 해당 슬라이드까지 등장한 개념과 파일만 사용한다.
- 실제 주문·브로커·계좌·시크릿 금지와 mock-first 동작을 유지한다.
- 새 필수 의존성을 추가하지 않는다.
- 수강생용 프롬프트 원문은 `lecture/exercises/수강생_붙여넣기_프롬프트_파트3.md` 한 곳에만 둔다.
- `_workspace/**`의 기존 사용자 파일은 수정하거나 커밋하지 않는다.

---

### Task 1: 학습자 지식 경계를 문서 계약 테스트로 고정

**Files:**
- Create: `tests/test_part3_student_learning_contract.py`
- Read: `강의자료/deck-src/part3/02-context.html`
- Read: `강의자료/강사용_실습진행_스크립트.md`
- Read: `lecture/exercises/수강생_붙여넣기_프롬프트_파트3.md`

**Interfaces:**
- Consumes: P3-S13 HTML, `P3-M1`~`P3-M4` Markdown 구간, 강사용 모듈 안내
- Produces: 원본 대조 금지, 정확한 블록 복사 안내, 진도 밖 질문 금지를 검사하는 테스트

- [ ] **Step 1: 실패하는 계약 테스트 작성**

```python
def test_student_module_prompts_do_not_require_original_prism(self):
    for block in module_blocks("P3-M1", "P3-M2", "P3-M3", "P3-M4"):
        self.assertNotIn("PIPELINE_ARCHITECTURE_ko.md", block)
        self.assertNotIn("원본 PRISM", block)

def test_slide_13_points_to_the_single_prompt_source(self):
    self.assertIn("P3-M1 블록 전체", slide_13)
    self.assertNotIn("원본 PRISM과 비교", slide_13)

def test_module_one_asks_only_current_progress_questions(self):
    block = module_block("P3-M1")
    self.assertNotIn("뒤의 매수 방식과 왜 잘 맞는가", block)
    self.assertNotIn("이미지 생성", block)
    self.assertIn("후보로 뽑힌 것과 실제 매수 결정은 왜 다른지", block)
```

- [ ] **Step 2: 테스트가 현재 문구 때문에 실패하는지 확인**

Run: `python3 -m unittest tests.test_part3_student_learning_contract -v`

Expected: 원본 PRISM 비교, 축약 슬라이드 프롬프트, 미래 매수 방식 질문 때문에 FAIL

- [ ] **Step 3: 테스트 파일만 검토**

Run: `python3 -m py_compile tests/test_part3_student_learning_contract.py`

Expected: exit 0

---

### Task 2: 수강생 붙여넣기 프롬프트를 실제 진도 순서로 재작성

**Files:**
- Modify: `lecture/exercises/수강생_붙여넣기_프롬프트_파트3.md`
- Test: `tests/test_part3_student_learning_contract.py`

**Interfaces:**
- Consumes: P3-01 → P3-02 → P3-M1 → P3-M2 → P3-M3 → P3-M4 학습 순서
- Produces: 수강생이 한 블록씩 복사해 현재 모듈만 관찰하는 프롬프트 계약

- [ ] **Step 1: 머리말에서 원본 PRISM 비교 지침 제거**

`원본 PRISM과 비교할 때는` 문단을 삭제하고, 강사가 부르는 블록 하나만 실행한다는 안내를 유지한다.

- [ ] **Step 2: P3-M1을 스크리닝 관찰 실습으로 제한**

다음 결과만 요구한다.

```text
- screening.py 단독 mock 실행
- 입력 → 필터 → 정렬 → 최대 3개 후보
- 각 탈락·선정 이유를 쉬운 말로 설명
- mock과 --real 경로의 차이는 실행하지 않고 코드에서만 짧게 구분
- 후보 선정은 매수 확정이 아님을 확인
```

마지막 질문은 아래 세 개로 고정한다.

```text
어떤 조건이 종목을 가장 먼저 걸러냈는가?
남은 후보는 어떤 기준으로 순서가 정해졌는가?
후보로 뽑힌 것과 실제 매수 결정은 왜 다른가?
```

- [ ] **Step 3: P3-M2를 보고서 역할 관찰로 제한**

원본 파일 대조와 CAN SLIM 선행 설명을 제거한다. 여섯 AgentSpec, 편집 에이전트, 매수 필드 부재, 한 섹션 실패 시 해당 섹션만 폴백하는 구조만 확인한다.

- [ ] **Step 4: P3-M3은 해당 시점에 배운 매수·실행 경계만 묻기**

원본 매매 코드 대조를 제거한다. `buy_agent.py`, `trading.py`, `operations.py`의 일회성 simulation 실행과 안전 조건만 확인한다.

- [ ] **Step 5: P3-M4는 피드백·기억 압축 관찰만 묻기**

원본 메모리 코드 대조를 제거한다. BUY 기록과 SELL 결과 교훈, 단기→중기→장기 압축, 제한된 기억 조회만 확인한다.

- [ ] **Step 6: 예상 질문·성공 증거·회고 문장 전수 교정**

각 블록의 예상 질문은 실행 전에 답할 수 있어야 하고, 회고는 실행 결과만 보고 완성할 수 있어야 한다. `네 단계`처럼 현재 5단계 파이프라인과 어긋난 표현도 함께 바로잡는다.

- [ ] **Step 7: 계약 테스트 실행**

Run: `python3 -m unittest tests.test_part3_student_learning_contract -v`

Expected: P3-M1~M4 프롬프트 관련 검사는 PASS, 아직 P3-S13·강사용 안내 검사는 FAIL

---

### Task 3: 13쪽과 강사용 진행선을 단일 프롬프트 원문에 연결

**Files:**
- Modify: `강의자료/deck-src/part3/02-context.html`
- Modify: `강의자료/deck-src/deck-manifest.json`
- Modify: `강의자료/deck-src/part3-index.md`
- Modify: `강의자료/강사용_실습진행_스크립트.md`
- Test: `tests/test_part3_student_learning_contract.py`
- Test: `tests/test_part3_deck_contract.py`

**Interfaces:**
- Consumes: `P3-M1` Markdown 블록
- Produces: 슬라이드에서 정확한 블록 복사 행동과 강사·수강생 역할 분리를 안내하는 수업 흐름

- [ ] **Step 1: P3-S13을 복사 안내 화면으로 교체**

제목은 `프롬프트 파일에서 P3-M1 전체를 복사합니다`로 바꾸고, 본문은 다음 세 영역만 남긴다.

```text
1. 프롬프트 파일에서 P3-M1 블록 전체를 찾는다.
2. 코딩 에이전트에 한 번 붙여넣는다.
3. 필터 순서·탈락 이유·최종 후보를 확인한다.
```

안전 문구는 `코드는 고치지 않고 연습 데이터로 한 번만 실행합니다.`로 둔다.

- [ ] **Step 2: manifest와 인덱스 제목 동기화**

P3-S13의 제목을 소스 HTML과 동일하게 갱신하고 `promptId`는 `P3-M1`로 유지한다.

- [ ] **Step 3: 강사용 스크립트에 역할 경계 추가**

모듈 1~4의 수강생 행동 앞에 다음 진행 원칙을 반영한다.

```text
원본 PRISM과의 비교는 강사가 앞선 그림과 비교 슬라이드에서 설명합니다.
수강생은 원본 저장소를 받거나 대조하지 않고, 지금 배운 lecture-prism 모듈만 읽고 실행합니다.
```

- [ ] **Step 4: 계약 테스트 실행**

Run: `python3 -m unittest tests.test_part3_student_learning_contract tests.test_part3_deck_contract -v`

Expected: PASS

---

### Task 4: 덱 재생성·시각 검증·전체 회귀 검증

**Files:**
- Generate: `강의자료/파트3_슬라이드.html`
- Verify: `강의자료/deck-src/part3/02-context.html`
- Verify: `lecture/exercises/수강생_붙여넣기_프롬프트_파트3.md`
- Verify: `강의자료/강사용_실습진행_스크립트.md`

**Interfaces:**
- Consumes: 수정된 슬라이드 소스와 문서
- Produces: 발표용 파트 3 HTML과 완료 증거

- [ ] **Step 1: 발표용 덱 재생성**

Run: `node 강의자료/deck-src/build-decks.mjs`

Expected: `part3: 38 slides`, `part4: 40 slides`

- [ ] **Step 2: P3-S13을 1280×720 브라우저 화면으로 확인**

제목 한 줄 유지, 본문 잘림·겹침·넘침 0건, `P3-M1` 블록 전체 복사 안내가 화면에서 읽히는지 확인한다. `$visual-verdict` 결과를 `.omx/state/part3-student-boundary/ralph-progress.json`에 저장한다.

- [ ] **Step 3: 관련 계약 테스트 실행**

Run: `python3 -m unittest tests.test_part3_student_learning_contract tests.test_part3_deck_contract tests.test_prism_core_foundation_contract tests.test_documentation_architecture_contract -v`

Expected: 모든 테스트 PASS

- [ ] **Step 4: 기본 데모 회귀 검증**

Run: `LECTURE_PROFILE=mock LECTURE_NOTIFY_DISCORD=0 LECTURE_SAVE_REPORTS=0 python3 main.py`

Expected: API 키·실주문 없이 5단계 완주

- [ ] **Step 5: 문구·민감정보·diff 검사**

Run: `rg -n "원본 PRISM|PIPELINE_ARCHITECTURE_ko.md|뒤의 매수 방식과 왜 잘 맞는가" lecture/exercises/수강생_붙여넣기_프롬프트_파트3.md`

Expected: no matches

Run: `git diff --check`

Expected: exit 0

- [ ] **Step 6: 커밋 전 공개 범위 확인**

Run: `git status --short && git diff --cached --name-only`

Expected: `_workspace/**`, `.env`, `prism.db`, 보고서·로그·시크릿 파일이 스테이징되지 않음
