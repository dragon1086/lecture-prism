# 런타임 프로필 가이드

lecture-prism은 한 저장소 안에서 초급자용 더미 데모부터 상태가 남는 교실 재생, 선택 실데이터·리서치·브로커 연결까지 단계적으로 구분합니다. 문서를 읽을 때는 먼저 **기본 학습 경로**와 **상태 기반 고급 경로**를 구분하세요.

- **기본 학습 경로**: `mock`과 `real_data`가 `screening.py` → `analysis_agents.py`·`analysis.py` → `buy_agent.py` → `trading.py` → `feedback.py`를 사용합니다. API 키 없는 첫 성공과 전략 A/B/C/D 수정의 출발점입니다.
- **상태 기반 고급 경로**: `classroom`, `backtest`, `paper`, `live`가 `prism_core`의 시장 국면·후보·주문 원장·체결 증거를 사용하거나 그 계약을 검증합니다. `paper/live`는 market provider 오류를 mock 매매로 바꾸지 않고 fail-closed로 막습니다.

수강생이 기본적으로 만지는 파일은 두 개입니다.

| 파일 | 역할 |
|---|---|
| `.env` | 더미/실데이터/리서치/매매 수준 선택, API 키 입력 |
| `trading/trading/config/kis_devlp.yaml` | KIS 계좌번호, App Key, App Secret, 모의/실전 계좌 설정 |

처음에는 `.env` 없이도 됩니다. 설정을 따로 만들고 싶다면 `.env.example`을 참고해 `.env`를 만들고 `LECTURE_PROFILE=mock`으로 시작하세요. 이 값이면 API 키가 없어도 스크리닝, 분석, 가상 매매, 피드백 저장, Markdown 보고서 생성까지 돌아갑니다.

아래 `text` 블록은 직접 실행할 터미널 명령이 아니라 **코딩 에이전트에게 그대로 붙여넣는 프롬프트**입니다.

## 1. 프로필 한 줄로 고르기

| 프로필 | 데이터 | 분석 보고서 | 매매 | 추천 대상 |
|---|---|---|---|---|
| `mock` | 더미 데이터 | 6섹션 기본 보고서 | 기존 가상 매매 | API 키 없는 첫 실행, Part 4 전략 실습 |
| `classroom` | 고정 KR/US fixture + regime screening | LLM 없음 | 상태형 paper replay | regime·candidate·order·fill 증거 학습 |
| `real_data` | yfinance 실데이터, 실패하면 더미 데이터 | 6섹션 기본 보고서 | 가상 매매 | 실제 가격·거래량으로 보고 싶은 수강생 |
| `research` | 실데이터 | LLM + Perplexity/Firecrawl 선택 리서치 | 가상 매매 | 원본 PRISM에 가까운 분석을 원하는 수강생 |
| `paper` | yfinance 실데이터 | research 보고서 | KIS 모의투자 등 선택 broker 경로 | provider 실패 시 fail-closed; KIS/Toss lifecycle은 fixture 검증 범위 |
| `live` | yfinance 실데이터 | research 보고서 | 이중 잠금된 실전 설정 경로 | provider fail-closed + 별도 live gate; 운영 준비 완료 아님 |
| `backtest` | 고정 fixture | LLM 없음 | legacy stateless simulation | 고정 fixture 호환 검증 |

```text
내 .env를 lecture-prism 런타임 프로필 방식으로 점검해줘.
내 목표는 [mock / classroom / real_data / research / paper / live / backtest] 중 하나야.
필요한 키가 빠졌는지 확인하고, 빠진 키가 있어도 더 안전한 단계로 돌아가는지 설명해줘.
실거래는 내가 명시적으로 원하기 전까지 절대 켜지 마.
```

## 2. 세부 스위치

프로필만으로 부족할 때는 아래 값을 직접 조정할 수 있습니다.

