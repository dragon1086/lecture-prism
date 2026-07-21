# Toss WTS 선택 브로커 구현 계획

> 설계: `docs/superpowers/specs/2026-07-20-toss-wts-adapter-design.md`

1. 가짜 `tossctl` runner로 인증·계좌·BUY/SELL·조회·취소 JSON 계약의 실패 테스트를 추가한다.
2. `brokers/tossctl.py`에 실행 파일 탐색, 버전 고정, 안전한 subprocess/JSON 경계를 구현한다.
3. `brokers/toss.py`를 KIS 대칭 어댑터로 교체한다.
4. `trading.py`의 KIS 전용 admission/reconcile을 공용화하고 Toss `UNKNOWN`·재시작 복구를 연결한다.
5. `.env.example`과 현재 기능 문서를 Toss 선택 어댑터 현실에 맞춘다.
6. 관련 테스트, 전체 unittest, 임시 DB mock 파이프라인, live 차단, compileall, 비밀값 검사를 실행한다.
