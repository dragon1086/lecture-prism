# API 키 준비 가이드

lecture-prism은 **API 키 없이도 기본 데모가 바로 실행**되도록 만들었습니다.
수강생에게 처음부터 키 발급을 요구하지 마세요.

## 1. 강의 기본 실습

| 범위 | 필요한 키 |
|---|---|
| `main.py` 데모 파이프라인 | 없음 |
| `screening.py` 데모 스크리닝 | 없음 |
| `analysis.py` mock 분석 | 없음 |
| `trading.py` 시뮬레이션 매매 | 없음 |
| `feedback.py`, `db.py`, `dashboard.py` | 없음 |

## 2. `.env` 프로필과 API 키

키를 준비하기 전에 먼저 [`docs/runtime-profiles.md`](runtime-profiles.md)의 프로필을 고르세요.

| 목표 | `.env` 추천값 | 필요한 키 |
|---|---|---|
| 키 없이 전체 흐름 확인 | `LECTURE_PROFILE=mock` | 없음 |
| 실제 가격·거래량만 사용 | `LECTURE_PROFILE=real_data` | 없음 (yfinance는 무료·무키) |
| 최신 뉴스·시장 리서치 보강 | `LECTURE_PROFILE=research` | ChatGPT Plus/Pro 로그인 또는 OpenAI API 키, 선택으로 Perplexity/Firecrawl |
| 증권사 모의투자 주문 경로 | `LECTURE_PROFILE=paper` | 실데이터 연결과 KIS 모의투자 키(선택 broker별 요구 사항은 다름) |
| 실전투자 | `LECTURE_PROFILE=live` | 브로커 real 키, 이중 안전 플래그 |

### 비밀값은 채팅이 아니라 설정 파일에 직접 입력합니다

코딩 에이전트에게는 `.env.example`을 `.env`로 복사하고, macOS 텍스트 편집기나 Windows 메모장 같은 운영체제의 기본 텍스트 편집기로 열어 달라고 합니다. API 키·웹후크·계좌정보는 채팅에 붙여넣지 않고 사용자가 파일에 직접 입력·저장합니다. 저장 뒤에는 값 자체를 출력하지 않는 방식으로 `준비됨 / 비어 있음 / 형식 오류`만 확인하게 하세요.

`.gitignore`는 `.env`와 실제 인증 파일이 Git에 올라가는 것을 막습니다. 하지만 에이전트의 로컬 파일 읽기까지 막는 보안 장치는 아닙니다. 프롬프트에는 항상 “비밀값을 읽어 답변·화면·도구 출력에 노출하지 말고 Git 추적 제외만 확인해 달라”고 함께 적습니다.

## 3. 실제 LLM 응답을 보고 싶을 때

둘 중 하나만 있으면 됩니다. `.env`에서 `LECTURE_LLM_MODE=auto`, `oauth`, `openai` 중 하나를 골라야 실제 호출을 시도합니다.

| 방식 | 수강생 준비물 | 설명 |
|---|---|---|
| 공식 Codex 구독 경로 | ChatGPT Plus 또는 Pro 계정, Codex CLI | 최초 `codex login` 후 공식 CLI가 토큰 저장·갱신을 맡습니다. 프로젝트는 인증 파일을 직접 읽지 않으며 종목당 통합 분석을 한 번만 호출합니다. |
| OpenAI API | `OPENAI_API_KEY` | ChatGPT 구독과 별도 과금되는 API 경로입니다. 서버형 운영이나 사용량 기반 제어가 필요할 때 선택합니다. |

초보 수강생에게는 **기본 실습을 mock으로 두고**, 구독 또는 API 키 연동은 선택 실습으로 보여주는 구성이 가장 쉽고 안전합니다. OAuth는 아래 문장을 코딩 에이전트에게 그대로 붙여넣으세요.

```text
내 컴퓨터에서 Codex CLI 설치 상태와 ChatGPT 로그인 상태를 확인해줘.
로그인이 안 되어 있으면 공식 codex login 절차를 안내하고, 브라우저를 쓸 수 없는 환경이면 device auth를 사용해줘.
로그인 뒤 lecture-prism의 .env에서 LECTURE_LLM_MODE=oauth만 켜고,
실거래 없이 종목 1개의 전문 보고서 에이전트 6개와 편집 에이전트가 개별 호출되는지 확인해줘.
각 호출의 역할 이름과 성공·섹션별 폴백만 보고하고 토큰은 읽지 마.
인증 파일과 토큰 내용은 읽거나 출력하거나 복사하지 마.
```

로그인은 보통 최초 1회만 필요하고 이후 access token 갱신은 Codex가 처리합니다. 로그아웃되거나 구독 호출이 실패하면 lecture-prism은 주문 조건을 완화하지 않고 규칙 분석으로 돌아갑니다.

## 4. 실데이터·리서치 도구

| 범위 | 필요한 것 | 기본 실습 필요 여부 |
|---|---|---|
| yfinance 가격·거래량 (분석·`screening.py --real` 공통) | `yfinance` 패키지와 인터넷 연결 | 선택 |
| KIS 가격·일별 투자자 수급 | paper 또는 real App Key와 App Secret. 계좌번호는 불필요 | Part 3 말미·Part 4 선택 실습 |
| Perplexity 리서치 | `PERPLEXITY_API_KEY` | 심화 |
| Firecrawl 웹 수집 | `FIRECRAWL_API_KEY` | 심화 |

