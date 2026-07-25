# 파트 3 실습 가이드
> AI 에이전트 매매 흐름 — 명령어 대신 프롬프트로 전체 과정 실행

> 수업 중에는 [수강생 붙여넣기 프롬프트 — 파트 3](수강생_붙여넣기_프롬프트_파트3.md)의 번호를 따라 **한 블록씩만** 코딩 에이전트에 붙여넣으세요. 각 블록은 실행 전 예상 → 실행 → 성공 증거 → 한 문장 회고 순서로 진행합니다.

---

## 사전 준비 (강의 전)

강사가 리포지토리 다운로드 방법은 따로 안내합니다. 수강생은 `lecture-prism` 폴더를 코딩 에이전트에서 연 뒤 아래 프롬프트부터 시작하면 됩니다.

```text
이 lecture-prism 프로젝트가 내 컴퓨터에서 기본 데모로 실행되는지 먼저 확인해줘.

반드시 아래 순서로 진행해줘:
1. 지금 열려 있는 폴더가 lecture-prism 프로젝트 루트인지 확인해줘.
2. 내 컴퓨터에 Python 3.10 이상이 설치되어 있는지 확인해줘.
3. Python이 없거나 버전이 낮으면, 내 운영체제에 맞는 설치 방법을 안내하고 가능한 범위에서 설치까지 도와줘.
4. 외부 패키지 설치는 일단 하지 말고, 먼저 API 키 없이 main.py 데모가 실행되는지 확인해줘.
5. 기본 데모가 성공하면 그 다음에 대시보드·실데이터·실LLM 선택 연동에 필요한 requirements.txt 설치를 진행해줘.
6. 패키지 설치가 실패하더라도 기본 데모가 이미 성공했는지는 따로 구분해서 설명해줘.
7. 마지막에 내가 다음에 입력할 수 있는 프롬프트 3개를 추천해줘.

내가 직접 터미널 명령어를 치지 않도록, 필요한 명령은 네가 실행하고 결과를 설명해줘.
```

선택 준비물:

- ChatGPT Plus 또는 Pro 구독 계정: 공식 Codex CLI 로그인 + oauth 모드 선택 실습용
- KIS 준비물은 수강생에게 필요 없음: 강사만 읽기 전용 생명주기·fixture·live gate 차단을 시연
- GitHub 계정 및 강사의 collaborator 초대 수락: 브랜치 제출을 선택할 때만 필요

---

## 실습 1 — 첫 성공 확인: 데모 파이프라인 (CH1 준비 · 5분)

**목표**: API 키 없이도 스크리닝 → 분석 → 가상 매매 → 피드백 저장 흐름이 도는지 먼저 확인

```text
main.py 전체 흐름을 API 키 없이 데모 모드로 실행해줘.
성공하면 스크리닝, 분석, 가상 매매, 피드백 저장이 각각 어떤 파일에서 일어났는지 설명해줘.
실패하면 내가 직접 명령어를 치게 하지 말고 원인을 찾아 고쳐줘.
```

---

## 선택 실습 — 공식 Codex 구독 LLM 연결 (CH1 라이브 데모)

**목표**: 공식 Codex CLI 로그인 뒤, 프로젝트가 인증 파일을 읽지 않는 격리된 단일 구조화 분석 호출 이해

> 이 단계는 강사 라이브 데모 또는 선택 실습입니다. 기본 흐름은 로그인 없이도 규칙 폴백으로 먼저 체험할 수 있습니다. 공식 로그인과 token refresh는 Codex CLI가 담당하고, 프로젝트는 인증 파일·토큰·시크릿을 읽지 않습니다. 실제 LLM 리서치는 사용자가 공식 로그인과 oauth 모드를 명시했을 때만 시도하며, 실패하거나 미설정이면 규칙 폴백이라고 선언합니다.

### 코딩 에이전트에 입력

