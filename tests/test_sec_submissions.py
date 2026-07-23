from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from pathlib import Path
import unittest

from workers.primary_sources.models import PrimarySourceRequest
from workers.sec.collector import BytesResponse, SecSettings
from workers.sec.submissions import SecSubmissionsCollector, SecSubmissionsError


FIXTURE_ROOT = Path("tests/fixtures/primary_sources")
OPERATOR_ID = "8ed47ebc-d5cf-40ad-80ce-d4d803f7c735"
CUTOFF = datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC)


class FixtureTransport:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = payloads
        self.requests: list[tuple[str, dict[str, str]]] = []

    def request(self, url: str, *, headers):
        self.requests.append((url, dict(headers)))
        body = self.payloads[url]
        return BytesResponse(
            body=body,
            status=200,
            headers={"Content-Type": "application/json"},
        )


def request(
    *,
    security_id: str,
    cik: str,
    issuer_name: str,
) -> PrimarySourceRequest:
    return PrimarySourceRequest(
        operator_id=OPERATOR_ID,
        security_id=security_id,
        cik=cik,
        issuer_name=issuer_name,
        primary_listing_exchange="NASDAQ",
        as_of_cutoff=CUTOFF,
    )


class SecSubmissionsCollectorTests(unittest.TestCase):
    def test_collector_accepts_only_authoritative_sec_submissions_origin(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "SEC submissions base URL is unsupported",
        ):
            SecSubmissionsCollector(
                SecSettings(
                    user_agent="Investment Research OS operator@example.com",
                    base_url="https://example.com",
                ),
                transport=FixtureTransport({}),
            )

    def test_discovers_cik_filings_and_preserves_explicit_cutoff_outcomes(
        self,
    ) -> None:
        body = (FIXTURE_ROOT / "rxrx-submissions.json").read_bytes()
        url = "https://data.sec.gov/submissions/CIK0001601830.json"
        transport = FixtureTransport({url: body})
        collector = SecSubmissionsCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
                base_url="https://data.sec.gov",
            ),
            transport=transport,
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )

        snapshot = collector.discover(
            request(
                security_id="f594edb2-7fff-4e40-9c26-2c06bcbecb91",
                cik="0001601830",
                issuer_name="Recursion Pharmaceuticals, Inc.",
            )
        )

        self.assertEqual(snapshot.operator_id, OPERATOR_ID)
        self.assertEqual(snapshot.security_id, "f594edb2-7fff-4e40-9c26-2c06bcbecb91")
        self.assertEqual(snapshot.cik, "0001601830")
        self.assertEqual(snapshot.as_of_cutoff, CUTOFF)
        self.assertEqual(snapshot.content_sha256, hashlib.sha256(body).hexdigest())
        self.assertEqual(
            [item.accession_number for item in snapshot.included_filings],
            ["0001601830-26-000040", "0001601830-26-000041"],
        )
        self.assertEqual(
            [item.reason_code for item in snapshot.excluded_filings],
            ["publication_after_cutoff", "publication_timezone_unresolved"],
        )
        self.assertEqual(
            transport.requests,
            [
                (
                    url,
                    {
                        "Accept": "application/json",
                        "User-Agent": "Investment Research OS operator@example.com",
                    },
                )
            ],
        )

    def test_same_collector_handles_materially_different_cik_without_symbol(
        self,
    ) -> None:
        first_url = "https://data.sec.gov/submissions/CIK0001601830.json"
        second_url = "https://data.sec.gov/submissions/CIK0001900001.json"
        transport = FixtureTransport(
            {
                first_url: (FIXTURE_ROOT / "rxrx-submissions.json").read_bytes(),
                second_url: (
                    FIXTURE_ROOT / "single-asset-submissions.json"
                ).read_bytes(),
            }
        )
        collector = SecSubmissionsCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
                base_url="https://data.sec.gov",
            ),
            transport=transport,
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )

        first = collector.discover(
            request(
                security_id="f594edb2-7fff-4e40-9c26-2c06bcbecb91",
                cik="0001601830",
                issuer_name="Recursion Pharmaceuticals, Inc.",
            )
        )
        second = collector.discover(
            request(
                security_id="8f121435-e5af-4df5-8328-d191463a50ae",
                cik="0001900001",
                issuer_name="Single Asset Therapeutics, Inc.",
            )
        )

        self.assertEqual(first.included_filings[0].form, "10-Q")
        self.assertEqual(second.included_filings[0].form, "10-Q")
        self.assertEqual(second.included_filings[0].publication_state, "exact")
        self.assertEqual(
            [call[0] for call in transport.requests],
            [first_url, second_url],
        )

    def test_identity_and_payload_shape_mismatches_fail_closed(self) -> None:
        body = (FIXTURE_ROOT / "rxrx-submissions.json").read_bytes()
        url = "https://data.sec.gov/submissions/CIK0001900001.json"
        collector = SecSubmissionsCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
                base_url="https://data.sec.gov",
            ),
            transport=FixtureTransport({url: body}),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )
        with self.assertRaisesRegex(SecSubmissionsError, "CIK mismatch"):
            collector.discover(
                request(
                    security_id="8f121435-e5af-4df5-8328-d191463a50ae",
                    cik="0001900001",
                    issuer_name="Single Asset Therapeutics, Inc.",
                )
            )

        wrong_accession = body.replace(
            b"0001601830-26-000040",
            b"0000000001-26-000040",
        )
        wrong_accession_collector = SecSubmissionsCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
                base_url="https://data.sec.gov",
            ),
            transport=FixtureTransport(
                {
                    "https://data.sec.gov/submissions/CIK0001601830.json": (
                        wrong_accession
                    )
                }
            ),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )
        with self.assertRaisesRegex(
            SecSubmissionsError,
            "filing CIK mismatch",
        ):
            wrong_accession_collector.discover(
                request(
                    security_id="f594edb2-7fff-4e40-9c26-2c06bcbecb91",
                    cik="0001601830",
                    issuer_name="Recursion Pharmaceuticals, Inc.",
                )
            )

        malformed = b'{"cik":"0001900001","name":"Issuer","filings":{"recent":{"form":[]}}}'
        malformed_collector = SecSubmissionsCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
                base_url="https://data.sec.gov",
            ),
            transport=FixtureTransport({url: malformed}),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )
        with self.assertRaisesRegex(SecSubmissionsError, "invalid recent filings"):
            malformed_collector.discover(
                request(
                    security_id="8f121435-e5af-4df5-8328-d191463a50ae",
                    cik="0001900001",
                    issuer_name="Single Asset Therapeutics, Inc.",
                )
            )


if __name__ == "__main__":
    unittest.main()
