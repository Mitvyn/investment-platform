from __future__ import annotations

import json
import subprocess
import sys
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

    # ------------------------------------------------------- symlink safety

    def test_load_rejects_diagnostics_file_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real_target = root / "elsewhere.json"
            real_target.write_text(
                json.dumps(
                    {
                        "contract_version": "moomoo_diagnostics_local.v1",
                        "entries": [
                            {
                                "timestamp": "2026-08-24T12:00:00",
                                "subsystem": "core_mcp",
                                "stage": "resume",
                                "reason_code": "ready",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            path = root / "moomoo-diagnostics.json"
            path.symlink_to(real_target)

            log = MoomooDiagnosticsLog(path=path)

            self.assertEqual(log.recent(), ())

    def test_load_rejects_parent_directory_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real_dir = root / "real"
            real_dir.mkdir()
            (real_dir / "moomoo-diagnostics.json").write_text(
                json.dumps(
                    {
                        "contract_version": "moomoo_diagnostics_local.v1",
                        "entries": [
                            {
                                "timestamp": "2026-08-24T12:00:00",
                                "subsystem": "core_mcp",
                                "stage": "resume",
                                "reason_code": "ready",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            symlinked_parent = root / "linked"
            symlinked_parent.symlink_to(real_dir)
            path = symlinked_parent / "moomoo-diagnostics.json"

            log = MoomooDiagnosticsLog(path=path)

            self.assertEqual(log.recent(), ())

    def test_record_does_not_persist_through_symlinked_diagnostics_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside.json"
            path = root / "moomoo-diagnostics.json"
            path.symlink_to(outside)

            log = MoomooDiagnosticsLog(path=path)
            log.record(subsystem="core_mcp", stage="resume", reason_code="ready")

            self.assertFalse(outside.exists())

    def test_record_does_not_persist_through_symlinked_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real_dir = root / "real"
            real_dir.mkdir()
            symlinked_parent = root / "linked"
            symlinked_parent.symlink_to(real_dir)
            path = symlinked_parent / "moomoo-diagnostics.json"

            log = MoomooDiagnosticsLog(path=path)
            log.record(subsystem="core_mcp", stage="resume", reason_code="ready")

            self.assertEqual(list(real_dir.iterdir()), [])

    def test_record_ignores_symlinked_lock_file_location(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "moomoo-diagnostics.json"
            outside_lock_target = root / "outside.lock"
            lock_path = root / f".{path.name}.lock"
            lock_path.symlink_to(outside_lock_target)

            log = MoomooDiagnosticsLog(path=path)
            log.record(subsystem="core_mcp", stage="resume", reason_code="ready")

            self.assertFalse(outside_lock_target.exists())
            self.assertFalse(path.exists())
            self.assertEqual([entry.reason_code for entry in log.recent()], ["ready"])

    # ------------------------------------------------- malformed file safety

    def test_truncated_file_is_ignored_without_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "moomoo-diagnostics.json"
            path.write_text('{"contract_version": "moomoo_d', encoding="utf-8")

            self.assertEqual(MoomooDiagnosticsLog(path=path).recent(), ())

    def test_non_json_file_is_ignored_without_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "moomoo-diagnostics.json"
            path.write_bytes(b"\x00\x01not-json-binary-garbage\xff")

            self.assertEqual(MoomooDiagnosticsLog(path=path).recent(), ())

    def test_oversized_file_is_ignored_without_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "moomoo-diagnostics.json"
            oversized_entries = [
                {
                    "timestamp": "2026-08-24T12:00:00",
                    "subsystem": "core_mcp",
                    "stage": "resume",
                    "reason_code": "x" * 100,
                }
            ] * 4000
            path.write_text(
                json.dumps(
                    {
                        "contract_version": "moomoo_diagnostics_local.v1",
                        "entries": oversized_entries,
                    }
                ),
                encoding="utf-8",
            )
            self.assertGreater(path.stat().st_size, 256 * 1024)

            self.assertEqual(MoomooDiagnosticsLog(path=path).recent(), ())

    def test_wrong_contract_version_file_is_ignored_without_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "moomoo-diagnostics.json"
            path.write_text(
                json.dumps(
                    {
                        "contract_version": "moomoo_diagnostics_local.v0",
                        "entries": [
                            {
                                "timestamp": "2026-08-24T12:00:00",
                                "subsystem": "core_mcp",
                                "stage": "resume",
                                "reason_code": "ready",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(MoomooDiagnosticsLog(path=path).recent(), ())

    def test_entry_missing_required_key_is_ignored_without_exception(self) -> None:
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
                                "stage": "resume",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(MoomooDiagnosticsLog(path=path).recent(), ())

    # ------------------------------------------------- cross-process locking

    def test_concurrent_recorders_in_separate_processes_preserve_both_entries(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "moomoo-diagnostics.json"
            script = (
                "import sys; sys.path.insert(0, {repo_root!r}); "
                "from pathlib import Path; "
                "from workers.moomoo_mcp.diagnostics import MoomooDiagnosticsLog; "
                "log = MoomooDiagnosticsLog(path=Path({path!r})); "
                "[log.record(subsystem='core_mcp', stage='resume', "
                "reason_code=sys.argv[1]) for _ in range(20)]"
            ).format(repo_root=str(Path(__file__).resolve().parents[1]), path=str(path))

            processes = [
                subprocess.Popen([sys.executable, "-c", script, reason_code])
                for reason_code in ("writer_one", "writer_two")
            ]
            for process in processes:
                self.assertEqual(process.wait(timeout=30), 0)

            final_log = MoomooDiagnosticsLog(path=path)
            reason_codes = [entry.reason_code for entry in final_log.recent()]
            self.assertEqual(reason_codes.count("writer_one"), 20)
            self.assertEqual(reason_codes.count("writer_two"), 20)
            self.assertEqual(len(reason_codes), 40)

    def test_clear_and_concurrent_record_serialize_without_partial_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "moomoo-diagnostics.json"
            log = MoomooDiagnosticsLog(path=path)
            log.record(subsystem="core_mcp", stage="resume", reason_code="before")

            clear_script = (
                "import sys; sys.path.insert(0, {repo_root!r}); "
                "from pathlib import Path; "
                "from workers.moomoo_mcp.diagnostics import MoomooDiagnosticsLog; "
                "MoomooDiagnosticsLog(path=Path({path!r})).clear()"
            ).format(repo_root=str(Path(__file__).resolve().parents[1]), path=str(path))
            record_script = (
                "import sys; sys.path.insert(0, {repo_root!r}); "
                "from pathlib import Path; "
                "from workers.moomoo_mcp.diagnostics import MoomooDiagnosticsLog; "
                "MoomooDiagnosticsLog(path=Path({path!r})).record("
                "subsystem='core_mcp', stage='resume', reason_code='after')"
            ).format(repo_root=str(Path(__file__).resolve().parents[1]), path=str(path))

            processes = [
                subprocess.Popen([sys.executable, "-c", clear_script]),
                subprocess.Popen([sys.executable, "-c", record_script]),
            ]
            for process in processes:
                self.assertEqual(process.wait(timeout=30), 0)

            final_entries = [
                entry.reason_code for entry in MoomooDiagnosticsLog(path=path).recent()
            ]
            # Lock enforces total ordering between clear() and record(): the
            # persisted result is either empty (clear ran last) or exactly
            # ["after"] (record ran last) -- never a torn/partial file and
            # never both "before" and "after" together.
            self.assertIn(final_entries, ([], ["after"]))

    def test_lock_and_temp_files_stay_inside_diagnostics_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "nested" / "moomoo-diagnostics.json"
            log = MoomooDiagnosticsLog(path=path)
            log.record(subsystem="core_mcp", stage="resume", reason_code="ready")
            log.clear()

            leftover = [
                entry.name
                for entry in path.parent.iterdir()
                if entry.name != path.name and not entry.name.endswith(".lock")
            ]
            self.assertEqual(leftover, [])
            for entry in root.rglob("*"):
                self.assertTrue(str(entry).startswith(str(root)))


    def test_running_instance_sees_records_from_another_live_instance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "moomoo-diagnostics.json"
            writer = MoomooDiagnosticsLog(path=path)
            reader = MoomooDiagnosticsLog(path=path)

            writer.record(
                subsystem="core_mcp", stage="resume", reason_code="writer_entry"
            )

            self.assertEqual(
                [entry.reason_code for entry in reader.recent()], ["writer_entry"]
            )

    def test_recent_reload_respects_limit_and_leaves_file_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "moomoo-diagnostics.json"
            writer = MoomooDiagnosticsLog(path=path)
            reader = MoomooDiagnosticsLog(path=path)
            for index in range(3):
                writer.record(
                    subsystem="core_mcp", stage="resume", reason_code=f"code{index}"
                )

            before = path.read_bytes()
            self.assertEqual(
                [entry.reason_code for entry in reader.recent(limit=2)],
                ["code1", "code2"],
            )
            self.assertEqual(path.read_bytes(), before)

    def test_recent_without_path_stays_in_memory_only(self) -> None:
        log = MoomooDiagnosticsLog()
        log.record(subsystem="core_mcp", stage="resume", reason_code="memory_only")
        self.assertEqual(
            [entry.reason_code for entry in log.recent()], ["memory_only"]
        )

    def test_recent_on_symlinked_path_uses_in_memory_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.json"
            target.write_text("{}", encoding="utf-8")
            link = root / "moomoo-diagnostics.json"
            link.symlink_to(target)

            log = MoomooDiagnosticsLog(path=link)
            log.record(subsystem="core_mcp", stage="resume", reason_code="unsafe_path")

            self.assertEqual(
                [entry.reason_code for entry in log.recent()], ["unsafe_path"]
            )
            self.assertEqual(target.read_text(encoding="utf-8"), "{}")

if __name__ == "__main__":
    unittest.main()
