from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace

from investment_research_os.evidence_bundles import CatalystSnapshot
from investment_research_os.valuation_snapshots.materiality import (
    FrozenEvidenceMaterialityPort,
)
from tests.test_evidence_bundle_storage import materialized_bundle
from tests.test_valuation_snapshot_workflow import SESSION


class FrozenEvidenceMaterialityPortTests(unittest.TestCase):
    def test_classifies_structured_catalyst_identity_and_unresolved_evidence(
        self,
    ) -> None:
        base = materialized_bundle()
        catalyst_item, catalyst_passage, identity_passage, unresolved = base.manifest[
            :4
        ]
        catalyst_item = replace(catalyst_item, item_kind="catalyst")
        bundle = replace(
            base,
            manifest=(
                catalyst_item,
                catalyst_passage,
                identity_passage,
                unresolved,
            ),
            catalysts=(
                CatalystSnapshot(
                    snapshot_id=catalyst_item.evidence_id,
                    event="Phase 2 data",
                    program="Programme A",
                    basis="clinical",
                    status="expected",
                    window_start=SESSION.session_date,
                    window_end=SESSION.session_date,
                    supporting_evidence_ids=(catalyst_passage.evidence_id,),
                ),
            ),
            metrics=(),
            risks=(),
            eligibility=SimpleNamespace(
                checks=(
                    SimpleNamespace(
                        rule_id="security_identity_verified",
                        evidence_reference=identity_passage.evidence_id,
                    ),
                ),
            ),
        )

        result = FrozenEvidenceMaterialityPort().assess(bundle, SESSION)

        by_id = {item.evidence_id: item for item in result.assessments}
        self.assertEqual(result.policy_version, "biotech-market-materiality-v1")
        self.assertEqual(
            by_id[catalyst_item.evidence_id].market_materiality,
            "material",
        )
        self.assertEqual(
            by_id[catalyst_passage.evidence_id].affected_domains,
            ("catalyst", "clinical"),
        )
        self.assertEqual(
            by_id[identity_passage.evidence_id].market_materiality,
            "non_material",
        )
        self.assertEqual(
            by_id[unresolved.evidence_id].market_materiality,
            "indeterminate",
        )


if __name__ == "__main__":
    unittest.main()
