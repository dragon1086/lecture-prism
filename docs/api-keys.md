# API 키 준비 가이드

lecture-prism은 **API 키 없이도 기본 데모가 즉시 실행**되도록 설계되어 있습니다.
수강생에게 처음부터 키 발급을 요구하지 마세요.

## 1. 강의 기본 실습

| 범위 | 필요한 키 |
|---|---|
| `main.py` 데모 파이프라인 | 없음 |
| `screening.py` 데모 스크리닝 | 없음 |
| `analysis.py` mock 분석 | 없음 |
| `trading.py` 시뮬레이션 매매 | 없음 |
| `feedback.py`, `db.py`, `dashboard.py` | 없음 |

## 2. 실제 LLM 응답을 보고 싶을 때

둘 중 하나만 있으면 됩니다.

| 방식 | 수강생 준비물 | 설명 |
|---|---|---|
| ChatGPT OAuth 프록시 | ChatGPT Plus 또는 Pro 계정 | 이 리포지토리의 `cores/chatgpt_proxy` 기본형 사용. OpenAI API 키는 필요 없습니다. |
| OpenAI API | `OPENAI_API_KEY` | 플랫폼 API 과금 계정이 있을 때만 사용합니다. |

초보 수강생에게는 **ChatGPT OAuth 프록시를 강사 데모 또는 선택 실습**으로 보여주는 구성이 가장 쉽습니다.

## 3. 실데이터·KIS 심화

| 범위 | 필요한 것 | 기본 실습 필요 여부 |
|---|---|---|
| `screening.py --real` 실데이터 | `pykrx` 패키지와 인터넷 연결 | 선택 |
| KIS 모의투자 조회·주문 구조 | 한국투자증권 모의투자 App Key, App Secret, HTS ID, 계좌번호 앞 8자리, 상품코드 2자리 | 심화 |
| KIS 실전투자 | 실전투자 App Key, App Secret, 실제 계좌 정보 | 강의 기본 실습에서는 금지 |

`trading.py`는 실거래 요청을 기본 차단합니다. KIS 브리지는 원본 PRISM 구조를 참고할 수 있게 들어 있지만, 초보 실습은 반드시 시뮬레이션으로 검증합니다.

## 4. PRISM 본 시스템급 확장

원본 PRISM-INSIGHT의 MCP·리서치 기능까지 확장하려면 아래 키가 선택적으로 필요할 수 있습니다.

| 키 | 용도 |
|---|---|
| `FIRECRAWL_API_KEY` | 웹 페이지 수집 |
| `PERPLEXITY_API_KEY` | 뉴스·시장 리서치 |
| `ANTHROPIC_API_KEY` | Claude 기반 에이전트 실험 |
| KRX/Kakao 로그인 정보 | KRX MCP 서버를 직접 사용할 때 |

이 키들은 lecture-prism 기본 수업에는 필요하지 않습니다.

## 5. 보안 원칙

- 실제 키·토큰·계좌 설정 파일은 절대 GitHub에 올리지 않습니다.
- `trading/trading/config/kis_devlp.yaml`은 실제 인증 파일이므로 커밋 금지입니다.
- 커밋 전에는 README의 “보안 점검 프롬프트”를 코딩 에이전트에게 입력하세요.
