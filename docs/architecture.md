# lecture-prism 아키텍처 그림 모음

이 문서는 코드를 처음 보는 수강생이 “어느 파일이 어떤 역할을 하는지” 먼저 잡을 수 있도록 만든 그림 설명입니다. README와 같은 한글 PNG 그림을 사용하므로 SVG/Mermaid 다이어그램을 읽지 않아도 흐름을 볼 수 있습니다.

## 1. 전체 학습 지도

![강의 학습 지도](assets/readme/hero-learning-map.png)

이 강의 저장소는 “내 전략을 말한다 → 코딩 에이전트가 실행·수정한다 → 데모 모드로 확인한다 → 보고서와 대시보드로 본다”는 흐름을 연습하는 공간입니다.

## 2. 처음 5분 루트

![처음 5분 루트](assets/readme/five-minute-start.png)

처음에는 설치·OAuth·Git을 한꺼번에 해결하지 않습니다. 가장 먼저 볼 것은 **API 키 없이 기본 데모가 실행되는지**입니다.

## 3. 강의용 투자 파이프라인

![강의용 투자 파이프라인 지도](assets/readme/pipeline-map.png)

| 단계 | 파일 | 쉬운 비유 | 결과 |
|---|---|---|---|
| 1 | `screening.py` | 넓은 시장에서 볼 종목을 줄이는 체 | 후보 종목 리스트 |
| 2 | `analysis.py` | 후보를 여러 관점에서 읽는 AI 분석팀 | 추천, 점수, 근거, 리스크 |
| 3 | `trading.py` | 살지 말지, 얼마나 살지 정하는 매매 규칙 | 시뮬레이션 체결 결과 |
| 4 | `feedback.py` | 매매일지를 쓰고 교훈을 뽑는 회고 담당 | 다음 판단에 쓸 교훈 |
| 5 | `dashboard.py` | 결과를 눈으로 보는 화면 | 웹 대시보드 |

LLM 연결이 없으면 더미 응답으로 동작합니다. 그래서 수업 초반에는 API 키가 없어도 전체 흐름을 먼저 볼 수 있습니다.

## 4. 옵션별 전체 아키텍처

![옵션별 전체 아키텍처 지도](assets/readme/runtime-architecture-map.png)

`.env`의 프로필 하나가 더미 데이터, 실데이터, LLM, Perplexity/Firecrawl, 브로커 모의투자, 실전투자 잠금까지 어느 깊이로 켤지 결정합니다. 키나 패키지가 없을 때 안전하게 건너뛰거나 mock으로 돌아가는 설명은 `mock` 기본 경로와 LLM·리서치 같은 **선택 분석 연동**에만 해당합니다. 아직 market provider가 연결되지 않은 paper/live 안전을 뜻하지 않습니다.

## 5. 파일별 역할 지도

![파일별 역할 지도](assets/readme/module-guide.png)

처음부터 전체 코드를 다 읽을 필요는 없습니다.

- 진입 조건을 바꾸고 싶다 → `screening.py`
- AI가 보는 관점을 바꾸고 싶다 → `analysis.py`
- 언제 팔지 바꾸고 싶다 → `trading.py`의 `_decide_exit`
- 얼마나 보수적으로 운용할지 바꾸고 싶다 → `trading.py`의 리스크 상수
- 결과를 보고 싶다 → `dashboard.py`

## 6. API 키와 선택 연동

![API 키와 선택 연동 안전 지도](assets/readme/optional-integrations-safety.png)

강의 기본 실습에는 필수 API 키가 없습니다. 실제 LLM은 내장 ChatGPT OAuth 프록시 또는 OpenAI API 키로 선택 연결하고, KIS API는 심화 실습에서만 다룹니다. `trading.py`는 실거래 요청을 기본으로 차단합니다.

## 7. 전략 하네스

![전략 하네스 흐름](assets/readme/strategy-harness-lite.png)

수강생이 전략을 두루뭉술하게 말해도, 코딩 에이전트가 진입·분석·청산·리스크 중 어디를 바꿀지 정리하고 가장 안전한 한 파일부터 수정·검증하도록 돕습니다.

## 8. 제출 전 보안 체크

![제출 전 보안 체크](assets/readme/submission-security.png)

GitHub에 올려야 하는 것은 학습 코드와 문서입니다. 실제 API 키, OAuth 토큰, KIS 설정, DB 파일, 로그 파일은 로컬에만 남겨야 합니다.

## 9. 본 시스템과의 관계

lecture-prism은 PRISM 본 시스템의 축소판입니다.

| 본 시스템에서 배우는 개념 | lecture-prism에서 보는 위치 |
|---|---|
| 많은 데이터 중 후보만 추리기 | `screening.py` |
| 여러 AI 에이전트를 순서대로 연결하기 | `analysis.py` |
| 구독 어댑터 또는 API 키로 실제 LLM 붙이기 | `cores/chatgpt_proxy/`, `analysis.py` |
| 주문 전 리스크 판단하기 | `trading.py` |
| 매매일지와 장기 기억 만들기 | `feedback.py`, `db.py` |
| 사람이 결과를 보고 다음 개선 방향 잡기 | `dashboard.py`, 실습 프롬프트 |

