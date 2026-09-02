# 선택형 보고 채널 설계

## 목표

`lecture-prism`의 판단 알림을 기본 Discord에서 선택형 보고 채널로 확장한다. 수강생은 `.env`에서 `discord`, `telegram`, `both`, `off` 중 하나를 고를 수 있어야 하며, Telegram을 준비한 사람은 원본 `prism-insight`와 같은 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID`를 사용한다.

기본 mock·simulation 경로는 API 키나 알림 설정 없이 계속 완주해야 한다. 알림 전송 실패는 스크리닝, 분석, 매매 판단, 피드백, DB 저장 결과를 바꾸지 않는다.

## 설정 계약

새 설정은 다음 네 값을 허용한다.

```dotenv
LECTURE_REPORT_CHANNEL=discord
```

- `discord`: Discord만 사용한다.
- `telegram`: Telegram만 사용한다.
- `both`: 준비된 Discord와 Telegram에 함께 보낸다.
- `off`: 모든 외부 알림을 끈다.

새 `.env.example`의 기본 선택은 `discord`다. 다만 `DISCORD_WEBHOOK_URL`이 비어 있으면 네트워크 요청을 보내지 않는다. Telegram은 `TELEGRAM_BOT_TOKEN`과 `TELEGRAM_CHANNEL_ID`가 모두 유효할 때만 활성화한다.

기존 `.env` 호환 규칙은 다음과 같다.

1. `LECTURE_REPORT_CHANNEL`이 있으면 새 설정을 우선한다.
2. 새 설정이 없고 `LECTURE_NOTIFY_DISCORD=1`이면 Discord를 사용한다.
3. 새 설정이 없고 `LECTURE_NOTIFY_DISCORD=0`이면 알림을 끈다.
4. 두 설정이 모두 없으면 기본 채널은 Discord로 해석하되, 유효한 웹후크가 없으므로 알림 없이 실행한다.
5. 알 수 없는 채널 값은 외부 전송을 모두 차단하고 경고만 남긴다.

`LECTURE_NOTIFY_DISCORD`는 새 문서와 프롬프트에서 더 이상 안내하지 않지만, 기존 사용자 호환을 위해 코드에서는 계속 읽는다.

## 코드 구조

`notifications.py`가 공통 메시지 포맷과 전송 제공자를 함께 관리한다. 교육용 저장소의 파일 수를 늘리지 않으면서도 각 클래스의 역할을 분리한다.

- 공통 단계 메서드: 스크리닝, 분석, 매매 판단, 판단 요약, 피드백, 운영 이벤트를 기존 포맷터로 만든다.
- `DiscordNotifier`: 기존 Incoming Webhook 전송을 유지한다.
- `TelegramNotifier`: Telegram Bot API `sendMessage`를 표준 라이브러리 `urllib.request`로 호출한다.
- `CompositeNotifier`: 같은 메시지를 준비된 제공자들에게 전달한다.
- `NullNotifier`: 알림이 꺼졌거나 유효한 제공자가 없을 때 네트워크 호출을 하지 않는다.
- `build_notifier()`: `.env` 선택과 자격 증명을 검증해 위 객체 중 하나를 반환한다.

`main.py`는 제공자 종류를 알지 않는다. 기존 notifier 인터페이스만 호출하며, 오류 로그도 `Discord 알림`이 아니라 `보고 채널 알림`으로 표현한다.

## Telegram 전송 계약

원본 `prism-insight`의 환경 변수와 재시도 원칙을 가져오되, `python-telegram-bot` 패키지는 추가하지 않는다. 강의용 데모 경로가 표준 라이브러리만으로 실행되어야 하기 때문이다.

전송 주소는 코드가 고정한 `https://api.telegram.org/bot{token}/sendMessage`만 사용한다. 사용자 입력으로 호스트를 바꿀 수 없다. 요청 본문에는 다음 값만 넣는다.

- `chat_id`: 검증된 `TELEGRAM_CHANNEL_ID`
- `text`: 기존 판단 메시지를 Telegram HTML 형식으로 안전하게 변환한 본문
- `parse_mode`: `HTML`
- `disable_web_page_preview`: `true`

기존 메시지의 `**강조**`는 HTML escape 뒤 `<b>강조</b>`로 바꾼다. 나머지 사용자·데이터 문자열은 HTML로 해석되지 않게 escape한다. 공통 메시지 길이는 기존 Discord 제한인 2,000자를 유지하므로 Telegram의 더 큰 제한에도 들어간다.

HTTP 429는 Telegram 응답의 `parameters.retry_after`를 읽어 최대 5초 안에서 한 번만 재시도한다. timeout, HTTP 오류, 잘못된 JSON, `ok=false`는 `False`를 반환하고 본 파이프라인을 계속한다. 로그에는 오류 종류와 HTTP 상태만 남기며 봇 토큰, 채널 ID, 요청 URL, 원문 오류 메시지는 남기지 않는다.

봇 토큰은 `숫자:문자열` 형식, 채널 ID는 정수형 채팅 ID 또는 `@채널이름` 형식만 허용한다. 값이 비어 있거나 공백·URL처럼 보이면 해당 제공자를 만들지 않는다.

