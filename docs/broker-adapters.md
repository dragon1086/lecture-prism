# 증권사 브로커 어댑터 확장 가이드

lecture-prism의 기본 성공 기준은 여전히 **API 키 없이 데모 모드에서 전략이 검증되는 것**입니다. 다만 수강생이 한국투자증권(KIS)이 아니라 키움증권, 토스증권, 다른 증권사 API를 준비해 오는 경우가 있어 브로커를 바꿔 끼울 수 있는 얇은 어댑터 구조를 제공합니다.

KIS와 Toss의 현재 구현 범위는 매수·매도·조회·취소·재시작 reconcile입니다. 주문 결과가 불확실하면 `UNKNOWN`으로 보존하고 재주문을 막습니다. 이 수명주기는 고정 fixture와 가짜 실행기로 검증하며, 실제 계좌 E2E를 수행했다는 뜻은 아닙니다.

## 1. 전체 구조

| 위치 | 역할 |
|---|---|
| `trading.py` | 전략이 만든 공통 주문 정보를 선택한 브로커로 넘깁니다. |
| `brokers/base.py` | 모든 브로커가 맞춰야 하는 최소 인터페이스입니다. |
| `brokers/kis.py` | 기존 한국투자증권 브리지를 감싸는 어댑터입니다. |
| `brokers/kiwoom.py` | 키움증권 REST API용 교육용 어댑터입니다. |
| `brokers/toss.py` | `tossctl 0.24.1`의 WTS JSON 출력을 변환하는 선택 어댑터입니다. |
| `brokers/tossctl.py` | shell 없이 고정 버전 CLI를 실행하고 JSON만 받는 보안 경계입니다. |
| `.env.example` | 브로커를 갈아끼우는 환경변수 예시입니다. 실제 `.env`는 커밋 금지입니다. |

`LECTURE_BROKER` 값만 바꾸면 `trading.py`는 같은 전략 로직을 유지한 채 다른 어댑터를 호출합니다.

| 값 | 의미 |
|---|---|
| `kis` | 기존 한국투자증권 브리지 사용 |
| `kiwoom` | 키움증권 REST API 어댑터 사용 |
| `toss` | 토스증권 WTS 선택 어댑터. 기본 상태에서는 주문하지 않음 |
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

토스 연동은 공식 공개 주문 API가 아니라 오픈소스 `tossinvest-cli`의 **비공식 WTS 세션**을 사용합니다. WTS 내부 endpoint와 cookie를 lecture-prism이 직접 다루지 않고, 검증한 `tossctl 0.24.1`의 JSON 출력만 읽습니다.

구현 범위는 국내 지정가 매수·매도, 주문 가능·보유 수량 제한, 주문 조회, 부분·전체 체결, 취소, 재시작 reconcile입니다. 세션 만료나 주문 결과 불명확 상태는 `UNKNOWN`으로 보존해 재주문을 막습니다.

Toss WTS에는 모의투자 backend가 없습니다. 실제 주문에는 공용 이중 플래그와 tossctl 자체 거래 설정이 모두 필요하며, QR 로그인·휴대폰 세션 연장은 사용자가 직접 승인해야 합니다. 자동 환전 동의와 주문 정정은 지원하지 않습니다.

수강생은 코딩 에이전트에게 아래처럼 진단을 맡깁니다.

```text
lecture-prism의 Toss WTS 선택 연동을 읽기 전용으로 점검해줘.

조건:
1. tossctl 버전, 실행 파일, 인증 만료 여부만 확인하고 세션 파일 내용은 읽거나 출력하지 마.
2. 매수·매도 → 접수 → 부분/전체 체결 → 취소 → 재시작 reconcile 테스트를 확인해줘.
3. 실제 계좌 주문은 실행하지 마.
4. WTS가 비공식 연동이고 영구 무인 로그인을 보장하지 않는다고 알려줘.
5. 설정이 부족하면 주문을 열지 말고 필요한 사용자 승인만 설명해줘.
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
- tossinvest-cli 참고 구현: <https://github.com/JungHoonGhae/tossinvest-cli>
