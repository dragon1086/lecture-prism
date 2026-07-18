# PRISM Core 실전 자동매매·강의 정렬 설계

> 상태: 사용자 승인 완료
> 승인일: 2026-07-19
> 대상 저장소: `lecture-prism`
> 기준 프로젝트: `prism-insight`, `tossinvest-cli`
> 강의 기준: https://fastcampus.co.kr/fin_thecamp_aitrading
> 선행 설계: `2026-07-15-observable-paper-trading-system-design.md`의 관찰성·알림·KIS paper 계약을 흡수한다.

## 1. 목적

`lecture-prism`을 API 키 없이 실행되는 교육용 데모에 머무르지 않고, 한국·미국 시장에서 동일한 안전 원칙으로 실제 데이터, 상태형 포트폴리오, 모의투자, 실거래 브로커까지 연결되는 작은 자동매매 시스템으로 발전시킨다.

동시에 3·4주차 각 2시간을 듣는 비전공자 수강생에게 원본 PRISM의 복잡도를 그대로 노출하지 않는다. 내부에는 운영 가능한 `PRISM Core`를 두고, 수강생은 전략 플러그인과 프롬프트 중심의 `Course Shell`만 다룬다.

핵심 원칙은 다음 두 문장이다.

1. 강의에서 단순화하는 것은 조작 화면과 수정 범위이지, 데이터·주문·상태의 정합성이 아니다.
2. 전략은 사람이 세우고 구현은 AI에게 맡기되, 주문 안전성과 상태 전이는 결정론적 코드가 강제한다.

## 2. 외부 약속과 설계 제약

### 2.1 FastCampus 판매 페이지와 맞춰야 하는 약속

- 4주 총 8시간, 비전공자·입문자 대상
- Windows 10/11과 macOS 12 이상 지원
- KIS 모의투자 환경에서 시작
- 토요일 휴장을 고려한 재현 가능한 모의 데이터 제공
- 3주차 결과물: 종목 탐색 → 분석 → 판단 → 포지션 사이징 → 주문·미체결 → 피드백
- 4주차 결과물: 수강생 투자 조건을 AI 코딩 에이전트로 수정하고 전체 시스템 재실행
- Claude Pro 또는 ChatGPT Plus 중 한 가지 AI 구독으로 수강 가능
- 모의투자에서 검증한 뒤 실전 구조로 확장

### 2.2 저장소의 기존 절대 원칙

- `python3 main.py`는 외부 키와 필수 패키지 없이 완주한다.
- 실거래는 기본 차단하고 이중 환경 플래그 없이 실행하지 않는다.
- `run_screening`, `run_analysis`, `run_trading`, `run_feedback`의 공개 시그니처를 유지한다.
- 외부 패키지는 선택 설치이며 기본 데모는 표준 라이브러리만 사용한다.
- 시크릿·계좌·토큰·실행 DB는 Git에 포함하지 않는다.
- 수강생 문서는 터미널 명령 대신 코딩 에이전트에게 붙여넣는 프롬프트를 제공한다.

### 2.3 이번 설계가 추가하는 불변 조건

- `paper`와 `live` 프로필에서 실데이터 실패를 mock으로 대체하지 않는다.
- 주문 요청을 보냈으나 결과가 불명확하면 자동 재주문하지 않는다.
- 브로커 체결보다 먼저 보유 포지션을 확정하지 않는다.
- 기존 보유를 reconcile하고 청산을 검사한 뒤 신규 진입을 평가한다.
- 시장, 통화, 주문 유형을 추론하지 않고 명시한다.
- LLM과 뉴스는 결정론적 시장 레짐을 뒤집을 수 없다.
- 실현되지 않은 BUY 판단을 학습 성과로 기록하지 않는다.
- KR/US 동등 지원은 동일한 데이터 필드가 아니라 동일한 사이클·상태·안전 보장을 뜻한다.

## 3. 범위

### 3.1 필수 범위