```text
공식 Codex CLI의 ChatGPT 구독 로그인을 사용해 lecture-prism 실제 LLM 분석을 연결해줘.
설치와 로그인 가능 여부를 먼저 확인하고, 필요하면 최초 1회 공식 로그인만 도와줘.
인증 파일과 토큰 내용은 읽거나 출력하지 마.
.env에는 LECTURE_LLM_MODE=oauth를 설정하고 종목 1개를 분석해줘.
기술·뉴스·리서치·리스크 정성 역할이 격리된 종목당 한 번의 구조화 호출로 처리되는지 검증해줘.

조건:
1. 공식 Codex CLI 로그인 경로만 사용하고, 프로젝트 안의 인증 파일이나 토큰을 읽지 마.
2. ChatGPT Plus 또는 Pro 계정 로그인이 필요한지 확인하고, 필요하면 브라우저 또는 device auth 로그인을 안내해줘.
3. Codex 셸·파일·브라우저 도구가 비활성화되고 부모 프로세스의 키·토큰 환경변수가 전달되지 않는지 테스트로 확인해줘.
4. analysis.py가 공식 로그인 + oauth 모드에서 실제 LLM 응답을 받았는지, 아니면 규칙 폴백으로 실행됐는지 구분해줘.
5. LLM이 정량 점수·추천·목표가·손절가를 올리지 못하고, BUY를 HOLD로만 veto할 수 있는지 확인해줘.

내가 직접 터미널 명령어를 치지 않도록 필요한 실행과 검증은 네가 해줘.
```

### 확인 프롬프트

```text
방금 확인한 공식 Codex CLI 로그인 + oauth 모드로 삼성전자 분석을 한 번만 실행해줘.
응답이 실제 LLM 리서치 응답인지, 규칙 폴백 응답인지 구분해서 설명해줘.
```

---

## 실습 2 — 스크리닝 실행 (CH2 · 10분)

**목표**: 전종목 → AI 후보 3종목을 고르는 결정론적 규칙 필터 흐름 이해

### 코딩 에이전트에 입력

```text
lecture-prism의 screening.py를 실행해줘.
거래량 급등 + 시가총액 5000억 이상 조건으로 종목을 뽑는 과정을 보여주고,
LLM이 아니라 결정론적 규칙 필터가 어떤 상수와 함수로 후보를 고르는지 초보자 기준으로 설명해줘.
```

### 코드에서 조건 수정해보기

```text
VOLUME_SURGE_RATIO를 5.0에서 3.0으로 바꾸고 다시 실행해줘.
수정 전과 수정 후 선정 종목이 어떻게 달라지는지 표로 비교해줘.
검증이 끝나면 변경된 파일과 변경 이유도 설명해줘.
```

### 예상 결과

```text
전종목 스크리닝 시작...
조건1: 거래량 급등 체크
조건2: 시가총액 체크
조건3: 이동평균 돌파 체크
선정 종목 목록 출력
```

> 기본은 작은 데모 유니버스라 즉시 동작합니다. `real_data`는 분석 단계의 실데이터 보강을 선택적으로 켜는 의미이고, 전체 스크리닝을 yfinance 실데이터로 다시 필터링하려면 코딩 에이전트에게 “--real 스크리닝으로 실행하고, 실패하거나 후보가 0개면 작은 데모 유니버스로 돌아가는지도 확인해줘”라고 요청하세요.

---

## 실습 3 — 분석 역할 파이프라인 (CH3 · 15분)

**목표**: 규칙 근거 생성 → 기술·뉴스·리스크 역할의 단일 구조화 호출 → 정량 gate 이해

> 역할을 왜 나누고, 강의용 경량판에서는 왜 종목당 1회 호출로 묶는지는 [`docs/why-multi-agent.md`](../../docs/why-multi-agent.md) 참고.

### 코딩 에이전트에 입력

```text
삼성전자 005930을 analysis.py로 분석해줘.
규칙 엔진이 만든 근거와 기술·뉴스·리스크 역할의 단일 구조화 LLM 호출을 구분하고,
LLM이 정성 서술과 veto만 담당하며 점수·목표가·손절가는 바꾸지 못하는 이유를 설명해줘.
공식 로그인 + oauth 모드가 아니어서 실제 LLM 리서치를 쓰지 못하면 규칙 폴백으로 동작한다고 명확히 말해줘.
```

### 프롬프트 수정 실험

```text
기술적 분석 에이전트 프롬프트를 RSI 과매도 30 이하 반등에 집중하도록 바꿔줘.
바꾼 후 삼성전자 분석을 다시 실행하고,
기존 CANSLIM 관점과 새 RSI 반등 관점이 결과 설명에서 어떻게 달라졌는지 비교해줘.
```

---

## 실습 4 — 시뮬레이션 매매 (CH4 · 10분)

**목표**: 분석 결과 → 살 금액 계산 → 가상 주문 이해

### 코딩 에이전트에 입력

```text
trading.py의 가상 매매를 실행해줘.
삼성전자 매수 판단에서 현재 포트폴리오 3종목 보유, 현금 1000만원 가정이 어떻게 수량 계산으로 이어지는지 설명해줘.
실거래는 절대 하지 말고 dry-run(실제 주문 없이 미리 보기) 또는 simulation(가상 매매) 결과만 보여줘.
```

