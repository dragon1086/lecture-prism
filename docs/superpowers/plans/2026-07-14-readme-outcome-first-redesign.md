# README 결과 중심 개편 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 비전공 수강생이 3~5분 안에 강의 결과물을 이해하도록 README를 축약하고, GPT Image 2가 한글을 직접 생성한 이미지와 세미나 장표·원고를 같은 서사로 맞춘다.

**Architecture:** README는 “내 전략 → 안전한 첫 실행 → 실데이터·실제 AI → KIS 모의·실전 주문 → 결과 확인”의 짧은 소개 페이지가 된다. 세 개의 독립 이미지가 각각 전체 여정, 실제 시스템 결과, A~D 전략 트랙을 담당하며 같은 정보를 반복하지 않는다. README 계약 테스트와 슬라이드 단일 파일 테스트로 문서 간 핵심 문구와 생성 결과를 검증한다.

**Tech Stack:** Markdown, GPT Image 2, Reveal.js HTML, Python `unittest`, 기존 `build_single_html.py`

## Global Constraints

- 기본 데모는 API 키와 `.env` 없이 완주되어야 한다.
- KIS 모의·실전은 같은 코드베이스에서 `.env` 모드 변경과 `trading/trading/config/kis_devlp.yaml` 작성으로 전환된다.
- 실전 주문은 `LECTURE_ENABLE_LIVE_BROKER=1`과 `LECTURE_ALLOW_REAL_BROKER=1`을 모두 요구한다.
- KIS 설정 파일명은 항상 소문자 `kis_devlp.yaml`로 표기한다.
- README 이미지의 배경·도형·아이콘·한글은 GPT Image 2가 한 번에 직접 생성한다.
- 글자 합성, PIL·HTML·SVG·Canvas 후처리, 이미지 위 텍스트 덧씌우기를 사용하지 않는다.
- 이미지 오탈자는 후처리하지 않고 해당 이미지를 재생성한다.
- 개인 계좌, 운영 DB, 실계좌 성과, 개인 대시보드, API 키, 계좌번호, 로컬 경로를 공개 이미지에 넣지 않는다.
- 사용자 작업이 섞인 현재 워크트리에서 이번 작업 파일만 수정·스테이징한다.

---

### Task 1: README 결과 계약을 테스트로 고정

**Files:**
- Create: `tests/test_readme_outcome_contract.py`
- Test: `tests/test_readme_outcome_contract.py`

**Interfaces:**
- Consumes: `README.md`, `lecture/slides/사전오픈_세미나_슬라이드.html`, `lecture/slides/사전오픈_세미나_발표_스크립트.md`
- Produces: README 길이·이미지 수·KIS 결과 문구·세미나 동기화를 검증하는 `unittest` 테스트

- [ ] **Step 1: 실패하는 계약 테스트 작성**

테스트는 다음을 확인한다.

```python
assert readme.count("![") == 3
assert "API 키 없이" in readme
assert ".env" in readme
assert "kis_devlp.yaml" in readme
assert "KIS 모의투자" in readme
assert "KIS 실전투자" in readme
assert "LECTURE_ALLOW_REAL_BROKER" not in readme
assert "내 전략을 넣는 네 가지 트랙" in readme
assert len(readme.splitlines()) <= 150
```

세미나 장표와 원고에는 `KIS 모의·실전`, `API 키 없이`, `내 전략을 넣는 네 가지 트랙`의 의미가 함께 있어야 한다.

- [ ] **Step 2: 테스트를 실행해 현재 README에서 실패 확인**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache python3 -m unittest tests.test_readme_outcome_contract -v`

Expected: 이미지 수, README 길이 또는 KIS 결과 계약에서 FAIL.

- [ ] **Step 3: 테스트 파일 자체 컴파일 확인**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache python3 -m py_compile tests/test_readme_outcome_contract.py`

Expected: exit code 0.

---

### Task 2: GPT Image 2로 README 이미지 세 장 생성

**Files:**
- Create: `docs/assets/readme/strategy-to-kis.png`
- Create: `docs/assets/readme/system-result.png`
- Create: `docs/assets/readme/strategy-tracks.png`

**Interfaces:**
- Consumes: 설계 문서의 이미지별 목적과 정확한 한글 문구
- Produces: README에서 직접 사용하는 공개 안전 이미지 세 장

- [ ] **Step 1: 전체 여정 이미지 생성**

GPT Image 2에 넓은 가로형 교육 인포그래픽을 요청한다. 이미지 안에서 직접 생성할 핵심 한글은 아래로 제한한다.