1. KR/US 공용 시장·주문·포트폴리오 도메인
2. 결정론적 5단계 시장 레짐
3. 실제 유니버스와 레짐 적응 스크리닝
4. 레짐별 진입·리스크·청산 정책
5. 재시작 가능한 SQLite 상태 저장
6. 주문·체결·취소·reconcile을 포함한 paper 엔진
7. KIS 국내·미국 모의/실전 어댑터
8. 무료·무키 중심 정성 근거 수집
9. ChatGPT Plus OAuth LLM 공급자
10. 수강생 전략 플러그인과 Strategy Harness
11. 토요일 수업용 deterministic replay
12. Windows/macOS 설치 진단, run-once, 잠금, health check
13. 실행 ID 기반 관찰성과 선택형 Discord/Telegram 알림
14. KIS가 안정된 뒤 Toss WTS 선택 어댑터
15. 단위·통합·재시작 E2E·walk-forward 검증

### 3.2 이번 범위에서 제외

- 원본 PRISM 전체 PDF·다국어 Telegram 방송 파이프라인 이식
- 다중 계좌
- 피라미딩
- 고빈도 주문 프로세스
- n8n 같은 외부 오케스트레이터
- 정교한 상시 스케줄러·서버 데몬
- 정통 강화학습
- LLM 기반 장기 기억 압축
- 수익률 보장 또는 특정 전략의 우월성 주장

스케줄링은 `run-once`가 안정된 뒤 macOS `launchd`와 Windows 작업 스케줄러용 선택 템플릿만 제공한다. 스케줄러 자체를 핵심 엔진으로 만들지 않는다.

## 4. 선택한 아키텍처

### 4.1 이중 구조

```text
Course Shell
  ├─ main.py / screening.py / analysis.py / trading.py / feedback.py
  ├─ MY_STRATEGY.md
  ├─ strategies/<strategy_name>/track_a..d
  ├─ classroom replay
  └─ dashboard / notifications / doctor / 학생용 프롬프트

PRISM Core
  ├─ market domain
  ├─ universe + data providers
  ├─ regime + screening + policy
  ├─ portfolio + ledger + feedback
  ├─ broker contracts
  ├─ LLM + evidence providers
  └─ cycle orchestrator + safety gates
```

루트 교육용 함수는 하위 호환 facade로 유지한다. 운영 기능은 독립 모듈로 분리해 수강생이 전략을 수정하다가 DB, 브로커, 인증, 안전 게이트를 손상시키지 않게 한다.

### 4.2 전체 사이클

```text
preflight
  → broker/account/order reconcile
  → existing position exit evaluation
  → exit order preview/submit/reconcile
  → market regime calculation
  → universe screening
  → qualitative evidence collection
  → rule + LLM analysis
  → regime-aware entry gate
  → risk/position sizing
  → entry order preview/submit/reconcile
  → ledger/position/high-water persistence
  → realized-performance feedback update
  → run summary/dashboard/optional notifications
```

청산이 신규 진입보다 항상 먼저다. 동일 프로세스 재실행과 프로세스 중단 후 재시작에서도 결과가 중복되지 않아야 한다.

## 5. 런타임 프로필

| 프로필 | 데이터 | LLM | 주문 | 실패 정책 | 용도 |
|---|---|---|---|---|---|
| `mock` | 내장 최소 fixture | 규칙/mock | 로컬 dry-run | 항상 완주 | 설치 첫 성공 |
| `classroom` | 고정 KR/US 시장 replay | 규칙 또는 OAuth | 상태형 local paper | 결정론적 재현 | 토요일 3·4주차 |
| `real_data` | 실데이터 | 규칙 | 주문 없음 | 데이터 오류 표시 | 실데이터 관찰 |
| `research` | 실데이터+근거 | OAuth/선택 API | 주문 없음 | LLM 실패 시 규칙 분석 | 분석 실습 |
| `paper` | 실데이터 | 규칙/OAuth | local paper 또는 KIS 모의 | fail-closed | 평일 검증 |
| `live` | 실데이터 | 규칙/OAuth | KIS/Toss 실계좌 | fail-closed+이중 게이트 | 소액 실운영 |
| `backtest` | 과거 snapshot | 사용 안 함이 기본 | 체결 모델 | 누락 구간 제외 | 전략·레짐 궁합 |

`mock`과 `classroom`은 서로 다르다. `mock`은 설치 확인용 작은 예시이고, `classroom`은 실제 시장 형식을 보존한 시계열 replay와 상태 전이를 검증한다.

## 6. 공용 도메인 계약

### 6.1 시장과 종목

```text
Market: KR | US
Instrument:
  symbol
  market
  exchange
  currency
  name
  sector
  lot_size
  price_precision
```

