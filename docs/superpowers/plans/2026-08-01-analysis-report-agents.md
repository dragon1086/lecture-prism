# Analysis Report Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 모듈 2를 일곱 개 보고서 에이전트로 분리하고 매수 판단을 모듈 3의 별도 에이전트로 이동한 뒤 모든 강의 자료를 동기화한다.

**Architecture:** `analysis_agents.py`가 전문 보고서 에이전트 계약을, `analysis.py`가 데이터 수집과 조립을, `buy_agent.py`가 진입 시나리오를 소유한다. `run_analysis()`는 기존 입출력을 보존하는 호환 래퍼이고 메인 파이프라인은 보고서와 매수 단계를 명시적으로 호출한다.

**Tech Stack:** Python 3.10+ 표준 라이브러리, asyncio, unittest, 기존 HTML 슬라이드 빌더

## Global Constraints

- API 키 없이 `python3 main.py`가 완주해야 한다.
- 실거래 이중 안전 플래그를 변경하지 않는다.
- `run_analysis`, `run_trading`, `run_feedback`의 기존 호출 계약을 유지한다.
- 새 필수 의존성을 추가하지 않는다.
- 보고서 에이전트는 매수·매도 판단을 출력하지 않는다.

---

### Task 1: 분석 보고서와 매수 판단 계약 고정

**Files:**
- Create: `tests/test_analysis_agent_boundaries.py`
- Modify: `tests/test_analysis_runtime_config.py`

**Interfaces:**
- Produces: `analysis.run_analysis_report(ticker) -> dict`, `buy_agent.run_buy_agent(report) -> dict`

- [ ] 보고서에 매수 판단 필드가 없고 매수 에이전트 결과에만 존재하는 실패 테스트를 작성한다.
- [ ] LLM 활성화 시 전문 에이전트 여섯 호출과 편집기 한 호출을 요구하는 실패 테스트를 작성한다.
- [ ] 전문 에이전트 하나의 실패가 섹션 폴백으로 격리되는 실패 테스트를 작성한다.
- [ ] 테스트를 실행해 새 모듈과 함수 부재로 실패하는지 확인한다.

### Task 2: 독립 보고서 에이전트 구현

**Files:**
- Create: `analysis_agents.py`
- Modify: `analysis.py`

**Interfaces:**
- Consumes: `analysis._llm_complete(system_prompt, user_msg)`와 데이터 근거 dict
- Produces: `run_report_agents(evidence, fallback_sections, llm_complete, llm_enabled) -> dict`

- [ ] 여섯 `AgentSpec`에 이름·역할·프롬프트·출력 키를 정의한다.
- [ ] 여섯 에이전트를 독립 태스크로 실행하고 실패한 섹션만 폴백한다.
- [ ] 편집 에이전트가 여섯 섹션으로 `executive_summary`만 작성하게 한다.
- [ ] `run_analysis_report()`가 보고서 전용 결과를 반환하게 한다.
- [ ] 경계 테스트를 실행해 보고서 에이전트 테스트를 통과시킨다.

### Task 3: 매수 에이전트와 메인 파이프라인 분리

**Files:**
- Create: `buy_agent.py`
- Modify: `analysis.py`
- Modify: `main.py`
- Modify: `trading.py`
- Modify: `notifications.py`
- Modify: `report_writer.py`

**Interfaces:**
- Consumes: `run_analysis_report()` 결과
- Produces: `run_buy_agent(report) -> 기존 scenario 형태 dict`

- [ ] 기존 정량 점수·시나리오 조립과 LLM 거부권을 `buy_agent.py`로 이동한다.
- [ ] `run_analysis()`를 보고서와 매수 에이전트를 잇는 호환 래퍼로 만든다.
- [ ] `main.py`가 보고서 작성과 매수 판단을 별도 단계로 호출하게 한다.
- [ ] `trading.py` 문구와 타입 설명을 매수 시나리오 입력으로 바로잡는다.
- [ ] 관련 테스트와 `python3 main.py`를 실행해 기존 동작을 유지한다.

### Task 4: 강의 슬라이드·스크립트·프롬프트 동기화

**Files:**
- Modify: `강의자료/deck-src/part3/*.html`
- Modify: `강의자료/deck-src/deck-manifest.json`
- Modify: `lecture/*.md`
- Modify: `lecture/curriculum.html`
- Modify: `docs/*.md`
- Create or Modify: `강의자료/assets/lecture-compare-analysis.png`
- Test: `tests/test_part3_deck_contract.py`
- Test: `tests/test_documentation_architecture_contract.py`

**Interfaces:**
- Consumes: 확정된 `analysis_agents.py`·`analysis.py`·`buy_agent.py` 경계
- Produces: 코드와 동일한 Part 3 설명, 강사용 진행 문구, 수강생 붙여넣기 프롬프트

- [ ] 단일 통합 호출과 모듈 2 매수 판단을 금지하는 문서 계약 테스트를 먼저 작성한다.
- [ ] 모듈 2 슬라이드를 여섯 전문 에이전트와 편집 에이전트 구조로 교체한다.
- [ ] 모듈 3 슬라이드에 매수 에이전트와 결정·실행 경계를 반영한다.
- [ ] 강사용 스크립트와 수강생 프롬프트의 파일 안내를 동기화한다.
- [ ] 덱을 재생성하고 브라우저에서 화면 넘침과 이미지 확대를 확인한다.

### Task 5: 전체 회귀 검증과 커밋

**Files:**
- Verify: repository-wide

**Interfaces:**
- Produces: 안전하게 실행되는 코드와 동기화된 강의 자료

- [ ] `python3 -m unittest discover -s tests -v`를 실행한다.
- [ ] `python3 main.py`, `python3 analysis.py 005930`, `python3 buy_agent.py 005930`, `python3 trading.py --live`를 실행한다.
- [ ] 민감정보·로컬 절대경로·불필요한 산출물을 검사한다.
- [ ] 의도한 파일만 스테이징하고 Lore 형식으로 커밋한다.