```text
내 전략이 KIS 매매까지
전략 3줄
AI가 한 트랙 수정
키 없이 먼저 검증
실데이터·실제 AI
KIS 모의·실전
.env + kis_devlp.yaml
```

- [ ] **Step 2: 실제 결과 이미지 생성**

가상 데이터임이 드러나는 고급 시스템 화면을 요청한다. 핵심 한글은 아래로 제한한다.

```text
내가 만드는 시스템
후보 선정
AI 분석
주문 판단
KIS 주문
매매 기록
KIS 연결: 모의투자
오늘의 교훈
```

- [ ] **Step 3: 네 트랙 이미지 생성**

네 영역이 멀리서도 구분되는 2×2 구성을 요청한다.

```text
내 전략을 넣는 네 가지 트랙
A 진입
거래량이 터지면 산다
B 분석
뉴스와 시황을 함께 본다
C 청산
손절·목표가를 정한다
D 리스크
종목 수와 비중을 제한한다
처음에는 하나만 바꿔도 성공
```

- [ ] **Step 4: 각 원본을 시각 검수**

`view_image` 원본 보기로 다음을 확인한다.

- 한글 오탈자와 깨진 글자 없음
- 핵심 문구가 배경과 충분히 대비됨
- 문구가 가장자리에서 잘리지 않음
- 동일한 카드 나열 구성을 세 장 모두 반복하지 않음
- 계좌번호·API 키·실제 수익률·개인 데이터 없음

실패한 이미지는 GPT Image 2로 다시 생성한다. 텍스트 합성으로 고치지 않는다.

- [ ] **Step 5: 축소 가독성 확인**

README 폭으로 축소했을 때 제목과 핵심 단계가 읽히는지 확인한다. 세부 문구가 작으면 문구 수를 줄여 GPT Image 2로 다시 생성한다.

---

### Task 3: README를 3~5분 분량으로 개편

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 2의 이미지 세 장, 기존 상세 문서 링크
- Produces: 150줄 이하의 결과 중심 README

- [ ] **Step 1: 첫 화면과 결과 정의 작성**

첫 화면은 다음 의미를 담는다.

```markdown
이 수업에서는 내 매매 전략 한 부분을 코딩 에이전트와 함께 코드로 옮깁니다.
API 키 없이 먼저 실행해 보고, 같은 프로젝트에 실데이터·실제 AI·KIS 모의·실전 주문까지 연결합니다.
```

`strategy-to-kis.png`를 바로 아래에 배치한다.

- [ ] **Step 2: 실제 실습 흐름과 시스템 결과 작성**

전략 3줄 작성 → 한 트랙 선택 → 에이전트 수정 → 키 없는 검증 → KIS 연결의 다섯 단계를 짧은 목록으로 쓴다. `system-result.png`와 함께 후보 선정·AI 분석·주문 판단·KIS 주문·기록이 남는다는 점을 설명한다.

- [ ] **Step 3: A~D 전략 트랙 작성**

`strategy-tracks.png`와 간결한 네 행 표를 사용한다. 파일명은 보조 정보로만 표시하고, 각 트랙에는 쉬운 예시 하나만 둔다.

- [ ] **Step 4: 수업이 끝나면 남는 것 작성**

다음 네 결과를 명시한다.

```text
내 전략이 반영된 코드
API 키 없이 완주한 기본 실행
수정 전후 결과 비교
.env와 kis_devlp.yaml 설정으로 KIS 모의·실전 주문을 사용할 수 있는 같은 프로젝트
```

실전 주문은 별도 안전장치를 직접 해제해야 한다는 한 문장을 붙이고 상세 변수는 `docs/runtime-profiles.md`로 연결한다.

- [ ] **Step 5: 상세 정보는 기존 문서 링크로 정리**

`START_HERE.md`, 파트3·파트4 실습 가이드, 런타임 프로필, API 키, 브로커 어댑터만 목적별로 연결한다. 기존 긴 FAQ·OAuth 프롬프트·설정표·제출 프롬프트·문제 해결 표는 README에서 제거한다.