KR은 6자리 종목 코드와 정수 호가·수량을 사용한다. US는 알파벳 심볼, USD 소수 가격, 선택적인 소수점 수량을 지원한다. 시장·통화가 없거나 일치하지 않으면 주문을 거부한다.

### 6.2 후보

기존 `run_screening()`은 `list[str]`를 반환한다. 내부에는 상세 후보 API를 추가한다.

```text
Candidate:
  instrument
  as_of
  trigger_type
  regime
  feature_values
  component_scores
  final_score
  reference_price
  stop_price
  target_price
  risk_reward_ratio
  source
```

티커 문자열 wrapper는 이 상세 객체에서 심볼만 반환한다. 스크리닝에서 계산한 trigger, regime, stop, score 문맥은 분석과 주문까지 보존한다.

### 6.3 주문

```text
BrokerOrder:
  client_order_id
  market
  symbol
  side
  order_type
  quantity
  amount
  limit_price
  currency
  fractional
  strategy_id
  reason
```

기존 필드에는 하위 호환 기본값을 제공하되, `paper/live`에서는 시장·통화·주문 유형 누락을 허용하지 않는다.

### 6.4 주문 상태

```text
CREATED → PREVIEWED → SUBMITTED → ACCEPTED → PARTIALLY_FILLED → FILLED
                                      ├─ REJECTED
                                      ├─ CANCELED
                                      └─ UNKNOWN
```

상태는 단조롭게 전진한다. `UNKNOWN`은 실패가 아니라 브로커가 요청을 받았을 가능성이 있는 상태다. 조회와 reconcile만 허용하고 새 주문으로 대체하지 않는다.

## 7. 시장 레짐과 전략 정책

### 7.1 5단계 레짐

- `strong_bull`
- `moderate_bull`
- `sideways`
- `moderate_bear`
- `strong_bear`

KR은 KOSPI/KOSDAQ의 20/60/120일선, 최근 수익률, 시장폭을 기본 입력으로 삼는다. US는 S&P 500/Nasdaq, 20/50/200일선, 최근 수익률, VIX를 기본 입력으로 삼는다.

레짐 계산은 순수 함수로 구현하고 합성 OHLCV fixture로 경계를 검증한다. 정확한 임계값은 원본 PRISM을 기준으로 초기화하되 table-driven 정책으로 외부화한다.

### 7.2 Market Pulse

분산일, drawdown, follow-through day를 다루는 상태는 5단계 레짐과 별도 축으로 유지한다.

이번 최소 범위에서는 복잡한 배치 중단 스케줄러로 쓰지 않는다. 관찰 지표와 진입 보수화 입력으로만 사용한다.

### 7.3 레짐이 강제하는 정책

- 활성 스크리닝 trigger
- trigger별 가중치
- 최소 후보 점수
- 최소 투자 판단 점수
- 최소 손익비
- 최대 손절폭
- 포트폴리오 최대 슬롯
- 종목당 계좌 위험률
- 현금 보유 하한
- 트레일링 폭
- 목표가 도달 후 보유/청산

이 정책은 프롬프트가 아니라 코드로 강제한다. LLM의 `Enter` 판단과 점수가 충돌하면 더 보수적인 결과를 따른다.

### 7.4 공용 청산 순서

1. 브로커/DB 보유 수량 불일치 차단
2. 시나리오 손절
3. 절대 손실 한도
4. 손실 중 핵심 이동평균 이탈
5. 수익 활성화 이후 레짐별 트레일링
6. 레짐별 목표가 처리
7. 전략 플러그인의 추가 청산 조건

목표가는 강세장에서 무조건 즉시 매도하는 값이 아니라 추세 관리의 마일스톤으로 취급할 수 있다.

## 8. 실제 유니버스와 데이터

### 8.1 공급자 구조

```text
UniverseProvider
MarketDataProvider
IndexDataProvider
CalendarProvider
EvidenceProvider
```

공급자는 캐시 시각, 원천, 시장, freshness를 반환한다. `paper/live`는 mock, stale, invalid price를 거부한다.

### 8.2 KR/US 지원

