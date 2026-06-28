"""
blank_pipeline.py — 파트4 실습용 뼈대

파트4 실습 목표: 4개 함수 중 '1개'를 본인 이론으로 채우는 것.
함수 시그니처(입력/출력 형태)는 반드시 유지해야 main.py와 연결됩니다.

Claude Code 프롬프트 예시:
  "현재 screen_stocks 함수는 비어 있어.
   RSI 30 이하이면서 거래량이 5일 평균의 3배 이상인 종목을 선정하도록 구현해줘.
   반환값은 종목코드 리스트 형태를 유지해줘."
"""

from typing import Optional


def screen_stocks() -> list[str]:  # noqa: ANN201
    """
    모듈 1: 종목 선정

    전체 종목 중 매매 후보를 추려서 종목코드 리스트로 반환합니다.

    Returns:
        list[str]: 선정된 종목코드 목록 (예: ["005930", "000660"])

    구현 아이디어:
        - 거래량 급등 (5일 평균 대비 N배 이상)
        - 모멘텀 (5일, 20일 이동평균 돌파)
        - 시가총액 필터 (너무 작은 종목 제외)
        - RSI 과매도/과매수 조건
        - 52주 신고가 근접
    """
    raise NotImplementedError("여기에 본인의 종목 선정 조건을 구현하세요")


def analyze_stock(ticker: str) -> dict:
    """
    모듈 2: 종목 분석

    단일 종목에 대한 투자 분석을 수행하고 결과를 반환합니다.

    Args:
        ticker: 종목코드 (예: "005930")

    Returns:
        dict: {
            "ticker": str,
            "recommendation": str,   # "BUY" | "HOLD" | "PASS"
            "score": int,            # 1~5 (5가 가장 강한 매수)
            "reason": str,           # 판단 근거 요약
            "risk": str,             # 주요 리스크
        }

    구현 아이디어:
        - Claude/GPT에게 기술적 분석 요청
        - 뉴스 분석 포함
        - 재무 데이터 기반 가치 평가
        - 섹터 트렌드 반영
    """
    raise NotImplementedError("여기에 본인의 분석 로직을 구현하세요")


def decide_trade(analysis: dict, portfolio: dict) -> Optional[dict]:
    """
    모듈 3: 매매 의사결정

    분석 결과와 현재 포트폴리오를 보고 매수/매도 여부를 결정합니다.

    Args:
        analysis: analyze_stock()의 반환값
        portfolio: {
            "cash": float,           # 현재 현금
            "slots_used": int,       # 현재 사용 중인 슬랏 수
            "holdings": list[dict],  # 보유 종목 목록
        }

    Returns:
        Optional[dict]: 매매하지 않으면 None, 매매하면:
        {
            "action": str,     # "BUY" | "SELL"
            "ticker": str,
            "quantity": int,   # 수량
            "price": float,    # 희망 가격
            "reason": str,
        }

    구현 아이디어:
        - score 기준으로 매수 여부 결정
        - 포지션 사이징 (슬랏당 균등 배분 등)
        - 섹터 집중 방지
        - 손절 조건 체크
    """
    raise NotImplementedError("여기에 본인의 매매 의사결정 로직을 구현하세요")


def record_feedback(trade_result: dict, analysis: dict) -> str:
    """
    모듈 4: 피드백 & 매매일지

    매매 결과를 기록하고 다음 매매에 활용할 교훈을 추출합니다.

    Args:
        trade_result: {
            "ticker": str,
            "action": str,
            "executed_price": float,
            "quantity": int,
            "success": bool,         # 체결 성공 여부
            "pnl": Optional[float],  # 수익/손실 (매도 시)
        }
        analysis: analyze_stock()의 반환값

    Returns:
        str: 추출된 교훈 또는 메모 (다음 매매 프롬프트에 반영됨)

    구현 아이디어:
        - 판단 오류 vs 실행 오류 구분
        - 수익/손실 패턴 기록
        - "이 종목은 왜 틀렸는가" 자동 분석
        - 다음번 같은 상황에서 다르게 할 것
    """
    raise NotImplementedError("여기에 본인의 피드백/매매일지 로직을 구현하세요")


# ── 직접 실행 시 테스트 ──────────────────────────────────────────
if __name__ == "__main__":
    print("blank_pipeline 테스트")
    print("=" * 40)

    # 구현한 함수만 주석 해제하여 테스트하세요
    try:
        tickers = screen_stocks()
        print(f"스크리닝 결과: {tickers}")
    except NotImplementedError:
        print("screen_stocks: 미구현")

    try:
        analysis = analyze_stock("005930")
        print(f"분석 결과: {analysis}")
    except NotImplementedError:
        print("analyze_stock: 미구현")
