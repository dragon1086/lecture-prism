# 외부 데이터 실습 실행 전 점검

`yfinance`, KIS, Discord, Telegram, OAuth처럼 인터넷을 쓰는 실습은 실행 전에 이 순서를 따릅니다. 이 문서는 수강생에게 명령어를 외우게 하려는 문서가 아니라, 코딩 에이전트가 잘못된 Python과 네트워크 경로를 고르지 않게 하는 기준입니다.

## 1. 프로젝트와 Python부터 확인

- 현재 폴더가 `lecture-prism` 루트인지 확인합니다.
- 프로젝트 루트의 `.venv/bin/python` 또는 Windows의 `.venv\\Scripts\\python.exe`를 먼저 찾습니다.
- `sys.executable`과 Python 버전을 먼저 보여 줍니다. Python 3.10 이상을 사용합니다.
- `.venv`가 없으면 사용자 전역 Python, pyenv의 전역 Python, `pip --user`를 쓰지 않습니다. Python 3.10 이상으로 프로젝트 전용 `.venv`를 만들 수 있는지 계획부터 보여 주고, 준비되지 않으면 실행을 멈춥니다.
- 작업 중인 Python이 `/usr/bin`, `/usr/local/bin`, 사용자 라이브러리의 Python 3.9.x라면 그대로 진행하지 않습니다.

## 2. 의존성은 프로젝트 `.venv`에만 준비

- `requirements.txt`에 필요한 패키지가 선언되어 있는지 먼저 확인합니다. 예를 들어 실데이터 비교에는 `yfinance`, 대시보드에는 `fastapi`가 필요합니다.
- `import` 가능 여부를 프로젝트 `.venv`의 Python으로 확인합니다.
- 패키지가 없으면 `requirements.txt`를 프로젝트 `.venv`에 설치할 범위와 네트워크 승인을 먼저 보여 줍니다.
- `pip install --user`, 전역 `pip`, 시스템 Python에 설치하지 않습니다.
- 설치 뒤에도 반드시 같은 `.venv` Python으로 다시 확인합니다. 다른 Python으로 설치하고 다른 Python으로 실행하지 않습니다.

## 3. 외부 네트워크는 DNS부터 확인

다음 도메인을 실제로 사용할 때만 필요한 범위의 네트워크 승인을 요청합니다.

- Yahoo Finance: `query1.finance.yahoo.com`, `query2.finance.yahoo.com`
- KIS paper: `https://openapivts.koreainvestment.com:29443`
- KIS real: `https://openapi.koreainvestment.com:9443`
- tossctl 설치: `github.com`, `github-releases.githubusercontent.com`
- Toss 공식 시세: `openapi.tossinvest.com`
- Discord 판단 알림: `discord.com`
- Telegram 판단 알림: `api.telegram.org`

전역 샌드박스를 끄거나 모든 권한을 우회하지 않습니다. 현재 실행 환경에서 DNS가 막히면 인증 토큰이나 API 요청부터 보내지 않습니다.
KIS는 일반 HTTPS 포트 443이 아니라 위에 적힌 환경별 API 포트로 HTTPS 연결을 확인합니다. DNS는 호스트 이름만 확인하고, HTTPS는 포트까지 포함한 전체 주소로 확인합니다.

DNS 또는 HTTPS 사전 확인이 샌드박스 안에서 실패하면 다음을 구분합니다.

1. 승인된 외부 네트워크 실행에서 같은 도메인을 한 번 확인합니다.
2. 외부에서는 정상이고 샌드박스에서만 실패하면 `현재 실행 환경의 DNS 제한`으로 기록하고, 승인된 외부 실행에서 읽기 전용 요청을 계속합니다.
3. 외부에서도 실패하면 KIS·Yahoo 장애, 로컬 네트워크, DNS 문제 중 확인된 범위만 보고합니다.

샌드박스 실패를 곧바로 KIS나 Yahoo의 서비스 장애라고 말하지 않습니다.

## 4. 재시도는 읽기 전용 요청에만 제한적으로

- DNS 해석 실패·연결 시간 초과·HTTP 429·HTTP 5xx는 짧은 간격으로 최대 2회까지 다시 확인합니다.
- 자격 증명 누락·잘못된 키·HTTP 4xx는 재시도하지 않습니다. 먼저 `.env`의 준비 상태만 확인합니다.
- KIS는 DNS·HTTPS 확인 뒤에만 인증 토큰을 요청합니다. 토큰 요청 전 DNS 실패를 보고합니다.
- 주문·취소·정정·잔고·계좌 API는 재시도하지 않고, 이 실습에서는 호출하지 않습니다.
- 재시도 횟수, 각 결과, 마지막 실패 원인을 결과에 남깁니다.

## 5. 결과에 반드시 남길 것

수강생에게는 다음만 간단히 보여 줍니다.

- 사용한 Python 경로와 버전
- 필요한 패키지 준비 상태
- 네트워크 확인 위치: 샌드박스 안 / 승인된 외부 실행
- DNS·HTTPS 확인 결과
- 데이터 조회 결과 또는 실패 원인
- KIS 또는 Toss의 인증 상태 확인 여부와 주문 계열 호출 0회 여부
- 선택한 보고 채널과 채널별 실제 전송 성공 여부 또는 실패 원인
- 다음에 할 한 가지

확인하지 못한 숫자는 만들지 않습니다. yfinance 또는 KIS 중 하나가 막혔다면 비교표의 해당 칸에 `조회 불가`를 쓰고, 성공한 것처럼 매매 판단을 만들지 않습니다.