| 영역 | KR | US |
|---|---|---|
| 유니버스 | KOSPI/KOSDAQ snapshot + KIS/Toss refresh | S&P 500/Nasdaq-100 snapshot + provider refresh |
| 가격 | KIS/Toss/yfinance | KIS/Toss/yfinance |
| 지수 | KOSPI/KOSDAQ | S&P 500/Nasdaq/VIX |
| 수급 | 제공될 때 외국인·기관 | 동일 필드로 위조하지 않음 |
| 통화 | KRW | USD |
| 시간 | Asia/Seoul | America/New_York |

내장 유니버스 snapshot은 수업 재현과 공급자 장애 복구용이다. `paper/live` 가격은 반드시 실데이터 공급자에서 받아야 한다.

## 9. 무료 정성 근거와 LLM

### 9.1 증거 객체

```text
Evidence:
  source_url
  publisher
  published_at
  fetched_at
  market
  symbol
  kind
  title
  excerpt
  is_primary
  provider
  confidence
```

본문 전체를 무단 저장하지 않는다. 출처, 날짜, 대상 종목을 검증하고 같은 이벤트를 중복 제거한다.

### 9.2 기본 공급자 우선순위

KR:

1. OpenDART 무료키
2. DART RSS 무키
3. 한국은행 RSS
4. GDELT 발견
5. yfinance headline fallback

US:

1. SEC EDGAR 무키
2. Fed/BLS RSS
3. GDELT 발견
4. Alpha Vantage 무료키 또는 yfinance fallback

선택 보강:

- FRED 무료키
- NAVER API HUB
- Firecrawl
- Perplexity

Firecrawl과 Perplexity는 필수 경로가 아니다.

### 9.3 LLM 역할

LLM은 수집기가 아니다. 검증·정규화된 근거를 다음 범주로 분류하고 요약한다.

- 공시
- 실적
- 재무
- 규제
- 제품·산업
- 거시
- 섹터
- 위험

LLM 실패 시 정량 레짐·스크리닝·리스크·주문 안전성은 영향을 받지 않는다.

### 9.4 ChatGPT Plus OAuth

`chatgpt_oauth`를 일급 `LLMProvider`로 구현한다.

- 최초 브라우저 PKCE 로그인
- access/refresh token의 사용자별 로컬 저장
- 동시 갱신 잠금
- refresh token 자동 갱신
- quota·expiry health check
- 토큰·응답 원문의 민감 로그 금지
- Windows/macOS 저장 권한 방어
- OAuth 실패 시 규칙 분석으로 폴백

이는 정식 OpenAI API 키와 별도의 구독 백엔드 어댑터임을 문서에 명시한다.

Claude Pro만 준비한 수강생도 코딩 에이전트로 모든 기본 실습을 완주할 수 있어야 한다. Claude CLI의 비대화형 런타임 공급자는 공식 지원과 안정성이 확인될 때만 선택 공급자로 추가한다. 수업 성공을 특정 런타임 LLM에 의존시키지 않는다.

## 10. 포트폴리오·원장·피드백

### 10.1 상태의 진실 원천

- local paper: SQLite 체결 엔진
- KIS/Toss: broker fill과 position inquiry

분석 결론이나 주문 접수만으로 보유를 생성하지 않는다. 브로커 체결 결과를 reconcile한 뒤 포지션을 갱신한다.

### 10.2 최소 테이블

- `pipeline_runs`
- `market_regimes`
- `candidates`
- `analysis_decisions`
- `orders`
- `order_events`
- `fills`
- `positions`
- `position_events`
- `realized_trades`
- `strategy_performance`
- `evidence_items`
- `notification_deliveries`

기존 DB는 파괴하지 않고 migration version을 둔다.

### 10.3 피드백

청산 완료 후 다음을 `strategy_id × market × regime × trigger_type`으로 집계한다.

- 표본 수
- 승률
- 평균/중앙 수익률
- MFE/MAE
- 손절 횟수
- 평균 보유 기간
- 최대 연속 손실

표본이 적을 때는 정책을 자동 변경하지 않는다. 먼저 분석 근거로 노출하고, 충분한 표본과 명시적 설정이 있을 때만 후보 점수에 제한적으로 반영한다.

### 10.4 실행 관찰성과 알림

모든 사이클은 하나의 `run_id`와 증가하는 `sequence`를 가진 이벤트를 남긴다. 후보, 분석, 주문 판단, broker 상태, 포지션, 피드백을 같은 실행으로 추적할 수 있어야 한다.

