from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

from investment_research_os.production_execution import EvaluationCorpus
from investment_research_os.providers.openai_contracts import (
    OpenAIEvaluationExecutionIdentity,
    OpenAIExecutionContractRegistry,
)
from investment_research_os.providers.openai_evaluation import (
    FrozenOpenAIEvaluationRunner,
)


REPO = Path(__file__).parents[1]


def frozen_inputs():
    registry = OpenAIExecutionContractRegistry.load(
        contract_path=(
            REPO
            / "packages"
            / "providers"
            / "openai"
            / "biotech_moonshot_catalyst_assessment.v1.json"
        ),
        prompt_path=(
            REPO
            / "packages"
            / "prompts"
            / "biotech_moonshot_catalyst_assessment.v1.json"
        ),
    )
    corpus = EvaluationCorpus.from_dict(
        json.loads(
            (
                REPO
                / "tests"
                / "fixtures"
                / "production_evaluation"
                / "biotech_committee_offline.v1.json"
            ).read_text()
        )
    )
    inference_hash = "4e9bd07b4728e99c74ec0ef72ac6e045a8041637876df4a4c328ed1832b7f3cd"
    identities = tuple(
        OpenAIEvaluationExecutionIdentity.freeze(
            contract=contract,
            model_config_id=(
                "biotech_committee_synthesizer_gpt_5_6_sol_medium_v1"
                if contract.execution_role == "synthesizer"
                else "biotech_committee_graders_openai_sol_medium_v1"
            ),
            model_config_version=(
                "biotech_committee_synthesizer_gpt_5_6_sol_medium_v1"
                if contract.execution_role == "synthesizer"
                else "biotech_committee_graders_openai_sol_medium_v1"
            ),
            inference_parameter_hash=inference_hash,
            price_card_id="gpt_5_6_sol_usd.v1",
            price_card_content_sha256="b" * 64,
            corpus=corpus,
        )
        for contract in registry.contracts
    )
    return corpus, identities


class FrozenOpenAIEvaluationRunnerTests(unittest.TestCase):
    def test_fake_six_role_run_emits_sanitized_automatic_results(self) -> None:
        corpus, identities = frozen_inputs()
        fixture = json.loads(
            (
                REPO
                / "tests"
                / "fixtures"
                / "production_evaluation"
                / "fake-six-role-results.v2.json"
            ).read_text()
        )

        report = FrozenOpenAIEvaluationRunner(
            corpus=corpus,
            execution_identities=identities,
        ).run(fixture)
        rendered = report.as_dict()
        checks = {item["check_id"]: item["status"] for item in rendered["checks"]}

        self.assertEqual(
            checks,
            {
                "grader_schema_valid": "passed",
                "grader_citations_valid": "passed",
                "synthesis_schema_valid": "passed",
                "synthesis_provenance_valid": "passed",
                "synthesis_authority_valid": "passed",
                "usage_within_token_caps": "passed",
                "estimated_cost_within_hard_budgets": "passed",
                "operator_sample_memo_approved": "pending_hitl",
            },
        )
        self.assertEqual(rendered["usage"]["input_tokens"], 600)
        self.assertEqual(rendered["usage"]["output_tokens"], 120)
        self.assertEqual(rendered["usage"]["total_tokens"], 720)
        self.assertEqual(rendered["estimated_cost_usd"], "0.006")
        self.assertRegex(rendered["content_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            rendered["content_sha256"],
            hashlib.sha256(
                json.dumps(
                    {
                        key: value
                        for key, value in rendered.items()
                        if key != "content_sha256"
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode()
            ).hexdigest(),
        )
        serialized = json.dumps(rendered).lower()
        for forbidden in (
            "authorization",
            "api_key",
            "raw_request",
            "raw_response",
            "reasoning_content",
        ):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
