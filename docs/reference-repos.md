# 참고 오픈소스와 증권 Open API 저장소

`lecture/curriculum.html`의 "오픈소스 매매 시스템 지형도"에서 언급한 프로젝트와, 증권사 API 연동 실습 때 참고할 저장소입니다.

| 분류 | 저장소 | 수강생 관점에서 볼 포인트 |
|---|---|---|
| 백테스팅 | [Backtrader](https://github.com/mementum/backtrader) | 규칙 기반 전략과 백테스트 구조 |
| 암호화폐 봇 | [Freqtrade](https://github.com/freqtrade/freqtrade) | 전략 파일·봇 운영 구조. 단, 공개 전략은 쉽게 파훼될 수 있음 |
| AI 퀀트 | [Microsoft Qlib](https://github.com/microsoft/qlib) | 시계열 예측·리서치 플랫폼 구조 |
| 강화학습 | [FinRL](https://github.com/AI4Finance-Foundation/FinRL) | RL 기반 트레이딩 연구 구조 |
| LLM 에이전트 | [TradingAgents](https://github.com/TauricResearch/TradingAgents) | 불/베어 리서처 토론형 멀티에이전트 패턴 |
| PRISM 원본 | [prism-insight](https://github.com/dragon1086/prism-insight) | lecture-prism의 원본 방향성·실운용 구조 |
| 토스증권 | [tossinvest-cli](https://github.com/JungHoonGhae/tossinvest-cli) | 토스증권 Open API/WTS를 에이전트·CLI에서 다루는 참고 구현 |
| 한국투자증권 | [open-trading-api](https://github.com/koreainvestment/open-trading-api) | KIS 공식 Open Trading API 샘플과 실전/모의투자 구조 |
| 에이전트 설계 | [Anthropic — Building effective agents](https://anthropic.com/research/building-effective-agents) | Prompt Chaining, Routing, Parallelization 같은 에이전트 패턴 |

주의: 참고 저장소의 코드를 그대로 복붙하기보다, lecture-prism에서는 `brokers/` 어댑터 구조와 데모 모드 안전장치를 유지한 채 필요한 아이디어만 가져오는 것을 권장합니다.
