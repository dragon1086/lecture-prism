"""Read-only KIS price and investor-flow snapshot for the course labs."""

from __future__ import annotations

import argparse
from datetime import date, timedelta
import os
from pathlib import Path
import sys
import time
from typing import Any, Mapping


class KISMarketDataError(RuntimeError):
    """A sanitized failure at the read-only teaching boundary."""


READ_ONLY_MAX_ATTEMPTS = 3
READ_ONLY_RETRY_DELAYS = (1.0, 2.0)


def _is_retryable_read_only_error(error: BaseException) -> bool:
    from brokers.kis_client import KISRequestError

    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, KISRequestError):
            return current.retryable
        if isinstance(current, (TimeoutError, ConnectionError, OSError)):
            return True
        current = current.__cause__
    return False


def _read_only_error_message(error: BaseException) -> str:
    from brokers.kis_client import KISRequestError

    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, KISRequestError) and current.status is not None:
            return f"KIS read-only market-data request failed (HTTP {current.status})"
        current = current.__cause__
    return "KIS read-only market-data request failed"


def _market_data_token_cache_path(environment: str) -> Path:
    configured = os.getenv("KIS_MARKET_DATA_TOKEN_FILE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parent / ".cache" / f"KIS_{environment}_market_data.token"


def _mode(value: str) -> str:
    selected = str(value).strip().lower()
    if selected in {"paper", "demo", "vps"}:
        return "paper"
    if selected in {"real", "live", "prod"}:
        return "real"
    raise ValueError("KIS environment must be paper or real")


def _price_rows(rows: object) -> dict[str, int]:
    if not isinstance(rows, list) or not rows:
        raise KISMarketDataError("KIS daily-price response has no rows")
    normalized: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise KISMarketDataError("KIS daily-price response contains an invalid row")
        raw_date = str(row.get("stck_bsop_date") or "").strip()
        raw_price = str(row.get("stck_clpr") or "").strip()
        if len(raw_date) != 8 or not raw_date.isdigit():
            raise KISMarketDataError("KIS daily-price response has invalid date")
        try:
            parsed_date = date(
                int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:8])
            ).isoformat()
            price = int(raw_price)
        except ValueError as exc:
            raise KISMarketDataError(
                "KIS daily-price response has invalid date or price"
            ) from exc
        if price <= 0:
            raise KISMarketDataError("KIS daily-price response has invalid price")
        normalized[parsed_date] = price
    return normalized


def fetch_kis_snapshot(
    ticker: str = "005930",
    mode: str = "paper",
    *,
    client=None,
    today: date | None = None,
    max_attempts: int = READ_ONLY_MAX_ATTEMPTS,
) -> dict[str, Any]:
    """Return one dated price/flow snapshot without touching account operations."""

    selected_ticker = str(ticker).strip()
    if len(selected_ticker) != 6 or not selected_ticker.isdigit():
        raise ValueError("ticker must be a six-digit domestic stock code")
    environment = _mode(mode)
    selected_day = today or date.today()
    if int(max_attempts) < 1:
        raise ValueError("max_attempts must be positive")
    if client is None:
        from brokers.kis_client import KISClient, KISConfig

        client = KISClient(
            KISConfig.from_env_market_data(environment),
            token_cache_path=_market_data_token_cache_path(environment),
        )

    start = (selected_day - timedelta(days=14)).strftime("%Y%m%d")
    end = selected_day.strftime("%Y%m%d")
    attempts = int(max_attempts)
    for attempt in range(attempts):
        try:
            prices = _price_rows(
                client.get_daily_prices(selected_ticker, start, end)
            )
            flow_rows = client.get_investor_flow(selected_ticker, end)
            break
        except KISMarketDataError:
            raise
        except Exception as exc:
            if attempt + 1 >= attempts or not _is_retryable_read_only_error(exc):
                raise KISMarketDataError(_read_only_error_message(exc)) from exc
            time.sleep(READ_ONLY_RETRY_DELAYS[min(attempt, len(READ_ONLY_RETRY_DELAYS) - 1)])

    if not isinstance(flow_rows, list) or not flow_rows:
        raise KISMarketDataError("KIS investor-flow response has no rows")
    flows: dict[str, Mapping[str, object]] = {}
    for row in flow_rows:
        if not isinstance(row, Mapping):
            raise KISMarketDataError("KIS investor-flow response contains an invalid row")
        as_of = str(row.get("as_of") or "").strip()
        if as_of:
            flows[as_of] = row

    common_dates = sorted(set(prices) & set(flows), reverse=True)
    if not common_dates:
        raise KISMarketDataError(
            "KIS price and investor flow have no common business date"
        )
    as_of = common_dates[0]
    flow = flows[as_of]
    return {
        "environment": environment,
        "source": "KIS Open API",
        "ticker": selected_ticker,
        "as_of": as_of,
        "price": prices[as_of],
        "institution_net_buy": int(flow["institution_net_buy"]),
        "foreign_net_buy": int(flow["foreign_net_buy"]),
        "individual_net_buy": int(flow["individual_net_buy"]),
        "order_calls": 0,
    }


def format_snapshot(snapshot: Mapping[str, object]) -> str:
    """Format the small student-facing proof without exposing credentials."""

    return "\n".join(
        (
            f"KIS 환경 {snapshot['environment']}",
            f"데이터 원천 {snapshot['source']}",
            f"종목 {snapshot['ticker']}",
            f"기준일 {snapshot['as_of']}",
            f"가격 {int(snapshot['price']):,}원",
            f"기관 순매수 {int(snapshot['institution_net_buy']):,}주",
            f"외국인 순매수 {int(snapshot['foreign_net_buy']):,}주",
            f"개인 순매수 {int(snapshot['individual_net_buy']):,}주",
            f"주문·취소·계좌 호출 {int(snapshot['order_calls'])}건",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KIS 읽기 전용 가격·수급 확인")
    parser.add_argument("--mode", choices=("paper", "real"), required=True)
    parser.add_argument("--ticker", default="005930")
    args = parser.parse_args(argv)
    try:
        snapshot = fetch_kis_snapshot(args.ticker, args.mode)
    except (KISMarketDataError, ValueError) as exc:
        print(f"KIS 읽기 전용 조회 실패: {exc}", file=sys.stderr)
        return 1
    print(format_snapshot(snapshot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
