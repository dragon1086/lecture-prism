# Toss WTS 선택 브로커 대칭 구현 설계

> 작성일: 2026-07-20
>
> 대상 저장소: `lecture-prism`
>
> 참고 구현: `tossinvest-cli` main `2c62e7a`
>
> 상태: 사용자 승인 완료

## 1. 결정 요약

Toss를 단순 미리보기 템플릿으로 남기지 않고, 현재 KIS 브로커 경로와 같은 주문 수명주기를 제공하는 선택 어댑터로 구현한다.

- 국내 주식 지정가 매수·매도
- 주문 가능 수량·보유 수량 확인
- 주문 preview와 제출
- 주문 식별자 저장
- 미체결·체결·부분 체결 조회
- 미체결 주문 취소
- 재시작 뒤 reconcile
- 인증 만료·timeout·불명확한 응답의 fail-closed 처리

직접 WTS HTTP endpoint나 쿠키 형식을 복제하지 않는다. 고정된 `tossctl` 실행 파일의 JSON CLI 계약만 사용하며, backend는 `wts`로 고정한다. 기본 mock 파이프라인과 KIS 기본 강의 경로는 바꾸지 않는다.

## 2. 목표와 비목표

### 목표

1. `LECTURE_BROKER=toss`를 선택했을 때 KIS와 대칭인 BUY/SELL·조회·취소·reconcile 계약을 제공한다.
2. Toss 인증 상태가 불확실하면 주문 subprocess를 시작하기 전에 차단한다.
3. 주문 요청 경계를 지난 뒤 결과가 불확실하면 `UNKNOWN`으로 보존하고 자동 재주문을 금지한다.
4. 모든 subprocess 호출을 argument list, `shell=False`, timeout, JSON parsing으로 제한한다.
5. 실제 Toss 세션이나 자격정보 없이 fixture와 가짜 실행기로 전체 수명주기를 검증한다.
6. API 키 없는 `python3 main.py` 데모와 기존 KIS 회귀를 그대로 유지한다.

### 비목표

- WTS 내부 HTTP API 직접 구현
- Toss 로그인·세션 파일을 lecture-prism이 직접 읽거나 수정
- 주문 정정(amend), 소수점 주문, 시장가 주문
- 자동 환전 동의 또는 투자 위험 동의 자동 처리
- 영구 무인 인증 약속
- 실제 계좌 주문 E2E 자동 실행
- Toss를 강의 기본 브로커로 변경

## 3. KIS와의 기능 대칭

| 수명주기 | KIS | Toss WTS 설계 |
|---|---|---|
| 전역 호출 게이트 | `LECTURE_ENABLE_LIVE_BROKER` | 동일 |
| 실계좌 추가 게이트 | `LECTURE_ALLOW_REAL_BROKER` | 동일 |
| 계좌/수량 제한 | 주문 가능 수량·보유 수량 | `tossctl` 잔고·보유 조회 결과로 상한 적용 |
| BUY/SELL | 국내 지정가 | 국내 지정가 |
| preview | 로컬 원장 상태 | `tossctl order preview` canonical/token 저장 |
| submit | KIS 주문 API | 같은 intent로 `order place --execute --confirm` |
| 주문 식별자 | 주문일·조직번호·주문번호 | 주문일·`order_id`; 조직번호는 고정 `toss` sentinel 사용 |
| 상태 조회 | 주문 조회 | `order show`, `orders list`, `orders completed` |
| 부분 체결 | 수량 기반 reconcile | 동일 |
| 취소 | 미체결 조회 뒤 취소 | 미체결 확인 뒤 preview/token을 거쳐 취소 |
| 재시작 복구 | pending ledger 조회 | 동일한 공용 ledger 사용 |
| 불확실한 제출 | `UNKNOWN`, 재주문 금지 | 동일 |

대칭은 결과 계약과 안전 상태 머신을 뜻한다. 인증 방식과 외부 명령 형식까지 KIS처럼 흉내 내지는 않는다.

## 4. 구성 요소

### 4.1 `brokers/toss.py`

`TossBrokerAdapter`가 다음 public async 메서드를 제공한다.

