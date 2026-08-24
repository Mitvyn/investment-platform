from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from investment_research_os.research_runs import (
    EligibilityCheck,
    EligibilityResult,
    ResearchRun,
    RULE_IDS,
    SecurityIdentity,
)
from investment_research_os.research_runs.file_storage import (
    FileResearchRunRepository,
    LocalResearchRunStorageError,
)


OPERATOR = "027d7f1b-d928-48d9-b6c8-f10d3c7ba792"
SECURITY = "22222222-2222-4222-8222-222222222222"
RUN = "10000000-0000-4000-8000-000000000000"
CUTOFF = datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC)
EVALUATED_AT = datetime(2026, 5, 7, 4, tzinfo=UTC)


def research_run(**changes) -> ResearchRun:
    values = {
        "id": RUN,
        "operator_id": OPERATOR,
        "security_id": SECURITY,
        "security_identity": SecurityIdentity(
            id=SECURITY,
            cik="0001601830",
            issuer_name="Recursion Pharmaceuticals, Inc.",
            symbol="RXRX",
            primary_listing_exchange="NASDAQ",
        ),
        "question_type": "biotech_moonshot_catalyst_assessment",
        "question_type_version": "biotech_moonshot_catalyst_assessment.v1",
        "workflow_config_version": "biotech-moonshot-catalyst-v1",
        "thesis_contract_id": "biotech_moonshot_catalyst_assessment",
        "as_of_cutoff": CUTOFF,
        "operator_focus_original": "Review financing through catalyst.",
        "operator_focus_normalized": "Review financing through catalyst.",
        "status": "eligibility_evaluated",
        "idempotency_key": "a" * 64,
        "eligibility": EligibilityResult(
            policy_version="biotech-security-eligibility-v1",
            eligible=True,
            checks=tuple(
                EligibilityCheck(
                    rule_id=rule_id,
                    rule_version=f"{rule_id}.v1",
                    passed=True,
                    evidence_reference=f"evidence-{rule_id}",
                    reason_code="eligible",
                    explanation="Rule passed using evidence valid at cutoff.",
                    evaluated_at=EVALUATED_AT,
                )
                for rule_id in RULE_IDS
            ),
            evaluated_at=EVALUATED_AT,
        ),
        "created_at": EVALUATED_AT,
    }
    values.update(changes)
    return ResearchRun(**values)


class FileResearchRunRepositoryTests(unittest.TestCase):
    def test_saved_run_round_trips_across_restart(self) -> None:
        run = research_run()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runs"
            FileResearchRunRepository(root).save(run)

            reloaded = FileResearchRunRepository(root).get(OPERATOR, RUN)

        self.assertEqual(reloaded, run)

    def test_first_save_wins_and_identical_replay_creates_no_duplicate(self) -> None:
        run = research_run()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runs"
            repository = FileResearchRunRepository(root)

            first = repository.save(run)
            second = repository.save(replace(run, status="drifted"))
            stored_files = sorted(path.name for path in (root / OPERATOR).iterdir())

        self.assertEqual(first, run)
        self.assertEqual(second, run)
        self.assertEqual(len(stored_files), 1)

    def test_foreign_operator_cannot_read_run(self) -> None:
        run = research_run()
        with tempfile.TemporaryDirectory() as directory:
            repository = FileResearchRunRepository(Path(directory) / "runs")
            repository.save(run)

            self.assertIsNone(
                repository.get("99999999-9999-4999-8999-999999999999", RUN)
            )
            self.assertIsNone(repository.get(OPERATOR, "0" * 8 + "-0000-4000-8000-000000000000"))

    def test_rejects_symlinked_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "real"
            target.mkdir()
            link = Path(directory) / "linked"
            link.symlink_to(target)

            with self.assertRaisesRegex(
                LocalResearchRunStorageError,
                "research run storage root must not be a symlink",
            ):
                FileResearchRunRepository(link)

    def test_rejects_record_whose_stored_identity_drifted(self) -> None:
        run = research_run()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runs"
            repository = FileResearchRunRepository(root)
            repository.save(run)
            path = root / OPERATOR / f"{RUN}.json"
            path.write_text(path.read_text().replace(RXRX_MARKER, '"symbol":"OTHR"'))

            with self.assertRaisesRegex(
                LocalResearchRunStorageError,
                "research run record is invalid",
            ):
                repository.get(OPERATOR, RUN)


RXRX_MARKER = '"symbol":"RXRX"'


if __name__ == "__main__":
    unittest.main()
