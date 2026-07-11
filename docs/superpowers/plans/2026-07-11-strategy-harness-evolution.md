# Strategy Harness Evolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 비전공 수강생이 `MY_STRATEGY.md`를 간단히 작성한 뒤 35분 안에 전략 한 트랙을 안전하게 수정·검증할 수 있도록 하네스를 확장한다.

**Architecture:** 기존 A/B/C/D 트랙과 공개 함수 계약은 유지한다. 하네스 프롬프트와 역할 정의에 전략 정밀화, 자료 준비 상태, 모순 처리, 수업 빠른 모드를 추가하고 표준 `unittest` 계약 테스트로 Codex·Claude·공용 사본의 동기화와 안전 규칙을 잠근다.

**Tech Stack:** Markdown, Codex TOML agent definitions, Claude Markdown agent definitions, Python 3.10+ standard library `unittest`

## Global Constraints

- API 키가 없어도 `python3 main.py` mock 데모가 완주해야 한다.
- 실거래는 기존 이중 안전 플래그 없이 계속 차단한다.
- 한 사이클에는 Part 4 트랙 A/B/C/D 중 하나만 수정한다.
- 수강생 안내에는 직접 실행할 터미널 명령 대신 코딩 에이전트용 프롬프트를 제공한다.
- 사용자 설명은 비전공자가 이해할 쉬운 한국어를 사용한다.
- 지원 기준은 CPython 3.10 이상이며 macOS와 Windows 경로를 모두 고려한다.
- 기존 사용자 변경인 README, 아키텍처 문서, Part 4 실습가이드, PRISM 이미지·문서는 수정하거나 스테이징하지 않는다.

---

### Task 1: 하네스 계약 회귀 테스트

**Files:**
- Create: `tests/test_strategy_harness_contract.py`

**Interfaces:**
- Consumes: 세 스킬 사본, Codex·Claude 역할 정의, `MY_STRATEGY.md`, `docs/harness-lite.md`, `.gitignore`
- Produces: 하네스 동기화·빠른 모드·자료 준비 상태·쉬운 말·안전 경계를 검사하는 `unittest` 계약

- [ ] **Step 1: 실패하는 계약 테스트 작성**

```python
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class StrategyHarnessContractTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_skill_copies_share_required_contract(self):
        paths = [
            ".codex/skills/lecture-prism-strategy-harness/SKILL.md",
            ".claude/skills/lecture-prism-strategy-harness/SKILL.md",
            ".agents/skills/lecture-prism-strategy-harness/SKILL.md",
        ]
        required = ["수업 빠른 모드", "지금 사용 가능", "키 또는 계정 필요", "사람이 넣어야 함", "이번 범위 밖"]
        for path in paths:
            text = self.read(path)
            for marker in required:
                self.assertIn(marker, text, f"{path}: {marker}")

    def test_student_template_captures_extended_strategy(self):
        text = self.read("MY_STRATEGY.md")
        for marker in ["시장 흐름", "필요한 자료", "직접 넣을 자료", "기억", "서로 충돌"]:
            self.assertIn(marker, text)

    def test_docs_keep_one_track_classroom_flow(self):
        text = self.read("docs/harness-lite.md")
        for marker in ["35분", "한 트랙", "API 키 없이", "Windows", "Python 3.10"]:
            self.assertIn(marker, text)

    def test_local_sensitive_inputs_are_ignored(self):
        text = self.read(".gitignore")
        for marker in ["student_inputs/", "lecture/slides/assets/"]:
            self.assertIn(marker, text)
```

- [ ] **Step 2: 테스트가 새 계약 누락으로 실패하는지 확인**

Run: `python3 -m unittest tests.test_strategy_harness_contract -v`

Expected: `수업 빠른 모드`, 확장 입력 항목 또는 ignore 규칙 누락으로 FAIL.

- [ ] **Step 3: 테스트 파일만 유지하고 구현은 다음 작업으로 넘기기**

검사 문구가 실제 사용자·하네스 계약을 나타내며 구현 세부사항을 과도하게 고정하지 않는지 확인한다.

---

### Task 2: 수강생 입력과 빠른 실습 흐름

**Files:**
- Modify: `MY_STRATEGY.md`
- Modify: `docs/harness-lite.md`

**Interfaces:**
- Consumes: 기존 30초 전략과 A/B/C/D 트랙
- Produces: 선택 입력 항목과 35분 수업 빠른 모드 프롬프트

