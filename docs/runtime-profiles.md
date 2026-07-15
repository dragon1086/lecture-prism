# 런타임 프로필 가이드

lecture-prism은 한 저장소 안에서 초급자용 더미 데모부터 고급자용 실데이터·리서치·브로커 연결까지 단계적으로 켤 수 있습니다.

수강생이 기본적으로 만지는 파일은 하나입니다.

| 파일 | 역할 |
|---|---|
| `.env` | 더미/실데이터/리서치/매매 수준 선택, 알림·KIS API 키와 계좌 입력 |

처음에는 `.env` 없이도 됩니다. 설정을 따로 만들고 싶다면 `.env.example`을 참고해 `.env`를 만들고 `LECTURE_PROFILE=mock`으로 시작하세요. 이 값이면 API 키가 없어도 스크리닝, 분석, 가상 매매, 피드백 저장, Markdown 보고서 생성까지 돌아갑니다.

## 1. 프로필 한 줄로 고르기

| 프로필 | 데이터 | 분석 보고서 | 매매 | 추천 대상 |
|---|---|---|---|---|
| `mock` | 더미 데이터 | 6섹션 기본 보고서 | 가상 매매 | 첫 실행, Part 4 전략 실습 |
| `real_data` | yfinance 실데이터, 실패하면 더미 데이터 | 6섹션 기본 보고서 | 가상 매매 | 실제 가격·거래량으로 보고 싶은 수강생 |
| `research` | 실데이터 | LLM + Perplexity/Firecrawl 선택 리서치 | 가상 매매 | 원본 PRISM에 가까운 분석을 원하는 수강생 |
| `paper` | 실데이터 | research 보고서 | 증권사 모의투자 경로 | KIS/키움 모의투자 키가 있는 수강생 |
| `live` | 실데이터 | research 보고서 | 실전투자 경로 | 강의 이후 본인이 책임지고 운영할 고급 사용자 |