- [ ] **Step 6: README 계약 테스트 실행**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache python3 -m unittest tests.test_readme_outcome_contract -v`

Expected: 세미나 동기화 항목을 제외한 README 계약은 PASS.

---

### Task 4: 세미나 슬라이드와 발표 원고를 README에 동기화

**Files:**
- Modify: `lecture/slides/사전오픈_세미나_슬라이드.html`
- Modify: `lecture/slides/사전오픈_세미나_발표_스크립트.md`
- Modify: `lecture/slides/test_build_single_html.py`
- Regenerate: `lecture/slides/사전오픈_세미나_슬라이드_단일파일.html`

**Interfaces:**
- Consumes: Task 3의 실제 README 순서와 표현
- Produces: README 라이브 투어와 같은 서사를 가진 슬라이드·원고·단일 HTML

- [ ] **Step 1: 슬라이드 테스트를 새 계약으로 변경하고 실패 확인**

README 미리보기 슬라이드가 다음 다섯 항목을 포함하도록 테스트한다.

```text
내 전략이 KIS까지 이어지는 시스템
API 키 없이 안전하게 첫 실행
실데이터·실제 AI·KIS 연결
내 전략을 넣는 네 가지 트랙
작동하는 코드와 주문 경로로 확인
```

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache python3 -m unittest lecture.slides.test_build_single_html -v`

Expected: 새 KIS 중심 문구에서 FAIL.

- [ ] **Step 2: README 미리보기 슬라이드 수정**

다섯 항목을 실제 README의 순서와 같은 표현으로 바꾼다. 안전장치는 마지막 성취가 아니라 KIS 실전 주문을 우발적으로 막는 조건으로 한 줄만 둔다.

- [ ] **Step 3: 발표 스크립트 수정**

발표자는 실제 README를 열어 첫 이미지, 키 없는 첫 실행, 시스템 결과, A~D 트랙, `.env`와 `kis_devlp.yaml`로 KIS 모의·실전 주문을 전환하는 결과물을 짚는다. 원고는 가상매매만 가능한 프로젝트처럼 들리지 않게 하고, 실제 주문의 이중 안전장치도 함께 말한다.

- [ ] **Step 4: 원본 슬라이드 테스트 통과**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache python3 -m unittest lecture.slides.test_build_single_html tests.test_readme_outcome_contract -v`

Expected: PASS.

- [ ] **Step 5: 단일 HTML 재생성**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache python3 lecture/slides/build_single_html.py`

Expected: 단일 HTML 경로와 파일 크기 출력, exit code 0.

---

### Task 5: 전체 품질과 공개 안전성 검증

**Files:**
- Verify: `README.md`
- Verify: `docs/assets/readme/strategy-to-kis.png`
- Verify: `docs/assets/readme/system-result.png`
- Verify: `docs/assets/readme/strategy-tracks.png`
- Verify: `lecture/slides/사전오픈_세미나_슬라이드.html`
- Verify: `lecture/slides/사전오픈_세미나_발표_스크립트.md`
- Verify: `lecture/slides/사전오픈_세미나_슬라이드_단일파일.html`

**Interfaces:**
- Consumes: Tasks 1~4의 결과
- Produces: 전달 가능한 README와 세미나 자료 검증 증거

- [ ] **Step 1: 전체 문서 테스트**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache python3 -m unittest tests.test_readme_outcome_contract lecture.slides.test_build_single_html -v`

Expected: 모든 테스트 PASS.

- [ ] **Step 2: 기본 데모 완주 확인**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache python3 main.py`

Expected: 후보 선정 → 분석 → 가상 주문 → 피드백·DB 저장까지 완주.

- [ ] **Step 3: 실거래 차단 확인**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache python3 trading.py --live`

Expected: 기본 설정에서 `live_blocked`, 실제 주문 없음.

- [ ] **Step 4: README 링크와 이미지 참조 확인**

README의 로컬 링크가 존재하고 이미지 세 장이 프로젝트 안에 저장되었는지 확인한다. README가 이전 다섯 이미지 경로를 더 이상 참조하지 않는지 확인한다.

- [ ] **Step 5: 단일 HTML 독립성 확인**

단일 HTML에 외부 `<img src>`, 외부 stylesheet, 외부 script가 없고 슬라이드 수가 기존 26장으로 유지되는지 확인한다.

- [ ] **Step 6: 민감정보와 변경 범위 확인**

`git status --short`, 대상 파일 diff, 공개 금지 패턴을 확인한다. `.env`, `kis_devlp.yaml`, API 키, 계좌번호, 개인 성과 자료를 스테이징하지 않는다.

- [ ] **Step 7: 최종 시각 검수**

세 이미지를 원본으로 다시 보고 한글, 대비, 여백, 정보 밀도를 확인한다. README 첫 화면과 세미나 README 슬라이드가 같은 약속을 하는지 마지막으로 비교한다.