Discord와 Telegram은 선택 채널이다. 알림 실패는 DB 저장이나 매매 사이클 결과를 바꾸지 않는다. 주문 POST와 달리 알림 전송만 제한적으로 재시도할 수 있으며, webhook·bot token·chat ID와 브로커 응답 원문은 이벤트나 대시보드에 노출하지 않는다.

FastCampus 1·2주차에서 Discord 준비를 마친 수강생은 같은 채널로 3주차 실행 결과를 받을 수 있다. Telegram은 강의 혜택과 원본 PRISM 운영 사례를 연결하는 선택 확장으로 제공한다. 3·4주차 핵심 실습은 알림 설정 실패와 무관하게 완주해야 한다.

## 11. 브로커 구조

### 11.1 공통 계약

```text
health()
get_market_status()
get_quote()
get_cash_balance()
get_positions()
preview_order()
place_order()
get_order_status()
list_open_orders()
list_fills()
cancel_order()
reconcile()
```

preview와 mutation을 분리한다. 모든 mutation은 idempotency key와 실행 결과를 저장한다.

### 11.2 KIS

강의의 기본 브로커다.

- 국내/미국 조회
- 모의/실전 계정 분리
- BUY/SELL
- 주문 가능 금액·수량
- 주문 조회
- 미체결 조회
- 취소
- 체결 reconcile
- 시장 시간·휴장 차단
- timeout 후 자동 재주문 금지

실전은 기존 이중 안전 플래그를 유지한다. 실계좌 E2E는 사용자의 별도 자격정보와 명시적 실행 승인 없이는 수행하지 않는다.

### 11.3 Toss WTS

KIS와 핵심 엔진이 완료된 뒤 선택 어댑터로 구현한다. 고정된 `tossctl` 버전의 JSON subprocess 계약을 사용한다.

- `shell=False`, argument list, timeout
- `--backend wts --output json` 고정
- 매 실행과 주문 직전 `auth status` 검증
- market/currency/order type 명시
- preview의 canonical intent와 confirm token 보존
- `unknown`과 timeout에 재주문 금지
- 주문·체결 조회로만 reconcile
- 거래 인증 요구 시 `manual_action_required`
- 자동 환전 동의 기본 비활성화
- amend 실거래 기본 비활성화

인증 목표는 최초 로그인 뒤 세션 유효 기간 동안 자동 운용하는 것이다. 현재 WTS 서버 세션 특성상 약 7일마다 휴대폰 승인이 필요할 수 있으므로 영구 무인 로그인을 약속하지 않는다.

로그인 경로는 다음 순서로 시도·검증한다.

1. 기존 Playwright 세션 import
2. interactive browser에서 휴대폰 번호 로그인 가능 여부 E2E 확인
3. 검증된 QR/딥링크 fallback

휴대폰 번호 경로는 실제 세션 호환 E2E가 통과하기 전까지 공식 수업 기능으로 표현하지 않는다.

## 12. Strategy Plugin과 Harness

### 12.1 구조

```text
strategies/
  default_oneil/
    screening_policy.py
    analysis_policy.py
    exit_policy.py
    risk_policy.py
    strategy.json
  my_strategy/
    ...
```

수강생 전략은 독립 폴더에 둔다. 기본 전략과 브로커 코어를 직접 수정하지 않는다.

### 12.2 트랙 매핑

| 트랙 | 수정 대상 | 검증 |
|---|---|---|
| A | candidate feature/filter/score | 레짐별 후보 순위 |
| B | evidence 관점·LLM prompt | 근거 누락·환각·전후 분석 |
| C | exit policy | 손절·트레일·목표가 fixture |
| D | sizing/slot/cash policy | 레짐별 계좌 위험·집중도 |

Strategy Harness는 다음 순서를 강제한다.

1. `MY_STRATEGY.md`를 네 트랙으로 분해
2. 한 트랙 선택
3. 기대 동작 테스트 작성
4. 플러그인 최소 수정
5. mock/classroom regression
6. 세 레짐 전후 비교
7. 다음 트랙 제안

## 13. 3·4주차 강의 구성

### 13.1 3주차: 실제 시스템 전체 사이클

콘텐츠 90분, Q&A 30분.

