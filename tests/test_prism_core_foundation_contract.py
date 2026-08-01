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

        follow_ons = self._section(text, "## 11. 완료 증거와 남은 연결 범위")
        for completed_item in (
            "공식 Codex",
            "KIS 매수·매도",
            "Toss WTS 선택 어댑터",
        ):
            self.assertRegex(
                follow_ons,
                rf"- 완료 — [^\n]*{re.escape(completed_item)}",
            )
        for incomplete_item in ("dashboard.py",):
            self.assertRegex(
                follow_ons,
                rf"- 미완료 — [^\n]*{re.escape(incomplete_item)}",
            )
        self.assertNotIn("paper/live용 market provider fail-closed", follow_ons)
        self.assertNotIn("시장 regime과 screening 결합", follow_ons)
        self.assertNotRegex(follow_ons, r"Toss.{0,30}(?:완성된|운영 준비 완료)")
        self.assertNotRegex(follow_ons, r"backtest.{0,40}PaperBroker")
        self.assertIn("core table 시각화는 미완료", follow_ons)

    def test_part3_uses_text_prompts_without_shell_or_live_cli(self):
        texts = [
            (ROOT / "lecture/exercises/수강생_붙여넣기_프롬프트_파트3.md").read_text(
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

    def test_part3_prompts_keep_simulation_and_real_order_boundary(self):
        text = (ROOT / "lecture/exercises/수강생_붙여넣기_프롬프트_파트3.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("연습 데이터(mock)", text)
        self.assertIn("가상 체결(simulation)", text)
        self.assertIn("실제 주문·브로커·계좌·시크릿", text)
        self.assertNotIn("trading.py --live", text)

    def test_part4_operations_prompts_keep_the_safe_learning_boundary(self):
        text = (ROOT / "lecture/exercises/수강생_붙여넣기_프롬프트_파트4.md").read_text(
            encoding="utf-8"
        )
        for phrase in (
            "main.py",
            "연습 데이터와 실제 주문 없는 예행 실행",
            "미완성일 수 있음을",
            "실제 주문·브로커·계좌·시크릿",
            "내가 승인하기 전에는 코드 수정이나 예약 변경을 하지 마",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)
        self.assertNotIn("trading.py --live", text)

    def test_course_prompts_use_the_coaching_loop_at_the_right_stage(self):
        part3 = (
            ROOT / "lecture/exercises/수강생_붙여넣기_프롬프트_파트3.md"
        ).read_text(encoding="utf-8")
        part4 = (
            ROOT / "lecture/exercises/수강생_붙여넣기_프롬프트_파트4.md"
        ).read_text(encoding="utf-8")
        for text in (part3, part4):
            for phrase in ("질문한다", "예측한다", "실행한다", "증거", "회고한다"):
                with self.subTest(phrase=phrase):
                    self.assertIn(phrase, text)
        self.assertNotIn("북극성", part3)
        self.assertIn("북극성", part4)

    def test_part4_selection_and_scheduler_prompts_do_not_mutate_during_class(self):
        text = (
            ROOT / "lecture/exercises/수강생_붙여넣기_프롬프트_파트4.md"
        ).read_text(encoding="utf-8")
        selection = self._section(
            text, "## P4-02 · 하네스로 한 트랙과 파일만 고르기"
        )
        self.assertIn("아직 코드", selection)
        self.assertIn("수정하거나 읽지 말고, 실행도 하지 마", selection)
        self.assertNotIn("최소한으로 수정", selection)

        scheduler = self._section(
            text, "## P4-08 · 오전 1회·오후 1회 연습 배치 설계하기"
        )
        self.assertIn("아직 예약 작업을 만들거나 등록하지 말고", scheduler)
        self.assertNotIn("예약 작업을 등록해줘", scheduler)
        self.assertIn("## O-01 · 수업 후 선택", text)

    def test_docs_reject_contradictory_completion_claims(self):
        combined = "\n".join(
            (ROOT / path).read_text(encoding="utf-8")
            for path in (
                "docs/architecture.md",
                "docs/runtime-profiles.md",
                "lecture/exercises/수강생_붙여넣기_프롬프트_파트3.md",
            )
        )
        for contradiction in (
            r"KIS[^.\n]{0,100}full lifecycle(?:이|은)? (?:완료됐|완성됐)",
            r"Toss[^.\n]{0,100}(?:adapter|어댑터)(?:가|는)? (?:완료됐|완성됐)",
            r"backtest[^.\n]{0,80}(?:상태형 )?PaperBroker(?:를|가) (?:사용|쓴)",
            r"dashboard[^.\n]{0,100}core table 시각화(?:가|는)? 완료",
        ):
            self.assertNotRegex(combined, contradiction)

    def test_current_course_docs_use_only_the_official_codex_oauth_path(self):
        architecture = (ROOT / "docs/architecture.md").read_text(encoding="utf-8")
        verification = (ROOT / "docs/agent-prompt-equivalence.md").read_text(
            encoding="utf-8"
        )
        curriculum = (ROOT / "lecture/curriculum.html").read_text(encoding="utf-8")
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        part4 = (ROOT / "lecture/exercises/수강생_붙여넣기_프롬프트_파트4.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("`llm_provider.py`, `analysis.py`", architecture)
        self.assertIn("공식 Codex 공급자 단위 테스트", verification)
        self.assertIn("LECTURE_LLM_MODE=oauth", curriculum)
        self.assertIn("공식 Codex CLI", requirements)
        self.assertIn("cores/chatgpt_proxy 참고 회귀", requirements)
        self.assertNotIn("_run_news_agent", part4)
        for text in (curriculum, requirements):
            self.assertNotIn("localhost:18741", text)
            self.assertNotIn("OPENAI_BASE_URL", text)
        self.assertNotIn("cores/chatgpt_proxy", curriculum)

    def test_course_docs_explain_regime_screening_as_one_safety_contract(self):
        paths = (
            "docs/architecture.md",
            "docs/runtime-profiles.md",
            "lecture/exercises/수강생_붙여넣기_프롬프트_파트3.md",
            "lecture/exercises/수강생_붙여넣기_프롬프트_파트4.md",
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
        part4 = documents["lecture/exercises/수강생_붙여넣기_프롬프트_파트4.md"]
        for track in ("트랙 A", "트랙 C", "트랙 D"):
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