- [ ] **Step 1: `MY_STRATEGY.md`에 선택 입력 추가**

기존 30초 버전과 트랙 입력은 그대로 두고 다음 선택 섹션을 추가한다.

```markdown
## 6. 더 자세히 반영하고 싶다면 (선택)

- 시장 흐름: 장이 좋을 때와 나쁠 때 무엇을 다르게 할까요?
- 필요한 자료: 가격·지수·뉴스·공시·수급 중 무엇이 필요한가요?
- 직접 넣을 자료: 유료 리포트나 캡처처럼 직접 줄 자료가 있나요?
- 기억: 다음 판단을 위해 어떤 기록을 남기고 싶나요?
- 나중에 확장: ETF·선물·코인 등 나중에 넓힐 대상이 있나요?
- 서로 충돌하는 생각: 둘 다 지키기 어려워 보이는 조건이 있나요?
```

기존 `오늘 수업에서 바꾸고 싶은 것`은 다음 번호로 이동하되 문구는 유지한다.

- [ ] **Step 2: `docs/harness-lite.md`에 수업 빠른 모드 추가**

다음 규칙을 쉬운 말로 설명한다.

```text
- 목표 시간: 전략 작성 3~5분, 수정 10~15분, 검증 5~10분
- 이번 시간에는 한 트랙만 끝낸다.
- 먼저 MY_STRATEGY.md, 트랙 지도, 대상 파일 하나만 읽는다.
- 외부 데이터 조사, 여러 트랙, ETF·선물·코인은 다음 할 일로 남긴다.
- API 키가 없어도 mock으로 계속한다.
```

macOS·Windows 공통으로 코딩 에이전트가 Python 3.10 이상과 기본 데모를 확인하는 프롬프트를 제공한다.

- [ ] **Step 3: 입력·문서 계약 테스트 실행**

Run: `python3 -m unittest tests.test_strategy_harness_contract -v`

Expected: 스킬과 `.gitignore` 관련 검사만 아직 FAIL.

---

### Task 3: 세 하네스 사본과 역할 정의 확장

**Files:**
- Modify: `.codex/skills/lecture-prism-strategy-harness/SKILL.md`
- Modify: `.claude/skills/lecture-prism-strategy-harness/SKILL.md`
- Modify: `.agents/skills/lecture-prism-strategy-harness/SKILL.md`
- Modify: `.codex/skills/lecture-prism-strategy-harness/references/track-map.md`
- Create: `.codex/skills/lecture-prism-strategy-harness/references/data-readiness-map.md`
- Modify: `.codex/agents/lecture-strategy-interviewer.toml`
- Modify: `.codex/agents/lecture-strategy-implementer.toml`
- Modify: `.codex/agents/lecture-strategy-verifier.toml`
- Modify: `.claude/agents/lecture-strategy-interviewer.md`
- Modify: `.claude/agents/lecture-strategy-implementer.md`
- Modify: `.claude/agents/lecture-strategy-verifier.md`

**Interfaces:**
- Consumes: 확장된 수강생 입력과 기존 트랙 함수 계약
- Produces: 동일한 전략 정리, 자료 준비 분류, 모순 처리, 빠른 모드, 검증 출력 계약

- [ ] **Step 1: canonical Codex 스킬 확장**

전략 정리 형식을 다음 항목으로 확장한다.

```text
목표 / 진입 / 분석 관점 / 청산 / 리스크 / 시장 흐름 /
필요한 자료 / 직접 넣을 자료 / 기억 / 향후 확장 /
서로 충돌하는 조건 / 하네스가 우선 가정한 값
```

자료 준비 상태는 정확히 다음 다섯 표현을 사용한다.

```text
지금 사용 가능 / 무료 연결 가능 / 키 또는 계정 필요 /
사람이 넣어야 함 / 이번 범위 밖
```

사용자 출력에서는 `adapter`, `schema`, `fallback` 대신 `데이터 연결 부품`, `결과 모양`, `안 되면 대신 쓰는 방법`을 사용한다.

- [ ] **Step 2: 수업 빠른 모드 규칙 추가**

빠른 모드를 기본값으로 두고, 35분 수업에서는 대상 파일 하나와 관련 테스트만 먼저 읽으며 외부 조사와 다음 트랙은 보고서로 넘기도록 한다. 사용자가 `심화 모드`를 명시했을 때만 범위를 넓힌다.

- [ ] **Step 3: 자료 준비 지도 작성**

