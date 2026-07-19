# 런타임 프로필 가이드

lecture-prism은 한 저장소 안에서 초급자용 더미 데모부터 상태가 남는 교실 재생, 선택 실데이터·리서치·브로커 연결까지 단계적으로 구분합니다. 프로필 이름이 있다고 해서 해당 운영 경로가 모두 완성됐다는 뜻은 아닙니다.

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
| `classroom` | 고정 KR/US 시세 | LLM 없음 | 상태형 paper replay | 주문·체결·보유·청산 증거 학습 |
| `real_data` | yfinance 실데이터, 실패하면 더미 데이터 | 6섹션 기본 보고서 | 가상 매매 | 실제 가격·거래량으로 보고 싶은 수강생 |
| `research` | 실데이터 | LLM + Perplexity/Firecrawl 선택 리서치 | 가상 매매 | 원본 PRISM에 가까운 분석을 원하는 수강생 |
| `paper` | 현재 `auto` | research 보고서 | 증권사 모의투자 설정 경로 | **후속 과제**, 운영 준비 완료 아님 |
| `live` | 현재 `auto` | research 보고서 | 이중 잠금된 실전 설정 경로 | **후속 과제**, 기본 차단 유지 |
| `backtest` | 고정 mock | LLM 없음 | offline simulation | 외부 연동을 고정 차단한 호환 프로필 |

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
| `LECTURE_SCREENING_MODE` | `mock`, `real` | 스크리닝 유니버스 원천 (`real` = yfinance 실데이터 필터) |
| `LECTURE_LLM_MODE` | `mock`, `auto`, `oauth`, `openai` | LLM 호출 여부 |
| `LECTURE_REPORT_MODE` | `lite`, `research` | 보고서 깊이 |
| `LECTURE_RESEARCH_TOOLS` | `perplexity,firecrawl` | 선택 리서치 도구 |
| `LECTURE_TRADE_MODE` | `simulation`, `demo`, `real` | 매매 실행 수준 |
| `LECTURE_SAVE_REPORTS` | `1`, `0` | `reports/` Markdown 저장 여부 |

`mock`, `real_data`, `research`의 선택 연동은 실패하면 더 안전한 기능으로 폴백합니다. 예를 들어 `research`에서 Perplexity 키가 없으면 해당 리서치만 빠지고 기본 분석은 계속됩니다.

다만 이 폴백 정책을 주문 경로까지 확대하면 안 됩니다. 목표 계약은 **paper/live에서는 mock 데이터로 주문 판단을 계속하지 않고 market provider 실패를 fail-closed로 막는 것**입니다. 이 market-provider slice는 아직 후속 과제이므로, 현재 `paper`와 `live`를 완성된 운영 프로필로 사용하거나 설명하지 않습니다.

`classroom`과 `backtest`는 환경변수로 data/LLM/broker 설정을 덮어쓸 수 없는 고정 offline simulation 프로필입니다. 둘 다 paper broker와 mock 데이터만 사용하고 live 플래그를 무시합니다. `classroom`은 여기에 상태형 KR/US replay가 연결되어 있고, `backtest`는 전체 백테스트 엔진 완성을 뜻하지 않습니다.

## 3. mock 첫 실행과 classroom 상태 재생

`mock`은 기존 강의 파이프라인입니다. API 키 없이 스크리닝, 6섹션 mock 분석, 가상 매매, 피드백 저장을 한 번에 경험하는 것이 목적입니다.

`classroom`은 주문 원장을 배우기 위한 별도 경로입니다. 삼성전자(KR/KRW)와 AAPL(US/USD)을 대상으로 아래 세 사이클을 결정론적으로 실행합니다.

1. 지정가 진입 주문과 fill 기록
2. 두 시장 포지션의 high-water 갱신
3. 트레일링 스탑 청산과 실현손익 기록

주문 제출은 `CREATED → PREVIEWED → SUBMITTED → ACCEPTED` 순서입니다. **ACCEPTED는 체결이 아닙니다.** 이 상태에서는 미체결 주문만 있고 `positions`는 생기지 않습니다. `fills`에 별도 실행 증거가 기록되어 `PARTIALLY_FILLED` 또는 `FILLED`가 된 뒤에만 포지션과 실현손익이 바뀝니다. classroom은 수업을 끝까지 재현하기 위해 이 명시적 fill 단계를 `auto_fill=True`로 호출합니다.

모든 증거는 같은 SQLite 파일의 `broker_orders`, `order_events`, `fills`, `positions`, `realized_trades`, `classroom_replays`에 저장됩니다. 새 프로세스가 같은 DB를 열면 주문·포지션·replay phase를 다시 읽어 이어갑니다. `realized_trades`의 `exit_client_order_id`와 `exit_fill_id`는 어떤 청산 주문과 체결이 손익을 만들었는지 보여주는 provenance입니다.

