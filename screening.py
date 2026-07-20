"""
screening.py — 모듈 1: 종목 스크리닝

전종목 → 매매 후보 N종목 필터링.
알고리즘이 담당하는 영역: 규칙이 명확하고 대량 처리가 필요한 부분.

실행:
    python screening.py              # 전종목 스크리닝
    python screening.py --verbose    # 탈락 종목 이유 포함
"""

import asyncio
import inspect
import logging
from typing import Optional

from prism_core.domain import Market, validate_market_contract

log = logging.getLogger(__name__)

# ── 스크리닝 조건 (파트4 트랙A에서 수강생이 수정하는 부분) ──────────
VOLUME_SURGE_RATIO = 5.0        # 거래량이 최근 평균(실데이터: 20일)의 N배 이상
MIN_MARKET_CAP_KRW = 500_000_000_000  # 시가총액 5000억 이상
MOMENTUM_DAYS = [5, 20]         # N일 이동평균 돌파 기준
MAX_CANDIDATES = 3              # 최종 선정 종목 수

# ── 데모용 내장 종목 유니버스 (실데이터 없이도 '필터가 실제로 작동'하도록) ──
# --real 모드에서는 이 유니버스의 종목들을 yfinance 실데이터로 다시 필터링합니다.
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
        use_real: True면 legacy yfinance 실데이터, False면 데모 예시값 (기본).
                  이 폴백은 mock/real_data 호환 경로에만 적용됩니다.

    Returns:
        선정된 종목코드 리스트
    """
    if target_ticker is not None:
        market = (
            Market.KR
            if isinstance(target_ticker, str)
            and len(target_ticker) == 6
            and target_ticker.isascii()
            and target_ticker.isdigit()
            else Market.US
        )
        validate_market_contract(market, target_ticker)

    from runtime_config import load_runtime_config

    config = load_runtime_config()
    if config.profile in {"classroom", "backtest", "paper", "live"}:
        log.info("운영 프로필 상세 스크리닝 시작: %s", config.profile)
        detailed = await run_detailed_screening(
            profile=config.profile,
            target_ticker=target_ticker,
        )
        return [candidate.instrument.symbol for candidate in detailed]

    if target_ticker is not None:
        log.info(f"단일 종목 모드: {target_ticker}")
        return [target_ticker]

    log.info("전종목 스크리닝 시작...")
    candidates = await _filter_candidates(use_real=use_real)
    log.info(f"스크리닝 완료: {len(candidates)}종목 선정")
    return candidates


async def run_detailed_screening(
    *, profile: str, target_ticker: Optional[str] = None
):
    """Delegate lazily to the stateful market pipeline when it is installed.

    The import and provider failures intentionally propagate. In particular,
    paper/live must never continue into the legacy demo universe.
    """

    from prism_core.market_pipeline import run_detailed_screening as detailed

    result = detailed(profile=profile, target_ticker=target_ticker)
    if inspect.isawaitable(result):
        result = await result
    return list(result)


async def _filter_candidates(use_real: bool = False) -> list[str]:
    """Legacy mock/real_data filter; real lookup may fall back to demo data."""
    log.info(f"  조건1: 거래량 급등 ({VOLUME_SURGE_RATIO}배 이상) 체크 중...")
    log.info(f"  조건2: 시가총액 {MIN_MARKET_CAP_KRW/1e8:.0f}억 이상 체크 중...")
    log.info(f"  조건3: {MOMENTUM_DAYS}일 이동평균 돌파 체크 중...")

    if use_real:
        real = await _filter_with_real_data()
        if real:
            log.info(f"  → 선정(실데이터): {real}")
            return real[:MAX_CANDIDATES]
        log.warning("  실데이터 스크리닝 결과 없음/실패 — 데모 유니버스로 폴백합니다.")

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


async def _filter_with_real_data() -> list[str]:
    """
    yfinance 실데이터 기반 스크리닝 (data_source.fetch_stock_data 재사용).

    KRX 전종목 벌크 조회(시가총액·거래대금)는 KRX가 로그인을 요구해
    무료·무로그인으로는 불가능합니다(pykrx 벌크 API 포함). 그래서
    데모 유니버스 종목들에 대해 '같은 필터'를 실데이터 지표로 계산합니다:
      1. 거래량 급등: 당일 거래량 / 20일 평균 ≥ VOLUME_SURGE_RATIO
      2. 시가총액  : market_cap ≥ MIN_MARKET_CAP_KRW
      3. 모멘텀    : 현재가가 5·20일 이동평균 위 + 당일 상승

    조건이 실데이터 기준으로 너무 엄격하면(예: 거래량 5배 급등은 드묾)
    통과 종목이 0개일 수 있고, 그 경우 데모 유니버스로 폴백합니다.
    VOLUME_SURGE_RATIO를 낮춰 보면 실데이터에서도 결과가 달라집니다.
    """
    def _query() -> list[str]:
        from data_source import fetch_stock_data

        scored: list[tuple[str, float]] = []
        for ticker, *_ in _SAMPLE_UNIVERSE:
            data = fetch_stock_data(ticker)
            if data.get("source") == "mock":  # 실데이터만 필터 대상
                log.info(f"  [{ticker}] 실데이터 없음 — 스크리닝에서 제외")
                continue

            price = data.get("current_price")
            vol_ratio = data.get("vol_ratio")
            market_cap = data.get("market_cap")
            ret_1d = data.get("ret_1d") or 0.0
            ma5, ma20 = data.get("ma5"), data.get("ma20")

            # 값이 없는 지표는 탈락 사유로 삼지 않음 (데이터 결측 ≠ 조건 미달)
            if vol_ratio is not None and vol_ratio < VOLUME_SURGE_RATIO:
                continue
            if market_cap is not None and market_cap < MIN_MARKET_CAP_KRW:
                continue
            if any(ma is not None and price < ma for ma in (ma5, ma20)):
                continue
            if ret_1d <= 0:
                continue
            scored.append((ticker, ret_1d))

        # 등락률 높은 순 상위 N개 (데모 경로와 동일한 정렬 기준)
        scored.sort(key=lambda x: x[1], reverse=True)
        return [ticker for ticker, _ in scored[:MAX_CANDIDATES]]

    # yfinance는 동기 라이브러리 → 이벤트 루프 블로킹 방지 위해 별도 스레드에서 실행
    try:
        return await asyncio.to_thread(_query)
    except Exception as e:  # noqa: BLE001 — 실데이터 실패는 어떤 경우든 데모로 폴백
        log.warning(f"  실데이터 스크리닝 오류({type(e).__name__}: {e}) — 데모값 사용")
        return []


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--ticker", type=str)
    parser.add_argument("--real", action="store_true", help="yfinance 실데이터 사용 (기본: 데모값)")
    args = parser.parse_args()

    result = asyncio.run(run_screening(target_ticker=args.ticker, use_real=args.real))
    print(f"\n최종 선정 종목: {result}")
