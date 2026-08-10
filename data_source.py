"""
data_source.py — 실데이터 연동 단일 접점 (무료·무로그인)

analysis.py가 6섹션 분석에 쓰는 원천 데이터를 이 파일 하나로 모읍니다.

런타임 폴백 설계:
  mock        : _PROFILES 더미 데이터 — 항상 동작, 키/설치 불필요
  yfinance    : 가격·거래량·재무·뉴스·지수 실데이터

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

import copy
import logging

log = logging.getLogger(__name__)

# 야후 파이낸스 심볼 접미사: 코스피 .KS / 코스닥 .KQ
# 6자리 종목코드 → 우선 .KS, 시장 불일치/데이터 없으면 .KQ 재시도.
_KRX_SUFFIXES = (".KS", ".KQ")

# 야후 exchange 코드 ↔ 접미사 매핑 (KSC=코스피, KOE=코스닥).
# 야후는 잘못된 접미사(예: 코스닥 종목의 .KS)도 같은 시세를 반환하지만
# 종목명·섹터 등 메타데이터가 깨지므로, 진짜 시장의 심볼만 채택합니다.
_EXCHANGE_BY_SUFFIX = {".KS": "KSC", ".KQ": "KOE"}

# 종목별 mock fixture (Tier 0). 실시간 사실을 흉내 내는 문장이 아니라,
# 고정된 가격·거래량·재무·뉴스 *시나리오*를 넣는다. analysis.py는 yfinance와
# 같은 규칙 템플릿과 점수 엔진으로 이 수치를 해석한다.
_FIXTURE_AS_OF = "2026-07-01 장 마감"
_FIXTURE_NOTICE = "교육용 고정 시나리오이며 현재 시장 정보가 아닙니다."
_PROFILES: dict[str, dict] = {
    "005930": dict(
        name="삼성전자", price=71200, sector="전기전자/반도체", industry="반도체",
        ma5=69900, ma20=68500, rsi=62.8, vol_ratio=1.8, ret_1d=2.1,
        supply={"up_down_vol_ratio": 2.1, "obv": "매집 우위"},
        finance={"per": 13.2, "pbr": 1.1, "roe": 8.4, "margin": 7.5,
                 "rev_growth": None, "eps_growth": 18.0},
        industry_context="메모리 업황 회복과 HBM 수요 확대를 가정한 경쟁력 우위 시나리오.",
        news=["HBM 공급 확대 기대가 투자심리를 개선한다는 가정",
              "파운드리 수주 회복이 촉매로 작용한다는 가정"]),
    "000660": dict(
        name="SK하이닉스", price=178500, sector="전기전자/반도체", industry="반도체",
        ma5=175000, ma20=168000, rsi=64.1, vol_ratio=2.1, ret_1d=1.7,
        supply={"up_down_vol_ratio": 3.4, "obv": "매집 우위"},
        finance={"per": 9.8, "pbr": 2.1, "roe": 18.0, "margin": 18.5,
                 "rev_growth": None, "eps_growth": 35.0},
        industry_context="AI 메모리 수요 확대로 HBM 공급이 타이트해진다는 업황 시나리오.",
        news=["HBM3E 공급 확대가 이어진다는 가정", "AI 서버 투자 증가가 수요를 지지한다는 가정"]),
    "035420": dict(
        name="NAVER", price=215000, sector="서비스/인터넷", industry="인터넷 콘텐츠·정보",
        ma5=214000, ma20=208000, rsi=59.2, vol_ratio=1.2, ret_1d=0.8,
        supply={"up_down_vol_ratio": 0.9, "obv": "중립"},
        finance={"per": 22.0, "pbr": 1.4, "roe": 8.0, "margin": 9.2,
                 "rev_growth": None, "eps_growth": 6.0},
        industry_context="AI 검색과 광고 회복이 재평가 촉매가 된다는 플랫폼 성장 시나리오.",
        news=["AI 검색 기능의 이용자 전환이 확대된다는 가정", "광고·커머스 마진이 회복된다는 가정"]),
    "042700": dict(
        name="한미반도체", price=143000, sector="반도체장비", industry="반도체 장비",
        ma5=140000, ma20=135000, rsi=67.0, vol_ratio=2.0, ret_1d=2.8,
        supply={"up_down_vol_ratio": 0.8, "obv": "중립"},
        finance={"per": 31.0, "pbr": 4.5, "roe": 9.0, "margin": 14.0,
                 "rev_growth": None, "eps_growth": 22.0},
        industry_context="HBM 본더 장비 발주가 확대된다는 전방 투자 시나리오.",
        news=["후공정 장비 수주가 늘어난다는 가정", "메모리 capex 회복이 이어진다는 가정"]),
    "247540": dict(
        name="에코프로비엠", price=168000, sector="2차전지", industry="양극재",
        ma5=174000, ma20=171000, rsi=28.0, vol_ratio=1.8, ret_1d=1.2,
        supply={"up_down_vol_ratio": 1.1, "obv": "매집 우위"},
        finance={"per": None, "pbr": 2.0, "roe": 5.0, "margin": 3.0,
                 "rev_growth": None, "eps_growth": None},
        industry_context="전기차 수요 둔화 뒤 재고 조정이 마무리된다는 반등 시나리오.",
        news=["양극재 재고 조정이 마무리된다는 가정", "전방 수요의 저점 통과 신호가 나온다는 가정"]),
    "005380": dict(
        name="현대차", price=245000, sector="자동차", industry="자동차 제조",
        ma5=250000, ma20=248000, rsi=76.0, vol_ratio=1.6, ret_1d=-0.4,
        supply={"up_down_vol_ratio": 1.1, "obv": "매집 우위"},
        finance={"per": 5.2, "pbr": 0.7, "roe": 9.0, "margin": 8.0,
                 "rev_growth": None, "eps_growth": 4.0},
        industry_context="하이브리드 판매 비중 상승이 이익을 지지한다는 완성차 시나리오.",
        news=["환율이 실적에 우호적으로 작용한다는 가정", "금리 변동이 밸류에이션을 제한한다는 가정"]),
    "035720": dict(
        name="카카오", price=47850, sector="서비스/인터넷", industry="인터넷 콘텐츠·정보",
        ma5=48000, ma20=49000, rsi=29.0, vol_ratio=1.8, ret_1d=0.3,
        supply={"up_down_vol_ratio": 0.8, "obv": "중립"},
        finance={"per": 28.0, "pbr": 1.3, "roe": 4.0, "margin": 4.0,
                 "rev_growth": None, "eps_growth": None},
        industry_context="플랫폼 규제와 경쟁 심화 속 신사업 수익성 회복을 기다리는 시나리오.",
        news=["신사업의 수익화 시점이 지연된다는 가정", "규제 불확실성이 투자심리를 제약한다는 가정"]),
    "105560": dict(
        name="KB금융", price=76300, sector="금융", industry="은행",
        ma5=76000, ma20=78000, rsi=46.0, vol_ratio=0.8, ret_1d=-0.6,
        supply={"up_down_vol_ratio": 0.7, "obv": "분산 우위"},
        finance={"per": 4.8, "pbr": 0.5, "roe": 9.0, "margin": 19.0,
                 "rev_growth": -2.0, "eps_growth": -1.0},
        industry_context="금리 방향과 주주환원 정책이 주가를 좌우한다는 금융지주 시나리오.",
        news=["배당 시즌 외 수급이 약하다는 가정", "금리 인하 기대가 순이자마진을 제한한다는 가정"]),
    "068270": dict(
        name="셀트리온", price=187000, sector="바이오", industry="바이오시밀러",
        ma5=188000, ma20=192000, rsi=78.0, vol_ratio=0.9, ret_1d=-1.4,
        supply={"up_down_vol_ratio": 0.6, "obv": "분산 우위"},
        finance={"per": 35.0, "pbr": 2.6, "roe": 5.0, "margin": 10.0,
                 "rev_growth": None, "eps_growth": None},
        industry_context="합병 뒤 이익 정상화 확인이 필요한 바이오시밀러 시나리오.",
        news=["섹터 투자심리가 약화된다는 가정", "실적 정상화 확인 전까지 변동성이 크다는 가정"]),
}

_DEFAULT_PROFILE = dict(
    name="", price=70000, sector="기타", industry="기타",
    ma5=70400, ma20=69000, rsi=58.0, vol_ratio=1.2, ret_1d=0.5,
    supply={"up_down_vol_ratio": 0.9, "obv": "중립"},
    finance={"per": None, "pbr": None, "roe": 8.0, "margin": None,
             "rev_growth": None, "eps_growth": None},
    industry_context="해당 섹터 평균 수준의 경쟁 위치를 가정한 시나리오.",
    news=["실적 개선 기대감이 유입된다는 가정"])

_MOCK_MARKET_INDEX = {
    "source": "fixture",
    "as_of": _FIXTURE_AS_OF,
    "KOSPI": {"last": 2_835.4, "ret_20d": 2.4},
    "KOSDAQ": {"last": 764.8, "ret_20d": -1.1},
}


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


def fetch_market_index() -> dict | None:
    """Return market index data according to LECTURE_DATA_MODE."""

    from runtime_config import load_runtime_config

    cfg = load_runtime_config()
    if cfg.data_mode == "mock":
        return copy.deepcopy(_MOCK_MARKET_INDEX)
    return _fetch_market_index_yfinance()


def _fetch_kis_snapshot(ticker: str) -> dict:
    from brokers.kis import selected_kis_mode
    from kis_market_data import fetch_kis_snapshot

    return fetch_kis_snapshot(ticker, selected_kis_mode())


def _enrich_supply_with_kis(data: dict, ticker: str) -> dict:
    try:
        snapshot = _fetch_kis_snapshot(ticker)
    except Exception:  # noqa: BLE001 - optional enrichment falls back once
        log.warning("  KIS 수급 조회 실패 — 기존 거래량 프록시 유지")
        return data
    enriched = copy.deepcopy(data)
    enriched["supply"] = {
        "source": "kis",
        "environment": snapshot["environment"],
        "as_of": snapshot["as_of"],
        "institution_net_buy": snapshot["institution_net_buy"],
        "foreign_net_buy": snapshot["foreign_net_buy"],
        "individual_net_buy": snapshot["individual_net_buy"],
    }
    return enriched


# ── 공개 단일 접점 ──────────────────────────────────────────────────────
def _fetch_mock(ticker: str) -> dict:
    prof = mock_profile(ticker)
    ma20 = prof.get("ma20")
    price = prof["price"]
    return {
        "source": "mock",
        "evidence_kind": "fixture",
        "as_of": _FIXTURE_AS_OF,
        "notice": _FIXTURE_NOTICE,
        "ticker": ticker,
        "name": prof["name"],
        "current_price": price,
        "sector": prof["sector"],
        "industry": prof["industry"],
        "industry_context": prof["industry_context"],
        # yfinance 경로와 같은 입력 계약: 보고서 문장은 analysis.py가 이
        # 숫자/목록으로 만들어 내며, 사전 작성한 매수 의견을 사용하지 않는다.
        "ma5": prof["ma5"], "ma20": ma20, "rsi": prof["rsi"],
        "vol_ratio": prof["vol_ratio"], "ret_1d": prof["ret_1d"],
        "price_vs_ma20": round((price / ma20 - 1) * 100, 1) if ma20 else None,
        "supply": copy.deepcopy(prof["supply"]),
        "finance": copy.deepcopy(prof["finance"]),
        "news": list(prof["news"]),
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
    data = _fetch_real(ticker) or _fetch_mock(ticker)
    if data.get("source") == "yfinance" and cfg.supply_source == "kis":
        return _enrich_supply_with_kis(data, ticker)
    return data
