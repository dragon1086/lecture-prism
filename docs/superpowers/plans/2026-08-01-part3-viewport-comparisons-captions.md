# Part 3 Viewport, Comparison Infographics, and Captions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Part 3 슬라이드를 브라우저 세로 공간에 맞춰 확대하고, 모듈별 비교 그림 4장과 이미지 단독 전체화면을 추가하며, PRISM 원본 그림 14개의 캡션을 원문에 맞게 교정한다.

**Architecture:** 1280×720 인쇄 캔버스는 유지하고 화면 모드에서만 JavaScript가 CSS `zoom` 배율을 계산한다. 모듈 비교 그림은 생성형 배경과 검증된 HTML 텍스트 레이어를 합쳐 1920×1080 PNG로 렌더링하며, 덱은 이 PNG를 일반 원본 그림처럼 표시한다. 이미지 뷰어는 덱 꼬리 스크립트에서 한 번 초기화한다.

**Tech Stack:** HTML/CSS/JavaScript, Node.js deck builder, Chrome rendering, Python 표준 라이브러리 `unittest`

## Global Constraints

- Part 3은 38장, 인쇄 캔버스는 1280×720을 유지한다.
- PRISM 원본 14장은 수정하지 않는다.
- 새 필수 패키지를 추가하지 않는다.
- 모든 비교 그림의 파일명과 함수명은 현재 코드에서 검증한 문자열만 사용한다.
- 기본 데모와 실거래 이중 안전 게이트를 변경하지 않는다.

---

### Task 1: 덱 정적 계약 테스트

**Files:**
- Create: `tests/test_part3_deck_contract.py`
- Inspect: `강의자료/deck-src/shared/part3-head.html`
- Inspect: `강의자료/deck-src/shared/part3-tail.html`

**Interfaces:**
- Consumes: 생성 전 덱 소스와 최종 `강의자료/파트3_슬라이드.html`
- Produces: 화면 배율·전체화면·비교 그림·캡션 계약을 검증하는 `unittest.TestCase`

- [ ] **Step 1: 현재 구현에서 실패하는 테스트 작성**

```python
class Part3DeckContractTests(unittest.TestCase):
    def test_screen_fit_and_fullscreen_viewer_are_declared(self):
        self.assertIn("--screen-scale", self.head)
        self.assertIn("requestFullscreen", self.tail)
        self.assertIn("fullscreenchange", self.tail)

    def test_four_module_comparison_assets_are_referenced(self):
        for name in ("screening", "analysis", "trading", "feedback"):
            self.assertIn(f"lecture-compare-{name}.png", self.sources)

    def test_all_architecture_captions_have_source_mapping(self):
        self.assertEqual(set(EXPECTED_CAPTIONS), set(self.source_image_names))
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m unittest tests.test_part3_deck_contract -v`
Expected: 화면 맞춤과 비교 자산 참조가 없어 FAIL

- [ ] **Step 3: 테스트 헬퍼에 소스 파일·이미지 크기 검사 추가**

표준 라이브러리 `html.parser`, `pathlib`, `struct`만 사용해 4개 PNG가 1920×1080인지, 비교 슬라이드가 카드형 `pattern-grid`를 더 이상 쓰지 않는지 검사한다.

- [ ] **Step 4: 테스트 파일만 커밋**

```bash
git add tests/test_part3_deck_contract.py
git commit
```

---

### Task 2: 모듈별 비교 인포그래픽 4장

**Files:**
- Create: `강의자료/assets/comparison-src/module-comparisons.html`
- Create: `강의자료/assets/comparison-src/blueprint-background.png`
- Create: `강의자료/assets/lecture-compare-screening.png`
- Create: `강의자료/assets/lecture-compare-analysis.png`
- Create: `강의자료/assets/lecture-compare-trading.png`
- Create: `강의자료/assets/lecture-compare-feedback.png`
- Modify: `강의자료/deck-src/part3/02-context.html`
- Modify: `강의자료/deck-src/part3/03-system-map.html`
- Modify: `강의자료/deck-src/part3/04-guided-practice.html`
- Modify: `강의자료/deck-src/part3/05-bridge.html`

**Interfaces:**
- Consumes: 현재 코드의 파일·함수 식별자와 설계 문서의 모듈별 매핑
- Produces: 1920×1080 PNG 4개와 덱의 `reference-shot` 참조

- [ ] **Step 1: 글자가 없는 블루프린트 배경 생성**

딥 네이비 격자, 왼쪽 청록색 복잡 경로, 오른쪽 주황·연두색 단순 경로, 중앙 축소 흐름만 포함하고 문자·로고·UI 패널은 생성하지 않는다.

- [ ] **Step 2: 정확한 텍스트 레이어 구현**

각 1920×1080 캔버스에 왼쪽 `PRISM Insight 운영형`, 가운데 `핵심만 남김`, 오른쪽 `lecture-prism 강의형`을 배치한다. 일반어 역할명을 30px 이상, 파일·함수명을 22px 이상으로 유지한다.

- [ ] **Step 3: Chrome으로 네 캔버스를 PNG 렌더링**

각 `article[data-module]`의 경계를 읽어 1920×1080으로 캡처하고 위 네 자산 경로에 저장한다.

