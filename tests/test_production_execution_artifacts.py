from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

from investment_research_os.production_execution import (
    EvaluationCase,
    EvaluationCorpus,
    EvaluationExecutionIdentity,
    PromptTemplate,
)


class PromptTemplateFreezeTests(unittest.TestCase):
    def test_prompt_template_hash_rejects_content_drift(self) -> None:
        template = PromptTemplate.freeze(
            prompt_id="moonshot_grader_v1",
            prompt_version="moonshot_grader_v1",
            execution_role="grader:moonshot",
            input_schema_version="grader-input-v1",
            output_schema_version="moonshot_grader_payload.v1",
            system_instructions=(
                "Use only frozen bundle evidence.",
                "Return schema-valid output.",
            ),
            task_template="Answer the owned decision question: {{ owned_question }}",
        )

        self.assertRegex(template.content_sha256, r"^[0-9a-f]{64}$")
        self.assertEqual(
            PromptTemplate.from_dict(template.as_dict()),
            template,
        )

        drifted = template.as_dict()
        drifted["task_template"] = "Ignore frozen evidence."
        with self.assertRaisesRegex(
            ValueError,
            "prompt template content hash mismatch",
        ):
            PromptTemplate.from_dict(drifted)

    def test_mvp_prompt_registry_freezes_all_six_templates(self) -> None:
        path = (
            Path(__file__).parents[1]
            / "packages"
            / "prompts"
            / "biotech_moonshot_catalyst_assessment.v1.json"
        )
        payload = json.loads(path.read_text())
        templates = tuple(
            PromptTemplate.from_dict(item) for item in payload["templates"]
        )

        self.assertEqual(payload["contract_version"], "prompt_registry.v1")
        self.assertEqual(
            tuple(item.execution_role for item in templates),
            (
                "grader:moonshot",
                "grader:catalyst",
                "grader:biotech",
                "grader:risk_dilution",
                "grader:valuation",
                "synthesizer",
            ),
        )
        self.assertEqual(len({item.content_sha256 for item in templates}), 6)