| 시간 | 내용 | 수강생 결과 |
|---|---|---|
| 10분 | 원본 PRISM과 강의판 지도 | 각 계층의 책임 설명 |
| 15분 | KR/US classroom replay | 전체 사이클 완주 |
| 20분 | 레짐과 스크리닝 궁합 | 같은 전략의 레짐별 차이 확인 |
| 20분 | 무료 근거 + GPT OAuth | 실제/규칙/mock 구분 |
| 25분 | KIS paper 주문 lifecycle | preview·미체결·체결·취소·reconcile 확인 |

대시보드에서 후보, 레짐, 분석 근거, 주문, 보유, 피드백이 한 실행 ID로 연결돼야 한다.

### 13.2 4주차: 자기 전략 플러그인

콘텐츠 90분, Q&A 30분.

| 시간 | 내용 | 수강생 결과 |
|---|---|---|
| 10분 | 투자철학 3줄 정리 | 진입·분석·청산·리스크 분해 |
| 15분 | Harness 트랙 선택 | 수정 파일·테스트 확정 |
| 35분 | 한 트랙 구현 | 자기 전략 플러그인 |
| 20분 | 강세·횡보·약세 비교 | 전후 결과표 |
| 10분 | 전체 paper 재실행 | 안전장치를 보존한 완주 |

성공 기준은 단순 실행이 아니다.

- 전략 문장과 코드 규칙이 대응한다.
- 세 레짐에서 결과 차이를 설명한다.
- 브로커와 상태 안전장치가 깨지지 않는다.
- 전체 사이클 regression이 통과한다.

## 14. 운영과 크로스플랫폼

### 14.1 학생용 명령 표면

수강생은 터미널 명령을 외우지 않고 다음 요청을 코딩 에이전트에 맡긴다.

- 설치·환경 진단
- classroom 전체 사이클 실행
- KIS 모의 연결 진단
- OAuth 로그인과 health check
- 전략 반영과 회귀 테스트
- dashboard 실행
- 민감정보 검사

### 14.2 최소 운영 기반

- `doctor`: Python, 선택 패키지, DB, provider, broker, OAuth 상태
- `run-once`: 중복 프로세스 잠금과 실행 ID
- `status`: 마지막 실행·주문·보유·인증 만료
- `notify-test`: 실제 주문과 분리된 무해한 Discord/Telegram 연결 점검
- atomic file/DB update
- 로그 rotation과 secret redaction
- 정상 종료·중단 복구
- macOS/Windows 경로 처리

Docker는 선택 경로다. native Python 경로도 동등하게 유지해 Docker 설치 실패가 수업 실패가 되지 않게 한다.

## 15. 오류 처리 원칙

| 상황 | mock/classroom | paper/live |
|---|---|---|
| 실데이터 실패 | fixture 사용 가능 | 주문 중단 |
| LLM 실패 | 규칙 분석 | 규칙 분석 또는 진입 보류 |
| stale price | 경고/fixture 규칙 | 주문 중단 |
| 시장 휴장 | replay 가능 | 주문 중단 |
| broker timeout | paper 상태 시뮬레이션 | UNKNOWN 저장·조회만 |
| DB/broker 불일치 | fixture 복구 가능 | 신규 주문 중단 |
| 인증 만료 | 안내 | 주문 중단·manual action |
| 잘못된 통화 | 테스트 실패 | 주문 거부 |

## 16. 검증 계약

### 16.1 순수 정책 테스트

- KR/US 5개 레짐 경계
- 레짐별 trigger와 score weight
- 레짐별 min score, RR, stop, slots, risk
- 공용 O'Neil exit tier
- KR/US 통화·가격 precision
- 휴장일과 시간대

### 16.2 상태형 paper E2E

1. cycle 1: 실제 형식 유니버스 → 후보 → BUY 접수 → fill → position
2. 프로세스 재시작
3. cycle 2: reconcile → high-water 갱신 → HOLD
4. 프로세스 재시작
5. cycle 3: stop/trailing → SELL → realized P&L → feedback

### 16.3 브로커 불변 조건

- 실패·거절 주문으로 ghost holding이 생기지 않는다.
- 체결 수량과 DB 포지션이 일치한다.
- 같은 client order ID로 중복 주문하지 않는다.
- timeout/UNKNOWN을 자동 재주문하지 않는다.
- 매도 전 실제 보유 수량과 reconcile한다.
- mock/stale/휴장/통화 불일치에서 실주문은 0건이다.

