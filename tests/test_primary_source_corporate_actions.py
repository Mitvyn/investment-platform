from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
import hashlib
import unittest

from workers.primary_sources.corporate_actions import reconcile_corporate_actions
from workers.primary_sources.models import PrimarySourceRequest
from workers.primary_sources.pipeline import PrimaryEvidencePassage


OPERATOR_ID = "8ed47ebc-d5cf-40ad-80ce-d4d803f7c735"
SECURITY_ID = "f594edb2-7fff-4e40-9c26-2c06bcbecb91"
CIK = "0001601830"
CUTOFF = datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC)
FROM_PERIOD = date(2025, 12, 31)
TO_PERIOD = date(2026, 3, 31)
NO_ACTION = (
    "From 2025-12-31 through 2026-03-31, no stock split, reverse stock split, "
    "recapitalization, share class conversion, merger conversion, or other "
    "corporate action changed the basic common share economic basis."
)
REVERSE_SPLIT = (
    "From 2025-12-31 through 2026-03-31, a 1-for-10 reverse stock split "
    "became effective on 2026-02-01 and changed the basic common share "
    "economic basis."
)
RXRX_COMPARATIVE_SHARE_BASIS = (
    "Common stock, $ 0.00001 par value; 2,000,000,000 shares "
    "(Class A 1,989,032,117 and Class B 10,967,883 ) authorized as of "
    "March 31, 2026 and December 31, 2025; 530,628,653 shares "
    "(Class A 524,464,320 , Class B 5,307,334 and Exchangeable 856,999 ) "
    "and 528,182,693 shares (Class A 521,831,046 , Class B 5,547,334 and "
    "Exchangeable 804,313 ) issued and outstanding as of March 31, 2026 "
    "and December 31, 2025, respectively"
)
SLS_COMPARATIVE_SHARE_BASIS = (
    "Common stock, $ 0.0001 par value; 350,000,000 shares authorized, "
    "153,103,459 and 73,977,459 shares issued and outstanding at "
    "December 31, 2025 and 2024, respectively"
)


def request() -> PrimarySourceRequest:
    return PrimarySourceRequest(
        operator_id=OPERATOR_ID,
        security_id=SECURITY_ID,
        cik=CIK,
        issuer_name="Example Therapeutics, Inc.",
        primary_listing_exchange="NASDAQ",
        as_of_cutoff=CUTOFF,
    )


def passage(
    text: str = NO_ACTION,
    *,
    reference_key: str = "corporate-action:basis-reconciliation",
) -> PrimaryEvidencePassage:
    return PrimaryEvidencePassage(
        reference_key=reference_key,
        source_class="financing",
        coverage_keys=frozenset(),
        source_locator=("0001601830-26-000040/issuer-20260331.htm#corporate-action"),
        canonical_url=(
            "https://www.sec.gov/Archives/edgar/data/1601830/"
            "000160183026000040/issuer-20260331.htm"
        ),
        publication_at=datetime(2026, 5, 6, 10, 32, 40, tzinfo=UTC),
        retrieved_at=datetime(2026, 5, 7, 1, tzinfo=UTC),
        effective_at=None,
        filing_period_start=FROM_PERIOD,
        filing_period_end=TO_PERIOD,
        document_content_hash=hashlib.sha256(text.encode()).hexdigest(),
        passage_text=text,
        freshness="current",
        origin_policy_version="sec-origin-v1",
        available_at=datetime(2026, 5, 6, 10, 32, 40, tzinfo=UTC),
    )