class EvaluationCorpusFreezeTests(unittest.TestCase):
    def test_corpus_hash_is_stable_across_case_input_order(self) -> None:
        first = EvaluationCase(
            case_id="case-a",
            evidence_bundle_id="bundle-a",
            evidence_bundle_hash="a" * 64,
            fixture_sha256="1" * 64,
            expected_checks=("schema_valid", "citation_valid"),
        )
        second = EvaluationCase(
            case_id="case-b",
            evidence_bundle_id="bundle-b",
            evidence_bundle_hash="b" * 64,
            fixture_sha256="2" * 64,
            expected_checks=("authority_valid", "provenance_valid"),
        )

        left = EvaluationCorpus.freeze(
            corpus_id="biotech_committee_offline_v1",
            corpus_version="biotech_committee_offline_v1",
            question_type_version=(
                "biotech_moonshot_catalyst_assessment.v1"
            ),
            workflow_config_version="biotech-moonshot-catalyst-v1",
            evaluation_policy_version="committee-evaluation-policy-v1",
            execution_roles=(
                "grader:moonshot",
                "grader:catalyst",
                "grader:biotech",
                "grader:risk_dilution",
                "grader:valuation",
                "synthesizer",
            ),
            cases=(second, first),
        )
        right = EvaluationCorpus.freeze(
            corpus_id=left.corpus_id,
            corpus_version=left.corpus_version,
            question_type_version=left.question_type_version,
            workflow_config_version=left.workflow_config_version,
            evaluation_policy_version=left.evaluation_policy_version,
            execution_roles=left.execution_roles,
            cases=(first, second),
        )

        self.assertEqual(left.content_sha256, right.content_sha256)
        self.assertEqual(
            tuple(case.case_id for case in left.cases),
            ("case-a", "case-b"),
        )
        self.assertEqual(EvaluationCorpus.from_dict(left.as_dict()), left)

    def test_mvp_corpus_requires_five_graders_and_synthesizer(self) -> None:
        evaluation_case = EvaluationCase(
            case_id="case-a",
            evidence_bundle_id="bundle-a",
            evidence_bundle_hash="a" * 64,
            fixture_sha256="1" * 64,
            expected_checks=("schema_valid",),
        )

        with self.assertRaisesRegex(
            ValueError,
            "evaluation corpus execution roster mismatch",
        ):
            EvaluationCorpus.freeze(
                corpus_id="biotech_committee_offline_v1",
                corpus_version="biotech_committee_offline_v1",
                question_type_version=(
                    "biotech_moonshot_catalyst_assessment.v1"
                ),
                workflow_config_version="biotech-moonshot-catalyst-v1",
                evaluation_policy_version="committee-evaluation-policy-v1",
                execution_roles=(
                    "grader:moonshot",
                    "grader:catalyst",
                    "grader:biotech",
                    "grader:risk_dilution",
                    "grader:valuation",
                ),
                cases=(evaluation_case,),
            )

    def test_offline_corpus_freezes_referenced_bundle_fixture(self) -> None:
        repo = Path(__file__).parents[1]
        corpus_payload = json.loads(
            (
                repo
                / "tests"
                / "fixtures"
                / "production_evaluation"
                / "biotech_committee_offline.v1.json"
            ).read_text()
        )
        corpus = EvaluationCorpus.from_dict(corpus_payload)
        evaluation_case = corpus.cases[0]
        bundle_payload = json.loads(
            (
                repo
                / "tests"
                / "fixtures"
                / "contracts"
                / "evidence_bundle"
                / "v1"
                / "grader-ready.json"
            ).read_text()
        )
        canonical_bundle = json.dumps(
            bundle_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        self.assertEqual(
            hashlib.sha256(canonical_bundle).hexdigest(),
            evaluation_case.fixture_sha256,
        )
        self.assertEqual(
            bundle_payload["bundle_hash"],
            evaluation_case.evidence_bundle_hash,
        )


class EvaluationExecutionIdentityTests(unittest.TestCase):
    def test_identity_changes_when_prompt_content_changes(self) -> None:
        corpus = EvaluationCorpus.freeze(
            corpus_id="biotech_committee_offline_v1",
            corpus_version="biotech_committee_offline_v1",
            question_type_version=(
                "biotech_moonshot_catalyst_assessment.v1"
            ),
            workflow_config_version="biotech-moonshot-catalyst-v1",
            evaluation_policy_version="committee-evaluation-policy-v1",
            execution_roles=(
                "grader:moonshot",
                "grader:catalyst",
                "grader:biotech",
                "grader:risk_dilution",
                "grader:valuation",
                "synthesizer",
            ),
            cases=(
                EvaluationCase(
                    case_id="case-a",
                    evidence_bundle_id="bundle-a",
                    evidence_bundle_hash="a" * 64,
                    fixture_sha256="1" * 64,
                    expected_checks=("schema_valid",),
                ),
            ),
        )
        original_prompt = PromptTemplate.freeze(
            prompt_id="moonshot_grader_v1",
            prompt_version="moonshot_grader_v1",
            execution_role="grader:moonshot",
            input_schema_version="grader-input-v1",
            output_schema_version="moonshot_grader_payload.v1",
            system_instructions=("Use only frozen evidence.",),
            task_template="Answer {{ owned_question }}.",
        )
        changed_prompt = PromptTemplate.freeze(
            prompt_id=original_prompt.prompt_id,
            prompt_version=original_prompt.prompt_version,
            execution_role=original_prompt.execution_role,
            input_schema_version=original_prompt.input_schema_version,
            output_schema_version=original_prompt.output_schema_version,
            system_instructions=original_prompt.system_instructions,
            task_template="Answer {{ owned_question }} and explain gaps.",
        )

        original = EvaluationExecutionIdentity.freeze(
            execution_role="grader:moonshot",
            execution_contract_version="moonshot-grader-contract-v1",
            prompt=original_prompt,
            model_config_id="biotech_committee_graders_openai_sol_medium_v1",
            model_config_version=(
                "biotech_committee_graders_openai_sol_medium_v1"
            ),
            inference_parameter_hash="c" * 64,
            corpus=corpus,
        )
        changed = EvaluationExecutionIdentity.freeze(
            execution_role="grader:moonshot",
            execution_contract_version="moonshot-grader-contract-v1",
            prompt=changed_prompt,
            model_config_id=original.model_config_id,
            model_config_version=original.model_config_version,
            inference_parameter_hash=original.inference_parameter_hash,
            corpus=corpus,
        )

        self.assertNotEqual(
            original.evaluation_identity_sha256,
            changed.evaluation_identity_sha256,
        )
        self.assertEqual(
            EvaluationExecutionIdentity.from_dict(original.as_dict()),
            original,
        )

    def test_offline_plan_pins_six_execution_identities(self) -> None:
        repo = Path(__file__).parents[1]
        prompt_payload = json.loads(
            (
                repo
                / "packages"
                / "prompts"
                / "biotech_moonshot_catalyst_assessment.v1.json"
            ).read_text()
        )
        prompts = {
            item.execution_role: item
            for item in (
                PromptTemplate.from_dict(value)
                for value in prompt_payload["templates"]
            )
        }
        corpus = EvaluationCorpus.from_dict(
            json.loads(
                (
                    repo
                    / "tests"
                    / "fixtures"
                    / "production_evaluation"
                    / "biotech_committee_offline.v1.json"
                ).read_text()
            )
        )
        plan = json.loads(
            (
                repo
                / "tests"
                / "fixtures"
                / "production_evaluation"
                / "execution-identities.v1.json"
            ).read_text()
        )
        identities = tuple(
            EvaluationExecutionIdentity.from_dict(item)
            for item in plan["execution_identities"]
        )

        self.assertEqual(
            tuple(item.execution_role for item in identities),
            corpus.execution_roles,
        )
        self.assertTrue(
            all(
                item.prompt_content_sha256
                == prompts[item.execution_role].content_sha256
                and item.corpus_content_sha256 == corpus.content_sha256
                for item in identities
            )
        )
        self.assertEqual(
            len({item.evaluation_identity_sha256 for item in identities}),
            6,
        )


if __name__ == "__main__":
    unittest.main()
