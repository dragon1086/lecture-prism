from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PrismCoreFoundationContractTest(unittest.TestCase):
    @staticmethod
    def _section(text: str, heading: str) -> str:
        start = text.index(heading) + len(heading)
        next_heading = text.find("\n## ", start)
        return text[start:] if next_heading < 0 else text[start:next_heading]

    def test_runtime_docs_distinguish_stateful_classroom_from_backtest(self):
        text = (ROOT / "docs/runtime-profiles.md").read_text(encoding="utf-8")
        profile_section = self._section(
            text, "## 3. mock 첫 실행과 classroom 상태 재생"
        )
        self.assertIn("classroom", profile_section)
        self.assertIn("PaperBroker", profile_section)
        self.assertRegex(
            profile_section,
            r"backtest.{0,120}legacy.{0,120}_simulate_trade",
        )
        self.assertIn("CREATED → PREVIEWED → SUBMITTED → ACCEPTED", profile_section)
        self.assertIn("ACCEPTED는 체결이 아닙니다", profile_section)

    def test_runtime_docs_scope_high_water_and_unknown_mutations(self):
        text = (ROOT / "docs/runtime-profiles.md").read_text(encoding="utf-8")
        profile_section = self._section(
            text, "## 3. mock 첫 실행과 classroom 상태 재생"
        )
        self.assertRegex(
            profile_section,
            r"포트폴리오 전체.{0,80}유효한 유한 quote.{0,120}청산 write 전에",
        )
        self.assertRegex(
            profile_section,
            r"누락.{0,30}잘못된 quote.{0,100}(건너뛰|fail-closed)",
        )
        self.assertRegex(
            profile_section,
            r"UNKNOWN.{0,160}(주문|order).{0,60}fill.{0,60}청산",
        )
        self.assertIn("high-water 관찰은 저장될 수", profile_section)
        self.assertIn("evidence-based reconciliation", profile_section)

    def test_architecture_scopes_fallback_and_follow_on_boundaries(self):
        text = (ROOT / "docs/architecture.md").read_text(encoding="utf-8")
        options = self._section(text, "## 4. 옵션별 전체 아키텍처")
        self.assertIn("mock", options)
        self.assertIn("선택 분석 연동", options)
        self.assertIn("paper/live", options)
        self.assertIn("fail-closed", options)

        follow_ons = self._section(
            text, "## 11. 아직 연결 완료로 말하면 안 되는 것"
        )
        for incomplete_item in (
            "분석 evidence와 OAuth",
            "KIS",
            "Toss WTS",
            "dashboard.py",
        ):
            self.assertRegex(
                follow_ons,
                rf"- 미완료 — [^\n]*{re.escape(incomplete_item)}",
            )
        self.assertIn("미완료인 후속 과제", follow_ons)
        self.assertNotIn("paper/live용 market provider fail-closed", follow_ons)
        self.assertNotIn("시장 regime과 screening 결합", follow_ons)
        self.assertNotRegex(follow_ons, r"(?:KIS|Toss).{0,30}(?:완성된|운영 준비 완료)")
        self.assertNotRegex(follow_ons, r"backtest.{0,40}PaperBroker")
        self.assertIn("core table 시각화는 미완료", follow_ons)

    def test_part3_uses_text_prompts_without_shell_or_live_cli(self):
        texts = [
            (ROOT / "lecture/exercises/part3_실습가이드.md").read_text(
                encoding="utf-8"
            ),
            (ROOT / "docs/runtime-profiles.md").read_text(encoding="utf-8"),
        ]
        for text in texts:
            fences = re.findall(r"```([^\n]*)\n(.*?)```", text, re.DOTALL)
            self.assertTrue(fences)
            self.assertFalse(
                any(
                    language.strip().lower()
                    in {"bash", "sh", "shell", "zsh", "console"}
                    for language, _ in fences
                )
            )
            self.assertNotIn("trading.py --live", text)
            self.assertNotRegex(
                text,
                r"trading\.py[^\n]{0,50}live 요청[^\n]{0,50}(?:실행|결과)",
            )

    def test_live_safety_prompt_requires_sanitized_mocked_unit_test(self):
        text = (ROOT / "lecture/exercises/part3_실습가이드.md").read_text(
            encoding="utf-8"
        )
        safety_section = self._section(text, "### live 기본 차단 확인")
        prompt_blocks = re.findall(
            r"```text\n(.*?)```", safety_section, re.DOTALL
        )
        self.assertEqual(len(prompt_blocks), 1)
        prompt = prompt_blocks[0]
        for required in (
            "격리 단위 테스트",
            "LECTURE_* enable/allow 변수를 모두 0",
            "broker factory",
            "place_order",
            "호출되면 실패",
            "계좌·config 파일을 읽지",
            "live_blocked",
        ):
            self.assertIn(required, prompt)

    def test_docs_reject_contradictory_completion_claims(self):
        combined = "\n".join(
            (ROOT / path).read_text(encoding="utf-8")
            for path in (
                "docs/architecture.md",
                "docs/runtime-profiles.md",
                "lecture/exercises/part3_실습가이드.md",
            )
        )
        for contradiction in (
            r"KIS[^.\n]{0,100}full lifecycle(?:이|은)? (?:완료됐|완성됐)",
            r"Toss[^.\n]{0,100}(?:adapter|어댑터)(?:가|는)? (?:완료됐|완성됐)",
            r"backtest[^.\n]{0,80}(?:상태형 )?PaperBroker(?:를|가) (?:사용|쓴)",
            r"dashboard[^.\n]{0,100}core table 시각화(?:가|는)? 완료",
        ):
            self.assertNotRegex(combined, contradiction)

    def test_course_docs_explain_regime_screening_as_one_safety_contract(self):
        paths = (
            "docs/architecture.md",
            "docs/runtime-profiles.md",
            "lecture/exercises/part3_실습가이드.md",
            "lecture/exercises/part4_실습가이드.md",
        )
        documents = {
            path: (ROOT / path).read_text(encoding="utf-8") for path in paths
        }
        combined = "\n".join(documents.values())

        for required in (
            "strong_bull",
            "strong_bear",
            "KR 120/60",
            "US 200/50",
            "VIX",
            "paper/live",
            "fail-closed",
            "미래 데이터",
            "수익 보장 아님",
            "ScreeningStrategy",
        ):
            self.assertIn(required, combined)
        self.assertIn(
            "provider validation → regime → screening → analysis gate → sizing → cycle",
            combined,
        )
        self.assertRegex(
            combined,
            r"같은 후보.{0,100}bull.{0,100}(통과|admit).{0,100}bear.{0,100}(거절|reject)",
        )
        self.assertRegex(
            combined,
            r"mock/real_data.{0,160}폴백.{0,160}paper/live.{0,160}fail-closed",
        )
        self.assertRegex(
            combined,
            r"classroom.{0,200}regime.{0,160}candidate.{0,160}order.{0,160}fill",
        )
        part4 = documents["lecture/exercises/part4_실습가이드.md"]
        self.assertRegex(part4, r"트랙 A[\s\S]{0,500}ScreeningStrategy")
        for track in ("Track B", "Track C", "Track D"):
            self.assertIn(track, part4)

        for path, text in documents.items():
            with self.subTest(path=path):
                self.assertNotRegex(
                    text,
                    r"```(?:bash|sh|shell|zsh|console|powershell)\b",
                )

        for forbidden_claim in (
            r"KIS.{0,100}full lifecycle.{0,40}(완료됐|완성됐|운영 준비 완료)",
            r"Toss WTS.{0,100}(adapter|어댑터).{0,40}(완료됐|완성됐|운영 준비 완료)",
            r"OAuth.{0,100}evidence.{0,40}(완료됐습니다|완료되었습니다|연결됐습니다)",
            r"대시보드.{0,100}(regime|candidate|order|fill).{0,40}(완료됐|통합됐)",
        ):
            self.assertNotRegex(combined, forbidden_claim)


if __name__ == "__main__":
    unittest.main()
