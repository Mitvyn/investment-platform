from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime

from workers.moomoo_mcp.diagnostics import (
    MoomooDiagnosticsLog,
    summarize_mcp_result_shape,
)


class MoomooDiagnosticsLogTests(unittest.TestCase):
    def test_safe_entries_survive_log_reopen_without_payload_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "moomoo-diagnostics.json"
            log = MoomooDiagnosticsLog(
                path=path,
                clock=lambda: datetime(2026, 8, 24, 12, 0, 0),
            )
            shape = summarize_mcp_result_shape(
                {
                    "structuredContent": {},
                    "content": [{"type": "text", "text": '{"private":"hidden"}'}],
                }
            )
            log.record(
                subsystem="core_mcp",
                stage="market_quote_malformed",
                reason_code="quote_result_invalid",
                shape=shape,
            )

            reopened = MoomooDiagnosticsLog(path=path)

            self.assertEqual(
                [entry.as_dict() for entry in reopened.recent()],
                [entry.as_dict() for entry in log.recent()],
            )
            serialized = path.read_text(encoding="utf-8")
            self.assertNotIn("private", serialized)
            self.assertNotIn("hidden", serialized)

    def test_clear_persists_empty_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "moomoo-diagnostics.json"
            log = MoomooDiagnosticsLog(path=path)
            log.record(subsystem="core_mcp", stage="resume", reason_code="ready")
            log.clear()

            self.assertEqual(MoomooDiagnosticsLog(path=path).recent(), ())

    def test_invalid_persisted_shape_is_ignored_without_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "moomoo-diagnostics.json"
            path.write_text(
                json.dumps(
                    {
                        "contract_version": "moomoo_diagnostics_local.v1",
                        "entries": [
                            {
                                "timestamp": "2026-08-24T12:00:00",
                                "subsystem": "core_mcp",
                                "stage": "market_quote_malformed",
                                "reason_code": "quote_result_invalid",
                                "shape": {
                                    "structured_kind": [],
                                    "structured_shape": "empty",
                                    "content_kind": "array",
                                    "content_count": 0,
                                    "content_types": [],
                                    "text_json_kind": "missing",
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(MoomooDiagnosticsLog(path=path).recent(), ())

    def test_summarizes_result_shape_without_provider_values_or_keys(self) -> None:
        provider_value = {
            "s": "ok",
            "d": {"quote_list": [{"code": "US.FRVO", "last_price": 12.34}]},
            "private_value": "do-not-log",
        }

        shape = summarize_mcp_result_shape(
            {
                "structuredContent": {},
                "content": [
                    {"type": "text", "text": json.dumps(provider_value)},
                    {"type": "image", "data": "not-retained"},
                ],
            }
        )

        self.assertEqual(
            shape.as_dict(),
            {
                "structured_kind": "object",
                "structured_shape": "empty",
                "content_kind": "array",
                "content_count": 2,
                "content_types": ["text", "image"],
                "text_json_kind": "object",
            },
        )
        serialized = json.dumps(shape.as_dict())
        self.assertNotIn("US.FRVO", serialized)
        self.assertNotIn("last_price", serialized)
        self.assertNotIn("private_value", serialized)
        self.assertNotIn("do-not-log", serialized)

    def test_summarizes_non_json_text_and_unknown_shapes_with_fixed_categories(self) -> None:
        shape = summarize_mcp_result_shape(
            {
                "structuredContent": {
                    "unexpected_provider_key": {"secret": "value"},
                },
                "content": [
                    {"type": "text", "text": "not json"},
                    {"type": "unknown", "payload": "hidden"},
                ],
            }
        )

        self.assertEqual(shape.structured_kind, "object")
        self.assertEqual(shape.structured_shape, "object")
        self.assertEqual(shape.content_kind, "array")
        self.assertEqual(shape.content_count, 2)
        self.assertEqual(shape.content_types, ("text", "other"))
        self.assertEqual(shape.text_json_kind, "invalid")
        self.assertNotIn("unexpected_provider_key", json.dumps(shape.as_dict()))

    def test_diagnostic_entry_includes_shape_only_when_supplied(self) -> None:
        log = MoomooDiagnosticsLog(clock=lambda: datetime(2026, 1, 1))
        shape = summarize_mcp_result_shape(
            {
                "structuredContent": {"s": "ok", "d": {}},
                "content": [],
            }
        )
        log.record(
            subsystem="core_mcp",
            stage="market_quote_malformed",
            reason_code="quote_result_invalid",
            shape=shape,
        )

        self.assertEqual(
            log.recent()[0].as_dict()["shape"],
            {
                "structured_kind": "object",
                "structured_shape": "s_d_envelope",
                "content_kind": "array",
                "content_count": 0,
                "content_types": [],
                "text_json_kind": "missing",
            },
        )

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
