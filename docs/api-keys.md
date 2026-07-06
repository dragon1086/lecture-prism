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
| 최신 뉴스·시장 리서치 보강 | `LECTURE_PROFILE=research` | OpenAI API 키 또는 강의용 구독 어댑터, 선택으로 Perplexity/Firecrawl |
| 증권사 모의투자 주문 경로 | `LECTURE_PROFILE=paper` | 브로커 demo 키, KIS라면 `kis_devlp.yaml` |
| 실전투자 | `LECTURE_PROFILE=live` | 브로커 real 키, 이중 안전 플래그 |

## 3. 실제 LLM 응답을 보고 싶을 때

둘 중 하나만 있으면 됩니다. `.env`에서 `LECTURE_LLM_MODE=auto`, `oauth`, `openai` 중 하나를 골라야 실제 호출을 시도합니다.

| 방식 | 수강생 준비물 | 설명 |
|---|---|---|
| 강의용 ChatGPT 어댑터 | ChatGPT Plus 또는 Pro 계정 | 이 리포지토리의 `cores/chatgpt_proxy` 기본형. 구독 계정을 로그인해 붙이는 강의·실습 편의용 경로입니다. |
| OpenAI API (정식·권장) | `OPENAI_API_KEY` | 정식으로 지원되는 안정적 경로. 실제 서비스 운영에는 이 방식을 권장합니다. |

초보 수강생에게는 **기본 실습을 mock으로 두고**, 구독 어댑터나 API 키 연동은 **강사 데모 또는 선택 실습**으로 보여주는 구성이 가장 쉽고 안전합니다.

## 4. 실데이터·리서치 도구

| 범위 | 필요한 것 | 기본 실습 필요 여부 |
|---|---|---|
| yfinance 가격·거래량 (분석·`screening.py --real` 공통) | `yfinance` 패키지와 인터넷 연결 | 선택 |
| Perplexity 리서치 | `PERPLEXITY_API_KEY` | 심화 |
| Firecrawl 웹 수집 | `FIRECRAWL_API_KEY` | 심화 |

Perplexity와 Firecrawl은 `LECTURE_REPORT_MODE=research`이고 해당 키가 있을 때만 보조 자료로 붙습니다. 키가 비어 있으면 그 도구만 건너뛰고 기본 보고서는 계속 생성됩니다.

## 5. 증권사 브로커 심화

| 범위 | 필요한 것 | 기본 실습 필요 여부 |
|---|---|---|
| KIS 모의투자 조회·주문 구조 | 한국투자증권 모의투자 App Key, App Secret, HTS ID, 계좌번호 앞 8자리, 상품코드 2자리 | 심화 |
| Kiwoom 모의투자/REST 구조 | 키움증권 REST API App Key, Secret Key 또는 Access Token | 심화 |
| Toss Securities | 2026년 6월 28일 기준 공개 공식 주문 API 문서 확인 불가. 파트너/비공개 문서가 있을 때만 템플릿 확장 | 선택 |
| 실전투자 | 각 증권사 실전투자 키와 실제 계좌 정보 | 강의 기본 실습에서는 금지 |

`trading.py`는 실거래 요청을 기본으로 차단합니다. KIS만 고정으로 쓰지 않고 `.env`의 `LECTURE_BROKER` 값으로 브로커 어댑터를 바꿀 수 있습니다.

| 브로커 | 선택값 | 구현 상태 |
|---|---|---|
| 한국투자증권 | `LECTURE_BROKER=kis` | 기존 PRISM KIS 브리지 wrapping |
| 키움증권 | `LECTURE_BROKER=kiwoom` | 공식 REST API의 `/oauth2/token`, `/api/dostk/ordr`, `kt10000/kt10001` 구조 반영 |
| 토스증권 | `LECTURE_BROKER=toss` | 공개 주문 API 미확인으로 기본 차단 템플릿 제공 |
| 기타 증권사 | `LECTURE_BROKER=custom` | `LECTURE_BROKER_ADAPTER=module:Class`로 수강생 전용 어댑터 연결 |

자세한 확장 방식은 [`docs/broker-adapters.md`](broker-adapters.md)를 참고하세요.

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

- 실제 키·토큰·계좌 설정 파일은 절대 GitHub에 올리지 않습니다.
- `trading/trading/config/kis_devlp.yaml`은 실제 인증 파일이므로 커밋 금지입니다.
- 커밋 전에는 README의 “보안 점검 프롬프트”를 코딩 에이전트에게 입력하세요.
