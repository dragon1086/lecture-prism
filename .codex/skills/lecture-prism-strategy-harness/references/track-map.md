# lecture-prism Harness Track Map

> 전략이 여러 트랙에 걸치면 한 번에 다 수정하지 말 것. 순서를 제안하고 [한 트랙 수정 → 데모 검증 → 전후 비교] 사이클을 트랙별로 반복한다.
> 35분 수업 빠른 모드에서는 첫 트랙만 끝낸다. 자료 요구는 `data-readiness-map.md`의 자료 준비 상태로 분류한다.

## Track A — screening.py

Good for:
- RSI, 거래량, 시총, 이동평균, 신고가, 변동성

Preserve:
- `run_screening(target_ticker: Optional[str] = None, use_real: bool = False) -> list[str]`

Verify:
- screening 단독 실행
- main 데모 실행

## Track B — analysis.py

Good for:
- 분석 철학, 투자 대가 관점, 뉴스/재무/모멘텀 프롬프트

Preserve:
- `run_analysis(ticker: str) -> dict`
- 반환 dict keys 유지: ticker, recommendation, decision, buy_score(0~10), rationale, risk, target_price, stop_loss + 6섹션 요약(technical/supply/financial/industry/news_summary, market_condition)

Verify:
- analysis 단독 실행
- LLM 미연결 시 mock 폴백이 깨지지 않는지 확인

## Track C — trading.py exit

Good for:
- 목표가, 손절, 트레일링 스탑, 절반 청산

Preserve:
- `_decide_exit(holding: dict, current_price: float) -> Optional[dict]`
- `run_exit_check(holdings: list[dict], price_map: dict) -> list[dict]`

Verify:
- 청산 데모에서 관련 시나리오 발화

## Track D — trading.py risk

Good for:
- 최대 보유 종목 수, 현금 비중, 매수 점수, 손절폭

Preserve:
- `_decide_position(analysis: dict, portfolio: dict) -> Optional[dict]`

Verify:
- 시뮬레이션 매매 실행
- 새 상수가 수량/매수 여부에 실제 반영되는지 설명

## Runtime/API settings are not strategy tracks

Good for:
- `.env` profile choice: mock, real_data, research, paper, live
- API keys: OpenAI/OAuth, Perplexity, Firecrawl
- Broker config: `LECTURE_BROKER`, `LECTURE_TRADE_MODE`, `kis_devlp.yaml`

Preserve:
- Strategy harness changes must still start from mock/simulation verification.
- Do not enable broker API calls while applying a strategy unless the user explicitly asks for paper/live setup.

Verify:
- Read `docs/runtime-profiles.md`
- Explain which integrations are active and which ones fall back
- Confirm real orders remain blocked unless both live broker safety flags are set

## 시장 흐름은 별도 트랙이 아니라 조정 조건

- 후보를 줄이거나 늘리면 A
- AI 분석에서 시장 맥락을 해석하면 B
- 시장 악화 때 청산하면 C
- 현금·슬롯·매수 크기를 바꾸면 D

시장 흐름 요구를 들었다는 이유만으로 여러 트랙을 한 번에 수정하지 않는다.