| 값 | 선택지 | 의미 |
|---|---|---|
| `LECTURE_DATA_MODE` | `mock`, `auto`, `yfinance` | 분석 데이터 원천 |
| `LECTURE_SUPPLY_SOURCE` | `proxy`, `kis` | 수급 섹션 원천. 기본 `proxy`; `kis`는 KIS 일별 기관·외국인·개인 순매수만 보강 |
| `LECTURE_SCREENING_MODE` | `mock`, `fixture`, `real` | 스크리닝 원천 (`fixture` = classroom/backtest, `real` = yfinance) |
| `LECTURE_LLM_MODE` | `mock`, `auto`, `oauth`, `openai` | `oauth`는 공식 Codex 구독, `openai`는 별도 API 키, `auto`는 API 키가 있을 때만 호출 |
| `LECTURE_REPORT_MODE` | `lite`, `research` | 보고서 깊이 |
| `LECTURE_RESEARCH_TOOLS` | `perplexity,firecrawl` | 선택 리서치 도구 |
| `LECTURE_TRADE_MODE` | `simulation`, `demo`, `real` | 매매 실행 수준 |
| `LECTURE_SAVE_REPORTS` | `1`, `0` | `reports/` Markdown 저장 여부 |
| `LECTURE_NOTIFY_DISCORD` | `1`, `0` | Discord 판단 알림 사용 여부 |
| `DISCORD_WEBHOOK_URL` | Discord Incoming Webhook URL | 알림을 받을 비밀 주소. `.env`에만 저장 |

이전 설정의 `PRISM_OPENAI_AUTH_MODE=chatgpt_oauth`도 명시적 호환 입력으로 인식하지만, 비공식 프록시를 시작하지 않고 공식 Codex 공급자를 선택합니다. `auto`는 이 명시적 값이나 API 키가 없으면 로컬 로그인 상태를 추측하지 않습니다.

`mock/real_data`의 관찰 경로와 `research`의 선택 연동은 실패하면 더 안전한 기능으로 폴백합니다. 예를 들어 `research`에서 Perplexity 키가 없으면 해당 리서치만 빠지고 기본 분석은 계속됩니다. 반면 `paper/live`는 market provider 검증이 실패하면 mock으로 주문 판단을 계속하지 않고 **fail-closed**로 막습니다.

`classroom`과 `backtest`는 환경변수로 data/LLM/외부 broker 설정을 덮어쓸 수 없는 고정 offline simulation 프로필이며 live 플래그를 무시합니다. 두 프로필의 서로 다른 실행 코어는 다음 절에서 구분합니다.

## 3. 운영 서비스 사다리

운영형 실행은 `doctor → simulation → paper → live` 순서로만 올립니다. `operations.py schedule`은 한 번 실행하고 끝나는 명령이 아니라 장중 보유 종목 점검, 미체결 주문 대사, 메모리 압축을 계속 기다리는 **long-lived service process**입니다. 이 프로세스를 항상 켜 두고 재시작하는 책임은 launchd, systemd, Windows Task Scheduler 같은 **service manager**가 맡습니다. lecture-prism은 예시 템플릿만 제공하며, 설치·등록·실행은 자동으로 하지 않습니다.

상태와 로그는 `LECTURE_OPERATIONS_RUNTIME_DIR` 아래에 남습니다. 비워 두면 운영체제 임시 폴더의 lecture-prism 전용 위치를 씁니다.

| 위치 | 의미 |
|---|---|
| `operations-state.json` | 스케줄러 pid, heartbeat, 작업별 성공·실패·stale_data 상태 |
| `scheduler.lock` / `scheduler.lock.advisory` | 같은 프로젝트에서 스케줄러를 한 개만 띄우기 위한 잠금 |
| `logs/operations-YYYY-MM-DD.log` | KST 날짜 기준 운영 이벤트 로그 |

운영 상태는 `operations.py status`가 같은 런타임 디렉터리를 읽어 보여 줍니다. `operations.py doctor`는 프로필, scheduler enable 힌트, 런타임 디렉터리 쓰기 가능 여부, 미해결 주문, 브로커별 읽기 전용 준비 상태를 점검합니다. `stale_data`가 보이면 fresh quote나 provider 증거가 부족해 해당 작업이 fail-closed로 닫힌 것입니다.

서비스 템플릿은 다음 파일에 있습니다.

| 운영체제 | 템플릿 |
|---|---|
| macOS launchd | `deploy/launchd/com.lecture-prism.operations.plist.example` |
| Linux systemd | `deploy/systemd/lecture-prism.service.example` |
| Windows Task Scheduler | `deploy/windows/lecture-prism-task.xml.example` |

모든 템플릿은 `{{PROJECT_DIR}}`의 `.venv` Python으로 `operations.py schedule`을 실행하고, 작업 디렉터리를 프로젝트 루트로 고정하며, 기본값에서 `--execute-broker`를 넣지 않습니다. 따라서 기본 서비스는 simulation 실행입니다. paper/live에서 브로커 API를 호출하려면 먼저 doctor가 준비 상태를 설명해야 하고, service manager 등록 템플릿도 사람이 검토한 뒤에만 바꿉니다.

