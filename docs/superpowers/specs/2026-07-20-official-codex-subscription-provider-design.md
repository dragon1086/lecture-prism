# 공식 Codex 구독 LLM 공급자 설계

## 결정

ChatGPT Plus/Pro 연동은 프로젝트가 OAuth 토큰을 직접 발급·저장·갱신하거나 비공개 백엔드를 호출하지 않는다. 공식 Codex CLI의 `codex login`을 최초 1회 수행하고, lecture-prism은 `codex exec`를 선택 LLM 공급자로 호출한다.

OpenAI 공식 문서는 Codex가 ChatGPT 구독 로그인과 API 키 로그인을 지원하고, 로그인 정보를 운영체제 자격 증명 저장소 또는 `~/.codex/auth.json`에 캐시하며 만료 전 갱신한다고 설명한다. 비대화형 자동화에는 `codex exec`를 제공한다.

- [Codex authentication](https://learn.chatgpt.com/docs/auth)
- [Codex CLI reference](https://developers.openai.com/codex/cli/reference/)
- [Using Codex with a ChatGPT plan](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan)

ChatGPT 구독과 OpenAI API 과금은 같은 것이 아니다. `LECTURE_LLM_MODE=oauth`는 구독 Codex, `openai`는 API 키, `mock`은 외부 호출 없음이다. `auto`는 예측 가능한 운영을 위해 API 키만 자동 감지하며 로컬 로그인 유무를 추측하지 않는다. 단, 이전 강의 설정의 `PRISM_OPENAI_AUTH_MODE=chatgpt_oauth`는 사용자가 명시한 호환 선택으로 받아 공식 Codex 경로를 사용한다.

## 호출 경계

- 셸 없이 argv 배열로 subprocess를 실행하고, 분석 입력은 프로세스 목록에 남지 않도록 stdin으로 전달한다.
- 임시 빈 작업 디렉터리, `--ephemeral`, `--sandbox read-only`, `--ignore-user-config`를 사용한다.
- Codex의 shell/unified-exec와 브라우저·플러그인·멀티에이전트 기능을 끈다. `read-only`만으로는 읽기를 막지 못하므로 도구 비활성화를 별도 보안 경계로 둔다.
- 부모 환경은 OS·Codex 로그인에 필요한 허용 목록만 전달하고 API 키·토큰을 상속하지 않는다. 프록시 환경변수는 사용자명·비밀번호가 없는 값만 전달한다. 인증 파일을 프로젝트가 읽거나 복사하지 않고 stdout/stderr 원문도 오류 메시지에 노출하지 않는다.
- 타임아웃·미설치·로그아웃·비정상 종료는 규칙 분석으로 폴백한다.
- macOS와 Windows 모두 Python 표준 라이브러리의 subprocess/tempfile 경로를 사용한다.

## 분석 비용과 구조

Codex 에이전트 런타임은 짧은 응답에도 고정 컨텍스트 비용이 크다. 따라서 기존 기술·뉴스·전략 3회 호출을 종목당 한 번의 구조화 호출로 합친다. 세 역할과 6섹션 출력은 유지하되 수집은 데이터 공급자가, 해석만 LLM이 담당한다.

LLM JSON은 신뢰 경계 밖 입력이다. 출력 스키마는 기술·뉴스 요약, 근거, 위험, `llm_veto`만 허용한다. 추천·점수·목표가·손절가는 정량 규칙이 단독 소유하며 LLM은 올릴 수 없다. LLM은 명시적 veto로 BUY를 HOLD로 내릴 수만 있다. 주문 직전에도 recommendation·decision·score를 함께 확인한다.

## 수강생 경험

기본 `python3 main.py`는 계속 API 키와 로그인 없이 완주한다. OAuth 선택 실습은 수강생이 터미널 명령을 외우는 대신 코딩 에이전트에게 설치·로그인 상태 확인과 최초 로그인, 종목 1개 검증을 요청한다. 이후 토큰 갱신은 Codex가 담당하므로 정상 환경에서는 재로그인이 필요 없다.

## 보류·격리

`cores/chatgpt_proxy`의 자체 PKCE/비공개 backend 구현은 기존 참고·회귀 테스트를 위해 남길 수 있지만 운영 파이프라인은 import하거나 시작하지 않는다. 향후 삭제 여부는 공개 강의 자료와 회귀 테스트를 별도 정리할 때 결정한다.
