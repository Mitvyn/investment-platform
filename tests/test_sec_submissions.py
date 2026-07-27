from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import unittest

from workers.primary_sources.models import PrimarySourceRequest
from workers.sec.collector import BytesResponse, SecSettings
from workers.sec.submissions import SecSubmissionsCollector, SecSubmissionsError


FIXTURE_ROOT = Path("tests/fixtures/primary_sources")
OPERATOR_ID = "8ed47ebc-d5cf-40ad-80ce-d4d803f7c735"
CUTOFF = datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC)


class FixtureTransport:
    def __init__(
        self,
        payloads: dict[str, bytes],
        *,
        final_urls: dict[str, str] | None = None,
    ) -> None:
        self.payloads = payloads
        self.final_urls = final_urls or {}
        self.requests: list[tuple[str, dict[str, str]]] = []

    def request(self, url: str, *, headers):
        self.requests.append((url, dict(headers)))
        body = self.payloads[url]
        return BytesResponse(
            body=body,
            status=200,
            headers={"Content-Type": "application/json"},
            final_url=self.final_urls.get(url, url),
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

    def test_redirected_root_submissions_response_is_rejected(self) -> None:
        url = "https://data.sec.gov/submissions/CIK0001601830.json"
        collector = SecSubmissionsCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
                base_url="https://data.sec.gov",
            ),
            transport=FixtureTransport(
                {url: (FIXTURE_ROOT / "rxrx-submissions.json").read_bytes()},
                final_urls={url: "https://example.com/redirected.json"},
            ),
        )

        with self.assertRaisesRegex(
            SecSubmissionsError,
            "submissions response redirected",
        ):
            collector.discover(
                request(
                    security_id="f594edb2-7fff-4e40-9c26-2c06bcbecb91",
                    cik="0001601830",
                    issuer_name="Recursion Pharmaceuticals, Inc.",
                )
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
            [
                "0001601830-26-000040",
                "0001601830-26-000041",
                "0001601830-26-000030",
            ],
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
        self.assertTrue(snapshot.submission_history_complete)
        self.assertEqual(snapshot.history_files, ())

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

    def test_discovery_fetches_and_merges_submission_history_chunks(self) -> None:
        payload = json.loads(
            (FIXTURE_ROOT / "rxrx-submissions.json").read_text()
        )
        payload["filings"]["files"] = [
            {
                "name": "CIK0001601830-submissions-001.json",
                "filingCount": 1,
                "filingFrom": "2024-02-20",
                "filingTo": "2024-02-20",
            }
        ]
        body = json.dumps(payload).encode()
        url = "https://data.sec.gov/submissions/CIK0001601830.json"
        history_url = (
            "https://data.sec.gov/submissions/"
            "CIK0001601830-submissions-001.json"
        )
        history_body = json.dumps(
            {
                "accessionNumber": ["0001601830-24-000030"],
                "acceptanceDateTime": ["2024-02-20T21:00:00Z"],
                "filingDate": ["2024-02-20"],
                "reportDate": ["2023-12-31"],
                "form": ["10-K"],
                "primaryDocument": ["rxrx-20231231.htm"],
            }
        ).encode()
        transport = FixtureTransport(
            {
                url: body,
                history_url: history_body,
            }
        )
        root_retrieved_at = datetime(2026, 5, 7, 1, 0, tzinfo=UTC)
        history_retrieved_at = datetime(2026, 5, 7, 1, 1, tzinfo=UTC)
        retrieval_times = iter((root_retrieved_at, history_retrieved_at))
        collector = SecSubmissionsCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
                base_url="https://data.sec.gov",
            ),
            transport=transport,
            clock=lambda: next(retrieval_times),
        )

        result = collector.discover(
            request(
                security_id="f594edb2-7fff-4e40-9c26-2c06bcbecb91",
                cik="0001601830",
                issuer_name="Recursion Pharmaceuticals, Inc.",
            )
        )

        self.assertTrue(result.submission_history_complete)
        self.assertEqual(len(result.history_files), 1)
        self.assertEqual(
            result.history_files[0].name,
            "CIK0001601830-submissions-001.json",
        )
        self.assertEqual(
            result.history_files[0].content_sha256,
            hashlib.sha256(history_body).hexdigest(),
        )
        self.assertEqual(result.retrieved_at, root_retrieved_at)
        self.assertEqual(
            result.history_files[0].retrieved_at,
            history_retrieved_at,
        )
        self.assertEqual(
            [item.accession_number for item in result.included_filings],
            [
                "0001601830-26-000040",
                "0001601830-26-000041",
                "0001601830-26-000030",
                "0001601830-24-000030",
            ],
        )
        self.assertEqual(
            [call[0] for call in transport.requests],
            [url, history_url],
        )
        self.assertEqual(result.source_url, url)

    def test_history_chunk_count_mismatch_fails_closed(self) -> None:
        payload = json.loads(
            (FIXTURE_ROOT / "rxrx-submissions.json").read_text()
        )
        history_name = "CIK0001601830-submissions-001.json"
        payload["filings"]["files"] = [
            {
                "name": history_name,
                "filingCount": 2,
                "filingFrom": "2024-02-20",
                "filingTo": "2024-02-20",
            }
        ]
        url = "https://data.sec.gov/submissions/CIK0001601830.json"
        history_url = f"https://data.sec.gov/submissions/{history_name}"
        history_body = json.dumps(
            {
                "accessionNumber": ["0001601830-24-000030"],
                "acceptanceDateTime": ["2024-02-20T21:00:00Z"],
                "filingDate": ["2024-02-20"],
                "reportDate": ["2023-12-31"],
                "form": ["10-K"],
                "primaryDocument": ["rxrx-20231231.htm"],
            }
        ).encode()
        collector = SecSubmissionsCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
                base_url="https://data.sec.gov",
            ),
            transport=FixtureTransport(
                {
                    url: json.dumps(payload).encode(),
                    history_url: history_body,
                }
            ),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )

        with self.assertRaisesRegex(
            SecSubmissionsError,
            "history filing count mismatch",
        ):
            collector.discover(
                request(
                    security_id="f594edb2-7fff-4e40-9c26-2c06bcbecb91",
                    cik="0001601830",
                    issuer_name="Recursion Pharmaceuticals, Inc.",
                )
            )

    def test_redirected_history_chunk_is_rejected(self) -> None:
        payload = json.loads(
            (FIXTURE_ROOT / "rxrx-submissions.json").read_text()
        )
        history_name = "CIK0001601830-submissions-001.json"
        payload["filings"]["files"] = [
            {
                "name": history_name,
                "filingCount": 1,
                "filingFrom": "2024-02-20",
                "filingTo": "2024-02-20",
            }
        ]
        url = "https://data.sec.gov/submissions/CIK0001601830.json"
        history_url = f"https://data.sec.gov/submissions/{history_name}"
        history_body = json.dumps(
            {
                "accessionNumber": ["0001601830-24-000030"],
                "acceptanceDateTime": ["2024-02-20T21:00:00Z"],
                "filingDate": ["2024-02-20"],
                "reportDate": ["2023-12-31"],
                "form": ["10-K"],
                "primaryDocument": ["rxrx-20231231.htm"],
            }
        ).encode()
        collector = SecSubmissionsCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
                base_url="https://data.sec.gov",
            ),
            transport=FixtureTransport(
                {
                    url: json.dumps(payload).encode(),
                    history_url: history_body,
                },
                final_urls={
                    history_url: "https://example.com/redirected.json"
                },
            ),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )

        with self.assertRaisesRegex(
            SecSubmissionsError,
            "history response redirected",
        ):
            collector.discover(
                request(
                    security_id="f594edb2-7fff-4e40-9c26-2c06bcbecb91",
                    cik="0001601830",
                    issuer_name="Recursion Pharmaceuticals, Inc.",
                )
            )

    def test_history_chunk_date_outside_advertised_window_fails_closed(
        self,
    ) -> None:
        payload = json.loads(
            (FIXTURE_ROOT / "rxrx-submissions.json").read_text()
        )
        history_name = "CIK0001601830-submissions-001.json"
        payload["filings"]["files"] = [
            {
                "name": history_name,
                "filingCount": 1,
                "filingFrom": "2024-02-20",
                "filingTo": "2024-02-20",
            }
        ]
        url = "https://data.sec.gov/submissions/CIK0001601830.json"
        history_url = f"https://data.sec.gov/submissions/{history_name}"
        history_body = json.dumps(
            {
                "accessionNumber": ["0001601830-23-000030"],
                "acceptanceDateTime": ["2023-02-20T21:00:00Z"],
                "filingDate": ["2023-02-20"],
                "reportDate": ["2022-12-31"],
                "form": ["10-K"],
                "primaryDocument": ["rxrx-20221231.htm"],
            }
        ).encode()
        collector = SecSubmissionsCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
                base_url="https://data.sec.gov",
            ),
            transport=FixtureTransport(
                {
                    url: json.dumps(payload).encode(),
                    history_url: history_body,
                }
            ),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )

        with self.assertRaisesRegex(
            SecSubmissionsError,
            "history filing date is outside advertised window",
        ):
            collector.discover(
                request(
                    security_id="f594edb2-7fff-4e40-9c26-2c06bcbecb91",
                    cik="0001601830",
                    issuer_name="Recursion Pharmaceuticals, Inc.",
                )
            )

    def test_history_chunk_name_must_match_requested_cik(self) -> None:
        payload = json.loads(
            (FIXTURE_ROOT / "rxrx-submissions.json").read_text()
        )
        payload["filings"]["files"] = [
            {
                "name": "CIK0001900001-submissions-001.json",
                "filingCount": 1,
                "filingFrom": "2024-02-20",
                "filingTo": "2024-02-20",
            }
        ]
        url = "https://data.sec.gov/submissions/CIK0001601830.json"
        collector = SecSubmissionsCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
                base_url="https://data.sec.gov",
            ),
            transport=FixtureTransport(
                {url: json.dumps(payload).encode()}
            ),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )

        with self.assertRaisesRegex(
            SecSubmissionsError,
            "history file CIK mismatch",
        ):
            collector.discover(
                request(
                    security_id="f594edb2-7fff-4e40-9c26-2c06bcbecb91",
                    cik="0001601830",
                    issuer_name="Recursion Pharmaceuticals, Inc.",
                )
            )

    def test_duplicate_history_chunk_reference_fails_before_fetch(self) -> None:
        payload = json.loads(
            (FIXTURE_ROOT / "rxrx-submissions.json").read_text()
        )
        history = {
            "name": "CIK0001601830-submissions-001.json",
            "filingCount": 0,
            "filingFrom": "2024-02-20",
            "filingTo": "2024-02-20",
        }
        payload["filings"]["files"] = [history, history]
        url = "https://data.sec.gov/submissions/CIK0001601830.json"
        transport = FixtureTransport({url: json.dumps(payload).encode()})
        collector = SecSubmissionsCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
                base_url="https://data.sec.gov",
            ),
            transport=transport,
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )

        with self.assertRaisesRegex(
            SecSubmissionsError,
            "duplicate history file",
        ):
            collector.discover(
                request(
                    security_id="f594edb2-7fff-4e40-9c26-2c06bcbecb91",
                    cik="0001601830",
                    issuer_name="Recursion Pharmaceuticals, Inc.",
                )
            )

        self.assertEqual([call[0] for call in transport.requests], [url])

    def test_history_chunk_fan_out_is_bounded_before_fetch(self) -> None:
        payload = json.loads(
            (FIXTURE_ROOT / "rxrx-submissions.json").read_text()
        )
        payload["filings"]["files"] = [
            {
                "name": (
                    f"CIK0001601830-submissions-{index:03d}.json"
                ),
                "filingCount": 0,
                "filingFrom": "2024-02-20",
                "filingTo": "2024-02-20",
            }
            for index in range(21)
        ]
        url = "https://data.sec.gov/submissions/CIK0001601830.json"
        transport = FixtureTransport({url: json.dumps(payload).encode()})
        collector = SecSubmissionsCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
                base_url="https://data.sec.gov",
            ),
            transport=transport,
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )

        with self.assertRaisesRegex(
            SecSubmissionsError,
            "too many history files",
        ):
            collector.discover(
                request(
                    security_id="f594edb2-7fff-4e40-9c26-2c06bcbecb91",
                    cik="0001601830",
                    issuer_name="Recursion Pharmaceuticals, Inc.",
                )
            )

        self.assertEqual([call[0] for call in transport.requests], [url])

    def test_missing_submission_history_metadata_is_not_complete(self) -> None:
        payload = json.loads(
            (FIXTURE_ROOT / "rxrx-submissions.json").read_text()
        )
        del payload["filings"]["files"]
        url = "https://data.sec.gov/submissions/CIK0001601830.json"
        collector = SecSubmissionsCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
                base_url="https://data.sec.gov",
            ),
            transport=FixtureTransport(
                {url: json.dumps(payload).encode()}
            ),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )

        result = collector.discover(
            request(
                security_id="f594edb2-7fff-4e40-9c26-2c06bcbecb91",
                cik="0001601830",
                issuer_name="Recursion Pharmaceuticals, Inc.",
            )
        )

        self.assertFalse(result.submission_history_complete)
        self.assertEqual(result.history_files, ())

    def test_conflicting_history_accession_fails_closed(self) -> None:
        payload = json.loads(
            (FIXTURE_ROOT / "rxrx-submissions.json").read_text()
        )
        history_name = "CIK0001601830-submissions-001.json"
        payload["filings"]["files"] = [
            {
                "name": history_name,
                "filingCount": 1,
                "filingFrom": "2026-05-06",
                "filingTo": "2026-05-06",
            }
        ]
        url = "https://data.sec.gov/submissions/CIK0001601830.json"
        history_url = f"https://data.sec.gov/submissions/{history_name}"
        history_body = json.dumps(
            {
                "accessionNumber": ["0001601830-26-000040"],
                "acceptanceDateTime": ["2026-05-06T20:00:00Z"],
                "filingDate": ["2026-05-06"],
                "reportDate": ["2026-03-31"],
                "form": ["8-K"],
                "primaryDocument": ["conflicting-document.htm"],
            }
        ).encode()
        collector = SecSubmissionsCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
                base_url="https://data.sec.gov",
            ),
            transport=FixtureTransport(
                {
                    url: json.dumps(payload).encode(),
                    history_url: history_body,
                }
            ),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )

        with self.assertRaisesRegex(
            SecSubmissionsError,
            "filing identity conflict",
        ):
            collector.discover(
                request(
                    security_id="f594edb2-7fff-4e40-9c26-2c06bcbecb91",
                    cik="0001601830",
                    issuer_name="Recursion Pharmaceuticals, Inc.",
                )
            )


if __name__ == "__main__":
    unittest.main()