시장 계약도 DB 쓰기 전에 검증합니다. KR 주문은 `KRW`, US 주문은 `USD`여야 하고, 한국 주식 수량은 정수여야 합니다. 상태가 `UNKNOWN`이면 체결 여부를 추측하지 않고 해당 대상의 다음 쓰기를 막습니다. 운영자가 저장된 증거를 조정하기 전까지 fail-closed로 유지됩니다.

사이클은 각 종목을 하나씩 청산하는 방식이 아닙니다. 먼저 **포트폴리오 전체 high-water**를 저장한 다음 청산 대상을 처리하며, 새 진입보다 **청산 우선** 순서를 지킵니다. 한 청산 응답을 잃어도 다른 포지션의 고점 기록이 먼저 남도록 한 구조입니다.

## 4. 추천 조합

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
KR/US 진입 → 포트폴리오 전체 high-water 갱신 → 청산 우선 트레일링 스탑이 어떻게 이어졌는지 설명해줘.
classroom과 backtest가 외부 환경변수로 data/LLM/broker를 바꿀 수 없는 고정 offline 프로필인지도 검증해줘.
```

### 중급자: 실제 가격·거래량만 켜기

```env
LECTURE_PROFILE=real_data
LECTURE_DATA_MODE=auto
LECTURE_TRADE_MODE=simulation
```

얻는 것: yfinance가 가능하면 실데이터를 쓰고, 실패하면 더미 데이터로 돌아갑니다.

### 고급자: 원본 PRISM에 가까운 리서치 보고서

```env
LECTURE_PROFILE=research
LECTURE_LLM_MODE=auto
LECTURE_REPORT_MODE=research
LECTURE_RESEARCH_TOOLS=perplexity,firecrawl
OPENAI_API_KEY="..."
PERPLEXITY_API_KEY="..."
FIRECRAWL_API_KEY="..."
```

얻는 것: 분석 에이전트가 LLM으로 기술·뉴스·전략 섹션을 쓰고, Perplexity/Firecrawl 컨텍스트가 뉴스 섹션에 보강됩니다.

### 모의투자 설정 구조 읽기 — 후속 과제

KIS 연결에 필요한 선택 패키지는 기본 mock/classroom 실행에는 필요하지 않습니다. 현재 저장소에는 부분 어댑터가 있지만, 주문·조회·정정·취소·체결 확인·재시작 reconcile을 포함한 full lifecycle은 완료되지 않았습니다. 아래 프롬프트는 실제 연결 시작이 아니라 현재 범위와 빈칸을 확인하는 용도입니다.

```text
lecture-prism의 KIS 관련 코드를 읽기 전용으로 점검해줘.
현재 실제로 연결된 주문 단계와 아직 없는 조회·정정·취소·체결 확인·재시작 reconcile을 표로 나눠줘.
paper/live의 market provider fail-closed가 아직 후속 과제인지 확인하고,
실계좌 주문이나 외부 API 호출은 절대 실행하지 마.
Toss도 완료된 어댑터라고 가정하지 말고 같은 기준으로 빈칸만 설명해줘.
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

현재 강의용 KIS 어댑터는 국내주식 **매수 주문 경로부터** 연결합니다. 청산 규칙은 시뮬레이션에서 검증할 수 있지만, KIS 매도 주문 연결은 이후 확장 과제입니다.

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

이중 플래그는 기존 안전장치 설명입니다. 이것만으로 live 운영 준비가 완료되지 않습니다. market provider fail-closed와 KIS full lifecycle 검증 전에는 실제 주문 경로를 켜지 않습니다.

## 5. 보고서 산출물

`LECTURE_SAVE_REPORTS=1`이면 `main.py`가 분석 이후 `reports/`에 Markdown 보고서를 저장합니다.

| 프로필 | 보고서 성격 |
|---|---|
| `mock` | 더미 데이터 기반 6섹션 교육용 보고서 |
| `real_data` | 실가격·거래량 기반 6섹션 보고서 |
| `research` 이상 | LLM·선택 리서치 도구가 붙은 심화 보고서 |

`reports/`는 실행할 때 생기는 결과물이므로 Git에 올리지 않습니다.

## 6. 상태 증거와 안전을 점검하는 프롬프트

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
내 환경의 실제 broker 설정이나 계좌 파일은 열거나 바꾸지 말고 trading.py의 live 요청을 실행해 live_blocked가 반환되는지 확인해줘.
주문·fill·position·실현손익 테이블에 외부 브로커 mutation이 생기지 않았는지도 안전한 임시 DB나 전후 건수 비교로 증명해줘.
```

OAuth 프록시 기본형과 KIS 부분 어댑터가 존재하더라도, 분석 evidence provenance, market regime, market-provider fail-closed, KIS full lifecycle, Toss WTS adapter는 모두 후속 과제입니다. 완료된 기능으로 설명하지 않습니다.

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