```text
lecture-prism 운영 서비스 템플릿을 내 컴퓨터에 맞게 준비해줘.
조건:
1. 내 운영체제에 맞는 deploy/ 아래 example 파일만 읽고, 바로 등록하거나 실행하지 마.
2. {{PROJECT_DIR}}, {{OPERATIONS_RUNTIME_DIR}}, {{MONITOR_INTERVAL_MINUTES}}, {{RECONCILE_INTERVAL_MINUTES}} placeholder를 실제 로컬 값으로 바꾼 사본을 만들어줘.
3. 기본값에는 --execute-broker를 넣지 말고 simulation으로만 동작하게 해줘.
4. .venv Python, operations.py schedule, 프로젝트 작업 디렉터리, 실패/재부팅 후 재시작 설정이 들어 있는지 점검해줘.
5. 상태는 operations-state.json, 로그는 logs/operations-YYYY-MM-DD.log, 잠금은 scheduler.lock에 남는다고 설명해줘.
6. 등록이나 시작은 내가 별도로 승인하기 전까지 하지 마.
```

```text
lecture-prism 운영 단계를 doctor → simulation → paper → live 순서로 점검해줘.
먼저 operations.py doctor와 status가 어떤 정보를 보여 주는지 코드와 테스트 근거로 설명하고,
simulation 서비스 템플릿에는 --execute-broker가 없는지 확인해줘.
paper/live로 올릴 때 필요한 LECTURE_ENABLE_LIVE_BROKER, LECTURE_ALLOW_REAL_BROKER,
LECTURE_UNATTENDED_LIVE_ACK 조건을 설명하되 실제 주문·취소·API 호출은 실행하지 마.
```

## 4. mock 첫 실행과 classroom 상태 재생

`mock`은 기존 강의 파이프라인입니다. API 키 없이 스크리닝, 6섹션 mock 분석, 가상 매매, 피드백 저장을 한 번에 경험하는 것이 목적입니다.

`classroom`은 주문 원장을 배우기 위한 별도 경로입니다. 삼성전자(KR/KRW)와 AAPL(US/USD)을 대상으로 아래 세 사이클을 결정론적으로 실행합니다.

`classroom`만 SQLite 상태와 `PaperBroker`를 사용합니다. `backtest`는 고정 offline이지만 legacy stateless `_simulate_trade` 경로를 유지하며, 상태형 paper broker나 완성된 백테스트 엔진이 아닙니다. 미래 데이터 누수를 차단한 비교는 프로필 실행과 별개인 `run_walk_forward()` 증거 API가 담당합니다.

1. 지정가 진입 주문과 fill 기록
2. 두 시장 포지션의 high-water 갱신
3. 트레일링 스탑 청산과 실현손익 기록

주문 제출은 `CREATED → PREVIEWED → SUBMITTED → ACCEPTED` 순서입니다. **ACCEPTED는 체결이 아닙니다.** 이 상태에서는 미체결 주문만 있고 `positions`는 생기지 않습니다. `fills`에 별도 실행 증거가 기록되어 `PARTIALLY_FILLED` 또는 `FILLED`가 된 뒤에만 포지션과 실현손익이 바뀝니다. classroom은 수업을 끝까지 재현하기 위해 이 명시적 fill 단계를 `auto_fill=True`로 호출합니다.

모든 증거는 같은 SQLite 파일의 `broker_orders`, `order_events`, `fills`, `positions`, `realized_trades`, `classroom_replays`에 저장됩니다. 새 프로세스가 같은 DB를 열면 주문·포지션·replay phase를 다시 읽어 이어갑니다. `realized_trades`의 `exit_client_order_id`와 `exit_fill_id`는 어떤 청산 주문과 체결이 손익을 만들었는지 보여주는 provenance입니다.

시장 계약도 DB 쓰기 전에 검증합니다. KR 주문은 `KRW`, US 주문은 `USD`여야 하고, 한국 주식 수량은 정수여야 합니다. 상태가 `UNKNOWN`이면 체결 여부를 추측하지 않고 해당 대상의 새 주문·replay 주문, fill, 청산 mutation을 막습니다. 유효한 quote를 관찰하는 포트폴리오 pass가 먼저 실행되므로 high-water 관찰은 저장될 수 있습니다. 명시적인 관찰 증거에 따른 **evidence-based reconciliation** 전까지 주문 계열 mutation은 fail-closed입니다.