```text
내 .env를 lecture-prism 런타임 프로필 방식으로 점검해줘.
내 목표는 [mock / real_data / research / paper / live] 중 하나야.
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

중요한 점은 각 스위치가 실패해도 전체 실행이 멈추지 않고 더 안전한 단계로 돌아간다는 것입니다. 예를 들어 `research`를 골랐지만 `PERPLEXITY_API_KEY`가 없으면 Perplexity 리서치만 빠지고, 기본 뉴스/데이터 분석은 계속 진행됩니다.

알림도 같은 원칙을 따릅니다. Discord 또는 Telegram 알림 실패는 해당 전달 상태를 `failed`로 남기지만 **파이프라인은 계속** 실행됩니다. Discord는 3주차 필수 준비이고 Telegram은 선택 준비이며, 인증값은 로컬 `.env`에만 둡니다.

| 채널 | 스위치 | 인증값 | 강의 기준 |
|---|---|---|---|
| Discord | `LECTURE_NOTIFY_DISCORD` | `DISCORD_WEBHOOK_URL` | 필수 준비, 4주차 기본 증거 채널 |
| Telegram | `LECTURE_NOTIFY_TELEGRAM` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | 선택, Discord와 같은 `run_id`·`sequence` 확인 |

## 3. 추천 조합

### 초급자: 무조건 돌아가는 첫 성공

```env
LECTURE_PROFILE=mock
LECTURE_TRADE_MODE=simulation
LECTURE_SAVE_REPORTS=1
```

얻는 것: 더미 데이터지만 전체 흐름이 끊기지 않고, `prism.db`와 `reports/`에 결과가 남습니다.

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

### 모의투자: 증권사 API 연결 연습

```env
LECTURE_PROFILE=paper
LECTURE_TRADE_MODE=demo
LECTURE_BROKER=kis
LECTURE_BROKER_MODE=demo
LECTURE_ENABLE_LIVE_BROKER=1
LECTURE_KIS_MODE=demo
KIS_PAPER_APP_KEY="..."
KIS_PAPER_APP_SECRET="..."
KIS_PAPER_ACCOUNT_NO="..." # 계좌번호 앞 8자리
KIS_PAPER_PRODUCT_CODE="01"
```

KIS 기본 클라이언트는 위 `KIS_PAPER_*` 값을 읽습니다. 실제 값은 로컬 `.env`에만 두고 출력하거나 제출하지 않습니다.

주의: `LECTURE_ENABLE_LIVE_BROKER=1`은 브로커 API 호출을 허용한다는 뜻입니다. 모의투자 모드라도 실제 증권사 서버에 요청이 나갈 수 있습니다.

3주차에는 KIS 모의투자 키 준비만 하고 `LECTURE_ENABLE_LIVE_BROKER=0`, `LECTURE_ALLOW_REAL_BROKER=0`, `LECTURE_ALLOW_REAL_KIS=0`을 유지합니다. 위의 paper 호출 허용은 4주차에 코딩 에이전트가 demo 계정과 안전 게이트를 다시 확인한 뒤 진행합니다.

### 실전투자: 이중 안전장치가 모두 필요

```env
LECTURE_PROFILE=live
LECTURE_TRADE_MODE=real
LECTURE_BROKER=kis
LECTURE_BROKER_MODE=real
LECTURE_ENABLE_LIVE_BROKER=1
LECTURE_ALLOW_REAL_BROKER=1
LECTURE_KIS_MODE=real
KIS_REAL_APP_KEY="..."
KIS_REAL_APP_SECRET="..."
KIS_REAL_ACCOUNT_NO="..." # 계좌번호 앞 8자리
KIS_REAL_PRODUCT_CODE="01"
```

실전 모드는 `KIS_REAL_*` 인증값을 별도로 읽습니다. 모의투자 키를 실전 서버에 재사용하지 않습니다.

이 상태에서도 주문 어댑터가 실패하면 결과에는 실패 사유가 기록되고, 파이프라인은 설명 가능한 상태로 종료됩니다.

## 4. 보고서 산출물

`LECTURE_SAVE_REPORTS=1`이면 `main.py`가 분석 이후 `reports/`에 Markdown 보고서를 저장합니다.

| 프로필 | 보고서 성격 |
|---|---|
| `mock` | 더미 데이터 기반 6섹션 교육용 보고서 |
| `real_data` | 실가격·거래량 기반 6섹션 보고서 |
| `research` 이상 | LLM·선택 리서치 도구가 붙은 심화 보고서 |

`reports/`는 실행할 때 생기는 결과물이므로 Git에 올리지 않습니다.

## 5. 에이전트에게 맡기는 점검 프롬프트

```text
lecture-prism의 현재 .env 설정을 점검해줘. 시크릿 값 자체는 출력하지 마.

확인할 것:
1. LECTURE_PROFILE 기준으로 어떤 데이터/리포트/매매 수준인지 설명해줘.
2. 빠진 API 키가 있으면 어떤 기능만 꺼지는지 알려줘.
3. main.py 기본 실행이 API 키 없이도 깨지지 않는지 확인해줘.
4. demo 또는 real 매매가 켜져 있다면 안전 플래그가 의도와 맞는지 확인해줘.
5. 실제 주문 가능성이 있으면 빨간불로 표시하고, 내가 원하지 않는 한 simulation으로 되돌려줘.
```

## 6. 4주차 System Completion Lane 증거

A/B/C/D 중 한 전략 트랙을 먼저 통과한 뒤, 같은 실행의 `run_id`와 이벤트 `sequence`, 실제 데이터 기준일 `data_as_of`, Discord 및 선택 Telegram 전달 상태, KIS 모의투자 주문 상태, 대시보드를 맞춰 봅니다. 주문 접수와 체결은 다르므로 `accepted`, `partial_fill`, `filled`, `blocked`, `live_blocked`를 구분하고 포트폴리오에는 체결 수량만 반영합니다.

```text
내 전략 트랙 검증이 끝났으니 System Completion Lane 증거를 점검해줘.
같은 run_id의 data_as_of와 sequence, Discord 전달, 설정된 경우 Telegram parity,
주문 접수·부분 체결·체결·차단 상태, 대시보드 표시가 서로 일치하는지 확인해줘.
알림 실패가 있어도 파이프라인은 계속되었는지 보여주고 시크릿 값은 출력하지 마.
실전 주문은 live_blocked 상태를 유지해줘.
```
