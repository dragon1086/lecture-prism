import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECK_ROOT = ROOT / "강의자료"
SOURCE_ROOT = DECK_ROOT / "deck-src"


class Part4DeckContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(
            (SOURCE_ROOT / "deck-manifest.json").read_text(encoding="utf-8")
        )
        files = [
            SOURCE_ROOT / module["file"]
            for module in cls.manifest["decks"]["part4"]["modules"]
        ]
        cls.sources = "\n".join(path.read_text(encoding="utf-8") for path in files)
        cls.assembled = (DECK_ROOT / "파트4_슬라이드.html").read_text(encoding="utf-8")

    def test_slide_four_is_the_shared_read_only_kis_enrichment_lab(self):
        slide = self._slide("P4-S04")
        for phrase in (
            "공통 실습 P4-KIS",
            "KIS real",
            "005930",
            "기관·외국인·개인",
            "가장 최근 영업일",
            "수급 섹션만",
            "simulation",
            "주문·취소·정정·잔고·계좌",
            "0회",
        ):
            self.assertIn(phrase, slide)

        rows = [
            item
            for module in self.manifest["decks"]["part4"]["modules"]
            for item in module["slides"]
        ]
        row = next(item for item in rows if item["id"] == "P4-S04")
        self.assertEqual("P4-KIS", row["promptId"])
        self.assertIn("KIS 실제 수급", row["title"])
        self.assertIn('data-slide-id="P4-S04"', self.assembled)
        self.assertIn("KIS 실제 수급", self.assembled)

    @classmethod
    def _slide(cls, slide_id: str) -> str:
        match = re.search(
            rf"<!-- {re.escape(slide_id)}\b.*?<section\b.*?</section>",
            cls.sources,
            flags=re.S,
        )
        if match is None:
            raise AssertionError(f"missing slide: {slide_id}")
        return match.group(0)


if __name__ == "__main__":
    unittest.main()