사이클은 각 종목을 하나씩 청산하는 방식이 아닙니다. **포트폴리오 전체 관찰 pass**에서 유효한 유한 quote가 있는 모든 포지션의 high-water를 청산 write 전에 저장한 다음, 청산 대상을 처리하고 새 진입을 봅니다. quote가 누락됐거나 잘못된 quote이면 그 포지션은 관찰 갱신과 주문 mutation을 건너뛰어 fail-closed로 남습니다. 한 청산 응답을 잃어도 valid quote가 있던 다른 포지션의 고점 기록이 먼저 남는 **청산 우선** 구조입니다.

## 5. 추천 조합

### 초급자: 무조건 돌아가는 첫 성공

```env
LECTURE_PROFILE=mock
LECTURE_TRADE_MODE=simulation
LECTURE_SAVE_REPORTS=1
```

얻는 것: 더미 데이터지만 전체 흐름이 끊기지 않고, `prism.db`와 `reports/`에 결과가 남습니다.

### 상태 학습: classroom 전체 사이클

```text
lecture-prism의 classroom 전체 사이클을 안전한 임시 SQLite DB로 실행해줘.
기존 prism.db는 수정하지 말고, 프로그램 안에서 db.DB_PATH를 임시 경로로 바꾼 뒤 main.py의 classroom 프로필을 실행해줘.
KR/US fixture의 유효한 유한 quote를 관찰해 두 포지션의 high-water를 청산 write 전에 갱신하고, 청산 우선 트레일링 스탑으로 이어지는 과정을 설명해줘.
classroom과 backtest가 외부 환경변수로 data/LLM/broker를 바꿀 수 없는 고정 offline 프로필인지 확인하되, classroom만 상태형 PaperBroker이고 backtest는 legacy _simulate_trade 경로라고 구분해줘.
provider validation → regime → screening → analysis gate → sizing → cycle 순서를 확인하고,
regime, candidate, order, fill이 같은 run_id로 어떻게 연결되는지 표로 보여줘.
```

### 중급자: 실제 가격·거래량만 켜기

```env
LECTURE_PROFILE=real_data
LECTURE_DATA_MODE=auto
LECTURE_TRADE_MODE=simulation
```

얻는 것: yfinance가 가능하면 실데이터를 쓰고, 실패하면 더미 데이터로 돌아갑니다.

### 선택: KIS 실제 수급만 읽기 전용으로 보강

`kis_market_data.py`는 선택한 KIS 환경에서 현재가와 일별 기관·외국인·개인 순매수만 읽습니다. `paper`는 `KIS_PAPER_APP_KEY`·`KIS_PAPER_APP_SECRET`, `real`은 `KIS_REAL_APP_KEY`·`KIS_REAL_APP_SECRET`을 사용하며 이 조회에는 계좌번호가 필요하지 않습니다. `LECTURE_KIS_MODE=demo|real`은 각각 paper/real 자격 증명 묶음을 선택합니다.

P3-04는 실제 숫자 한 묶음이 오는지 확인하는 smoke test이므로 실패를 연습 데이터 성공으로 바꾸지 않습니다. Part 4 분석에서는 `LECTURE_SUPPLY_SOURCE=kis`를 이번 실행에만 적용합니다. KIS가 실패하면 다른 다섯 분석 섹션은 유지하고 수급만 거래량 프록시로 돌아가며, 보고서에 그 사실을 명시합니다. 어떤 경우에도 주문·취소·정정·잔고·계좌 API는 호출하지 않고 매매는 simulation입니다.

```text
lecture-prism에서 삼성전자 005930의 KIS 읽기 전용 데이터 한 묶음을 확인해줘.
내가 고른 환경은 [paper 또는 real]이야. kis_market_data.py와 테스트를 먼저 읽고 현재가와 일별 기관·외국인·개인 순매수만 호출하는지 확인해줘.
기준일·가격·세 투자주체 순매수·환경·주문 계열 호출 0회를 보여줘. 주말이면 가장 최근 영업일이라고 적어.
키·토큰은 출력하지 말고 주문·취소·정정·잔고·계좌 API는 호출하지 마. 실패하면 재시도·환경 전환·mock 위장을 하지 마.
```

### 고급자: 원본 PRISM에 가까운 리서치 보고서

```env
LECTURE_PROFILE=research
LECTURE_LLM_MODE=oauth
LECTURE_REPORT_MODE=research
LECTURE_RESEARCH_TOOLS=""
```

