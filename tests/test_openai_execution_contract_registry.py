from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import hashlib
import json
import tempfile
import unittest

from investment_research_os.production_execution import (
    EvaluationCorpus,
    MVP_EVALUATION_EXECUTION_ROLES,
)
from investment_research_os.grader_executions import ProviderRequest
from investment_research_os.providers.openai_contracts import (
    OpenAIEvaluationExecutionIdentity,
    OpenAIExecutionContractRegistry,
)
from investment_research_os.research_workflows import (
    build_inactive_production_personal_research_mvp_config,
    build_personal_research_mvp_config,
)


REPO = Path(__file__).parents[1]
CONTRACTS = (
    REPO
    / "packages"
    / "providers"
    / "openai"
    / "biotech_moonshot_catalyst_assessment.v1.json"
)
PROMPTS = REPO / "packages" / "prompts" / "biotech_moonshot_catalyst_assessment.v1.json"
CORPUS = (
    REPO
    / "tests"
    / "fixtures"
    / "production_evaluation"
    / "biotech_committee_offline.v1.json"
)


def provider_request(contract, logical_input) -> ProviderRequest:
    return ProviderRequest(
        execution_identity="b" * 64,
        request_hash="c" * 64,
        provider="openai",
        model="gpt-5.6-sol",
        logical_input=logical_input,
        reasoning_effort="medium",
        thinking_enabled=True,
        temperature="provider_default",
        input_token_cap=16_000,
        output_token_cap=2_000,
        execution_role=contract.execution_role,
        prompt_id=contract.prompt.prompt_id,
        prompt_version=contract.prompt.prompt_version,
        prompt_content_sha256=contract.prompt.content_sha256,
        input_schema_version=contract.prompt.input_schema_version,
        output_schema_version=contract.prompt.output_schema_version,
        attempt_number=1,
        validation_errors=(),
    )


def content_hash(value) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def rehash_registry(payload) -> None:
    for contract in payload["contracts"]:
        contract["content_sha256"] = content_hash(
            {key: value for key, value in contract.items() if key != "content_sha256"}
        )
    payload["content_sha256"] = content_hash(
        {key: value for key, value in payload.items() if key != "content_sha256"}
    )


