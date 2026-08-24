from __future__ import annotations

import unittest
from datetime import datetime

from workers.moomoo_mcp.diagnostics import MoomooDiagnosticsLog


class MoomooDiagnosticsLogTests(unittest.TestCase):
    def test_records_bounded_safe_fields(self) -> None:
        clock_values = iter(
            [datetime(2026, 8, 21, 12, 0, 0), datetime(2026, 8, 21, 12, 0, 1)]
        )
        log = MoomooDiagnosticsLog(clock=lambda: next(clock_values))
        log.record(subsystem="core_mcp", stage="resume", reason_code="credential_missing")
        log.record(subsystem="optional_stream", stage="disconnect", reason_code="ok")
        entries = log.recent()
        self.assertEqual(len(entries), 2)
        self.assertEqual(
            entries[0].as_dict(),
            {
                "timestamp": "2026-08-21T12:00:00",
                "subsystem": "core_mcp",
                "stage": "resume",
                "reason_code": "credential_missing",
            },
        )

    def test_capacity_is_bounded_and_drops_oldest(self) -> None:
        log = MoomooDiagnosticsLog(max_entries=3, clock=lambda: datetime(2026, 1, 1))
        for index in range(5):
            log.record(
                subsystem="core_mcp", stage="resume", reason_code=f"code{index}"
            )
        entries = log.recent()
        self.assertEqual(len(entries), 3)
        self.assertEqual([entry.reason_code for entry in entries], ["code2", "code3", "code4"])

    def test_unknown_subsystem_is_rejected(self) -> None:
        log = MoomooDiagnosticsLog()
        with self.assertRaises(ValueError):
            log.record(subsystem="trade_engine", stage="resume", reason_code="ok")

    def test_reason_code_with_unsafe_characters_is_rejected(self) -> None:
        log = MoomooDiagnosticsLog()
        with self.assertRaises(ValueError):
            log.record(
                subsystem="core_mcp",
                stage="resume",
                reason_code="Bearer eyJhbGciOi...",
            )

    def test_free_form_provider_text_is_rejected_not_truncated(self) -> None:
        log = MoomooDiagnosticsLog()
        with self.assertRaises(ValueError):
            log.record(
                subsystem="core_mcp",
                stage="resume",
                reason_code="connection reset by peer at https://mcp.moomoo.com/mcp?code=abc",
            )

    def test_recent_supports_a_limit(self) -> None:
        log = MoomooDiagnosticsLog(clock=lambda: datetime(2026, 1, 1))
        for index in range(5):
            log.record(
                subsystem="core_mcp", stage="resume", reason_code=f"code{index}"
            )
        self.assertEqual(
            [entry.reason_code for entry in log.recent(limit=2)], ["code3", "code4"]
        )

    def test_clear_removes_all_local_diagnostics(self) -> None:
        log = MoomooDiagnosticsLog()
        log.record(subsystem="core_mcp", stage="resume", reason_code="credential_missing")
        log.clear()
        self.assertEqual(log.recent(), ())


if __name__ == "__main__":
    unittest.main()
