from __future__ import annotations

import unittest
from dataclasses import replace

from investment_research_os.readiness_and_theses import ThesisChain
from investment_research_os.readiness_and_theses.storage import (
    ReadinessThesisRuntimeStorageError,
    SupabaseReadinessAndThesisRepository,
)
from tests.test_readiness_thesis_runtime_storage import readiness_result


class RuntimeStoreFake:
    def __init__(self, error: Exception | None = None) -> None:
        self.persisted = []
        self.error = error

    def persist(self, result):
        self.persisted.append(result)
        if self.error is not None:
            raise self.error


class ReadModelFake:
    def __init__(
        self,
        result,
        error: Exception | None = None,
        *,
        chain: ThesisChain | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.chain = chain
        self.run_reads = []
        self.readiness_reads = []
        self.thesis_reads = []
        self.chain_reads = []

    def get_for_run(self, operator_id: str, research_run_id: str):
        self.run_reads.append((operator_id, research_run_id))
        if self.error is not None:
            raise self.error
        return self.result

    def get_readiness_by_id(
        self,
        operator_id: str,
        readiness_gate_result_id: str,
    ):
        self.readiness_reads.append((operator_id, readiness_gate_result_id))
        return None if self.result is None else self.result.readiness

    def get_thesis_by_id(
        self,
        operator_id: str,
        thesis_version_id: str,
    ):
        self.thesis_reads.append((operator_id, thesis_version_id))
        return None if self.result is None else self.result.thesis

    def get_chain(
        self,
        operator_id: str,
        security_id: str,
        thesis_contract_id: str,
    ):
        self.chain_reads.append(
            (operator_id, security_id, thesis_contract_id)
        )
        return self.chain


class SupabaseReadinessAndThesisRepositoryTests(unittest.TestCase):
    def test_save_persists_and_reloads_exact_canonical_result(self) -> None:
        result = readiness_result()
        runtime_store = RuntimeStoreFake()
        read_model = ReadModelFake(result)
        repository = SupabaseReadinessAndThesisRepository(
            runtime_store=runtime_store,
            read_model=read_model,
        )

        saved = repository.save(result)

        self.assertIs(saved, result)
        self.assertEqual(runtime_store.persisted, [result])
        self.assertEqual(
            read_model.run_reads,
            [
                (
                    result.readiness.operator_id,
                    result.readiness.research_run_id,
                )
            ],
        )

    def test_save_persists_and_reloads_exact_no_thesis_result(self) -> None:
        result = readiness_result(terminal_state="failed")
        runtime_store = RuntimeStoreFake()
        read_model = ReadModelFake(result)
        repository = SupabaseReadinessAndThesisRepository(
            runtime_store=runtime_store,
            read_model=read_model,
        )

        saved = repository.save(result)

        self.assertIs(saved, result)
        self.assertIsNone(saved.thesis)
        self.assertEqual(saved.thesis_creation.creation_outcome, "no_thesis")
        self.assertEqual(runtime_store.persisted, [result])
        self.assertEqual(
            read_model.run_reads,
            [
                (
                    result.readiness.operator_id,
                    result.readiness.research_run_id,
                )
            ],
        )

    def test_save_replay_persists_and_reloads_without_cache(self) -> None:
        result = readiness_result()
        runtime_store = RuntimeStoreFake()
        read_model = ReadModelFake(result)
        repository = SupabaseReadinessAndThesisRepository(
            runtime_store=runtime_store,
            read_model=read_model,
        )

        first = repository.save(result)
        second = repository.save(result)

        self.assertIs(first, result)
        self.assertIs(second, result)
        self.assertEqual(runtime_store.persisted, [result, result])
        self.assertEqual(
            read_model.run_reads,
            [
                (
                    result.readiness.operator_id,
                    result.readiness.research_run_id,
                ),
                (
                    result.readiness.operator_id,
                    result.readiness.research_run_id,
                ),
            ],
        )

    def test_save_rejects_mismatched_reloaded_result(self) -> None:
        result = readiness_result()
        mismatched = replace(
            result,
            thesis_creation=replace(
                result.thesis_creation,
                reason_code="mismatched_reload",
            ),
        )
        runtime_store = RuntimeStoreFake()
        repository = SupabaseReadinessAndThesisRepository(
            runtime_store=runtime_store,
            read_model=ReadModelFake(mismatched),
        )

        with self.assertRaisesRegex(
            ReadinessThesisRuntimeStorageError,
            "reloaded readiness thesis result does not match",
        ):
            repository.save(result)

        self.assertEqual(runtime_store.persisted, [result])

    def test_save_propagates_atomic_storage_failure_without_reading(self) -> None:
        result = readiness_result()
        error = ReadinessThesisRuntimeStorageError(
            "atomic persistence unavailable"
        )
        runtime_store = RuntimeStoreFake(error)
        read_model = ReadModelFake(result)
        repository = SupabaseReadinessAndThesisRepository(
            runtime_store=runtime_store,
            read_model=read_model,
        )

        with self.assertRaisesRegex(
            ReadinessThesisRuntimeStorageError,
            "atomic persistence unavailable",
        ):
            repository.save(result)

        self.assertEqual(runtime_store.persisted, [result])
        self.assertEqual(read_model.run_reads, [])

    def test_save_propagates_reload_failure_after_atomic_persistence(self) -> None:
        result = readiness_result()
        error = ReadinessThesisRuntimeStorageError("read model unavailable")
        runtime_store = RuntimeStoreFake()
        read_model = ReadModelFake(result, error)
        repository = SupabaseReadinessAndThesisRepository(
            runtime_store=runtime_store,
            read_model=read_model,
        )

        with self.assertRaisesRegex(
            ReadinessThesisRuntimeStorageError,
            "read model unavailable",
        ):
            repository.save(result)

        self.assertEqual(runtime_store.persisted, [result])
        self.assertEqual(
            read_model.run_reads,
            [
                (
                    result.readiness.operator_id,
                    result.readiness.research_run_id,
                )
            ],
        )

    def test_save_rejects_missing_reload_after_atomic_persistence(self) -> None:
        result = readiness_result()
        runtime_store = RuntimeStoreFake()
        repository = SupabaseReadinessAndThesisRepository(
            runtime_store=runtime_store,
            read_model=ReadModelFake(None),
        )

        with self.assertRaisesRegex(
            ReadinessThesisRuntimeStorageError,
            "reloaded readiness thesis result is unavailable",
        ):
            repository.save(result)

        self.assertEqual(runtime_store.persisted, [result])

    def test_read_methods_delegate_without_local_cache(self) -> None:
        result = readiness_result()
        assert result.thesis is not None
        chain = ThesisChain(
            operator_id=result.readiness.operator_id,
            security_id=result.readiness.security_id,
            thesis_contract_id=result.readiness.thesis_contract_id,
            active_canonical_thesis_version_id=(
                result.thesis.thesis_version_id
            ),
            canonical_versions=(result.thesis,),
            provisional_branches=(),
            generated_at=result.thesis.created_at,
        )
        read_model = ReadModelFake(result, chain=chain)
        repository = SupabaseReadinessAndThesisRepository(
            runtime_store=RuntimeStoreFake(),
            read_model=read_model,
        )

        loaded_result = repository.get_for_run(
            result.readiness.operator_id,
            result.readiness.research_run_id,
        )
        loaded_readiness = repository.get_readiness_by_id(
            result.readiness.operator_id,
            result.readiness.readiness_gate_result_id,
        )
        loaded_thesis = repository.get_thesis_by_id(
            result.readiness.operator_id,
            result.thesis.thesis_version_id,
        )
        loaded_chain = repository.get_chain(
            result.readiness.operator_id,
            result.readiness.security_id,
            result.readiness.thesis_contract_id,
        )

        self.assertIs(loaded_result, result)
        self.assertIs(loaded_readiness, result.readiness)
        self.assertIs(loaded_thesis, result.thesis)
        self.assertIs(loaded_chain, chain)
        self.assertEqual(
            read_model.run_reads,
            [
                (
                    result.readiness.operator_id,
                    result.readiness.research_run_id,
                )
            ],
        )
        self.assertEqual(
            read_model.readiness_reads,
            [
                (
                    result.readiness.operator_id,
                    result.readiness.readiness_gate_result_id,
                )
            ],
        )
        self.assertEqual(
            read_model.thesis_reads,
            [
                (
                    result.readiness.operator_id,
                    result.thesis.thesis_version_id,
                )
            ],
        )
        self.assertEqual(
            read_model.chain_reads,
            [
                (
                    result.readiness.operator_id,
                    result.readiness.security_id,
                    result.readiness.thesis_contract_id,
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
