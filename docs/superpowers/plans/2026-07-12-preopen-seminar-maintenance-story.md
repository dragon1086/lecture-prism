# 사전오픈 세미나 유지보수 서사 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 선생님의 실제 투자 경험과 출퇴근 유지보수 루틴을 이미지와 함께 20분·26장 세미나로 완성한다.

**Architecture:** 기존 Reveal.js 한 파일 구조와 1280×720 디자인 체계를 유지한다. 로컬 자료와 새 이미지는 `lecture/slides/assets/`에 모으고, 장표 HTML은 이 자산만 상대경로로 참조한다.

**Tech Stack:** Reveal.js, HTML/CSS, 로컬 PNG/JPEG, OpenAI 내장 이미지 생성 도구

## Global Constraints

- 슬라이드는 개인 투자 연혁 1장과 PRISM 개발 연혁 2장을 포함한 26장으로 구성하고 발표는 20분을 넘기지 않는다.
- 실계좌 식별 정보, 서버 주소, 토큰, API 키, 운영 경로를 노출하지 않는다.
- 원본 KOSPI 차트의 수치와 선형은 바꾸지 않는다.
- 과거 성과는 기간·기준·한계를 함께 표시한다.
- 새 필수 의존성을 추가하지 않는다.

---

### Task 1: 발표 자산 제작

**Files:**
- Create: `lecture/slides/assets/kospi-annotated-2018-2025.png`
- Create: `lecture/slides/assets/investment-research-team.png`
- Create: `lecture/slides/assets/commute-maintenance-routine.png`
- Copy: `docs/assets/prism-insight/kospi-kosdaq-mcp.png`
- Copy: `docs/assets/prism-insight/pdf-report-example.png`
- Copy: `docs/assets/prism-insight/season1_history.png`

- [ ] KOSPI 차트에 세 구간 주석을 추가하고 원본 보존을 확인한다.
- [ ] 특정 실존 인물과 닮지 않은 투자 분석팀 이미지를 만든다.
- [ ] 휴대전화·Mac mini·운영서버·GitHub 흐름을 담은 유지보수 이미지를 만든다.
- [ ] 모든 소비 자산을 슬라이드 자산 폴더에 둔다.

### Task 2: 26장 서사 재작성

**Files:**
- Modify: `lecture/slides/사전오픈_세미나_슬라이드.html`

- [ ] 표지와 2~4장 문제의식을 수정한다.
- [ ] 5~8장을 MCP·PDF·분석팀·시즌1 흐름으로 재구성한다.
- [ ] 유지보수 구간을 출퇴근 루틴·DB와 로그 조사·GitHub 이슈·배포 검증·손절·슬리피지로 나눈다.
- [ ] 기록 구간을 로그의 의미·실제 로그·대시보드·실계좌 검증으로 나눈다.
- [ ] 마지막 구간을 역할 분담·오픈소스·README 맛보기·질문으로 마무리한다.

### Task 3: 한국어 윤문

**Files:**
- Create: `_workspace/2026-07-12-001/final.md`
- Modify: `lecture/slides/사전오픈_세미나_슬라이드.html`

- [ ] 고유명사·수치·날짜를 잠근다.
- [ ] 번역투, 기계적 병렬, 명사형 나열, 반복되는 결말 표현을 줄인다.
- [ ] 슬라이드 문구와 발표자용 문장을 최종 HTML에 반영한다.
- [ ] 자체검증 6항을 기록한다.

### Task 4: 구조·안전·시각 검증

**Files:**
- Modify: `.omx/state/preopen-seminar/ralph-progress.json`

- [ ] HTML 파싱, 슬라이드 26장, 이미지 경로 존재를 검사한다.
- [ ] 민감 문자열과 과장 표현을 검사한다.
- [ ] 1280×720로 핵심 장표를 렌더링한다.
- [ ] 시각 판정 90점 이상이 될 때까지 텍스트와 배치를 조정한다.
- [ ] `python3 main.py` mock 파이프라인을 다시 실행한다.