## 동시 전송과 부분 실패

`both`는 두 자격 증명이 모두 있어야만 시작되는 일괄 트랜잭션이 아니다. 유효하게 준비된 제공자는 각각 독립적으로 활성화한다.

- Discord만 유효하면 Discord에 보낸다.
- Telegram만 유효하면 Telegram에 보낸다.
- 둘 다 유효하면 두 곳에 보낸다.
- 둘 다 유효하지 않으면 `NullNotifier`를 사용한다.

한 메시지가 적어도 한 채널에 전달되면 합성 전송 결과는 성공으로 본다. 어느 채널도 성공하지 못하면 실패로 본다. 이 반환값은 관찰용이며 매매·저장 결과에는 영향을 주지 않는다.

## 시크릿과 개인정보 경계

- 실제 `.env`는 읽거나 수정하거나 출력하지 않는다.
- 테스트는 가짜 토큰·채널과 가짜 HTTP 응답만 사용한다.
- `TELEGRAM_BOT_TOKEN`, `DISCORD_WEBHOOK_URL`, 계좌번호는 로그·문서 예시·메시지에 실제 값으로 들어가지 않는다.
- `TELEGRAM_CHANNEL_ID`도 운영 로그와 에이전트 답변에 실제 값으로 출력하지 않는다.
- 운영 이벤트 정리기는 `token`, `webhook`, `channel_id`, 계좌·잔고·URL을 민감 필드로 처리한다.
- Telegram이나 Discord를 끄는 설정은 매매 모드와 무관하다. 알림을 꺼도 broker 안전 게이트는 그대로 유지된다.

## 강의자료와 문서

Discord만 전제로 한 현재 교육 흐름을 “선택한 보고 채널” 기준으로 바꾼다.

- `.env.example`: 새 채널 선택과 두 제공자의 빈 자격 증명을 함께 제시한다.
- `docs/runtime-profiles.md`: 네 가지 선택값, Discord 준비, Telegram 준비, 동시 전송, `off` 폴백을 설명한다.
- `docs/runtime-execution-preflight.md`: 승인 대상 도메인을 선택한 채널에 맞게 제한한다.
- `docs/architecture.md`, `README.md`, `AGENTS.md`: Discord 전용 표현을 선택형 보고 채널로 고친다.
- `강의자료/강사용_실습진행_스크립트.md`: 준비 여부, 실제 전송 확인, 실패 폴백을 채널 공통 표현으로 바꾼다.
- `lecture/exercises/수강생_붙여넣기_프롬프트_파트3.md`: 수강생이 선택한 채널만 준비하고 채널별 성공 여부를 확인하도록 바꾼다.
- `강의자료/수업_시작_전_안내.md`: 선택 연동이 자동으로 켜지지 않는다는 경계를 두 채널에 적용한다.
- `lecture/exercises/수강생_붙여넣기_프롬프트_파트4.md`: 외부 알림 금지 실습에서 Discord와 Telegram을 모두 끄도록 쓴다.
- `강의자료/deck-src/part3/00-opening.html`의 5페이지: Discord 또는 Telegram을 쓸 사람이 설정 프롬프트를 먼저 사용하고 `.env`에 값을 직접 입력한다고 안내한다.
- 생성된 `강의자료/파트3_슬라이드.html`은 원본 모듈에서 다시 조립한다.

문서 예시는 터미널 명령 대신 코딩 에이전트에 붙여넣는 프롬프트 형태를 유지한다.

## 검증 기준

1. 새 설정이 없고 자격 증명이 없으면 네트워크 없이 `NullNotifier`가 만들어진다.
2. `discord`, `telegram`, `both`, `off`가 정확히 라우팅된다.
3. 기존 `LECTURE_NOTIFY_DISCORD=1/0` 설정이 새 설정이 없을 때만 호환된다.
4. Telegram 요청은 고정된 공식 HTTPS 호스트, 검증된 채널 ID, 안전한 HTML 본문을 사용한다.
5. Telegram 429는 최대 한 번, 최대 5초 지연 뒤 재시도한다.
6. Discord 또는 Telegram 한쪽 실패가 다른 채널과 파이프라인을 막지 않는다.
7. 메시지와 로그에 계좌·현금·토큰·웹후크·채널 ID가 나타나지 않는다.
8. 관련 단위 테스트와 문서 계약 테스트가 통과한다.
9. 파트3 슬라이드 원본을 다시 조립했을 때 5페이지에 Discord와 Telegram 선택 안내가 보인다.
10. `python3 main.py`가 API 키 없이 mock·simulation으로 완주한다.
11. `trading.py --live`의 이중 안전 게이트는 바뀌지 않는다.

## 제외 범위

- Telegram 봇 생성, 채널 생성, 관리자 권한 부여를 자동화하지 않는다.
- 실제 로컬 토큰으로 메시지를 보내지 않는다.
- 이미지·PDF·파일 전송, 다국어 Telegram 채널, 구독자 관리 기능을 넣지 않는다.
- 이메일이나 추가 메신저 제공자를 구현하지 않는다.
- 이번 기능과 무관한 기존 강의자료 계약 실패를 함께 정리하지 않는다.
