"""DART 회사별 RSS를 읽고 분석 입력 전 품질을 검토합니다."""

from __future__ import annotations

import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable


DEFAULT_DART_RSS_URL = (
    "https://dart.fss.or.kr/api/companyRSS.xml?crpCd=00126380"
)
DEFAULT_FIXTURE = Path("lecture/fixtures/dart-samsung-company-rss.xml")
_ERROR_MARKERS = ("service unavailable", "access denied", "bad gateway")
_PERSONAL_HOLDING = "임원ㆍ주요주주특정증권등소유상황보고서"
_RELEVANT_TITLE_MARKERS = (
    "사업보고서",
    "분기보고서",
    "반기보고서",
    "유상증자",
    "무상증자",
    "전환사채",
    "자기주식",
    "주식소각",
    "최대주주",
    "합병",
    "분할",
)


def parse_company_rss(xml_data: bytes | str, *, max_items: int = 10) -> list[dict]:
    """RSS에서 title·link·pubDate만 최대 max_items건 읽습니다."""
    root = ET.fromstring(xml_data)
    records = []
    for item in root.findall("./channel/item")[:max_items]:
        records.append(
            {
                "title": (item.findtext("title") or "").strip(),
                "link": (item.findtext("link") or "").strip(),
                "pubDate": (item.findtext("pubDate") or "").strip(),
            }
        )
    return records


def load_company_rss(
    url: str,
    fixture_path: str | Path,
    *,
    timeout: int = 5,
    opener: Callable = urllib.request.urlopen,
) -> dict:
    """실제 RSS를 한 번만 요청하고 실패하면 저장된 fixture를 읽습니다."""
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "lecture-prism-instructor-demo/1.0"},
    )
    try:
        response = opener(request, timeout=timeout)
        try:
            payload = response.read()
        finally:
            close = getattr(response, "close", None)
            if close:
                close()
        records = parse_company_rss(payload)
        return {"source": "actual_rss", "error": "", "records": records}
    except Exception as exc:  # noqa: BLE001 - 한 번 실패하면 fixture로 재현
        payload = Path(fixture_path).read_bytes()
        return {
            "source": "fixture",
            "error": str(exc),
            "records": parse_company_rss(payload),
        }


def review_disclosures(
    records: list[dict],
    *,
    target_company: str,
    as_of: datetime | None = None,
    valid_days: int = 10,
    confirmed_claims: dict[str, str] | None = None,
) -> dict:
    """공시 목록을 포함·제외·검토 필요로 분류합니다."""
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    claims = confirmed_claims or {}
    reviewed = []
    llm_input = []
    seen = set()

    for record in records[:10]:
        title = str(record.get("title") or "").strip()
        link = str(record.get("link") or "").strip()
        pub_date = str(record.get("pubDate") or "").strip()
        status, reason = _review_one(
            title,
            link,
            pub_date,
            target_company=target_company,
            now=now,
            valid_days=valid_days,
            seen=seen,
            confirmed_claim=claims.get(link, "").strip(),
        )
        item = {**record, "status": status, "reason": reason}
        reviewed.append(item)
        if status == "include" and len(llm_input) < 3:
            llm_input.append(
                {
                    "title": title,
                    "link": link,
                    "pubDate": pub_date,
                    "confirmed_claim": claims[link].strip()[:300],
                }
            )

    counts = {
        name: sum(item["status"] == name for item in reviewed)
        for name in ("include", "exclude", "needs_review")
    }
    return {"counts": counts, "items": reviewed, "llm_input": llm_input}


def _review_one(
    title: str,
    link: str,
    pub_date: str,
    *,
    target_company: str,
    now: datetime,
    valid_days: int,
    seen: set,
    confirmed_claim: str,
) -> tuple[str, str]:
    combined = f"{title} {link} {pub_date}".lower()
    if any(marker in combined for marker in _ERROR_MARKERS):
        return "exclude", "통신 오류 문구"
    if target_company not in title:
        return "exclude", "대상 회사 불일치"
    if not link.startswith("https://dart.fss.or.kr/") or not pub_date:
        return "exclude", "공식 출처·작성일 없음"
    try:
        published = parsedate_to_datetime(pub_date)
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return "exclude", "작성일 형식 오류"
    if (now - published).days > valid_days:
        return "exclude", "유효기간 지남"
    if _PERSONAL_HOLDING in title:
        return "exclude", "임원 개인 사건"

    normalized = re.sub(r"\[기재정정\]", "", title)
    normalized = re.sub(r"\s+", "", normalized)
    duplicate_key = (normalized, link)
    if duplicate_key in seen:
        return "exclude", "중복"
    seen.add(duplicate_key)

    if not any(marker in title for marker in _RELEVANT_TITLE_MARKERS):
        return "exclude", "분석 질문과 무관"
    if not confirmed_claim:
        return "needs_review", "원문 확인 필요"
    return "include", "원문에서 확인한 주장 있음"


def main() -> None:
    loaded = load_company_rss(DEFAULT_DART_RSS_URL, DEFAULT_FIXTURE)
    result = review_disclosures(
        loaded["records"],
        target_company="삼성전자",
    )
    print(
        json.dumps(
            {"source": loaded["source"], "error": loaded["error"], **result},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
