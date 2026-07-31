# 처음 시작하는 수강생용 5분 루트

처음에는 설치·API·Git을 한꺼번에 해결하려고 하지 마세요.
목표는 딱 하나입니다.

> **“API 키 없이 lecture-prism이 한 번 실행되는 것”을 먼저 확인한다.**

ChatGPT Plus/Pro 선택 연결은 공식 Codex 로그인을 사용합니다. 기본 데모에는 로그인도 API 키도 필요 없습니다.
하지만 첫 5분에는 LLM·API 키·KIS를 연결하지 말고, 더미 데이터 데모가 끝까지 도는지만 먼저 확인하세요.

## 1단계 — 폴더를 코딩 에이전트에서 열기

강사가 안내한 방식으로 `lecture-prism` 폴더를 받은 뒤, Claude Code·Codex 같은 코딩 에이전트에서 이 폴더를 여세요.

## 2단계 — 첫 실행 프롬프트 붙여넣기

```text
이 lecture-prism 프로젝트가 내 컴퓨터에서 기본 데모로 실행되는지 먼저 확인해줘.

순서:
1. 지금 열려 있는 폴더가 lecture-prism 프로젝트 루트인지 확인해줘.
2. Python 3.10 이상이 있는지 확인해줘.
3. 외부 패키지 설치는 일단 하지 말고, 먼저 API 키 없이 main.py 데모가 실행되는지 확인해줘.
4. 실행이 성공하면 어떤 단계가 돌아갔는지 초보자 기준으로 풀어서 설명해줘.
5. 실행이 실패하면 내가 직접 명령어를 치게 하지 말고, 원인을 설명하고 고쳐줘.
6. 대시보드나 실데이터에 필요한 패키지는 첫 데모 성공 이후에 설치해줘.
```

## 3단계 — 성공했으면 다음 경로 하나 고르기

첫 성공 뒤에는 한 번에 모든 선택 기능을 켜지 않습니다. 목표에 맞는 경로 하나만 고릅니다.

- **기본 학습 경로**: root `screening.py`·`analysis_agents.py`·`buy_agent.py`·`trading.py` 중 한 책임을 A/B/C/D 전략 트랙으로 바꾸고 다시 데모를 실행합니다.
- **상태 기반 고급 경로**: `classroom`의 고정 offline replay로 `prism_core`가 남기는 regime·candidate·order·fill 증거를 읽습니다. `backtest`·`paper`·`live`는 이 경로를 확장한 프로필이며, 첫 성공에 필요하지 않습니다.
- **선택 연동 경로**: 실데이터, 공식 Codex OAuth, KIS 또는 Toss 진단을 각각 따로 켭니다. 실제 주문은 이 문서의 첫 실행 범위가 아닙니다.

### 내 전략을 root 데모에 넣기

```text
MY_STRATEGY.md를 읽고 내 전략을 lecture-prism에 반영해줘.
내 설명이 부족하면 네가 먼저 합리적으로 정리하고,
진짜 꼭 필요한 질문만 하나만 해줘.
처음에는 Part 4 트랙 A/B/C/D 중 가장 안전한 것 하나만 골라서 수정해줘.
수정 후에는 API 키 없이 데모 모드로 실행 검증하고,
수정 전후 차이를 초보자도 이해하게 설명해줘.
실거래는 절대 하지 마.
```

### classroom의 주문·체결 증거 보기

```text
lecture-prism의 classroom 상태 재생을 안전한 임시 SQLite DB에서 실행해줘.
기본 mock 데모와 classroom이 서로 다른 경로인지 먼저 설명해줘.
그 뒤 regime, candidate, order, fill, realized trade를 같은 run_id 기준으로 표로 연결해 보여줘.
실데이터·LLM·외부 broker·실제 prism.db는 사용하지 마.
```

### 선택 연동을 읽기 전용으로 진단하기

```text
lecture-prism의 선택 연동 준비 상태를 읽기 전용으로 점검해줘.
공식 Codex OAuth, yfinance, KIS, Toss 중 내 컴퓨터에 준비된 항목만 구분해줘.
KIS와 Toss의 매수·매도·조회·취소·재시작 reconcile은 fixture 테스트 범위이고 실제 계좌 E2E가 아니라는 점을 설명해줘.
실제 주문, 로그인 세션 파일, API 키, 계좌 설정은 읽거나 변경하지 마.
```

## 막히면

```text
지금 내가 어디서 막혔는지 README.md와 START_HERE.md 기준으로 진단해줘.
내가 직접 터미널 명령어를 치지 않도록 다음 행동을 하나씩 진행해줘.
```