`data-readiness-map.md`에 각 상태의 판단 기준, 사용자 안내, mock 대체, 키 보안, 수동 자료의 UTF-8 텍스트 우선, 저작권 자료 Git 제외 규칙을 기록한다.

- [ ] **Step 4: Codex 스킬을 Claude·공용 스킬에 동기화**

세 `SKILL.md`의 본문을 동일하게 유지한다. 환경별 경로 차이가 필요하면 에이전트 정의에서만 다룬다.

- [ ] **Step 5: 인터뷰어·구현자·검증자 역할 확장**

인터뷰어는 확실한 내용·가정·이번 범위 밖을 분리한다. 구현자는 빠른 모드와 자료 준비 상태를 따른다. 검증자는 쉬운 말, Windows/Python 3.10, mock 폴백, 로컬 자료 Git 제외를 확인한다.

- [ ] **Step 6: 역할 계약 검사 추가 및 실행**

`tests/test_strategy_harness_contract.py`에 Codex·Claude 역할 파일이 `시장 흐름`, `자료 준비 상태`, `수업 빠른 모드`, `쉬운 말`을 포함하는지 검사한다.

Run: `python3 -m unittest tests.test_strategy_harness_contract -v`

Expected: `.gitignore` 관련 검사만 아직 FAIL.

---

### Task 4: 로컬 자료 Git 안전 경계

**Files:**
- Modify: `.gitignore`
- Modify: `tests/test_strategy_harness_contract.py`

**Interfaces:**
- Consumes: 로컬 수동 입력과 현재 `lecture/slides/assets/`의 실계좌·대시보드 원본
- Produces: 공개 저장소에 추가되지 않는 로컬 자료 경계

- [ ] **Step 1: 로컬 입력과 발표 원본 제외 규칙 추가**

`.gitignore`의 로컬 작업 산출물에 다음을 추가한다.

```gitignore
student_inputs/
lecture/slides/assets/
```

슬라이드 HTML과 공개 가능한 코드·문서는 제외하지 않고, 원본 이미지 폴더만 차단한다.

- [ ] **Step 2: 실제 ignore 동작 검사 추가**

테스트에서 문자열 존재뿐 아니라 `git check-ignore`를 호출해 다음 예시가 무시되는지 검사한다.

```text
student_inputs/paid-report.md
lecture/slides/assets/kis-account-example.jpeg
```

- [ ] **Step 3: 계약 테스트 실행**

Run: `python3 -m unittest tests.test_strategy_harness_contract -v`

Expected: 모든 하네스 계약 테스트 PASS.

---

### Task 5: Python 3.10·다중 실행 검증

**Files:**
- Modify: `tests/test_strategy_harness_contract.py`

**Interfaces:**
- Consumes: 루트 Python 데모 파일과 하네스 문서
- Produces: Python 3.10 문법, 크로스플랫폼 경로, mock·실거래 차단 검증 증거

- [ ] **Step 1: Python 3.10 문법 계약 추가**

`ast.parse(source, feature_version=(3, 10))`으로 루트 데모 파일과 `brokers/` Python 파일을 검사한다. 고정 `/Users/` 경로와 Windows 드라이브 경로가 실행 코드에 없는지도 검사한다.

- [ ] **Step 2: 하네스 계약과 전체 단위 테스트 실행**

Run: `python3 -m unittest discover -s tests -v`

Expected: 전체 테스트 PASS.

- [ ] **Step 3: 문법 검사 실행**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache python3 -m compileall main.py analysis.py screening.py trading.py feedback.py db.py dashboard.py runtime_config.py brokers`

Expected: exit 0.

- [ ] **Step 4: mock 전체 파이프라인 실행**

Run: `python3 main.py`

Expected: 스크리닝→분석→시뮬레이션 매매→피드백→DB 저장 완주.

- [ ] **Step 5: 트랙별 대표 실행**

Run: `python3 main.py --ticker 005930`

Run: `python3 trading.py --exit`

Expected: 단일 종목 파이프라인과 손절·트레일링·목표가 시나리오 정상 출력.

- [ ] **Step 6: 실거래 차단 실행**

Run: `python3 trading.py --live`

Expected: 주문이 실행되지 않고 `live_blocked` 반환.

- [ ] **Step 7: 공개 안전 검사**

Run: `git status --short`

Run: `git diff --cached --name-only`

Expected: 사용자 기존 변경과 하네스 변경이 구분되며, `tasks/`, `student_inputs/`, `lecture/slides/assets/`, 시크릿, DB가 스테이징되지 않음.
