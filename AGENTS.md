# AGENTS.md

이 파일은 이 저장소에서 작업하는 코딩 에이전트(Codex 등)를 위한 안내입니다.

## 이 프로젝트가 무엇인가

**lecture-prism** 은 실운용 오픈소스 AI 자동매매 시스템 [`prism-insight`](https://github.com/dragon1086/prism-insight)(`~/Desktop/rocky/prism-insight/prism-insight`)를 **강의용으로 소형화한 축소판**입니다. 패스트캠퍼스 「AI 네이티브 자동매매 시스템 구축」 강의(파트3·4, 강사 문상록)의 교재 리포지토리입니다.

- **대상 수강생**: 매매 전략 아이디어는 있으나 API/코딩 경험이 약한 비전공자·바이브코딩 입문자.
- **핵심 교육 철학**: "전략은 사람이 세우고, 구현은 AI 코딩 에이전트에게 위임한다." 수강생은 터미널 명령어를 직접 치지 않고, 코딩 에이전트에게 프롬프트로 설치·실행·검증을 맡깁니다.
- **완제품 자동매매가 아님**: 목적은 실전 자동매매 운영이 아니라, 수강생이 자기 전략을 코드로 옮기는 **첫 경험**입니다. 그래서 **mock-first / simulation-first** 구조입니다.

## 절대 원칙 (작업 시 반드시 지킬 것)

1. **API 키 없이 데모가 즉시 돌아가야 한다.** `python3 main.py`는 표준 라이브러리만으로 스크리닝→분석→시뮬레이션 매매→피드백→DB 저장이 완주해야 합니다. LLM/실데이터 연결이 없으면 **자동으로 mock 폴백**합니다. 이 "첫 성공 경험"을 절대 깨지 마세요.
2. **실거래 금지가 기본값.** `trading.py --live`나 브로커 주문은 이중 안전 플래그(`LECTURE_ENABLE_LIVE_BROKER`, `LECTURE_ALLOW_REAL_BROKER`) 없이는 실제 주문을 하지 않고 `live_blocked`를 반환합니다. 이 게이트를 우회/약화하지 마세요.
3. **함수 시그니처 유지.** `run_screening`, `run_analysis`, `run_trading`, `run_feedback` 등의 입출력 형태는 `main.py` 파이프라인이 의존하므로 바꾸지 마세요.
4. **새 필수 의존성 추가 금지.** 데모 경로는 표준 라이브러리로만 동작해야 합니다. 외부 패키지는 전부 "선택 연동"(`requirements.txt`)입니다.
5. **시크릿을 커밋 대상으로 만들지 말 것.** `.env`, `*.secrets.yaml`, KIS 인증 파일, `prism.db`는 모두 `.gitignore`로 제외됩니다. `tasks/`, `.omc/`, `.omx/`도 로컬 운영용이라 커밋하지 않습니다.

## 파이프라인 구조 (루트의 교육용 코드)

4단계 파이프라인 + 확인 화면. `main.py`가 오케스트레이터입니다.

| 파일 | 역할 | 영역 | 수강생이 주로 바꾸는 곳 |
|---|---|---|---|
| `screening.py` | 전종목 → 후보 N종목 필터 | **알고리즘** (규칙·대량·속도) | `VOLUME_SURGE_RATIO`, `MIN_MARKET_CAP_KRW`, `MOMENTUM_DAYS`, `MAX_CANDIDATES` |
| `analysis.py` | 후보 → 6섹션 분석 → 투자의견 | **LLM+규칙 혼합** | 에이전트 프롬프트 3종(기술·뉴스·전략) |
| `data_source.py` | 실데이터 단일 접점 (yfinance→mock 폴백) | **데이터** | `_PROFILES` mock, 지표 계산 |
| `trading.py` | 분석 → 포지션 사이징 → 청산 판단 | **의사결정** | 리스크 상수, `STOP_LOSS`/`TAKE_PROFIT`/`TRAILING_STOP`, `_decide_exit` |
| `feedback.py` | 매매 결과 → 교훈 추출 → 메모리 저장 | **자기개선** | `_extract_lesson` |
| `db.py` | 공용 SQLite(`prism.db`) 스키마·읽기·쓰기 | 저장소 | 보통 수정 안 함 (스키마 단일 소스) |
| `dashboard.py` | localhost:8080 로컬 웹 대시보드 (FastAPI, 빌드 없는 단일 HTML) | 확인 화면 | 표·카드 추가 |
| `blank_pipeline.py` | 4함수 빈 뼈대 (심화: 처음부터 구현) | 실습 | 4함수 중 1개 |

**데이터 흐름**: `analysis.py` → `run_analysis()`가 원본 PRISM scenario 형태 dict 반환(`recommendation`/`decision`/`buy_score`/`target_price`/`stop_loss`/`risk_reward_ratio` + 6섹션 요약 `technical/supply/financial/industry/news_summary`·`market_condition` 등) → `trading.py`가 `buy_score`·`current_price`로 매수/수량 결정 → `feedback.py`가 `db.py`를 통해 `prism.db`에 기록 → `dashboard.py`가 읽어 표시. (피드백 루프가 실제로 연결되어 있음.)

**6섹션 분석 (v2 리치 리포트)**: `analysis.py`는 원본 PRISM처럼 기술·수급·재무·산업·뉴스·시장 6개 섹션을 냅니다. **규칙으로 되는 건 규칙으로**(수급·재무·산업·시장 = `data_source` 실데이터 지표 템플릿), **맥락 판단은 LLM으로**(기술·뉴스·전략 = 3-에이전트 체인, 파트4 트랙B). 3계층 동작: ① Tier 0 mock(표준 라이브러리) → ② Tier 1 `pip install yfinance` 실데이터 → ③ Tier 2 `+OPENAI/OAuth` LLM 심층 서술. 각 계층 실패 시 하위로 자동 폴백.

### 핵심 규칙 (헷갈리기 쉬운 것)

- **매수 점수(`buy_score`)는 0~10점 스케일.** (과거 5점에서 전수 통일됨. 5점으로 되돌리지 마세요.) 진입 게이트: `analysis.MIN_BUY_SCORE = 6`, `trading.BUY_SCORE_THRESHOLD = 6`.
- **모든 튜닝 값은 각 파일 상단 상수**에 모여 있어 한 줄만 고치면 동작이 실제로 바뀝니다.
- **매매 철학**: 윌리엄 오닐식 추세추종. 목표가는 '마일스톤', 수익은 트레일링 스탑으로 보호. 청산 점검 순서 = ① 손절 → ② 트레일링 스탑 → ③ 목표가.
- `screening.py`의 `_SAMPLE_UNIVERSE`는 필터가 "실제로 작동"함을 보여주는 데모 유니버스입니다. `--real` 플래그를 켜면 이 유니버스 종목들을 yfinance 실데이터로 다시 필터링하고, 실패/결과 0개 시 데모값으로 자동 폴백합니다.
- `data_source.fetch_stock_data()` — 분석·스크리닝 공통 실데이터 단일 접점 (`screening._filter_with_real_data()`도 이 함수를 재사용). yfinance 시도→mock 폴백을 단일 처리하므로, 다른 소스로 바꾸려면 이 함수만 교체.
- **데이터 소스 주의**: KRX는 전종목 벌크 조회(시총·거래대금·수급·재무·지수)에 로그인을 요구해 pykrx로 못 가져옵니다(2026-07 실측: 벌크 API는 KeyError로 깨지고 per-ticker 시세만 동작). 그래서 스크리닝·분석 모두 무료·무로그인 **yfinance**(가격·거래량·시총·재무·뉴스·지수)를 쓰고, 수급은 **거래량 파생 프록시**로 정직하게 대체합니다. yfinance 뉴스는 **영문 국제 기사**라 LLM이 한글로 해석합니다.
- **런타임 프로필**: `.env`의 `LECTURE_PROFILE=mock|real_data|research|paper|live`이 `runtime_config.py`를 통해 데이터/LLM/리포트/매매 경로를 라우팅합니다(`docs/runtime-profiles.md`). `research_tools.py`(Perplexity/Firecrawl)·`report_writer.py`(`reports/` 저장)는 전부 선택 연동이며 미설정 시 자동 폴백 — 기본 mock 경로를 절대 깨지 마세요.

## `cores/` 는 원본 참조 사본 (주의)

`cores/analysis.py`, `cores/data_prefetch.py`, `cores/agents/agents/*` 는 **원본 prism-insight에서 가져온 참조용 사본**입니다. `mcp_agent`, `cores.report_generation` 등 이 저장소에 없는 모듈에 의존하므로 **그대로는 실행되지 않으며, 루트 교육용 파이프라인은 이것을 import 하지 않습니다.** (루트 `analysis.py`가 교육용 경량 버전.) 수강생이 원본 에이전트 프롬프트를 열람하는 용도로만 존재합니다. 혼동 주의: `main.py`가 쓰는 건 항상 루트의 `analysis.py`입니다.

**실제로 파이프라인이 쓰는 `cores/` 하위는 `cores/chatgpt_proxy` 뿐입니다** — ChatGPT OAuth 프록시(API 키 없이 ChatGPT 구독으로 GPT 호출). `main.py`는 `PRISM_OPENAI_AUTH_MODE=chatgpt_oauth`일 때만 프록시를 시도하고, 실패하면 mock으로 폴백합니다. 프록시는 localhost:18741에서 뜹니다.

## 브로커 어댑터 (`brokers/`)

`trading.py`를 갈아엎지 않고 `.env`의 `LECTURE_BROKER=kis|kiwoom|toss|custom`으로 증권사를 교체하는 플러그형 어댑터 구조. 기본은 `kis`. 공통 주문 객체 `BrokerOrder`를 어댑터가 각 API 필드로 변환합니다. `custom`은 `LECTURE_BROKER_ADAPTER=module:Class`로 확장. **모든 경로가 기본적으로 실주문 차단**(위 절대 원칙 2번).

## 문서 작성 관례 (중요)

수강생용 문서(README, START_HERE, `lecture/`, `docs/`)에는 **터미널 명령어 블록을 직접 넣지 않습니다.** 대신 "코딩 에이전트에게 그대로 붙여넣는 프롬프트"를 제공합니다. 이 저장소의 문서를 수정할 때 이 스타일을 유지하세요. (강사가 리포지토리 다운로드 방법은 별도 안내한다는 전제.)

- 파트4 실습 = **트랙 A(진입/`screening.py`) / B(분석/`analysis.py`) / C(청산/`trading.py`) / D(리스크/`trading.py`)** 중 하나만 본인 로직으로 교체하면 성공.
- **Strategy Harness Lite** (`.claude/`, `.codex/`, `MY_STRATEGY.md`, `docs/harness-lite.md`): 수강생이 전략을 애매하게 말해도 인터뷰어→구현자→검증자 역할로 최소 한 파일만 안전하게 수정하도록 돕는 하네스. 관련 스킬: `lecture-prism-strategy-harness`.

## 개발/검증 명령

```bash
python3 main.py                     # 기본 데모 (mock 폴백, 키 불필요) — 반드시 완주해야 함
python3 main.py --ticker 005930     # 단일 종목
python3 main.py --real              # yfinance 실데이터 스크리닝 (실패 시 데모 폴백)
python3 trading.py --exit           # 청산 3시나리오(손절/트레일링/목표가) 데모
python3 trading.py --live           # 반드시 live_blocked 반환(실주문 안 함)이어야 정상
python3 dashboard.py                # http://localhost:8080 (fastapi/uvicorn 필요)
python3 -m unittest discover -s tests -v   # 브로커/프록시 번역 테스트

# 컴파일 체크 (pycache를 저장소 밖으로)
PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache python3 -m compileall main.py analysis.py screening.py trading.py feedback.py db.py dashboard.py
```

작업 완료 전 최소 검증: `python3 main.py` 완주 + 관련 테스트 통과 + 민감정보/로컬 경로 미포함 확인.

## Git / 브랜치

- 원격: `https://github.com/dragon1086/lecture-prism` (공개 레포 기준으로 안전한 파일만 커밋).
- 코드 파일(`.py` 등) 변경은 feature 브랜치 + PR. 문서(`.md`)만 변경은 main 직접 커밋 가능.
- `main`에 직접 push 금지. 작업 전 브랜치부터.

## 더 읽을 것

- `tasks/handoff.md` — 세션 연속성 문서(로컬 전용, ignore). 최근 작업·다음 액션·검증 체크리스트.
- `tasks/강사_과정정보_초안.md` — 강사/과정 소개 원문(패스트캠퍼스 제출본 동기화).
- `tasks/upgrade-todo.md` — Opus 4.8 업그레이드 진행 기록.
- `docs/architecture.md`, `docs/why-multi-agent.md`, `docs/broker-adapters.md`, `docs/api-keys.md`, `docs/harness-lite.md`, `docs/agent-prompt-equivalence.md`.
