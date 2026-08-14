from __future__ import annotations

from datetime import date, datetime
from decimal import localcontext
import unittest

from investment_research_os.quant import (
    CorporateActionSet,
    QuantContractError,
    StockSplit,
)


SECURITY_ID = "3f1b0c2e-9d4a-4c7f-b1e2-8a5d6c7f0912"


class StockSplitContractTests(unittest.TestCase):
    def test_equivalent_ratios_have_one_canonical_identity(self) -> None:
        first = StockSplit(
            effective_session=date(2026, 2, 2),
            new_shares=4,
            old_shares=2,
        )
        second = StockSplit(
            effective_session=date(2026, 2, 2),
            new_shares=2,
            old_shares=1,
        )

        self.assertEqual(first, second)
        self.assertEqual(first.to_record(), second.to_record())

    def test_rejects_invalid_split_dates_and_ratios(self) -> None:
        invalid = (
            (datetime(2026, 2, 2), 2, 1),
            (date(2026, 2, 2), True, 1),
            (date(2026, 2, 2), 2, False),
            (date(2026, 2, 2), 0, 1),
            (date(2026, 2, 2), 2, -1),
            (date(2026, 2, 2), 1, 1),
        )
        for effective_session, new_shares, old_shares in invalid:
            with self.subTest(
                effective_session=effective_session,
                new_shares=new_shares,
                old_shares=old_shares,
            ):
                with self.assertRaises(QuantContractError):
                    StockSplit(
                        effective_session=effective_session,  # type: ignore[arg-type]
                        new_shares=new_shares,
                        old_shares=old_shares,
                    )


class CorporateActionSetTests(unittest.TestCase):
    def test_requires_strict_action_order_and_canonical_security(self) -> None:
        later = StockSplit(date(2026, 3, 2), 2, 1)
        earlier = StockSplit(date(2026, 2, 2), 3, 1)
        for actions in ((later, earlier), (earlier, earlier)):
            with self.subTest(actions=actions):
                with self.assertRaisesRegex(
                    QuantContractError,
                    "strictly increasing",
                ):
                    CorporateActionSet(
                        security_id=SECURITY_ID,
                        source="fixture",
                        actions=actions,
                    )
        with self.assertRaisesRegex(QuantContractError, "canonical security UUID"):
            CorporateActionSet(
                security_id=SECURITY_ID.upper(),
                source="fixture",
                actions=(),
            )

    def test_hash_is_context_independent_and_pins_source_and_actions(self) -> None:
        actions = (
            StockSplit(date(2026, 2, 2), 2, 1),
            StockSplit(date(2026, 3, 2), 1, 5),
        )
        subject = CorporateActionSet(
            security_id=SECURITY_ID,
            source="fixture",
            actions=actions,
        )
        with localcontext() as context:
            context.prec = 6
            low_precision_hash = subject.content_sha256
        with localcontext() as context:
            context.prec = 28
            normal_precision_hash = subject.content_sha256

        self.assertEqual(low_precision_hash, normal_precision_hash)
        self.assertNotEqual(
            subject.content_sha256,
            CorporateActionSet(
                security_id=SECURITY_ID,
                source="other-fixture",
                actions=actions,
            ).content_sha256,
        )
        self.assertNotEqual(
            subject.content_sha256,
            CorporateActionSet(
                security_id=SECURITY_ID,
                source="fixture",
                actions=(StockSplit(date(2026, 2, 2), 3, 1), actions[1]),
            ).content_sha256,
        )


if __name__ == "__main__":
    unittest.main()
