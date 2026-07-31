from datetime import datetime
import unittest

import operations


class OperationsScheduleTest(unittest.TestCase):
    def test_due_jobs_match_weekday_and_exact_minute(self):
        jobs = [
            operations.JobSpec(
                name="analysis",
                at="09:30",
                weekdays=(0, 1, 2, 3, 4),
                command="batch",
            ),
            operations.JobSpec(
                name="compression",
                at="03:00",
                weekdays=(6,),
                command="compress",
            ),
        ]

        monday = datetime(2026, 8, 3, 9, 30)
        self.assertEqual(
            [job.name for job in operations.due_jobs(monday, jobs)],
            ["analysis"],
        )

    def test_due_jobs_do_not_repeat_in_same_minute(self):
        job = operations.JobSpec(
            name="monitor",
            at="10:00",
            weekdays=(0,),
            command="monitor",
        )
        now = datetime(2026, 8, 3, 10, 0)
        seen = set()

        first = operations.due_jobs(now, [job], seen=seen)
        second = operations.due_jobs(now, [job], seen=seen)

        self.assertEqual([item.name for item in first], ["monitor"])
        self.assertEqual(second, [])

    def test_invalid_schedule_time_is_rejected(self):
        with self.assertRaises(ValueError):
            operations.JobSpec(
                name="broken",
                at="25:90",
                weekdays=(0,),
                command="batch",
            )


if __name__ == "__main__":
    unittest.main()