- `check_auth()`
- `get_account()`
- `get_orderable_quantity(ticker, price)`
- `place_order(order)`
- `get_order_status(order_id, *, market="kr")`
- `get_pending_orders()`
- `get_completed_orders(*, market="kr")`
- `cancel_order(order_id, ticker)`

어댑터는 subprocess 실행, JSON 검증, Toss 상태를 lecture-prism의 공통 결과 dict로 정규화하는 일만 담당한다. DB를 직접 수정하지 않는다.

### 4.2 `brokers/tossctl.py`

subprocess 경계를 별도 모듈로 둔다.

- 실행 파일 탐색: 명시적 `TOSSCTL_PATH` 우선, 그 다음 `tossctl`/Windows `tossctl.exe`
- 호환 버전 고정: `0.24.1`; 불일치 시 fail-closed
- 공통 인수: `--backend wts --output json`
- `asyncio.to_thread` 또는 동등한 비동기 경계에서 `subprocess.run`
- `shell=False`, 문자열 command 금지
- 최소 환경 전달과 timeout
- stdout JSON만 파싱하고 stderr는 비밀값을 제거한 진단 메시지로만 사용
- exit code, timeout, invalid JSON, schema mismatch를 서로 다른 예외로 분류

세션 파일 경로나 cookie/token 값은 lecture-prism 결과·로그·DB에 저장하지 않는다.

### 4.3 `trading.py`

KIS 전용으로 묶인 원장 admission/reconcile 흐름을 공용 브로커 흐름으로 일반화한다.

- 공용 `OrderIntent` 생성
- `broker`, `broker_mode`별 unresolved 주문 admission
- 제출 전 `PREVIEWED`, 제출 직전 `SUBMITTED`
- broker identity 저장
- 조회 snapshot을 `ACCEPTED`, `PARTIALLY_FILLED`, `FILLED`, `CANCELED`, `REJECTED`, `UNKNOWN`으로 매핑
- `reconcile_pending_broker_orders(broker=...)` 공용 진입점
- 기존 `reconcile_pending_kis_orders`는 호환 wrapper로 유지

KIS 수량 제한 로직과 Toss 수량 제한 로직은 어댑터 capability로 호출하되, 계좌 조회 실패가 노출을 늘리지 않도록 둘 다 주문을 차단한다.

### 4.4 공용 ledger

현재 `prism_core.ledger`의 broker/mode/identity/pending 계약을 재사용한다. 스키마 변경은 원칙적으로 하지 않는다.

Toss identity mapping:

- `broker_order_date`: Toss 응답 `order_date`
- `broker_org_no`: `"toss"`
- `broker_order_no`: Toss `order_id`

이 조합은 기존 unique identity 제약을 만족하며 Toss session·계정 비밀을 저장하지 않는다.

## 5. 고정 CLI 계약

모든 명령은 실행 파일 뒤에 `--backend wts --output json`을 붙인다. 아래 표기는 읽기 편하게 축약한 것이며 실제 구현은 argument list다.

| 기능 | 명령 계약 |
|---|---|
| 인증 | `tossctl --backend wts --output json auth status` |
| 계좌 요약 | `... account summary` |
| 보유 종목 | `... portfolio positions` |
| 매도 가능 수량 | `... quote sellable 005930` |
| preview | `... order preview --symbol 005930 --market kr --side buy --type limit --qty 1 --price 70000 --currency-mode KRW` |
| 제출 | `... order place <동일 intent> --execute --confirm TOKEN` |
| 단건 조회 | `... order show ORDER_ID --market kr` |
| 미체결 | `... orders list` |
| 체결 | `... orders completed --market kr` |
| 취소 preview | `... order cancel --order-id ORDER_ID --symbol 005930` |
| 취소 제출 | `... order cancel <동일 intent> --execute --confirm TOKEN` |

preview와 mutation 사이에는 다음 불변식을 검사한다.

1. preview `kind`가 예상 mutation과 일치한다.
2. `canonical`과 `confirm_token`이 비어 있지 않다.
3. `live_ready`와 `mutation_ready`가 모두 참이다.
4. mutation은 preview에 사용한 것과 byte-for-byte 동일한 정규화 intent 인수를 사용한다.
5. preview token은 해당 호출 한 번에만 메모리에서 사용하고 저장소나 로그에 노출하지 않는다.