강의에서는 “처음부터 완벽한 자동매매”보다, 본인의 전략을 작은 코드 변경으로 반영하고 검증하는 감각을 먼저 익힙니다.

원본 시스템의 실제 실행 순서와 세부 매매 로직까지 보려면 다음 문서를 이어서 읽으세요.

- [`run_full_pipeline` 전체 아키텍처](prism-insight/run-full-pipeline-architecture.md)
- [원본 매매·시황·비중 제어 구조](prism-insight/trading-and-regime-architecture.md)
- [원본 구조 기반 강의 질문 은행](prism-insight/lecture-question-bank.md)

## 10. 지금 연결된 상태형 paper 코어

기본 `mock`은 처음 성공을 위한 기존 경로입니다. API 키 없이 `screening.py` → `analysis.py` → `trading.py` → `feedback.py`를 지나며, 기존 강의용 테이블에 분석·매매·교훈을 남깁니다. 반면 `classroom`은 같은 기본 데모의 별칭이 아니라, `prism_core/`를 실제로 호출하는 **고정 offline 상태 재생**입니다. 삼성전자(KR)와 AAPL(US)을 진입하고, 고점을 갱신한 다음, 트레일링 스탑으로 청산하는 세 사이클을 재현합니다.

| 구성요소 | 현재 구현된 역할 |
|---|---|
| `prism_core/domain.py` | 주문 상태와 시장별 계약을 정의합니다. KR은 KRW, US는 USD이며 한국 주식 수량은 정수여야 합니다. |
| `prism_core/paper_broker.py` | 주문을 `CREATED` → `PREVIEWED` → `SUBMITTED` → `ACCEPTED`로 진행합니다. `ACCEPTED`만으로는 포지션을 만들지 않고, 별도의 fill이 기록되어야 체결됩니다. |
| `prism_core/ledger.py` | SQLite에 주문 이벤트, fills, positions, realized trades, classroom replay 상태를 저장합니다. 프로세스를 재시작해도 이어지며, 청산 거래에는 주문·fill provenance를 함께 남깁니다. |
| `prism_core/cycle.py` | 포트폴리오 전체를 관찰해 **유효한 유한 quote가 있는 모든 포지션**의 high-water를 청산 write 전에 먼저 저장합니다. quote가 없거나 잘못된 포지션은 건너뛰고 주문 mutation을 만들지 않은 뒤, 청산 판단과 주문을 새 진입보다 먼저 처리합니다. 즉 **청산 우선**입니다. |
| `prism_core/classroom.py` | KR/US 진입 → 고점 갱신 → 트레일링 청산을 결정론적으로 실행하고, 중단된 세션은 SQLite 증거에 맞춰 재개합니다. |

`UNKNOWN` 주문은 성공이나 실패를 추측하지 않습니다. 해당 종목의 새 주문이나 replay 주문, fill, 청산 mutation을 막고, 명시적인 관찰 증거에 근거한 reconciliation이 끝날 때까지 fail-closed로 유지합니다. 다만 사이클 앞단의 관찰과 mutation은 구분됩니다. 유효한 quote가 있다면 UNKNOWN 주문이 있어도 포지션의 high-water 관찰은 먼저 저장될 수 있습니다. 이 규칙은 네트워크 응답을 잃어버렸을 때 같은 주문을 두 번 내는 문제를 피하기 위한 안전장치입니다.

## 11. 아직 연결 완료로 말하면 안 되는 것

아래 항목은 **모두 미완료인 후속 과제**입니다. 현재 상태형 paper 코어의 완료 범위에 포함되지 않습니다.

- 미완료 — paper/live용 market provider fail-closed: 실데이터를 못 얻었을 때 mock으로 거래 판단을 계속하지 않고 주문 경로를 닫는 연결
- 미완료 — 시장 regime과 screening 결합
- 미완료 — 분석 evidence와 OAuth 응답의 end-to-end 출처 연결
- 미완료 — KIS 주문·조회·정정·취소·체결 확인·재시작 reconcile을 포함한 full lifecycle
- 미완료 — Toss WTS 어댑터와 같은 수준의 lifecycle 검증
- 미완료 — `dashboard.py`에서 `broker_orders`, `order_events`, `fills`, `positions`, `realized_trades`, `classroom_replays`를 직접 시각화하는 화면

현재 대시보드는 기존 `trade_history`, `analysis_decisions`, `feedback_lessons`만 읽으며 **core table 시각화는 미완료**입니다. 따라서 classroom 실행 증거는 SQLite 조회로 확인해야 하며, 대시보드에 core table이 보인다고 설명하면 안 됩니다. KIS는 기존 강의용 부분 어댑터가 있고 OAuth 프록시 기본형도 있지만, 위 lifecycle·evidence 연결까지 완료됐다는 뜻은 아닙니다. Toss 역시 완료된 브로커 경로로 취급하지 않습니다.
