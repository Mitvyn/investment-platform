from __future__ import annotations

from decimal import Decimal
import unittest

from investment_research_os.quant import ParticipationLimit, QuantContractError


class ParticipationLimitTests(unittest.TestCase):
    def test_truncates_execution_session_volume_to_participation_cap(self) -> None:
        limit = ParticipationLimit(
            max_participation_bps=Decimal("100"),
            volume_basis="execution_bar",
            zero_volume_policy="block",
            unfilled_policy="cancel",
            min_fill_shares=0,
        )

        self.assertEqual(limit.cap_for_volume(1_000), 10)
        self.assertEqual(limit.cap_for_volume(999), 9)

    def test_contract_rejects_unsafe_rate_and_policy_values(self) -> None:
        common = {
            "volume_basis": "execution_bar",
            "zero_volume_policy": "block",
            "unfilled_policy": "cancel",
            "min_fill_shares": 0,
        }
        for rate in (Decimal("-1"), Decimal("10000.01"), 0.05):
            with self.subTest(rate=rate):
                with self.assertRaisesRegex(
                    QuantContractError, "max_participation_bps"
                ):
                    ParticipationLimit(max_participation_bps=rate, **common)

        with self.assertRaisesRegex(QuantContractError, "min_fill_shares"):
            ParticipationLimit(
                max_participation_bps=Decimal("100"),
                **{**common, "min_fill_shares": True},
            )

    def test_hash_pins_every_declared_liquidity_input(self) -> None:
        common = {
            "volume_basis": "execution_bar",
            "zero_volume_policy": "block",
            "unfilled_policy": "cancel",
            "min_fill_shares": 0,
        }
        first = ParticipationLimit(
            max_participation_bps=Decimal("100"),
            **common,
        )
        same_value = ParticipationLimit(
            max_participation_bps=Decimal("100.0"),
            **common,
        )
        changed = ParticipationLimit(
            max_participation_bps=Decimal("101"),
            **common,
        )

        self.assertEqual(first.content_sha256, same_value.content_sha256)
        self.assertNotEqual(first.content_sha256, changed.content_sha256)


if __name__ == "__main__":
    unittest.main()