class CorporateActionReconciliationTests(unittest.TestCase):
    def test_explicit_no_action_verifies_factor_one_with_provenance(self) -> None:
        result = reconcile_corporate_actions(
            request=request(),
            passages=(passage(),),
            from_period_end=FROM_PERIOD,
            to_period_end=TO_PERIOD,
        )

        self.assertEqual(result.state, "verified")
        self.assertEqual(result.reason_codes, ("corporate_action_no_action_verified",))
        self.assertIsNotNone(result.reconciliation)
        assert result.reconciliation is not None
        self.assertEqual(result.reconciliation.prior_to_current_factor, "1")
        self.assertEqual(
            result.reconciliation.evidence_reference_keys,
            ("corporate-action:basis-reconciliation",),
        )

    def test_comparative_sec_share_basis_verifies_factor_one(self) -> None:
        result = reconcile_corporate_actions(
            request=request(),
            passages=(passage(RXRX_COMPARATIVE_SHARE_BASIS),),
            from_period_end=FROM_PERIOD,
            to_period_end=TO_PERIOD,
        )

        self.assertEqual(result.state, "verified")
        self.assertEqual(
            result.reason_codes,
            ("corporate_action_comparative_basis_verified",),
        )
        self.assertIsNotNone(result.reconciliation)
        assert result.reconciliation is not None
        self.assertEqual(result.reconciliation.prior_to_current_factor, "1")

    def test_comparative_balance_sheet_share_basis_verifies_factor_one(self) -> None:
        result = reconcile_corporate_actions(
            request=request(),
            passages=(passage(SLS_COMPARATIVE_SHARE_BASIS),),
            from_period_end=date(2024, 12, 31),
            to_period_end=date(2025, 12, 31),
        )

        self.assertEqual(result.state, "verified")
        self.assertEqual(
            result.reason_codes,
            ("corporate_action_comparative_basis_verified",),
        )
        self.assertIsNotNone(result.reconciliation)
        assert result.reconciliation is not None
        self.assertEqual(result.reconciliation.prior_to_current_factor, "1")

    def test_explicit_reverse_split_derives_prior_to_current_factor(self) -> None:
        result = reconcile_corporate_actions(
            request=request(),
            passages=(passage(REVERSE_SPLIT),),
            from_period_end=FROM_PERIOD,
            to_period_end=TO_PERIOD,
        )

        self.assertEqual(result.state, "verified")
        assert result.reconciliation is not None
        self.assertEqual(result.reconciliation.prior_to_current_factor, "0.1")
        self.assertEqual(result.reason_codes, ("corporate_action_split_verified",))

    def test_missing_evidence_never_defaults_to_factor_one(self) -> None:
        result = reconcile_corporate_actions(
            request=request(),
            passages=(),
            from_period_end=FROM_PERIOD,
            to_period_end=TO_PERIOD,
        )

        self.assertEqual(result.state, "unresolved")
        self.assertIsNone(result.reconciliation)
        self.assertEqual(result.reason_codes, ("corporate_action_evidence_missing",))

    def test_period_mismatch_and_post_cutoff_evidence_fail_closed(self) -> None:
        mismatched = passage(NO_ACTION.replace("2025-12-31", "2025-09-30"))
        late = replace(
            passage(),
            publication_at=datetime(2026, 5, 7, tzinfo=UTC),
            available_at=datetime(2026, 5, 7, tzinfo=UTC),
        )
        for evidence, reason in (
            (mismatched, "corporate_action_period_mismatch"),
            (late, "corporate_action_evidence_after_cutoff"),
        ):
            with self.subTest(reason=reason):
                result = reconcile_corporate_actions(
                    request=request(),
                    passages=(evidence,),
                    from_period_end=FROM_PERIOD,
                    to_period_end=TO_PERIOD,
                )
                self.assertEqual(result.state, "unresolved")
                self.assertEqual(result.reason_codes, (reason,))

    def test_conflicting_records_remain_unresolved(self) -> None:
        result = reconcile_corporate_actions(
            request=request(),
            passages=(
                passage(),
                passage(REVERSE_SPLIT, reference_key="corporate-action:split"),
            ),
            from_period_end=FROM_PERIOD,
            to_period_end=TO_PERIOD,
        )

        self.assertEqual(result.state, "unresolved")
        self.assertIsNone(result.reconciliation)
        self.assertEqual(result.reason_codes, ("corporate_action_evidence_conflict",))

    def test_untrusted_origin_or_invalid_ratio_fails_closed(self) -> None:
        invalid_ratio = passage(REVERSE_SPLIT.replace("1-for-10", "10-for-1"))
        untrusted = replace(passage(), canonical_url="https://example.com/action")
        for evidence, reason in (
            (invalid_ratio, "corporate_action_ratio_invalid"),
            (untrusted, "corporate_action_source_invalid"),
        ):
            with self.subTest(reason=reason):
                result = reconcile_corporate_actions(
                    request=request(),
                    passages=(evidence,),
                    from_period_end=FROM_PERIOD,
                    to_period_end=TO_PERIOD,
                )
                self.assertEqual(result.state, "unresolved")
                self.assertEqual(result.reason_codes, (reason,))


if __name__ == "__main__":
    unittest.main()