## 6. 인증과 수동 조치

매 adapter 호출과 주문 직전에 `auth status`를 검증한다.

주문 가능 조건:

- `active=true`
- `expired=false`
- `validated=true`
- `valid=true`
- `server_expires_at`이 현재보다 뒤

조건을 만족하지 않거나 status 자체를 확인할 수 없으면 subprocess mutation을 호출하지 않는다.

- 세션 없음·만료·휴대폰 연장 필요: `manual_action_required`
- 실행 파일 없음·버전 불일치: `configuration_error`
- 일시적 인증 검증 실패: `auth_unknown`

문서에는 터미널 명령 대신 “코딩 에이전트에게 Toss 로그인/연장을 도와달라”는 프롬프트를 제공한다. QR·휴대폰 승인은 사용자가 직접 완료해야 한다.

## 7. 주문 상태와 오류 정책

### 제출 전 실패

실행 파일 없음, 인증 차단, preview 불가, `mutation_ready=false`, 입력 오류는 브로커 경계를 넘지 않았으므로 terminal `blocked` 또는 `rejected`다.

### 제출 경계 이후 실패

`order place --execute`가 시작된 뒤 발생한 timeout, 비정상 종료, invalid JSON, 식별자 없는 성공 응답은 주문 접수 여부를 단정할 수 없다.

- ledger를 `UNKNOWN`으로 기록
- 결과는 `terminal=false`, `accepted=false`, `executed=false`
- 같은 broker/mode/market/symbol/side의 새 주문 admission 차단
- 자동으로 `order place`를 다시 호출하지 않음
- 이후 `order show`·미체결·체결 조회만 수행

공식 경로로 fallback하지 않고 `--backend wts`를 고정하므로, 한 intent가 다른 backend에 중복 제출될 여지도 제거한다.

### 상태 매핑

| Toss 상태/수량 | 공용 상태 |
|---|---|
| 접수, 체결 0, 잔량 전체 | `ACCEPTED` |
| 0 < 체결 < 주문량 | `PARTIALLY_FILLED` |
| 체결량 = 주문량, 잔량 0 | `FILLED` |
| 취소, 잔량 > 0 | `CANCELED` |
| 명시적 거절 | `REJECTED` |
| 충돌·누락·판단 불가 | `UNKNOWN` |

텍스트 status보다 수량 불변식(`filled + remaining = requested`)을 우선하며, 모순이면 `UNKNOWN`이다.

## 8. 수량 제한

- BUY: `account summary`의 `orderable_amount_krw`를 지정가로 나눈 내림값과 전략 요청 수량 중 작은 값. 수수료·기타 제약으로 실제 가능 수량이 더 작으면 Toss가 명시적으로 거절할 수 있지만 요청 노출은 계산값보다 커지지 않는다.
- SELL: `quote sellable TICKER`의 `sellable_quantity`, `portfolio positions`의 보유 수량, 전략 요청 수량 중 가장 작은 값
- 계좌/보유 조회 실패: 0으로 추정하지 않고 `account_unavailable`로 차단
- 음수·NaN·정수가 아닌 국내 주식 수량: 입력 오류
- 자동 환전 또는 부족 자금 동의 요구: `manual_action_required`

계좌 출력의 원문 `raw`는 로그나 거래 결과에 복사하지 않는다.

## 9. 취소와 재시작 reconcile

취소는 로컬 ledger만 보고 실행하지 않는다.

1. `order show` 또는 미체결 목록에서 현재 주문과 남은 수량 확인
2. 이미 terminal이면 취소 subprocess를 호출하지 않고 현재 상태 반환
3. 취소 preview 생성·검증
4. 같은 token으로 취소 mutation 한 번 호출
5. 결과가 불확실하면 `UNKNOWN`
6. 미체결·체결 조회로 최종 상태 reconcile

