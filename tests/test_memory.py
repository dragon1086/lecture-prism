from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import db
import memory


class MemoryCompressionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_patch = mock.patch.object(
            db, "DB_PATH", Path(self.tmp.name) / "memory.db"
        )
        self.db_patch.start()
        db.init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.tmp.cleanup()

    def _save_at(self, *, days_ago: int, lesson: str, ticker: str = "005930"):
        db.save_lesson(
            ticker=ticker,
            action="SELL",
            lesson=lesson,
            tier="short",
            error_type="JUDGMENT",
        )
        timestamp = (
            datetime(2026, 7, 31, 12, 0) - timedelta(days=days_ago)
        ).isoformat(timespec="seconds")
        with db._connect() as conn:
            conn.execute(
                "UPDATE feedback_lessons SET timestamp=? "
                "WHERE id=(SELECT MAX(id) FROM feedback_lessons)",
                (timestamp,),
            )

    def test_old_short_memories_become_medium_and_repeated_rules_become_long(self):
        repeated = "추격 진입 뒤 손절. 거래량과 시장 방향을 함께 확인한다."
        self._save_at(days_ago=40, lesson=repeated)
        self._save_at(days_ago=38, lesson=repeated, ticker="000660")
        self._save_at(days_ago=10, lesson="돌파 거래량이 약하면 진입을 보류한다.")

        result = memory.compress_memories(now=datetime(2026, 7, 31, 12, 0))

        self.assertEqual(result["short_to_medium"], 3)
        self.assertEqual(result["medium_to_long"], 2)
        long_rows = db.get_memory_rows(tier="long", active_only=True)
        self.assertEqual(len(long_rows), 1)
        self.assertEqual(long_rows[0]["support_count"], 2)

    def test_relevant_memories_prefer_same_ticker_then_long_principles(self):
        db.save_lesson(
            ticker="005930",
            action="SELL",
            lesson="같은 종목 최근 손절 뒤에는 재진입 조건을 다시 확인한다.",
            tier="medium",
        )
        db.save_lesson(
            ticker="*",
            action="SELL",
            lesson="반복 원칙: 시장 방향과 거래량이 함께 맞을 때만 진입한다.",
            tier="long",
            support_count=4,
        )

        lessons = memory.get_relevant_memories("005930", limit=2)

        self.assertEqual(len(lessons), 2)
        self.assertIn("같은 종목", lessons[0])
        self.assertIn("반복 원칙", lessons[1])

    def test_long_memory_count_is_bounded(self):
        for index in range(25):
            db.save_lesson(
                ticker="*",
                action="SELL",
                lesson=f"장기 원칙 {index}",
                tier="long",
                support_count=index + 1,
            )

        result = memory.compress_memories(
            now=datetime(2026, 7, 31, 12, 0),
            max_long=20,
        )

        self.assertEqual(result["long_deactivated"], 5)
        self.assertEqual(
            len(db.get_memory_rows(tier="long", active_only=True)),
            20,
        )


if __name__ == "__main__":
    unittest.main()