얻는 것: 공식 Codex 로그인으로 `analysis_agents.py`의 전문 보고서 에이전트 6개를 개별 호출하고 편집 에이전트가 요약합니다. 이어 `buy_agent.py`가 보고서를 읽습니다. 추천·점수·목표가·손절가는 규칙이 소유하고, LLM은 BUY를 HOLD로만 veto할 수 있습니다. Perplexity/Firecrawl은 선택 보강입니다.

### KIS 모의투자 전체 주문 주기 확인

KIS 연결에 필요한 선택 패키지는 기본 mock/classroom 실행에는 필요하지 않습니다. 현재 저장소는 매수·매도, 주문가능수량·보유수량 제한, 주문 상태·체결 조회, 취소, 재시작 reconcile을 연결합니다. 접수는 체결로 보지 않고, 응답을 잃으면 UNKNOWN으로 기록해 중복 주문을 막습니다. 정정은 별도 명령 대신 취소 후 새 주문으로 처리합니다.

```text
lecture-prism의 KIS 관련 코드를 읽기 전용으로 점검해줘.
매수·매도 → 접수 저장 → 체결 조회 → 부분/전체 체결 → 취소 → 재시작 reconcile을 표로 보여줘.
정정이 취소 후 재주문 정책인 점과 UNKNOWN이 새 주문을 막는 조건도 설명해줘.
paper/live market provider fail-closed는 현재 코드·테스트 근거로 확인하고,
실계좌 주문이나 외부 API 호출은 절대 실행하지 마.
Toss WTS 선택 어댑터도 같은 기준으로 매수·매도·조회·취소·재시작 reconcile과 UNKNOWN 차단을 설명해줘.
다만 비공식 WTS 세션이며 실제 모의투자 backend가 없고, 실제 계좌 E2E는 수행하지 않았다고 명시해줘.
```

```env
LECTURE_PROFILE=paper
LECTURE_TRADE_MODE=demo
LECTURE_BROKER=kis
LECTURE_BROKER_MODE=demo
LECTURE_ENABLE_LIVE_BROKER=1
LECTURE_KIS_MODE=demo
```

추가로 `trading/trading/config/kis_devlp.yaml`에 KIS 모의투자 App Key, App Secret, HTS ID, 계좌번호를 채웁니다.

주의: `LECTURE_ENABLE_LIVE_BROKER=1`은 브로커 API 호출을 허용한다는 뜻입니다. 모의투자 모드라도 실제 증권사 서버에 요청이 나갈 수 있습니다.

현재 강의용 KIS 어댑터는 국내주식 매수와 매도 모두 연결합니다. 실계좌 검증은 실제 키·장 운영시간·사용자 승인이 필요하므로 자동 테스트에서는 외부 주문을 보내지 않습니다.

### 실전투자 설정 구조 — 실행 실습 아님

```env
LECTURE_PROFILE=live
LECTURE_TRADE_MODE=real
LECTURE_BROKER=kis
LECTURE_BROKER_MODE=real
LECTURE_ENABLE_LIVE_BROKER=1
LECTURE_ALLOW_REAL_BROKER=1
LECTURE_KIS_MODE=real
```

추가로 `kis_devlp.yaml`의 `default_mode`와 계좌별 `mode`도 `real`이어야 합니다.

이중 플래그는 market provider fail-closed와 별개인 **별도 live gate**입니다. KIS와 Toss의 전체 수명주기는 코드와 고정 fixture로 검증했지만, 그것만으로 live 운영 준비가 완료되지는 않습니다. 실제 계좌 E2E는 실제 키·장 운영시간·사용자 승인이 필요한 별도 작업이므로, 강의 문서와 자동 테스트는 주문 경로를 실행하지 않습니다.

## 6. Discord로 AI 판단 받기

Discord는 어떤 계좌에 얼마가 있는지 보여 주는 잔고 알림이 아닙니다. `main.py` 한 번에서 나온 스크리닝 후보, 종목별 6개 분석 근거, BUY/SELL/HOLD/PASS 판단, 마지막 AI 판단 요약을 순서대로 보냅니다. 계좌 잔고·계좌번호·webhook URL은 메시지에 보내지 않습니다.

```env
LECTURE_NOTIFY_DISCORD=1
DISCORD_WEBHOOK_URL="내 Discord 채널에서 만든 Incoming Webhook URL"
```

