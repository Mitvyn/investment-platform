from __future__ import annotations

import unittest

from workers.research_committee.runner import ResearchCommitteeRunner


class WorkerFake:
    def __init__(self, results: list[bool]) -> None:
        self.results = results
        self.calls = 0

    def run_once(self) -> bool:
        self.calls += 1
        return self.results.pop(0)


class ResearchCommitteeRunnerTests(unittest.TestCase):
    def test_once_processes_at_most_one_command_without_sleeping(self) -> None:
        worker = WorkerFake([True, True])
        sleeps: list[float] = []
        runner = ResearchCommitteeRunner(
            worker,
            poll_interval_seconds=2,
            sleeper=sleeps.append,
        )

        runner.run(once=True)

        self.assertEqual(worker.calls, 1)
        self.assertEqual(sleeps, [])

    def test_polling_sleeps_only_when_idle_and_honors_stop(self) -> None:
        worker = WorkerFake([False, True])
        sleeps: list[float] = []
        runner = ResearchCommitteeRunner(
            worker,
            poll_interval_seconds=2,
            sleeper=sleeps.append,
        )

        runner.run(
            once=False,
            stop_requested=lambda: len(sleeps) == 1,
        )

        self.assertEqual(worker.calls, 1)
        self.assertEqual(sleeps, [2])

    def test_poll_interval_is_bounded_before_worker_execution(self) -> None:
        worker = WorkerFake([False])

        for interval in (0, 0.09, 60.01):
            with self.subTest(interval=interval):
                with self.assertRaisesRegex(
                    ValueError,
                    "poll interval must be between 0.1 and 60 seconds",
                ):
                    ResearchCommitteeRunner(
                        worker,
                        poll_interval_seconds=interval,
                    )

        self.assertEqual(worker.calls, 0)


if __name__ == "__main__":
    unittest.main()
