"""Optional research API helpers for advanced lecture-prism profiles.

The default pipeline does not require these tools. They only run when the
student provides API keys in `.env` and selects a research-oriented profile.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

PERPLEXITY_SONAR_URL = "https://api.perplexity.ai/v1/sonar"
FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v2/scrape"


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str],
               timeout: float) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - official user-configured APIs
        text = response.read().decode("utf-8")
    return json.loads(text) if text else {}


def perplexity_query(query: str, *, timeout: float = 30.0) -> dict[str, Any]:
    """Ask Perplexity Sonar for current market context."""

    api_key = os.getenv("PERPLEXITY_API_KEY")
    if not api_key:
        return {}
    payload = {
        "model": os.getenv("PERPLEXITY_MODEL", "sonar-pro"),
        "messages": [{"role": "user", "content": query}],
        "web_search_options": {"search_mode": "web"},
    }
    try:
        response = _post_json(
            PERPLEXITY_SONAR_URL,
            payload,
            {"Authorization": f"Bearer {api_key}"},
            timeout,
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        log.warning("Perplexity 조회 실패: %s", exc)
        return {}

    choices = response.get("choices") or []
    content = ""
    if choices and isinstance(choices[0], dict):
        message = choices[0].get("message") or {}
        content = message.get("content", "")
    return {
        "content": content,
        "citations": response.get("citations") or [],
        "search_results": response.get("search_results") or [],
    }


def firecrawl_scrape(url: str, *, timeout: float = 30.0) -> str:
    """Scrape a page as markdown through Firecrawl."""

    api_key = os.getenv("FIRECRAWL_API_KEY")
    if not api_key:
        return ""
    payload = {
        "url": url,
        "formats": ["markdown"],
        "onlyMainContent": True,
        "removeBase64Images": True,
        "blockAds": True,
        "timeout": int(timeout * 1000),
    }
    try:
        response = _post_json(
            FIRECRAWL_SCRAPE_URL,
            payload,
            {"Authorization": f"Bearer {api_key}"},
            timeout,
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        log.warning("Firecrawl 스크랩 실패: %s", exc)
        return ""
    data = response.get("data") if isinstance(response, dict) else {}
    if not isinstance(data, dict):
        return ""
    return data.get("markdown") or data.get("summary") or ""


def build_research_context(ticker: str, company_name: str, sector: str = "") -> str:
    """Build optional current-news context for `analysis.py`.

    The returned string is deliberately compact so it can be appended to the
    existing lightweight news prompt without turning lecture-prism into the full
    PRISM report generator.
    """

    parts = []
    naver_url = f"https://finance.naver.com/item/news.naver?code={ticker}"
    scraped = firecrawl_scrape(naver_url)
    if scraped:
        parts.append("[Firecrawl: 네이버 금융 뉴스]\n" + scraped[:2500])

    query = (
        f"오늘 기준 {company_name}({ticker}) 한국 주식의 주요 뉴스, 섹터 동향, "
        f"투자자가 확인해야 할 리스크를 한국어로 요약해줘. 섹터: {sector or '알 수 없음'}."
    )
    perplexity = perplexity_query(query)
    if perplexity.get("content"):
        citations = perplexity.get("citations") or []
        citation_text = "\n".join(f"- {url}" for url in citations[:5])
        parts.append("[Perplexity: 최신 리서치]\n" + perplexity["content"][:2500])
        if citation_text:
            parts.append("[Perplexity citations]\n" + citation_text)

    return "\n\n".join(parts)
