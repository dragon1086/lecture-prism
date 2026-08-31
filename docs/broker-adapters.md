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
| `brokers/toss.py` | Toss 공식 Open API 조회 경계와 `tossctl 0.24.1` WTS JSON 출력을 분리한 선택 어댑터입니다. |
| `brokers/tossctl.py` | shell 없이 고정 버전 CLI를 실행하고 JSON만 받는 보안 경계입니다. |
| `.env.example` | 브로커를 갈아끼우는 환경변수 예시입니다. 실제 `.env`는 커밋 금지입니다. |

`LECTURE_BROKER` 값만 바꾸면 `trading.py`는 같은 전략 로직을 유지한 채 다른 어댑터를 호출합니다.

| 값 | 의미 |
|---|---|
| `kis` | 기존 한국투자증권 브리지 사용 |
| `kiwoom` | 키움증권 REST API 어댑터 사용 |
| `toss` | 토스증권 선택 어댑터. 공식 Open API와 WTS를 구분하며 기본 상태에서는 주문하지 않음 |
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

## 3. 운영 준비 사다리

브로커를 운영 서비스에 붙일 때도 순서는 `doctor → simulation → paper → live`입니다. `operations.py doctor`는 읽기 전용 준비 상태만 확인하고, 주문·취소는 호출하지 않습니다. 상태는 `READY`, `CONDITIONAL`, `BLOCKED`로 닫히며, 하나라도 `BLOCKED`이면 service manager가 `operations.py schedule`을 오래 띄워도 브로커 실행으로 올리지 않습니다.

| 단계 | 의미 |
|---|---|
| `doctor` | `.env`, 런타임 디렉터리, 미해결 주문, 브로커 read-only capability 확인 |
| `simulation` | service template 기본값. `--execute-broker` 없이 `operations.py schedule` 실행 |
| `paper` | market provider fail-closed와 브로커 읽기 전용 준비 상태를 통과한 뒤 모의투자 API 호출 허용 |
| `live` | 실전 이중 플래그와 `LECTURE_UNATTENDED_LIVE_ACK`까지 맞춘 뒤에도 실제 주문 E2E 별도 승인 필요 |

KIS는 인증, 시장일, 계좌 접근, 보유 수량, 주문가능수량, fresh quote, 미체결 주문 조회가 읽기 전용으로 확인되어야 합니다. 키움은 공식 REST 기준 인증, 계좌, 주문가능수량, 보유/매도가능수량, 현재가, 미체결·체결 조회, 취소 capability가 있어야 합니다. 정정은 별도 명령으로 추측하지 않고 **취소 후 새 주문** 정책으로 설명합니다. KIS와 키움 모두 주문 결과가 불명확하면 `UNKNOWN`을 보존하고 재시작 reconcile 전까지 새 주문을 막습니다.

Toss는 공식 Open API와 WTS를 분리합니다. 공식 Open API는 승인된 read-only client가 주입되지 않으면 자격 증명이 있어도 `BLOCKED`입니다. Toss paper/demo backend는 없으므로 paper는 열지 않습니다. WTS는 `tossctl 0.24.1` JSON fixture와 비공식 세션 경계를 검증하지만, 세션 만료와 수동 복구 책임 때문에 읽기 전용 점검이 통과해도 live `READY`로 보지 않습니다. Toss의 실제 주문 E2E는 수행했다는 뜻이 아니며, 별도 사용자 승인 없이는 실행하지 않습니다.

```text
lecture-prism의 브로커 운영 준비 상태를 doctor → simulation → paper → live 순서로 점검해줘.
조건:
1. operations.py doctor의 KIS, 키움, Toss readiness check가 무엇을 읽기 전용으로 확인하는지 표로 보여줘.
2. READY, CONDITIONAL, BLOCKED 의미를 설명하고 BLOCKED가 있으면 service manager 템플릿을 broker 실행으로 올리지 마.
3. KIS와 키움의 UNKNOWN 주문 차단과 취소 후 새 주문 정책을 설명해줘.
4. Toss 공식 Open API와 WTS/tossctl 경계를 구분하고, Toss paper/demo backend가 없다는 점을 명시해줘.
5. 실제 주문 E2E, 주문, 취소, 계좌 API 호출은 실행하지 마.
```

## 4. 키움증권 어댑터

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

## 5. 토스증권 어댑터

토스 연동은 두 갈래를 일부러 분리합니다. **공식 Open API**는 토스증권이 공개한 REST API이고, **WTS**는 오픈소스 `tossinvest-cli`의 비공식 웹 세션 경로입니다. 둘을 같은 준비 상태로 보지 않습니다.

### 5-1. 공식 Open API 경계

공식 Open API는 `client_id`와 `client_secret`으로 OAuth2 client credentials 토큰을 받고, 계좌·보유·시세·미체결 주문 같은 계좌 API에는 계좌 식별 헤더가 추가로 필요합니다. 공개 스펙 기준으로 REST only이며, 조회 그룹별 rate limit이 있습니다. 예를 들어 계좌 조회는 매우 낮은 초당 한도를 가지므로 operations doctor는 429나 rate-limit 오류를 **준비 실패**로 닫습니다.

