# lecture-prism Harness Track Map

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
- 반환 dict keys: ticker, recommendation, score, reason, risk, technical_summary, news_summary

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
