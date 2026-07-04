# 증권사 브로커 어댑터 확장 가이드

lecture-prism의 기본 성공 기준은 여전히 **API 키 없이 데모 모드에서 전략이 검증되는 것**입니다. 다만 수강생이 한국투자증권(KIS)이 아니라 키움증권, 토스증권, 다른 증권사 API를 준비해 오는 경우가 있어 브로커를 바꿔 끼울 수 있는 얇은 어댑터 구조를 제공합니다.

## 1. 전체 구조

| 위치 | 역할 |
|---|---|
| `trading.py` | 전략이 만든 공통 주문 정보를 선택한 브로커로 넘깁니다. |
| `brokers/base.py` | 모든 브로커가 맞춰야 하는 최소 인터페이스입니다. |
| `brokers/kis.py` | 기존 한국투자증권 브리지를 감싸는 어댑터입니다. |
| `brokers/kiwoom.py` | 키움증권 REST API용 교육용 어댑터입니다. |
| `brokers/toss.py` | 토스증권 파트너/비공개 문서가 있을 때 채워 넣는 안전 템플릿입니다. |
| `.env.example` | 브로커를 갈아끼우는 환경변수 예시입니다. 실제 `.env`는 커밋 금지입니다. |

`LECTURE_BROKER` 값만 바꾸면 `trading.py`는 같은 전략 로직을 유지한 채 다른 어댑터를 호출합니다.

| 값 | 의미 |
|---|---|
| `kis` | 기존 한국투자증권 브리지 사용 |
| `kiwoom` | 키움증권 REST API 어댑터 사용 |
| `toss` | 토스증권 안전 템플릿 사용. 기본 상태에서는 주문하지 않음 |
| `custom` | 수강생이 만든 `module:Class` 어댑터 사용 |

## 2. 안전장치

브로커를 선택해도 기본값은 주문 차단입니다.

| 환경변수 | 의미 |
|---|---|
| `LECTURE_ENABLE_LIVE_BROKER=1` | 모의/더미 브로커 API 호출을 허용합니다. |
| `LECTURE_ALLOW_REAL_BROKER=1` | 실전투자 모드를 추가로 허용합니다. |
| `LECTURE_ENABLE_LIVE_KIS=1` | 기존 KIS 전용 호환 플래그입니다. |
| `LECTURE_ALLOW_REAL_KIS=1` | 기존 KIS real 모드 호환 플래그입니다. |

수업 중에는 `LECTURE_ALLOW_REAL_BROKER=1`을 쓰지 않는 것이 원칙입니다.

## 3. 키움증권 어댑터

공식 키움 REST API 가이드에서 확인한 핵심은 다음과 같습니다.

| 항목 | 공식 문서 기준 |
|---|---|
| 운영 도메인 | `https://api.kiwoom.com` |
| 모의투자 도메인 | `https://mockapi.kiwoom.com` |
| 접근토큰 발급 | `POST /oauth2/token`, API ID `au10001` |
| 주문 | `POST /api/dostk/ordr` |
| 매수 API ID | `kt10000` |
| 매도 API ID | `kt10001` |
| 주요 주문 필드 | `dmst_stex_tp`, `stk_cd`, `ord_qty`, `ord_uv`, `trde_tp`, `cond_uv` |

수강생이 키움증권 API를 가져온 경우 코딩 에이전트에게 이렇게 말하면 됩니다.

```text
lecture-prism에서 KIS 대신 키움증권 어댑터를 쓰게 설정해줘.

조건:
1. 실제 키는 내가 로컬 .env에 직접 넣을 것이므로 너는 키 값을 만들거나 커밋하지 마.
2. .env.example을 참고해서 LECTURE_BROKER=kiwoom, KIWOOM_MODE=demo 구조로 안내해줘.
3. 먼저 LECTURE_ENABLE_LIVE_BROKER=0 상태에서 --live가 차단되는지 확인해줘.
4. 실제 주문 호출은 강사 허가 전까지 절대 하지 마.
5. 키움 공식 문서의 /oauth2/token, /api/dostk/ordr, kt10000/kt10001 필드와 코드가 맞는지 점검해줘.
```

## 4. 토스증권 어댑터

2026년 6월 28일 기준으로 확인 가능한 토스 공식 개발자 문서는 토스페이먼츠 결제 API 중심입니다. 토스증권의 공개 개인용 주문 API 문서는 확인하지 못했습니다. 그래서 `brokers/toss.py`는 **주문을 보내지 않는 안전 템플릿**입니다.

수강생이 토스증권 파트너/비공개 API 문서를 가져온 경우에는 아래 프롬프트로 확장합니다.

```text
lecture-prism의 brokers/toss.py를 내가 제공하는 토스증권 API 문서에 맞게 채워줘.

조건:
1. 공개 문서에 없는 엔드포인트를 추측하지 마.
2. 토큰 발급, 계좌 조회, 주문 요청, 응답 필드를 문서 근거로만 구현해줘.
3. 실제 키는 .env에만 두고 커밋하지 마.
4. 기본값은 demo/mock 또는 주문 차단이어야 해.
5. 먼저 테스트에서 요청 payload만 검증하고, 실제 주문 API 호출은 하지 마.
```

## 5. 완전히 다른 증권사 붙이기

새 브로커는 `BrokerOrder`를 받아 `dict` 결과를 돌려주면 됩니다.

```python
class MyBrokerAdapter:
    name = "mybroker"
    mode = "demo"

    async def place_order(self, order):
        return {
            "success": False,
            "mode": "mybroker_demo_stub",
            "order_no": None,
            "message": "아직 실제 주문을 보내지 않는 스텁입니다.",
        }
```

수강생에게는 직접 파일을 만들라고 하지 말고 코딩 에이전트에게 이렇게 맡기게 하세요.

```text
lecture-prism에 내가 가져온 증권사 API 문서를 기반으로 새 브로커 어댑터를 추가해줘.

조건:
1. brokers/base.py의 BrokerOrder 인터페이스를 유지해줘.
2. 새 파일은 brokers/ 안에 만들고, LECTURE_BROKER=custom 또는 새 브로커 이름으로 선택 가능하게 해줘.
3. 실제 키는 .env에만 두고, .env.example에는 빈 예시만 추가해줘.
4. 실전 주문은 기본 차단하고, demo/mock 호출 또는 payload 검증 테스트부터 통과시켜줘.
5. README와 docs/api-keys.md에 수강생용 프롬프트 방식으로 사용법을 추가해줘.
```

## 6. 공식 참고 링크

- 키움 REST API 가이드: <https://openapi.kiwoom.com/guide/apiguide>
- 키움 REST API 테스트 샘플: <https://openapi.kiwoom.com/guide/guideTestSample>
- 토스증권 공식 사이트: <https://www.tossinvest.com/>
- 토스페이먼츠 개발자센터 API 참고: <https://docs.tosspayments.com/reference>
