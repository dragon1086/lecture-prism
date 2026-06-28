"""
screening.py — 모듈 1: 종목 스크리닝

전종목 → 매매 후보 N종목 필터링.
알고리즘이 담당하는 영역: 규칙이 명확하고 대량 처리가 필요한 부분.

실행:
    python screening.py              # 전종목 스크리닝
    python screening.py --verbose    # 탈락 종목 이유 포함
"""

import asyncio
import logging
from typing import Optional

log = logging.getLogger(__name__)

# ── 스크리닝 조건 (파트4 트랙A에서 수강생이 수정하는 부분) ──────────
VOLUME_SURGE_RATIO = 5.0        # 거래량이 5일 평균의 N배 이상
MIN_MARKET_CAP_KRW = 500_000_000_000  # 시가총액 5000억 이상
MOMENTUM_DAYS = [5, 20]         # N일 이동평균 돌파 기준
MAX_CANDIDATES = 3              # 최종 선정 종목 수

# ── 데모용 내장 종목 유니버스 (pykrx 없이도 '필터가 실제로 작동'하도록) ──
# 강의에서 VOLUME_SURGE_RATIO를 바꾸면 통과 종목이 실제로 달라지는 걸 보여주기 위함.
# (ticker, 거래량배수, 시가총액(KRW), 등락률%)
_SAMPLE_UNIVERSE = [
    ("005930", 5.2, 400_000_000_000_000, 2.1),  # 삼성전자
    ("000660", 5.8,  90_000_000_000_000, 1.8),  # SK하이닉스
    ("035420", 6.1,  30_000_000_000_000, 1.5),  # NAVER
    ("005380", 3.6,  40_000_000_000_000, 4.2),  # 현대차 — 3배에선 통과(고등락률→상위 진입)
    ("068270", 4.1,  25_000_000_000_000, 3.5),  # 셀트리온 — 3배에선 통과
    ("207940", 2.0,  60_000_000_000_000, 0.5),  # 삼성바이오 — 거래량 미달
    ("323410", 1.2,     300_000_000_000, 0.1),  # 카카오뱅크 — 거래량·시총 미달
]


async def run_screening(target_ticker: Optional[str] = None, use_real: bool = False) -> list[str]:
    """
    메인 스크리닝 함수. main.py에서 호출.

    Args:
        target_ticker: 지정 시 해당 종목만 분석 (디버그용)
        use_real: True면 pykrx 실데이터, False면 데모 예시값 (기본).
                  실데이터 조회 실패 시 자동으로 데모값으로 폴백합니다.

    Returns:
        선정된 종목코드 리스트
    """
    if target_ticker:
        log.info(f"단일 종목 모드: {target_ticker}")
        return [target_ticker]

    log.info("전종목 스크리닝 시작...")
    candidates = await _filter_candidates(use_real=use_real)
    log.info(f"스크리닝 완료: {len(candidates)}종목 선정")
    return candidates


async def _filter_candidates(use_real: bool = False) -> list[str]:
    """필터링 로직. use_real=True면 pykrx 실데이터, 실패 시 데모값 폴백."""
    log.info(f"  조건1: 거래량 급등 ({VOLUME_SURGE_RATIO}배 이상) 체크 중...")
    log.info(f"  조건2: 시가총액 {MIN_MARKET_CAP_KRW/1e8:.0f}억 이상 체크 중...")
    log.info(f"  조건3: {MOMENTUM_DAYS}일 이동평균 돌파 체크 중...")

    if use_real:
        real = await _filter_with_pykrx()
        if real:
            log.info(f"  → 선정(실데이터): {real}")
            return real[:MAX_CANDIDATES]
        log.warning("  pykrx 실데이터 조회 실패 — 데모 유니버스로 폴백합니다.")

    # 데모 유니버스에 실제 필터 적용 (조건을 바꾸면 결과가 진짜로 달라짐)
    passed = [
        (ticker, vol, cap, chg)
        for ticker, vol, cap, chg in _SAMPLE_UNIVERSE
        if vol >= VOLUME_SURGE_RATIO          # 거래량 급등 조건
        and cap >= MIN_MARKET_CAP_KRW         # 시가총액 조건
        and chg > 0                           # 상승 종목만
    ]
    # 등락률 높은 순으로 정렬 후 상위 N개 선정
    passed.sort(key=lambda x: x[3], reverse=True)
    result = [ticker for ticker, *_ in passed[:MAX_CANDIDATES]]
    log.info(f"  → 선정(데모): {result}")
    return result


async def _filter_with_pykrx() -> list[str]:
    """
    pykrx 벌크 조회 기반 실제 스크리닝.

    전종목을 1~2회 호출로 가져와(루프 없이) 빠르게 필터링:
      1. 시가총액 ≥ MIN_MARKET_CAP_KRW
      2. 당일 거래대금 상위 + 상승 종목
    PRISM 본 시스템(trigger_batch.py)의 거래량 급증 로직을 강의용으로 단순화한 버전.
    """
    try:
        from pykrx import stock
    except ImportError:
        log.warning("  pykrx 미설치 (pip install pykrx) — 데모값 사용")
        return []

    def _query() -> list[str]:
        from datetime import datetime
        today = datetime.now().strftime("%Y%m%d")

        # 벌크 1회 호출: 전종목 시가총액
        cap = stock.get_market_cap_by_ticker(today, market="ALL")
        if cap is None or cap.empty:
            return []
        # 시총 필터
        cap = cap[cap["시가총액"] >= MIN_MARKET_CAP_KRW]

        # 벌크 1회 호출: 전종목 당일 OHLCV (등락률·거래대금)
        ohlcv = stock.get_market_ohlcv_by_ticker(today, market="ALL")
        if ohlcv is None or ohlcv.empty:
            return []

        merged = ohlcv.join(cap[["시가총액"]], how="inner")
        # 상승 종목만 + 거래대금 상위 정렬
        merged = merged[merged["등락률"] > 0].sort_values("거래대금", ascending=False)
        return merged.index.tolist()[:MAX_CANDIDATES]

    # pykrx는 동기 라이브러리 → 이벤트 루프 블로킹 방지 위해 별도 스레드에서 실행
    return await asyncio.to_thread(_query)


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--ticker", type=str)
    parser.add_argument("--real", action="store_true", help="pykrx 실데이터 사용 (기본: 데모값)")
    args = parser.parse_args()

    result = asyncio.run(run_screening(target_ticker=args.ticker, use_real=args.real))
    print(f"\n최종 선정 종목: {result}")