Perplexity와 Firecrawl은 `LECTURE_REPORT_MODE=research`이고 해당 키가 있을 때만 보조 자료로 붙습니다. 키가 비어 있으면 그 도구만 건너뛰고 기본 보고서는 계속 생성됩니다.

## 5. 증권사 브로커 심화

KIS에는 서로 다른 두 범위가 있습니다. 강의에서 먼저 쓰는 것은 **읽기 전용 시장 데이터**입니다. `kis_market_data.py`가 현재가와 일별 기관·외국인·개인 순매수만 조회하며, 계좌번호 없이 선택한 환경의 아래 두 값만 사용합니다.

| 환경 | 로컬 `.env` 값 |
|---|---|
| 모의투자 `paper` | `KIS_PAPER_APP_KEY`, `KIS_PAPER_APP_SECRET` |
| 실전 `real` | `KIS_REAL_APP_KEY`, `KIS_REAL_APP_SECRET` |

강사 시연은 `real` 환경의 실제 데이터를 사용하되 주문·취소·정정·잔고·계좌 API를 호출하지 않고 매매를 simulation으로 유지합니다. 수강생은 준비한 `paper` 또는 `real` 중 하나를 명시적으로 고릅니다. 실패하면 다른 환경으로 자동 전환하거나 mock 값을 KIS 성공으로 꾸미지 않습니다.

선택한 자격 증명 묶음은 `.env`의 `LECTURE_KIS_MODE`로 고릅니다. `paper`는 `demo`, `real`은 `real`입니다. 이 값은 비밀값이 아니지만 App Key/Secret과 같은 환경을 가리켜야 합니다.

| 범위 | 필요한 것 | 기본 실습 필요 여부 |
|---|---|---|
| KIS 가격·일별 투자자 수급 조회 | 선택한 환경의 App Key, App Secret | 선택 공통 실습 |
| KIS 모의투자 조회·주문 구조 | `.env`의 `KIS_PAPER_APP_KEY`, `KIS_PAPER_APP_SECRET`, `KIS_PAPER_ACCOUNT_NO`, `KIS_PAPER_PRODUCT_CODE`, 선택 `KIS_HTS_ID` | 심화 |
| KIS 실전투자 조회·주문 구조 | `.env`의 `KIS_REAL_APP_KEY`, `KIS_REAL_APP_SECRET`, `KIS_REAL_ACCOUNT_NO`, `KIS_REAL_PRODUCT_CODE`, 선택 `KIS_HTS_ID` | 강의 기본 실습에서는 금지 |
| Kiwoom 모의투자/REST 구조 | 키움증권 REST API App Key, Secret Key 또는 Access Token | 심화 |
| Toss Securities | `tossctl 0.24.1`과 사용자가 직접 승인한 WTS 로그인 세션. API 키는 lecture-prism이 보관하지 않음 | 선택 |
| 실전투자 | 각 증권사 실전투자 키와 실제 계좌 정보 | 강의 기본 실습에서는 금지 |

`trading.py`는 실거래 요청을 기본으로 차단합니다. KIS만 고정으로 쓰지 않고 `.env`의 `LECTURE_BROKER` 값으로 브로커 어댑터를 바꿀 수 있습니다.

| 브로커 | 선택값 | 구현 상태 |
|---|---|---|
| 한국투자증권 | `LECTURE_BROKER=kis` | 매수·매도·조회·취소·재시작 reconcile을 구현하고 fixture로 검증한 KIS 어댑터 |
| 키움증권 | `LECTURE_BROKER=kiwoom` | 공식 REST API의 `/oauth2/token`, `/api/dostk/ordr`, `kt10000/kt10001` 구조 반영 |
| 토스증권 | `LECTURE_BROKER=toss` | 비공식 WTS 선택 어댑터. 매수·매도·조회·취소·재시작 reconcile, 인증 만료·UNKNOWN 차단 |
| 기타 증권사 | `LECTURE_BROKER=custom` | `LECTURE_BROKER_ADAPTER=module:Class`로 수강생 전용 어댑터 연결 |

자세한 확장 방식은 [`docs/broker-adapters.md`](broker-adapters.md)를 참고하세요.

KIS와 Toss의 수명주기는 `UNKNOWN`이면 재주문을 막는 공통 원장을 사용합니다. 이는 코드·fixture 검증 범위이며, 실제 계좌 E2E가 수행되었다는 뜻은 아닙니다.

수강생이 키움증권이나 다른 증권사 API를 준비해 왔다면, 직접 파일을 고치게 하지 말고 코딩 에이전트에게 아래처럼 말하게 하세요.

```text
lecture-prism에서 기본 KIS 브리지 옆에 내가 준비한 증권사 API 어댑터를 추가해줘.

조건:
1. trading.py의 전략 로직은 그대로 두고 brokers/ 안에 새 어댑터를 만들어줘.
2. 브로커 선택은 .env의 LECTURE_BROKER 값으로 바꾸게 해줘.
3. 실제 키·토큰·계좌번호는 .env에만 두고 절대 커밋하지 마.
4. 실전 주문은 기본 차단하고 demo/mock 또는 payload 검증부터 통과시켜줘.
5. 공식 문서에 없는 엔드포인트와 필드는 추측하지 마.
```

## 6. 보안 원칙

- 실제 키·토큰·계좌 설정이 들어간 `.env`는 절대 GitHub에 올리지 않습니다.
- 과거 실습에서 만든 KIS 인증 파일이 남아 있다면 그것도 커밋 금지입니다.
- 커밋 전에는 README의 “보안 점검 프롬프트”를 코딩 에이전트에게 입력하세요.