### 매수 로직 이해

```text
BUY_SCORE_THRESHOLD를 6에서 5로 낮추면 매수 기준이 어떻게 달라지는지 설명해줘. (매수 점수는 10점 만점)
코드를 수정하지 말고, 먼저 현재 코드 기준으로 영향만 분석해줘.
```

---

## 실습 5 — 피드백 & 대시보드 (CH5 · 5분)

**목표**: 파이프라인이 `prism.db`에 쓴 데이터를 대시보드로 확인

### 코딩 에이전트에 입력

```text
main.py를 한 번 실행해서 매매·분석·교훈이 prism.db에 저장되는지 확인해줘.
그 다음 dashboard.py를 실행해서 로컬 대시보드를 볼 수 있게 도와줘.
대시보드에서 매매현황, AI 분석 근거, 축적된 교훈이 각각 어디에 표시되는지도 설명해줘.
```

### 예상 결과

- 대시보드 상단에 시뮬레이션 데이터 상태가 보입니다.
- 매매현황, AI 분석 근거, 축적된 교훈 표가 보입니다.
- `feedback.py`의 `get_recent_lessons()`가 DB 교훈을 읽어 다음 매매 판단 재료로 쓸 수 있음을 확인합니다.

> 현재 대시보드는 기존 `trade_history`, `analysis_decisions`, `feedback_lessons`만 보여줍니다. 아래 classroom 실습의 core table은 아직 직접 시각화하지 않습니다. 이것이 지금 대시보드의 한계이며, core table 화면은 후속 과제입니다.

---

## 선택 심화 — classroom 상태형 paper 코어 (수업 뒤 advanced lab)

**목표**: 본수업 핵심 4단계 뒤에, “주문을 받았다”와 “실제로 체결됐다”를 구분하고 재시작 가능한 KR/US 진입·청산 증거 확인

기본 `mock`은 API 키 없는 첫 성공을 위한 기존 4단계 파이프라인입니다. 아래 `classroom`은 본수업 필수 분량이 아니라 수업 뒤 선택 심화 lab입니다. 별도의 고정 offline replay로 삼성전자(KR/KRW)와 AAPL(US/USD)의 진입 → 고점 갱신 → 트레일링 청산을 SQLite에 남깁니다. `classroom`과 `backtest`는 환경변수로 실데이터·LLM·외부 broker를 켤 수 없지만 실행 코어는 다릅니다. classroom만 상태형 `PaperBroker`를 쓰고, backtest는 legacy stateless `_simulate_trade` 경로입니다.

### classroom 전체 사이클 실행

```text
lecture-prism의 classroom 전체 사이클을 실행해줘.

조건:
1. 기존 prism.db는 건드리지 말고 임시 SQLite 파일을 만든 뒤, 프로그램 안에서 db.DB_PATH를 그 경로로 바꿔 main.py classroom 프로필을 실행해줘.
2. KR/US fixture의 유효한 유한 quote를 관찰해 두 포지션의 high-water를 청산 write 전에 갱신하고, 청산 우선 트레일링 스탑으로 이어지는 세 사이클을 설명해줘.
3. CREATED → PREVIEWED → SUBMITTED → ACCEPTED는 주문 접수 과정이고, ACCEPTED는 체결이 아니라는 점을 확인해줘.
4. 별도 fill 뒤에만 FILLED, positions, realized_trades가 바뀌는지 증거로 보여줘.
5. KR은 KRW와 정수 수량, US는 USD 계약을 지켰는지 확인해줘.
6. 같은 임시 DB를 새 Ledger 인스턴스로 다시 열어 재시작 후에도 기록을 읽을 수 있는지 확인해줘.
```

### 미체결 → 체결 → 청산 증거 읽기

시황 판단과 후보 선정은 한 쌍입니다. 같은 후보가 `strong_bull`에서는 통과하고 `strong_bear`에서는 거절되는지 보아야 regime이 실제 정책을 바꿘다고 말할 수 있습니다. KR은 **KR 120/60**, US는 **US 200/50** 이동평균을 쓰고 US는 VIX 경계도 함께 봅니다.