재시작 시에는 공용 ledger의 Toss unresolved 주문만 읽는다. 조회 외 mutation은 절대 수행하지 않는다. 주문 식별자가 없으면 미체결·체결 목록에서 symbol/side/quantity/price/order date로 보수적으로 복구하되 후보가 정확히 하나일 때만 bind한다. 0개 또는 여러 개면 `UNKNOWN`을 유지한다.

## 10. 설정

기존의 문서 근거 없는 HTTP 설정은 제거한다.

```text
TOSS_SECURITIES_MODE=real
TOSSCTL_PATH=""
TOSSCTL_TIMEOUT_SECONDS=15
```

호환 버전은 코드 상수 `0.24.1`로 고정한다. 다른 버전을 조용히 허용하는 환경변수는 두지 않는다. 버전을 올릴 때에는 JSON fixture와 전체 수명주기 회귀를 먼저 갱신한다.

Toss WTS는 실제 계좌 세션이므로 `demo`를 실재하는 모의투자 backend처럼 표현하지 않는다. 호환을 위해 `TOSS_SECURITIES_MODE`는 읽되, 주문 가능한 값은 `real`뿐이다. 다른 값에서는 preview/read-only 진단까지만 허용하고 mutation은 차단한다.

실주문에는 lecture-prism의 두 전역 플래그와 tossctl 자체 config의 `trading.place`, `trading.sell`, `trading.cancel`, `trading.allow_live_order_actions`가 모두 필요하다.

## 11. 테스트 전략

### 단위 테스트

- 실행 파일 탐색과 버전 불일치
- argument list 정확성, `shell=False`, timeout
- 최소 환경과 stderr redaction
- 인증 상태 전체 조합
- BUY/SELL preview·place 인수 대칭
- canonical/token/mutation-ready 검증
- pending/completed/show JSON 정규화
- 부분 체결·완전 체결·취소·거절 매핑
- invalid JSON·timeout·식별자 누락 → `UNKNOWN`
- 계좌 조회 실패와 보유/주문 가능 수량 상한
- `account summary`·`portfolio positions`·`quote sellable` JSON 계약

### 통합 테스트

가짜 `tossctl` executable fixture로 다음을 검증한다.

1. 인증 정상 → preview → BUY 제출 → accepted → partial → filled
2. 인증 정상 → SELL 수량 상한 → 제출 → filled
3. accepted → cancel preview → cancel → canceled
4. 제출 timeout → restart → 조회로 recovered
5. 제출 timeout → 조회 후보 충돌 → `UNKNOWN` 유지와 재주문 차단
6. 세션 만료 → `manual_action_required`, mutation 미호출

### 전체 회귀

- 전체 unittest
- 임시 DB를 사용한 `python3 main.py` mock 완주
- `python3 trading.py --live` 기본 `live_blocked`
- compileall
- `git diff --check`
- 비밀값·세션 파일·로컬 절대 경로 scan

실제 Toss 계좌 mutation은 자동 검증 항목이 아니다. 사용자의 별도 자격정보와 명시적 실행 승인 없이는 수행하지 않는다.

## 12. 문서 변경

- `.env.example`: tossctl 실행 파일·버전·timeout 빈 설정
- `docs/broker-adapters.md`: 비공식 WTS 위험, 선택 기능, 에이전트용 로그인·진단 프롬프트
- `docs/api-keys.md`: API 키 대신 tossctl 소유 세션을 사용한다고 수정
- `docs/runtime-profiles.md`, `docs/architecture.md`, 강의 가이드: 구현 완료 범위를 실제 테스트 증거에 맞춰 갱신

문서에는 직접 실행하는 터미널 명령 블록을 추가하지 않는다.

## 13. 완료 조건

- Toss BUY/SELL·조회·부분 체결·취소·재시작 reconcile 테스트가 통과한다.
- 인증 만료와 제출 후 불확실성이 fail-closed한다.
- 미결·`UNKNOWN` 주문이 중복 제출을 차단한다.
- 실제 세션·cookie·token·계정 데이터가 코드, 로그, DB, Git에 들어가지 않는다.
- KIS 기능과 기존 테스트가 퇴행하지 않는다.
- API 키 없는 기본 데모가 완주한다.
- 문서가 Toss를 공식 API나 완전 무인 서비스로 오해하게 만들지 않는다.