class OpenAIExecutionContractRegistryTests(unittest.TestCase):
    def test_offline_and_production_profiles_have_distinct_identities(self) -> None:
        offline = build_personal_research_mvp_config()
        production = build_inactive_production_personal_research_mvp_config()

        self.assertNotEqual(
            offline.contract_fingerprint,
            production.contract_fingerprint,
        )

        for grader in offline.graders:
            self.assertEqual(grader.model.environment, "test")
            self.assertEqual(grader.model.temperature, "0")
            self.assertEqual(grader.policy.required_environment, "test")
            self.assertNotEqual(
                grader.model.config_version,
                production.graders[0].model.config_version,
            )
            self.assertNotEqual(grader.model, production.graders[0].model)

        self.assertEqual(offline.synthesizer.model.environment, "test")
        self.assertEqual(offline.synthesizer.model.temperature, "0")
        self.assertEqual(
            offline.synthesizer.policy.required_environment,
            "test",
        )
        self.assertNotEqual(
            offline.synthesizer.model.config_version,
            production.synthesizer.model.config_version,
        )
        self.assertNotEqual(
            offline.synthesizer.model,
            production.synthesizer.model,
        )

    def test_inactive_personal_production_config_matches_approved_profile(
        self,
    ) -> None:
        config = build_inactive_production_personal_research_mvp_config()

        self.assertEqual(len(config.graders), 5)
        for grader in config.graders:
            self.assertEqual(
                grader.model.config_id,
                "biotech_committee_graders_openai_sol_medium_v1",
            )
            self.assertEqual(grader.model.temperature, "provider_default")
            self.assertEqual(grader.model.input_token_cap, 48_000)
            self.assertEqual(grader.model.output_token_cap, 4_000)
            self.assertEqual(grader.model.environment, "production")
            self.assertFalse(grader.model.active)
            self.assertFalse(grader.model.evaluation_passed)
            self.assertFalse(grader.prompt.active)
            self.assertFalse(grader.prompt.evaluation_passed)
            self.assertEqual(
                grader.policy.required_environment,
                "production",
            )
            self.assertEqual(str(grader.price_card.cache_write_per_million), "6.25")
            self.assertEqual(
                grader.price_card.effective_to.date().isoformat(),
                "2026-08-21",
            )

        synthesizer = config.synthesizer
        self.assertEqual(
            synthesizer.model.config_id,
            "biotech_committee_synthesizer_gpt_5_6_sol_medium_v1",
        )
        self.assertEqual(synthesizer.model.temperature, "provider_default")
        self.assertEqual(synthesizer.model.input_token_cap, 160_000)
        self.assertEqual(synthesizer.model.output_token_cap, 6_000)
        self.assertEqual(synthesizer.model.environment, "production")
        self.assertFalse(synthesizer.model.active)
        self.assertFalse(synthesizer.model.evaluation_passed)
        self.assertFalse(synthesizer.prompt.active)
        self.assertFalse(synthesizer.prompt.evaluation_passed)
        self.assertEqual(
            synthesizer.policy.required_environment,
            "production",
        )
        self.assertEqual(
            str(synthesizer.price_card.cache_write_per_million),
            "6.25",
        )
        self.assertEqual(
            synthesizer.price_card.effective_to.date().isoformat(),
            "2026-08-21",
        )

    def test_loads_exact_frozen_six_role_registry(self) -> None:
        registry = OpenAIExecutionContractRegistry.load(
            contract_path=CONTRACTS,
            prompt_path=PROMPTS,
        )

        self.assertEqual(registry.execution_roles, MVP_EVALUATION_EXECUTION_ROLES)
        self.assertEqual(len(registry.contracts), 6)
        for contract in registry.contracts:
            self.assertRegex(contract.output_schema_content_sha256, r"^[0-9a-f]{64}$")
            self.assertRegex(contract.content_sha256, r"^[0-9a-f]{64}$")
            self.assertEqual(contract.output_schema["type"], "object")
            self.assertFalse(contract.output_schema["additionalProperties"])

    def test_rejects_reordered_execution_roster(self) -> None:
        payload = json.loads(CONTRACTS.read_text())
        payload["execution_roles"][0], payload["execution_roles"][1] = (
            payload["execution_roles"][1],
            payload["execution_roles"][0],
        )
        with tempfile.TemporaryDirectory() as directory:
            drifted = Path(directory) / "contracts.json"
            drifted.write_text(json.dumps(payload))

            with self.assertRaisesRegex(
                ValueError,
                "execution contract registry roster mismatch",
            ):
                OpenAIExecutionContractRegistry.load(
                    contract_path=drifted,
                    prompt_path=PROMPTS,
                )

    def test_grader_resolver_rejects_another_opinion_in_logical_input(self) -> None:
        registry = OpenAIExecutionContractRegistry.load(
            contract_path=CONTRACTS,
            prompt_path=PROMPTS,
        )
        contract = registry.contracts[0]
        logical_input = {
            "bundle": {"bundle_id": "bundle-1"},
            "evidence_passages": [],
            "valuation_snapshot": None,
            "question_type_id": "biotech_moonshot_catalyst_assessment",
            "question_type_version": registry.question_type_version,
            "workflow_config_version": registry.workflow_config_version,
            "proposition_id": "biotech_moonshot_catalyst_case",
            "proposition_version": "biotech_moonshot_catalyst_case.v1",
            "rendered_proposition": "Frozen proposition.",
            "grader": {"grader_id": "moonshot"},
            "execution_contract": {
                "execution_contract_version": contract.execution_contract_version,
                "content_sha256": contract.content_sha256,
                "owned_decision_question": contract.owned_decision_question,
                "eligibility_rule_version": contract.eligibility_rule_version,
                "eligibility_rules": list(contract.eligibility_rules),
                "rubric_version": contract.rubric_version,
                "rubric": list(contract.rubric),
                "abstention_rule_version": contract.abstention_rule_version,
                "abstention_rules": list(contract.abstention_rules),
                "authority_rules": list(contract.authority_rules),
                "output_schema_content_sha256": (contract.output_schema_content_sha256),
            },
            "grader_opinions": [{"grader_id": "catalyst"}],
        }
        request = provider_request(contract, logical_input)

        with self.assertRaisesRegex(
            ValueError,
            "grader logical input boundary violation",
        ):
            registry.resolve(request)

    def test_synthesizer_resolver_rejects_frozen_bundle_content(self) -> None:
        registry = OpenAIExecutionContractRegistry.load(
            contract_path=CONTRACTS,
            prompt_path=PROMPTS,
        )
        contract = registry.contracts[-1]
        logical_input = {
            "committee": {
                "contract_version": "committee_state.v1",
                "grader_results": [],
            },
            "calculation_ids": [],
            "authority": "reconciliation_only",
            "prompt": {
                "prompt_version": contract.prompt.prompt_version,
                "content_sha256": contract.prompt.content_sha256,
            },
            "execution_contract": contract.logical_input_contract(),
            "bundle": {"passages": ["must not be visible to synthesis"]},
        }

        with self.assertRaisesRegex(
            ValueError,
            "synthesizer logical input boundary violation",
        ):
            registry.resolve(provider_request(contract, logical_input))

    def test_evaluation_identity_changes_when_output_schema_changes(self) -> None:
        registry = OpenAIExecutionContractRegistry.load(
            contract_path=CONTRACTS,
            prompt_path=PROMPTS,
        )
        contract = registry.contracts[0]
        corpus = EvaluationCorpus.from_dict(json.loads(CORPUS.read_text()))
        original = OpenAIEvaluationExecutionIdentity.freeze(
            contract=contract,
            model_config_id="biotech_committee_graders_openai_sol_medium_v1",
            model_config_version=("biotech_committee_graders_openai_sol_medium_v1"),
            inference_parameter_hash="a" * 64,
            price_card_id="gpt_5_6_sol_usd.v1",
            price_card_content_sha256="b" * 64,
            corpus=corpus,
        )
        drifted = OpenAIEvaluationExecutionIdentity.freeze(
            contract=replace(
                contract,
                output_schema_content_sha256="c" * 64,
                content_sha256="d" * 64,
            ),
            model_config_id=original.model_config_id,
            model_config_version=original.model_config_version,
            inference_parameter_hash=original.inference_parameter_hash,
            price_card_id=original.price_card_id,
            price_card_content_sha256=original.price_card_content_sha256,
            corpus=corpus,
        )

        self.assertNotEqual(
            original.evaluation_identity_sha256,
            drifted.evaluation_identity_sha256,
        )
        self.assertEqual(
            original.output_schema_content_sha256,
            contract.output_schema_content_sha256,
        )
        self.assertEqual(
            original.execution_contract_content_sha256,
            contract.content_sha256,
        )

    def test_rejects_self_consistent_prompt_binding_drift(self) -> None:
        payload = json.loads(CONTRACTS.read_text())
        payload["contracts"][0]["prompt_version"] = "moonshot_grader_v2"
        rehash_registry(payload)
        with tempfile.TemporaryDirectory() as directory:
            drifted = Path(directory) / "contracts.json"
            drifted.write_text(json.dumps(payload))

            with self.assertRaisesRegex(
                ValueError,
                "execution contract prompt binding mismatch",
            ):
                OpenAIExecutionContractRegistry.load(
                    contract_path=drifted,
                    prompt_path=PROMPTS,
                )

    def test_rejects_self_consistent_output_schema_hash_drift(self) -> None:
        payload = json.loads(CONTRACTS.read_text())
        payload["contracts"][0]["output_schema_content_sha256"] = "e" * 64
        rehash_registry(payload)
        with tempfile.TemporaryDirectory() as directory:
            drifted = Path(directory) / "contracts.json"
            drifted.write_text(json.dumps(payload))

            with self.assertRaisesRegex(
                ValueError,
                "output schema content hash mismatch",
            ):
                OpenAIExecutionContractRegistry.load(
                    contract_path=drifted,
                    prompt_path=PROMPTS,
                )


if __name__ == "__main__":
    unittest.main()