중요한 제한은 **모의투자/demo 환경이 문서화되어 있지 않다**는 점입니다. 그래서 Toss paper는 항상 `BLOCKED`입니다. 공식 live도 계좌·보유·시세·미체결·주문 상태 조회까지 확인되더라도, 별도로 승인된 실제 주문 E2E가 없으면 최대 `CONDITIONAL`입니다. operations doctor는 공식 경로에서 주문·취소를 호출하지 않습니다.

현재 기본 operations doctor에는 Toss 공식 REST를 실제로 읽는 client가 연결되어 있지 않습니다. 따라서 `TOSS_OPENAPI_CLIENT_ID`, `TOSS_OPENAPI_CLIENT_SECRET`, `TOSS_OPENAPI_ACCOUNT_SEQ`가 있어도 이는 설정 존재만 뜻하며, 기본 진단은 `toss_official_read_client_integration`을 `BLOCKED`로 보고합니다. 공식 read-only 점검은 승인된 client를 코드의 `toss_official_adapter_factory` seam으로 명시 주입한 경우에만 실행합니다. endpoint를 추측해 직접 HTTP 호출을 추가하거나, 자격 증명만으로 준비 상태가 통과했다고 보면 안 됩니다.

### 5-1a. Part 4의 Toss 실제 시세 선택 실습

P4-TOSS는 주문 어댑터나 operations doctor를 여는 실습이 아닙니다. 최신 `tossctl 0.43.1` 이상의 `quote get` 결과를 `TossctlQuoteAdapter`가 공통 `BrokerQuote`로 바꾸는 읽기 전용 실습입니다. 토스 계좌와 공식 Open API 키가 없는 수강생은 설치·로그인 성공을 요구받지 않고, 미리 준비한 연습 응답으로 구조만 확인합니다.

준비된 수강생은 토스증권 WTS에서 직접 Open API 키를 만들고 허용 IP를 등록합니다. tossctl 로그인은 키와 비밀값을 명령에 직접 넣는 방식이므로, 에이전트 채팅에는 전달하지 않고 본인 터미널에서 직접 처리합니다. 키와 계좌 정보는 tossctl의 사용자 로컬 설정에만 두며, lecture-prism의 `.env`, 로그, DB에는 저장하지 않습니다. 이후 `openapi status`와 삼성전자 005930 현재가 한 건만 확인합니다. 주문·취소·정정·잔고·계좌 API는 호출하지 않습니다.

수강생은 별도 진단 프롬프트를 만들지 않습니다. 강의 자료의 `P4-TOSS-SETUP`을 먼저, 준비됨일 때만 `P4-TOSS-RUN`을 그대로 붙여넣습니다. 계좌와 키가 없다면 `TossctlQuoteAdapter` 테스트로 연습 결과를 확인하고 끝냅니다.

### 5-2. WTS / tossctl 경계

WTS 경로는 공식 공개 주문 API가 아니라 오픈소스 `tossinvest-cli`의 **비공식 WTS 세션**을 사용합니다. WTS 내부 endpoint와 cookie를 lecture-prism이 직접 다루지 않고, 검증한 `tossctl 0.24.1`의 JSON 출력만 읽습니다.

구현 범위는 국내 지정가 매수·매도, 주문 가능·보유 수량 제한, 주문 조회, 부분·전체 체결, 취소, 재시작 reconcile입니다. 세션 만료나 주문 결과 불명확 상태는 `UNKNOWN`으로 보존해 재주문을 막습니다. WTS-only live는 읽기 전용 점검이 통과해도 `READY`가 아닙니다. 이유는 비공식 세션이 만료될 수 있고, QR 로그인·휴대폰 세션 연장 같은 수동 복구 책임이 사용자에게 남기 때문입니다.

Toss WTS에도 모의투자 backend가 없습니다. 실제 주문에는 공용 이중 플래그와 tossctl 자체 거래 설정이 모두 필요하며, 자동 환전 동의와 주문 정정은 지원하지 않습니다.

수강생은 코딩 에이전트에게 아래처럼 진단을 맡깁니다.

```text
lecture-prism의 Toss WTS 선택 연동을 읽기 전용으로 점검해줘.

조건:
1. tossctl 버전, 실행 파일, 인증 만료 여부만 확인하고 세션 파일 내용은 읽거나 출력하지 마.
2. 매수·매도 → 접수 → 부분/전체 체결 → 취소 → 재시작 reconcile 테스트를 확인해줘.
3. 실제 계좌 주문은 실행하지 마.
4. WTS가 비공식 연동이고 영구 무인 로그인을 보장하지 않는다고 알려줘.
5. 세션 만료, malformed JSON, UNKNOWN 주문 상태는 전부 실패로 닫히는지 확인해줘.
6. 설정이 부족하면 주문을 열지 말고 필요한 사용자 승인만 설명해줘.
```

## 6. 완전히 다른 증권사 붙이기

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

## 7. 공식 참고 링크

- 키움 REST API 가이드: <https://openapi.kiwoom.com/guide/apiguide>
- 키움 REST API 테스트 샘플: <https://openapi.kiwoom.com/guide/guideTestSample>
- 토스증권 공식 Open API 문서: <https://developers.tossinvest.com/docs>
- 토스증권 공식 OpenAPI 스펙: <https://openapi.tossinvest.com/openapi-docs/latest/openapi.json>
- tossinvest-cli 참고 구현: <https://github.com/JungHoonGhae/tossinvest-cli>