### 16.4 전략 검증

최소 2~3년 walk-forward에서 `market × regime × strategy × trigger`별로 다음을 비교한다.

- 표본 수
- 승률
- 평균/중앙 수익률
- MFE/MAE
- 손절률
- 평균 보유 기간
- 최대 낙폭

전체 수익률 하나로 전략의 유효성을 주장하지 않는다. 구현 성공과 전략 성과를 분리한다.

### 16.5 크로스플랫폼 검증

- macOS native Python
- Windows 10/11 PowerShell·Python
- 경로 공백
- UTF-8 한글
- Chrome/OAuth 탐색
- tossctl/tossctl.exe 탐색
- SQLite 파일 잠금·재시작

실제 Windows 장비가 없으면 CI와 fixture 결과를 실제 장비 E2E로 표현하지 않는다.

## 17. 구현 순서

1. 공용 도메인·DB migration·paper ledger
2. observable cycle orchestrator와 재시작 E2E
3. KR/US 레짐·calendar·유니버스·스크리닝
4. 레짐별 entry/risk/exit policy
5. 무료 evidence와 LLM provider
6. ChatGPT Plus OAuth health/persistence
7. KIS KR/US paper/live 계약
8. classroom replay·dashboard·notifications·doctor
9. Strategy Plugin·Harness·3·4주차 문서
10. backtest/walk-forward
11. Toss WTS adapter·인증 진단
12. 전체 보안·크로스플랫폼·회귀 검증

각 단계는 실패 테스트 작성 → 최소 구현 → 전체 회귀 → 문서 동기화 순서로 진행한다.

## 18. 대안과 기각 사유

### 원본 PRISM 전체 이식

기각. PDF, Telegram, 서버, 외부 데이터, 여러 프로세스의 의존성이 강의판과 Windows 환경을 압도한다. 구조화된 scenario를 직접 매매에 넘기는 강의판의 장점을 유지한다.

### 기존 코드에 KIS/Toss 호출만 추가

기각. mock 스크리닝, 하드코딩 포트폴리오, BUY-only, 비영속 상태가 남아 실제 자동매매가 되지 않는다.

### Toss를 3·4주차 기본 브로커로 사용

기각. 판매 페이지의 기본 실습은 KIS 모의투자이고, WTS의 비공식성·세션 연장·거래 인증 문제가 2시간 수업의 핵심을 흐린다. Toss는 선택 확장으로 제공한다.

### 뉴스/LLM이 레짐까지 결정

기각. 재현성과 검증 가능성을 잃는다. 가격·시장폭 기반 레짐을 고정하고 정성 근거는 설명과 리스크 보강에만 쓴다.

### paper/live에서도 mock fallback

기각. 가짜 가격으로 실제 주문을 만들 수 있다. mock fallback은 `mock/classroom`에만 허용한다.

## 19. 완료 정의

다음 조건을 모두 만족해야 “실제로 돌아가는 강의용 자동매매 시스템”으로 완료 선언한다.

- 기본 무키 데모가 계속 완주한다.
- classroom에서 KR/US 전체 매수→보유→청산 cycle이 재현된다.
- paper/live는 mock·stale 데이터에 fail-closed한다.
- KIS KR/US BUY/SELL/조회/미체결/취소/reconcile 계약이 구현된다.
- 실제 체결 이전에 ghost holding이 생기지 않는다.
- GPT Plus OAuth가 최초 로그인 뒤 refresh와 health check를 수행한다.
- 무료 정성 근거가 유료 도구 없이 분석에 들어간다.
- 동일한 run ID로 DB·대시보드·선택 알림의 결과를 추적할 수 있다.
- 알림 장애가 매매 상태나 파이프라인 성공 여부를 바꾸지 않는다.
- 한 전략 플러그인이 KR/US와 세 레짐 fixture에서 동작한다.
- 수강생이 한 트랙만 수정하고 전체 회귀를 통과할 수 있다.
- macOS와 Windows 검증 결과를 구분해 기록한다.
- Toss WTS가 선택 브로커로 연결되고 인증 만료·UNKNOWN 주문에 fail-closed한다.
- 관련 단위·통합·재시작 E2E·보안 검사가 통과한다.
- 3·4주차 강의안과 판매 페이지의 결과물 약속이 코드 현실과 일치한다.
