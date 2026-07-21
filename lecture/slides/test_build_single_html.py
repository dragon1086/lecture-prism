import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_single_html


class SingleHtmlBuildTest(unittest.TestCase):
    def test_readme_preview_is_a_live_tour_transition(self):
        source = build_single_html.SOURCE.read_text(encoding="utf-8")

        self.assertRegex(source, r"이제 실제 README를(?:<br>)?열어보겠습니다")
        self.assertIn("첫 번째 그림 · 전략에서 KIS 매수 주문까지", source)
        self.assertIn("두 번째 그림 · 시스템의 전체 흐름", source)
        self.assertIn("세 번째 그림 · 내 전략을 넣는 네 가지 트랙", source)
        self.assertIn("네 번째 그림 · 수업 뒤에도 자라는 나무 모종", source)
        self.assertIn("한 영역씩 수정·검증", source)
        self.assertIn("모의·실전 매수 주문 경로", source)
        self.assertIn("매수 주문 경로", source)
        self.assertIn("실계좌 주문은 기본 차단", source)

    def test_personal_and_prism_chronology_slides_are_present(self):
        source = build_single_html.SOURCE.read_text(encoding="utf-8")

        self.assertEqual(source.count('<section class="slide'), 26)
        self.assertIn("2018 · 투자 시작", source)
        self.assertIn("코로나 시기 · 잠깐의 수익", source)
        self.assertIn("2025.02 · MCP 공개", source)
        self.assertIn("2025.08 · 오픈소스와 실계좌", source)
        self.assertIn("2026.01 · 보수적인 프롬프트", source)
        self.assertIn("2026.05 · 짧은 보유 손실", source)
        self.assertIn("2026.06 · 10분 실시간 루프", source)
        self.assertIn("2026.07 · 급락장 방어", source)

    def test_open_source_repositories_are_linked_from_the_relevant_slides(self):
        source = build_single_html.SOURCE.read_text(encoding="utf-8")

        self.assertIn("https://github.com/dragon1086/prism-insight", source)
        self.assertIn(
            "https://github.com/dragon1086/kospi-kosdaq-stock-server", source
        )

    def test_portrait_and_routine_images_are_not_cropped(self):
        source = build_single_html.SOURCE.read_text(encoding="utf-8")

        self.assertRegex(
            source,
            r"\.media-card img \{[^}]*object-fit: contain;",
        )
        self.assertRegex(
            source,
            r"\.routine-image img \{[^}]*object-fit: contain;",
        )

    def test_operating_case_slides_include_the_requested_evidence_images(self):
        source = build_single_html.SOURCE.read_text(encoding="utf-8")

        for image_name in (
            "delay_message.png",
            "skip_message.png",
            "github_issue.png",
            "sell_message.png",
            "new_buy_message.png",
        ):
            self.assertIn(image_name, source)

        self.assertRegex(
            source,
            r"\.case-image img \{[^}]*object-fit: contain;",
        )

    def test_build_inlines_only_html_image_sources(self):
        output = build_single_html.build()
        html = output.read_text(encoding="utf-8")

        self.assertNotRegex(html, r'<img[^>]+src="(?!data:)')
        self.assertNotRegex(html, r'<link[^>]+href=')
        self.assertNotRegex(html, r'<script[^>]+src=')
        self.assertIn('src="${e}"', html)


if __name__ == "__main__":
    unittest.main()