두 값 중 하나라도 없으면 Discord는 조용히 꺼집니다. webhook 형식이 잘못됐거나 Discord가 응답하지 않아도 스크리닝·분석·매매·피드백 저장은 계속됩니다. mock에서는 모든 메시지의 데이터 원천과 매매 모드가 연습 데이터·simulation이라는 사실을 함께 확인하세요.

```text
lecture-prism의 Discord 판단 알림 설정을 도와줘.
Discord Incoming Webhook URL은 내가 직접 .env에 넣을 테니 화면이나 답변에 출력하지 마.
LECTURE_NOTIFY_DISCORD=1과 webhook 설정이 모두 있을 때만 알림이 켜지는지 확인하고,
실제 주문 없이 mock 파이프라인을 실행해 스크리닝 → 종목별 분석 → 매매 판단 → AI 판단 요약 순서를 점검해줘.
메시지에 계좌 잔고·계좌번호·webhook 값이 들어가지 않는지도 확인해줘.
```

## 7. 보고서 산출물

`LECTURE_SAVE_REPORTS=1`이면 `main.py`가 분석 이후 `reports/`에 Markdown 보고서를 저장합니다.

| 프로필 | 보고서 성격 |
|---|---|
| `mock` | 더미 데이터 기반 6섹션 교육용 보고서 |
| `real_data` | 실가격·거래량 기반 6섹션 보고서 |
| `research` 이상 | LLM·선택 리서치 도구가 붙은 심화 보고서 |

`reports/`는 실행할 때 생기는 결과물이므로 Git에 올리지 않습니다.

## 8. 상태 증거와 안전을 점검하는 프롬프트

```text
방금 만든 classroom 임시 DB에서 주문과 체결 증거를 읽어 설명해줘.
broker_orders와 order_events에서는 CREATED → PREVIEWED → SUBMITTED → ACCEPTED와 FILLED를 구분하고,
fills에서는 실제 체결 수량·가격, positions에서는 보유 중 상태, realized_trades에서는 청산 손익과 exit provenance를 보여줘.
결과를 미체결 → 체결 → 청산 순서로 표로 정리하고, 마지막 positions가 0인지 확인해줘.
SQL은 네가 실행하되 DB를 수정하지는 마.
```

```text
dashboard.py가 현재 어떤 SQLite 테이블을 읽는지 코드로 확인해줘.
classroom core의 broker_orders, fills, positions, realized_trades가 현재 대시보드에 직접 보이는지 답하고,
보이지 않는다면 대시보드의 한계와 지금은 SQLite 증거로 확인해야 한다는 점을 설명해줘.
기능을 구현한 것처럼 말하지 말고, core table 시각화는 후속 과제로 표시해줘.
```

```text
lecture-prism의 실거래 기본 차단을 검증해줘.
live CLI나 main 파이프라인은 실행하지 말고, 격리 단위 테스트 tests.test_broker_adapters.BrokerAdapterTest.test_live_gate_isolated_test_never_reads_config_or_calls_adapter만 실행해줘.
테스트가 모든 LECTURE_* enable/allow 변수를 모두 0으로 고정하는지 확인해줘.
broker factory와 adapter place_order를 mock으로 감싸 호출되면 실패하게 하고, 계좌·config 파일을 읽지 않는지도 검증해줘.
그 조건에서 결과가 live_blocked이고 adapter 호출이 0회라는 테스트 증거만 설명해줘.
```

market regime·screening·provider fail-closed, 공식 Codex OAuth 역할별 분석 호출, KIS와 Toss WTS의 매수·매도·체결 조회·취소·재시작 reconcile은 현재 구현 범위입니다. Toss는 고정 `tossctl` JSON fixture로 검증했으며 실제 계좌 E2E는 수행하지 않았습니다. dashboard core-table 시각화는 후속 과제입니다.

### 기존 프로필 설정 점검 프롬프트

```text
lecture-prism의 현재 .env와 kis_devlp.yaml 설정을 점검해줘.

확인할 것:
1. LECTURE_PROFILE 기준으로 어떤 데이터/리포트/매매 수준인지 설명해줘.
2. 빠진 API 키가 있으면 어떤 기능만 꺼지는지 알려줘.
3. main.py 기본 실행이 API 키 없이도 깨지지 않는지 확인해줘.
4. demo 또는 real 매매가 켜져 있다면 안전 플래그가 의도와 맞는지 확인해줘.
5. 실제 주문 가능성이 있으면 빨간불로 표시하고, 내가 원하지 않는 한 simulation으로 되돌려줘.
```