```text
lecture-prism의 classroom 전체 사이클을 기존 prism.db를 건드리지 않고 임시 DB에서 실행해줘.
provider validation → regime → screening → analysis gate → sizing → cycle 순서를 코드와 실행 증거로 확인해줘.
classroom의 regime, candidate, order, fill을 run_id와 심볼 기준으로 연결해 한 표로 정리해줘.
같은 후보가 bull에서 통과하고 bear에서 거절되는 정책 차이를 점수·손익비·손절폭으로 설명해줘.
실거래, 외부 브로커, 루트 DB는 사용하지 마.
```

```text
방금 classroom 실행에 쓴 임시 DB를 읽기 전용으로 조사해줘.

- broker_orders: 주문 ID, 시장, 매수/매도, 최종 상태
- order_events: CREATED, PREVIEWED, SUBMITTED, ACCEPTED, FILLED의 최초 관찰 순서
- fills: 실제 체결 ID, 수량, 가격, 통화
- positions: 보유 상태와 high_since_entry
- realized_trades: 진입가, 청산가, 손익, exit_client_order_id, exit_fill_id
- classroom_replays: 세션, phase, 완료 상태

결과를 미체결 → 체결 → 청산 순서로 표로 정리해줘.
최종 positions가 0이고 KR/US realized_trades가 각각 한 건인지 확인해줘.
재시작 provenance를 추측하지 말고 SQLite에 실제로 저장된 값만 설명해줘.
```

### UNKNOWN 안전 규칙 확인

```text
prism_core의 UNKNOWN 주문 처리 규칙을 코드와 테스트로 설명해줘.
실제 DB를 수정하는 장애 주입은 하지 말고 기존 테스트를 실행해,
체결 여부를 알 수 없는 주문에서 새 주문·replay 주문, fill, 청산 mutation을 fail-closed로 막는지 확인해줘.
단, 유효한 quote의 high-water 관찰은 먼저 저장될 수 있음을 구분하고, 명시적인 evidence-based reconciliation 전에는 주문 mutation을 재개하지 않는다고 설명해줘.
```

### 대시보드의 한계 설명

```text
dashboard.py의 /api/data가 읽는 테이블을 확인해줘.
classroom의 broker_orders, order_events, fills, positions, realized_trades, classroom_replays를 현재 화면에서 직접 볼 수 있는지 설명해줘.
아직 보이지 않는다면 구현됐다고 말하지 말고, SQLite 조회로 확인할 수 있는 증거와 대시보드의 한계를 나눠 알려줘.
core table 시각화는 후속 과제로 표시해줘.
```

### live 기본 차단 확인

```text
live CLI나 main 파이프라인을 실행하지 말고 lecture-prism의 live 기본 차단 격리 단위 테스트만 실행해줘.
대상은 tests.test_broker_adapters.BrokerAdapterTest.test_live_gate_isolated_test_never_reads_config_or_calls_adapter야.
테스트 안에서 모든 LECTURE_* enable/allow 변수를 모두 0으로 고정하고,
broker factory와 adapter place_order를 mock으로 감싸 호출되면 실패하는지 확인해줘.
실제 계좌·config 파일을 읽지 않고 결과가 live_blocked이며 adapter 호출이 0회라는 증거만 설명해줘.
```

> regime·결정론적 screening·paper/live market-provider fail-closed, 공식 Codex CLI 로그인 + oauth 모드의 격리된 단일 분석 호출은 현재 구현 범위입니다. KIS는 강사용 읽기 전용 생명주기·fixture·live gate 차단 시연 범위이며, 실돈 주문은 시도하지 않습니다. Toss는 비공식 WTS 선택 연동이며 실제 계좌 E2E는 수행하지 않았습니다. dashboard core-table 시각화는 후속 과제입니다.

---

## 전체 파이프라인 한 번에

```text
main.py 전체 흐름을 실행해줘.
스크리닝 → 분석 → 가상 매매 → 피드백까지 전부 실행하고,
각 단계의 성공 여부와 생성된 데이터를 표로 정리해줘.
```

---

## 막혔을 때 질문 예시

| 상황 | 코딩 에이전트에 입력 |
|---|---|
| 에러 발생 | “이 에러가 났어: [에러 메시지]. 원인을 설명하고, 고친 뒤 같은 실행을 다시 검증해줘.” |
| 코드 이해 안 될 때 | “`_decide_position` 함수가 어떻게 동작하는지 예시 숫자로 설명해줘.” |
| 조건 바꾸고 싶을 때 | “현재 [조건]은 [값]이야. [내 생각]으로 바꾸고 싶어. 함수 시그니처는 유지하고, 바꾼 뒤 데모 실행으로 검증해줘.” |