- [ ] **Step 4: 기존 카드형 비교 슬라이드 교체**

각 비교 슬라이드는 짧은 제목, 새 `reference-shot`, 한 문장 캡션만 남기고 `pattern-grid`와 `takeaway`를 제거한다.

- [ ] **Step 5: 정적 계약 테스트 통과 확인**

Run: `python3 -m unittest tests.test_part3_deck_contract -v`
Expected: 비교 자산 관련 테스트 PASS

---

### Task 3: 브라우저 화면 맞춤과 이미지 전체화면

**Files:**
- Modify: `강의자료/deck-src/shared/part3-head.html`
- Modify: `강의자료/deck-src/shared/part3-tail.html`
- Regenerate: `강의자료/파트3_슬라이드.html`

**Interfaces:**
- Produces: `updateScreenScale()`, `openImageViewer(img)`, `closeImageViewer()` 브라우저 동작

- [ ] **Step 1: 화면 전용 배율 CSS와 계산 함수 구현**

`min((innerWidth - 16) / 1280, (innerHeight - 16) / 720)`를 `--screen-scale`에 넣고 resize 때 다시 계산한다. `@media print`에서는 `zoom: 1 !important`를 적용한다.

- [ ] **Step 2: 이미지 중심 레이아웃 확대**

`image-focus`, `large-diagram`, `source-map-slide`의 안쪽 여백과 제목 간격을 줄이고 원본 이미지 최대 높이를 약 610~625px로 늘린다.

- [ ] **Step 3: 전체화면 이미지 뷰어 구현**

모든 슬라이드 `<img>`에 `tabindex=0`, `role=button`, 확대 레이블을 부여한다. 클릭·Enter·Space로 검은 오버레이를 열고 Fullscreen API를 시도하며, 이미지·배경·Esc·`fullscreenchange`로 닫는다.

- [ ] **Step 4: 덱 재생성**

Run: `node 강의자료/deck-src/build-decks.mjs`
Expected: `part3: 38 slides`, `part4: 40 slides`

- [ ] **Step 5: 브라우저 실측**

1920×958에서 슬라이드 높이 930px 이상, 위아래 여백 합계 20px 이하인지 확인한다. 대표 원본 이미지의 렌더링 상자가 변경 전 1160×500보다 큰지 확인한다.

---

### Task 4: 원본 그림 14장 캡션 교정

**Files:**
- Modify: `강의자료/deck-src/part3/01-first-success.html`
- Modify: `강의자료/deck-src/part3/02-context.html`
- Modify: `강의자료/deck-src/part3/03-system-map.html`
- Modify: `강의자료/deck-src/part3/04-guided-practice.html`
- Modify: `강의자료/deck-src/part3/05-bridge.html`
- Regenerate: `강의자료/파트3_슬라이드.html`

**Interfaces:**
- Consumes: PRISM `docs/PIPELINE_ARCHITECTURE_ko.md`의 각 이미지 직후 설명
- Produces: 이미지별 1~2문장의 사실 기반 캡션

- [ ] **Step 1: 14개 이미지와 원문 설명 1:1 매핑**

전체 흐름, Market Pulse, 분산일, 오전·오후 조건, 후보 재정렬, 두 시장 판단, 여섯 분석, CAN SLIM 2장, 진입 게이트, 피라미딩, 매도, 독립 보호, 피드백을 빠짐없이 대응한다.

- [ ] **Step 2: 조건과 한계를 포함한 짧은 캡션으로 교체**

`shadow/live`, `fail-open`, 관찰 모드, 보호 도구의 스케줄 미등록, 자율 강화학습 아님처럼 결론을 바꾸는 조건을 필요한 그림에 포함한다.

- [ ] **Step 3: 덱 재생성과 정적 검사**

Run: `node 강의자료/deck-src/build-decks.mjs && python3 -m unittest tests.test_part3_deck_contract -v`
Expected: 38장과 캡션 매핑 PASS

---

### Task 5: 시각 QA와 전체 회귀 검증

**Files:**
- Modify if required: 위 구현 파일
- Persist local-only verdict: `.omx/state/part3-viewport/ralph-progress.json`

**Interfaces:**
- Consumes: 최종 브라우저 렌더와 비교 인포그래픽 PNG
- Produces: 90점 이상 시각 판정과 테스트 증거

- [ ] **Step 1: 대표 슬라이드와 비교 그림 4장 전체 크기 검사**

제목 줄바꿈, 캡션 잘림, 이미지 테두리, 코드 식별자, 대응선과 대비를 확인한다.

- [ ] **Step 2: visual-verdict 기록**

90점 미만이면 차이와 다음 수정 사항을 JSON에 기록하고 한 번에 한 종류의 시각 문제만 수정한다.

- [ ] **Step 3: 전체 테스트**

Run: `python3 main.py`
Expected: 키 없이 스크리닝→분석→모의매매→피드백 완주

Run: `python3 -m unittest discover -s tests -v`
Expected: 전체 PASS

- [ ] **Step 4: 보안·Git 범위 확인 후 구현 커밋**

Run: `git diff --check`, `git status --short`, `git diff --cached --name-only`
Expected: `_workspace/`, 시크릿, 로컬 절대경로가 커밋 대상에 없음
