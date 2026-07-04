"""
data_source.py — 실데이터 연동 단일 접점 (무료·무로그인)

analysis.py가 6섹션 분석에 쓰는 원천 데이터를 이 파일 하나로 모읍니다.

런타임 폴백 설계:
  mock        : _PROFILES 더미 데이터 — 항상 동작, 키/설치 불필요
  yfinance    : 가격·거래량·재무·뉴스·지수 실데이터
  kospi_kosdaq: 선택 서버 모듈이 있을 때 KRX 계열 가격·수급·지수 조회

원본 PRISM은 KRX 로그인 크롤링 MCP·firecrawl·perplexity를 적극적으로 쓰지만,
강의 기본값은 계정·API 키·로그인이 전혀 필요 없는 mock입니다.

  ✅ 가격/거래량/이평/RSI → yfinance history      (기술적 분석)
  ✅ 재무 PER/ROE/성장률  → yfinance info/재무제표  (재무 분석)
  ✅ 뉴스 헤드라인        → yfinance .news         (뉴스/촉매)
  ✅ 섹터/산업           → yfinance info          (산업 분석)
  ✅ KOSPI/KOSDAQ 지수    → yfinance ^KS11/^KQ11    (시장 국면)
  ❌ 기관/외국인/개인 수급 → KRX 로그인 필요 → 거래량 파생 프록시로 대체

수강생은 `.env`의 LECTURE_PROFILE/LECTURE_DATA_MODE로 어느 단계까지 쓸지 고릅니다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

# 야후 파이낸스 심볼 접미사: 코스피 .KS / 코스닥 .KQ
# 6자리 종목코드 → 우선 .KS, 시장 불일치/데이터 없으면 .KQ 재시도.
_KRX_SUFFIXES = (".KS", ".KQ")

# 야후 exchange 코드 ↔ 접미사 매핑 (KSC=코스피, KOE=코스닥).
# 야후는 잘못된 접미사(예: 코스닥 종목의 .KS)도 같은 시세를 반환하지만
# 종목명·섹터 등 메타데이터가 깨지므로, 진짜 시장의 심볼만 채택합니다.
_EXCHANGE_BY_SUFFIX = {".KS": "KSC", ".KQ": "KOE"}

# 종목별 mock 프로필 (Tier 0). 실데이터가 없어도 6섹션 리치 리포트가 나오도록
# 기술·수급·재무·산업·뉴스 문장을 모두 담습니다. 실데이터 연동 시 이 값들이 실측치로 대체됩니다.
_PROFILES: dict[str, dict] = {
    "005930": dict(
        name="삼성전자", price=71200, sector="전기전자/반도체", rec="BUY", buy_score=8, period="중기", ret=14, loss=5,
        tech="20일선 회복 후 거래량 5일 평균 3배 동반 상승. 정배열 초입으로 추세 전환 신호.",
        supply="최근 5거래일 상승일 거래량이 하락일의 2.1배로 매집 우위. 거래대금 20일 평균 상회.",
        finance="PER 13.2배·PBR 1.1배로 밸류 부담 낮음. ROE 8.4%, 영업이익률 개선 흐름.",
        industry="메모리 업황 저점 통과 국면. HBM·파운드리로 성장축 이동, 경쟁구도 상위.",
        news="HBM·파운드리 수주 기대와 메모리 업황 저점 통과 전망이 우호적. 외국인 순매수 유입."),
    "000660": dict(
        name="SK하이닉스", price=178500, sector="전기전자/반도체", rec="BUY", buy_score=9, period="중기", ret=16, loss=6,
        tech="정배열 유지하며 52주 신고가 근접. 눌림목마다 매수세 유입, 돌파 시 강한 모멘텀.",
        supply="외국인·기관 동반 순매수 추정(거래량 급증비 3.4배). 대금 상위 지속.",
        finance="PER 9.8배로 이익 대비 저평가. ROE 18%대, 실적 레버리지 큼.",
        industry="HBM3E 사실상 과점. AI 메모리 수요 급증의 최대 수혜주.",
        news="HBM3E 공급 확대와 목표주가 상향 리포트 다수. AI 서버 수요 강세."),
    "035420": dict(
        name="NAVER", price=215000, sector="서비스/인터넷", rec="BUY", buy_score=7, period="중기", ret=12, loss=6,
        tech="박스권 상단 돌파 시도. 거래량 점증하며 수급 개선 신호.",
        supply="기관 순매수 전환 구간. 거래량 5일 평균 1.8배로 관심 확대.",
        finance="PER 22배로 성장 기대 반영. 광고·커머스 이익률 회복 중.",
        industry="국내 검색·커머스 1위. AI 검색·광고 신사업이 재평가 촉매.",
        news="AI 검색·광고 매출 회복 기대감이 투자심리를 자극."),
    "042700": dict(
        name="한미반도체", price=143000, sector="반도체장비", rec="BUY", buy_score=8, period="중기", ret=15, loss=6,
        tech="후공정 장비 수주 모멘텀으로 신고가 근접. 눌림목 매수세 견조.",
        supply="거래대금 급증(20일 평균 2.6배). 상승일 거래 집중 = 매집 우위.",
        finance="PER 30배대의 성장주 밸류. 수주잔고 기반 이익 가시성 높음.",
        industry="HBM 본더 핵심 벤더. 전방 capex 확대의 직접 수혜.",
        news="HBM 본더 수주 증가와 전방 capex 기대가 긍정적."),
    "247540": dict(
        name="에코프로비엠", price=168000, sector="2차전지", rec="BUY", buy_score=7, period="중기", ret=13, loss=7,
        tech="낙폭과대 후 기관 순매수 전환. 이평선 수렴 후 반등 시도.",
        supply="바닥권 거래량 증가. 하락일 대비 상승일 거래 우위로 전환 초기.",
        finance="업황 부진으로 PER 변동성 큼. 중장기 성장성엔 프리미엄.",
        industry="양극재 국내 선두. 전기차 캐즘 구간이나 업황 바닥 신호 포착.",
        news="2차전지 업황 바닥 통과 신호가 일부 지표에서 포착."),
    "005380": dict(
        name="현대차", price=245000, sector="자동차", rec="HOLD", buy_score=5, period="중기", ret=9, loss=5,
        tech="단기 급등 후 과열 구간. 20일선까지 눌림목 형성 가능.",
        supply="차익실현 매물 출회. 거래량 증가하나 상·하락 혼조.",
        finance="PER 5배대 저평가·고배당. 이익 체력 견조하나 성장률 둔화.",
        industry="글로벌 완성차 상위. 전동화·하이브리드 믹스가 관건.",
        news="실적은 양호하나 환율·금리 변수로 방향성은 중립."),
    "035720": dict(
        name="카카오", price=47850, sector="서비스/인터넷", rec="HOLD", buy_score=5, period="단기", ret=8, loss=5,
        tech="20일선 부근 등락 반복. 방향성 불명확.",
        supply="거래 한산, 뚜렷한 주체 없음. 관망 구간.",
        finance="PER 부담 구간. 신사업 수익성 개선이 재평가 조건.",
        industry="플랫폼 규제·경쟁 심화. 뚜렷한 성장 촉매 부재.",
        news="신사업 모멘텀이 약화되며 뚜렷한 촉매가 부재."),
    "105560": dict(
        name="KB금융", price=76300, sector="금융", rec="PASS", buy_score=3, period="단기", ret=7, loss=5,
        tech="거래량 한산, 모멘텀 부재. 박스권 하단 부근.",
        supply="수급 공백. 배당 시즌 외 관심 저조.",
        finance="PER 5배 미만·고배당의 전형적 밸류주. 성장성은 제한적.",
        industry="대형 금융지주. 금리 방향과 정책 변수에 민감.",
        news="밸류 매력은 있으나 단기 촉매가 보이지 않음."),
    "068270": dict(
        name="셀트리온", price=187000, sector="바이오", rec="PASS", buy_score=2, period="단기", ret=7, loss=7,
        tech="이평선 정배열 붕괴 + 수급 이탈. 추세 훼손.",
        supply="기관·외국인 순매도 추정. 거래량 감소 속 하락.",
        finance="PER 고평가 논란. 합병 이후 이익 정상화 확인 필요.",
        industry="바이오시밀러 선두이나 섹터 투자심리 악화.",
        news="바이오 섹터 투자심리 악화로 반등 동력 약함."),
}

_DEFAULT_PROFILE = dict(
    name="", price=70000, sector="기타", rec="BUY", buy_score=7, period="중기", ret=12, loss=6,
    tech="20일선 위 거래량 급등, 매수 신호 감지.",
    supply="거래량 증가로 관심 유입 추정.",
    finance="밸류·이익 지표는 중립 수준.",
    industry="해당 섹터 평균 수준의 경쟁 위치.",
    news="실적 개선 기대감, 수급 유입.")


def mock_profile(ticker: str) -> dict:
    """Tier 0 mock 프로필 반환 (없으면 기본값)."""
    prof = dict(_DEFAULT_PROFILE)
    prof.update(_PROFILES.get(ticker, {}))
    if not prof.get("name"):
        prof["name"] = ticker
    return prof


# ── 순수 파이썬 기술적 지표 (pandas 비의존) ─────────────────────────────
def _sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _rsi(closes: list[float], period: int = 14) -> float | None:
    """표준 RSI(14). 데이터 부족 시 None."""
    if len(closes) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def _obv_direction(closes: list[float], volumes: list[float], lookback: int = 10) -> str:
    """최근 OBV 방향으로 매집/분산 판단."""
    if len(closes) < lookback + 1:
        return "중립"
    obv = 0.0
    for i in range(-lookback, 0):
        if closes[i] > closes[i - 1]:
            obv += volumes[i]
        elif closes[i] < closes[i - 1]:
            obv -= volumes[i]
    if obv > 0:
        return "매집 우위"
    if obv < 0:
        return "분산 우위"
    return "중립"


def _supply_proxy(closes: list[float], volumes: list[float]) -> dict:
    """
    거래량 파생 수급 프록시.

    기관/외국인/개인 세부 순매수는 KRX 로그인이 필요해 가져올 수 없으므로,
    '실제 거래량'에서 매수·매도 우위를 추정합니다(정직한 대체 지표).
    """
    n = min(5, len(closes) - 1)
    up_vol = down_vol = 0.0
    for i in range(-n, 0):
        if closes[i] >= closes[i - 1]:
            up_vol += volumes[i]
        else:
            down_vol += volumes[i]
    ratio = round(up_vol / down_vol, 1) if down_vol else None
    return {
        "up_down_vol_ratio": ratio,       # 상승일/하락일 거래량 비 (>1 = 매수 우위)
        "obv": _obv_direction(closes, volumes),
    }


# ── Tier 1: yfinance 실데이터 ──────────────────────────────────────────
def _fetch_real(ticker: str) -> dict | None:
    """yfinance로 실데이터 조회. 미설치·실패·데이터없음 시 None."""
    try:
        import yfinance as yf
    except ImportError:
        log.info("  yfinance 미설치 (pip install yfinance) — mock 데이터 사용")
        return None

    for suffix in _KRX_SUFFIXES:
        symbol = f"{ticker}{suffix}"
        try:
            data = _fetch_symbol(yf, ticker, symbol)
        except Exception as e:  # noqa: BLE001 — 네트워크/파싱 실패는 조용히 폴백
            log.warning("  yfinance 조회 실패(%s): %s", symbol, e)
            continue
        if data:
            log.info("  실데이터 연동 성공: %s (yfinance)", symbol)
            return data
    return None


def _num(row: dict, *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if value is not None:
            try:
                return float(str(value).replace(",", ""))
            except ValueError:
                continue
    return None


def _date_key(item) -> str:
    return str(item[0])


def _fetch_kospi_kosdaq(ticker: str) -> dict | None:
    """Fetch Korean market data through the optional kospi_kosdaq server module."""

    try:
        import kospi_kosdaq_stock_server as server  # type: ignore[import-not-found]
    except ImportError:
        log.info("  kospi_kosdaq_stock_server 미설치 — 다음 데이터 소스로 폴백")
        return None

    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=120)).strftime("%Y%m%d")
    try:
        raw = server.get_stock_ohlcv(start_date, end_date, ticker)
    except Exception as exc:  # noqa: BLE001
        log.warning("  kospi_kosdaq OHLCV 조회 실패(%s): %s", ticker, exc)
        return None
    if not isinstance(raw, dict) or not raw or "error" in raw:
        return None

    rows = []
    for _, row in sorted(raw.items(), key=_date_key):
        if not isinstance(row, dict):
            continue
        close = _num(row, "Close", "close", "종가")
        volume = _num(row, "Volume", "volume", "거래량")
        if close is not None:
            rows.append((close, volume or 0.0))
    if len(rows) < 2:
        return None

    closes = [close for close, _ in rows]
    volumes = [volume for _, volume in rows]
    price = closes[-1]
    ma5, ma20 = _sma(closes, 5), _sma(closes, 20)
    vol_sma20 = _sma(volumes, 20)
    vol_ratio = round(volumes[-1] / vol_sma20, 1) if vol_sma20 else None
    supply = _supply_proxy(closes, volumes)

    latest_flow = {}
    try:
        flow = server.get_stock_trading_volume(start_date, end_date, ticker)
        if isinstance(flow, dict) and flow and "error" not in flow:
            _, latest = sorted(flow.items(), key=_date_key)[-1]
            if isinstance(latest, dict):
                latest_flow = latest
    except Exception as exc:  # noqa: BLE001
        log.warning("  kospi_kosdaq 투자자별 수급 조회 실패(%s): %s", ticker, exc)

    if latest_flow:
        supply["investor_flow_available"] = True
        supply["latest_investor_flow"] = latest_flow
    else:
        supply["investor_flow_available"] = False

    prof = mock_profile(ticker)
    return {
        "source": "kospi_kosdaq",
        "ticker": ticker,
        "name": prof["name"],
        "current_price": int(round(price)),
        "sector": prof["sector"],
        "industry": prof.get("industry", ""),
        "ma5": ma5, "ma20": ma20, "rsi": _rsi(closes),
        "vol_ratio": vol_ratio,
        "ret_1d": round((closes[-1] / closes[-2] - 1) * 100, 2),
        "price_vs_ma20": round((price / ma20 - 1) * 100, 1) if ma20 else None,
        "supply": supply,
        "finance": prof["finance"],
        "news": prof["news"],
    }


def _fetch_symbol(yf, ticker: str, symbol: str) -> dict | None:
    t = yf.Ticker(symbol)

    # 시장-접미사 일치 검증: 코스닥 종목을 .KS로 조회하면 메타데이터가 깨짐 → 다음 접미사로
    expected = _EXCHANGE_BY_SUFFIX.get(symbol[len(ticker):])
    try:
        exchange = t.fast_info.get("exchange")
    except Exception:  # noqa: BLE001 — exchange 확인 불가 시 기존 동작 유지
        exchange = None
    if exchange and expected and exchange != expected:
        log.info("  %s: 시장 불일치(exchange=%s) — 다른 접미사 재시도", symbol, exchange)
        return None

    hist = t.history(period="3mo")
    if hist is None or hist.empty:
        return None
    hist = hist.dropna(subset=["Close"])
    if len(hist) < 2:
        return None

    closes = [float(x) for x in hist["Close"].tolist()]
    volumes = [float(x) for x in hist["Volume"].tolist()]

    # 현재가: fast_info 우선(당일 미체결 행 회피), 없으면 마지막 종가
    price = None
    try:
        price = float(t.fast_info.get("lastPrice"))
    except Exception:  # noqa: BLE001
        price = None
    if not price:
        price = closes[-1]

    ma5, ma20 = _sma(closes, 5), _sma(closes, 20)
    rsi = _rsi(closes)
    vol_sma20 = _sma(volumes, 20)
    vol_ratio = round(volumes[-1] / vol_sma20, 1) if vol_sma20 else None
    ret_1d = round((closes[-1] / closes[-2] - 1) * 100, 2) if len(closes) >= 2 else 0.0
    supply = _supply_proxy(closes, volumes)

    info = {}
    try:
        info = t.info or {}
    except Exception:  # noqa: BLE001
        info = {}

    finance = _extract_finance(t, info)
    news = _extract_news(t)

    return {
        "source": "yfinance",
        "ticker": ticker,
        "name": info.get("shortName") or info.get("longName") or mock_profile(ticker)["name"],
        "current_price": int(round(price)),
        "sector": info.get("sector") or "기타",
        "industry": info.get("industry") or "",
        # 시가총액 (KRW) — screening.py --real 의 시총 필터에서 사용
        "market_cap": info["marketCap"] if isinstance(info.get("marketCap"), (int, float)) else None,
        # 기술
        "ma5": ma5, "ma20": ma20, "rsi": rsi,
        "vol_ratio": vol_ratio, "ret_1d": ret_1d,
        "price_vs_ma20": round((price / ma20 - 1) * 100, 1) if ma20 else None,
        # 수급 프록시
        "supply": supply,
        # 재무
        "finance": finance,
        # 뉴스
        "news": news,
    }


def _extract_finance(t, info: dict) -> dict:
    """재무 지표 추출. trailingPE 등이 비면 재무제표에서 역산."""
    per = info.get("trailingPE") or info.get("forwardPE")
    pbr = info.get("priceToBook")
    roe = info.get("returnOnEquity")
    margin = info.get("profitMargins")
    rev_growth = info.get("revenueGrowth")
    eps_growth = info.get("earningsGrowth")
    psr = info.get("priceToSalesTrailing12Months")
    mcap = info.get("marketCap")

    # PER/PBR 역산 (info가 비었을 때): PER=시총/순이익, PBR=시총/자본
    if (per is None or pbr is None) and mcap:
        try:
            fin = t.financials
            if per is None and fin is not None and "Net Income" in fin.index:
                ni = float(fin.loc["Net Income"].iloc[0])
                if ni:
                    per = round(mcap / ni, 1)
        except Exception:  # noqa: BLE001
            pass
        try:
            bs = t.balance_sheet
            if pbr is None and bs is not None:
                for key in ("Stockholders Equity", "Common Stock Equity",
                            "Total Equity Gross Minority Interest"):
                    if key in bs.index:
                        eq = float(bs.loc[key].iloc[0])
                        if eq:
                            pbr = round(mcap / eq, 2)
                        break
        except Exception:  # noqa: BLE001
            pass

    return {
        "per": round(per, 1) if isinstance(per, (int, float)) else None,
        "pbr": round(pbr, 2) if isinstance(pbr, (int, float)) else None,
        "roe": round(roe * 100, 1) if isinstance(roe, (int, float)) else None,
        "margin": round(margin * 100, 1) if isinstance(margin, (int, float)) else None,
        "rev_growth": round(rev_growth * 100, 1) if isinstance(rev_growth, (int, float)) else None,
        "eps_growth": round(eps_growth * 100, 1) if isinstance(eps_growth, (int, float)) else None,
        "psr": round(psr, 1) if isinstance(psr, (int, float)) else None,
    }


def _extract_news(t, limit: int = 5) -> list[str]:
    """yfinance .news에서 헤드라인 추출 (야후 뉴스, 영문·무료·무키)."""
    try:
        raw = t.news or []
    except Exception:  # noqa: BLE001
        return []
    titles = []
    for item in raw[:limit]:
        content = item.get("content") if isinstance(item, dict) else None
        title = (content or item).get("title") if isinstance(content or item, dict) else None
        if title:
            titles.append(title.strip())
    return titles


# ── 시장 지수 (KOSPI/KOSDAQ) ────────────────────────────────────────────
def _fetch_market_index_yfinance() -> dict | None:
    """KOSPI(^KS11)/KOSDAQ(^KQ11) 20거래일 수익률. 실패 시 None."""
    try:
        import yfinance as yf
    except ImportError:
        return None
    out = {}
    for name, sym in (("KOSPI", "^KS11"), ("KOSDAQ", "^KQ11")):
        try:
            h = yf.Ticker(sym).history(period="1mo")
            h = h.dropna(subset=["Close"]) if h is not None else None
            if h is None or len(h) < 2:
                continue
            closes = [float(x) for x in h["Close"].tolist()]
            out[name] = {
                "last": round(closes[-1], 1),
                "ret_20d": round((closes[-1] / closes[0] - 1) * 100, 1),
            }
        except Exception:  # noqa: BLE001
            continue
    return out or None


def _fetch_market_index_kospi_kosdaq() -> dict | None:
    """KOSPI/KOSDAQ index data via optional kospi_kosdaq server module."""

    try:
        import kospi_kosdaq_stock_server as server  # type: ignore[import-not-found]
    except ImportError:
        return None
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=45)).strftime("%Y%m%d")
    out = {}
    for name, ticker in (("KOSPI", "1001"), ("KOSDAQ", "2001")):
        try:
            raw = server.get_index_ohlcv(start_date, end_date, ticker)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(raw, dict) or not raw or "error" in raw:
            continue
        closes = []
        for _, row in sorted(raw.items(), key=_date_key):
            if isinstance(row, dict):
                close = _num(row, "Close", "close", "종가")
                if close is not None:
                    closes.append(close)
        if len(closes) >= 2:
            out[name] = {
                "last": round(closes[-1], 1),
                "ret_20d": round((closes[-1] / closes[0] - 1) * 100, 1),
            }
    return out or None


def fetch_market_index() -> dict | None:
    """Return market index data according to LECTURE_DATA_MODE."""

    from runtime_config import load_runtime_config

    cfg = load_runtime_config()
    if cfg.data_mode == "mock":
        return None
    if cfg.data_mode == "kospi_kosdaq":
        return _fetch_market_index_kospi_kosdaq()
    if cfg.data_mode == "yfinance":
        return _fetch_market_index_yfinance()
    if "kospi_kosdaq" in cfg.research_tools and cfg.tool_ready.get("kospi_kosdaq"):
        return _fetch_market_index_kospi_kosdaq() or _fetch_market_index_yfinance()
    return _fetch_market_index_yfinance()


# ── 공개 단일 접점 ──────────────────────────────────────────────────────
def _fetch_mock(ticker: str) -> dict:
    prof = mock_profile(ticker)
    return {
        "source": "mock",
        "ticker": ticker,
        "name": prof["name"],
        "current_price": prof["price"],
        "sector": prof["sector"],
        "industry": prof["industry"],
        "tech": prof["tech"],
        "supply": prof["supply"],
        "finance": prof["finance"],
        "news": prof["news"],
        # mock 판단 기준값 (실데이터엔 없음 — 전략 단계에서 규칙/LLM이 산출)
        "rec": prof["rec"], "buy_score": prof["buy_score"],
        "ret": prof["ret"], "loss": prof["loss"], "period": prof["period"],
    }


def fetch_stock_data(ticker: str) -> dict:
    """
    종목 원천 데이터 반환 (실데이터 → mock 폴백).

    analysis.py는 이 함수 하나만 호출합니다. 반환 dict의 source 키로
    실데이터/모의 여부를 구분할 수 있습니다.
    """
    from runtime_config import load_runtime_config

    cfg = load_runtime_config()
    if cfg.data_mode == "mock":
        return _fetch_mock(ticker)
    if cfg.data_mode == "kospi_kosdaq":
        return _fetch_kospi_kosdaq(ticker) or _fetch_mock(ticker)
    if cfg.data_mode == "yfinance":
        return _fetch_real(ticker) or _fetch_mock(ticker)
    if "kospi_kosdaq" in cfg.research_tools and cfg.tool_ready.get("kospi_kosdaq"):
        return _fetch_kospi_kosdaq(ticker) or _fetch_real(ticker) or _fetch_mock(ticker)
    return _fetch_real(ticker) or _fetch_mock(ticker)
