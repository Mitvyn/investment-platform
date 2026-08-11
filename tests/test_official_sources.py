from __future__ import annotations

from datetime import UTC, date, datetime
import hashlib
from pathlib import Path
import unittest

from workers.primary_sources.models import PrimarySourceRequest
from workers.regulatory import FDARegulatoryEvidenceAdapter
from workers.official_sources import (
    OfficialBytesResponse,
    OfficialIssuerEvidenceAdapter,
    OfficialPassageSpec,
    OfficialSourceIntegrityError,
    OfficialSourceLocator,
)


OPERATOR_ID = "8ed47ebc-d5cf-40ad-80ce-d4d803f7c735"
SECURITY_ID = "f594edb2-7fff-4e40-9c26-2c06bcbecb91"
CUTOFF = datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC)
RETRIEVED_AT = datetime(2026, 5, 7, 1, 0, tzinfo=UTC)
ISSUER_URL = "https://investors.example-biotech.com/news/programme-update.html"
PASSAGE = (
    "The Phase 2 study remains active and topline data are expected "
    "in the fourth quarter of 2026."
)
FDA_URL = "https://www.fda.gov/drugs/news-events/regulatory-update"
FDA_PASSAGE = (
    "FDA granted Fast Track designation for Asset Alpha in the "
    "Example oncology programme."
)


def source_request() -> PrimarySourceRequest:
    return PrimarySourceRequest(
        operator_id=OPERATOR_ID,
        security_id=SECURITY_ID,
        cik="0001234567",
        issuer_name="Example Biotech, Inc.",
        primary_listing_exchange="NASDAQ",
        as_of_cutoff=CUTOFF,
    )


class FixtureTransport:
    def __init__(self, responses: dict[str, OfficialBytesResponse]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, dict[str, str]]] = []

    def request(self, url: str, *, headers):
        self.requests.append((url, dict(headers)))
        return self.responses[url]


class OfficialIssuerEvidenceAdapterTests(unittest.TestCase):
    def test_collects_exact_issuer_document_passage_and_coverage(self) -> None:
        body = Path(
            "tests/fixtures/official_sources/issuer-programme-update.html"
        ).read_bytes()
        transport = FixtureTransport(
            {
                ISSUER_URL: OfficialBytesResponse(
                    body=body,
                    status=200,
                    headers={"Content-Type": "text/html; charset=utf-8"},
                    final_url=ISSUER_URL,
                )
            }
        )
        adapter = OfficialIssuerEvidenceAdapter(
            allowed_hosts=("investors.example-biotech.com",),
            transport=transport,
            clock=lambda: RETRIEVED_AT,
        )
        locator = OfficialSourceLocator(
            source_key="programme-update-2026-q1",
            requirement_id="issuer_pipeline",
            title="Programme update",
            source_url=ISSUER_URL,
            publication_time="2026-05-05T20:00:00Z",
            effective_date=date(2026, 5, 5),
            passages=(
                OfficialPassageSpec(
                    passage_key="phase-2-timing",
                    locator="main > p",
                    exact_text=PASSAGE,
                ),
            ),
        )

        snapshot = adapter.collect(source_request(), (locator,))

        self.assertEqual(snapshot.operator_id, OPERATOR_ID)
        self.assertEqual(snapshot.security_id, SECURITY_ID)
        self.assertEqual(snapshot.cik, "0001234567")
        self.assertEqual(snapshot.as_of_cutoff, CUTOFF)
        self.assertEqual(snapshot.source_class, "issuer")
        self.assertEqual(snapshot.coverage_state, "complete")
        self.assertEqual(
            snapshot.coverage_results[0].requirement_id,
            "issuer_pipeline",
        )
        self.assertEqual(snapshot.coverage_results[0].state, "complete")
        result = snapshot.source_results[0]
        self.assertEqual(result.state, "available")
        self.assertEqual(result.reason_code, "official_source_collected")
        self.assertIsNotNone(result.document)
        assert result.document is not None
        self.assertEqual(result.document.source_url, ISSUER_URL)
        self.assertEqual(result.document.final_url, ISSUER_URL)
        self.assertEqual(result.document.retrieved_at, RETRIEVED_AT)
        self.assertEqual(result.document.publication_state, "exact")
        self.assertEqual(
            result.document.publication_reason_code,
            "publication_time_verified_at_cutoff",
        )
        self.assertEqual(
            result.document.content_sha256,
            hashlib.sha256(body).hexdigest(),
        )
        self.assertEqual(result.document.content_text, body.decode("utf-8"))
        self.assertEqual(len(result.passages), 1)
        self.assertEqual(result.passages[0].passage_text, PASSAGE)
        self.assertEqual(
            result.passages[0].passage_sha256,
            hashlib.sha256(PASSAGE.encode()).hexdigest(),
        )
        self.assertEqual(
            transport.requests,
            [
                (
                    ISSUER_URL,
                    {"Accept": ("text/html,application/xhtml+xml,text/plain")},
                )
            ],
        )

    def test_rejects_non_https_or_unapproved_issuer_origin_before_request(
        self,
    ) -> None:
        transport = FixtureTransport({})
        adapter = OfficialIssuerEvidenceAdapter(
            allowed_hosts=("investors.example-biotech.com",),
            transport=transport,
        )

        for source_url in (
            "http://investors.example-biotech.com/news/update.html",
            "https://example-biotech.com/news/update.html",
            "https://investors.example-biotech.com.evil.example/update.html",
            "https://user@investors.example-biotech.com/update.html",
            "https://investors.example-biotech.com:8443/update.html",
        ):
            with self.subTest(source_url=source_url):
                locator = OfficialSourceLocator(
                    source_key="programme-update",
                    requirement_id="issuer_pipeline",
                    title="Programme update",
                    source_url=source_url,
                    publication_time="2026-05-05T20:00:00Z",
                    effective_date=date(2026, 5, 5),
                    passages=(),
                )
                with self.assertRaisesRegex(
                    OfficialSourceIntegrityError,
                    "source URL origin is not allowed",
                ):
                    adapter.collect(source_request(), (locator,))

        self.assertEqual(transport.requests, [])

    def test_publication_uncertainty_or_after_cutoff_is_reason_coded_without_fetch(
        self,
    ) -> None:
        cases = (
            (
                None,
                "unavailable",
                "publication_time_unavailable",
            ),
            (
                "2026-05-05T20:00:00",
                "ambiguous",
                "publication_timezone_unresolved",
            ),
            (
                "2026-05-06",
                "ambiguous",
                "publication_time_date_only_at_cutoff",
            ),
            (
                "2026-05-07T00:00:00Z",
                "after_cutoff",
                "publication_after_cutoff",
            ),
        )

        for publication_time, state, reason_code in cases:
            with self.subTest(publication_time=publication_time):
                transport = FixtureTransport({})
                adapter = OfficialIssuerEvidenceAdapter(
                    allowed_hosts=("investors.example-biotech.com",),
                    transport=transport,
                )
                locator = OfficialSourceLocator(
                    source_key="programme-update",
                    requirement_id="issuer_pipeline",
                    title="Programme update",
                    source_url=ISSUER_URL,
                    publication_time=publication_time,
                    effective_date=None,
                    passages=(),
                )

                snapshot = adapter.collect(source_request(), (locator,))

                self.assertEqual(snapshot.coverage_state, "incomplete")
                self.assertEqual(snapshot.coverage_results[0].state, "incomplete")
                self.assertEqual(
                    snapshot.coverage_results[0].reason_codes,
                    (reason_code,),
                )
                result = snapshot.source_results[0]
                self.assertEqual(result.state, state)
                self.assertEqual(result.reason_code, reason_code)
                self.assertIsNone(result.document)
                self.assertEqual(result.passages, ())
                self.assertEqual(transport.requests, [])

    def test_future_effective_date_is_after_cutoff_without_fetch(self) -> None:
        transport = FixtureTransport({})
        adapter = OfficialIssuerEvidenceAdapter(
            allowed_hosts=("investors.example-biotech.com",),
            transport=transport,
        )
        locator = OfficialSourceLocator(
            source_key="programme-update",
            requirement_id="issuer_pipeline",
            title="Programme update",
            source_url=ISSUER_URL,
            publication_time="2026-05-05T20:00:00Z",
            effective_date=date(2026, 5, 7),
            passages=(),
        )

        snapshot = adapter.collect(source_request(), (locator,))

        result = snapshot.source_results[0]
        self.assertEqual(result.state, "after_cutoff")
        self.assertEqual(result.reason_code, "effective_date_after_cutoff")
        self.assertIsNone(result.document)
        self.assertEqual(transport.requests, [])

    def test_http_failure_is_explicit_source_unavailable(self) -> None:
        transport = FixtureTransport(
            {
                ISSUER_URL: OfficialBytesResponse(
                    body=b"not found",
                    status=404,
                    headers={"Content-Type": "text/plain"},
                    final_url=ISSUER_URL,
                )
            }
        )
        adapter = OfficialIssuerEvidenceAdapter(
            allowed_hosts=("investors.example-biotech.com",),
            transport=transport,
        )
        locator = OfficialSourceLocator(
            source_key="programme-update",
            requirement_id="issuer_pipeline",
            title="Programme update",
            source_url=ISSUER_URL,
            publication_time="2026-05-05T20:00:00Z",
            effective_date=None,
            passages=(),
        )

        snapshot = adapter.collect(source_request(), (locator,))

        result = snapshot.source_results[0]
        self.assertEqual(result.state, "unavailable")
        self.assertEqual(result.reason_code, "official_source_http_unavailable")
        self.assertIsNone(result.document)
        self.assertEqual(snapshot.coverage_state, "incomplete")
        self.assertEqual(
            snapshot.coverage_results[0].reason_codes,
            ("official_source_http_unavailable",),
        )

    def test_rejects_response_from_unapproved_final_origin(self) -> None:
        transport = FixtureTransport(
            {
                ISSUER_URL: OfficialBytesResponse(
                    body=b"<html><body>copied release</body></html>",
                    status=200,
                    headers={"Content-Type": "text/html"},
                    final_url="https://cdn.evil.example/copied-release.html",
                )
            }
        )
        adapter = OfficialIssuerEvidenceAdapter(
            allowed_hosts=("investors.example-biotech.com",),
            transport=transport,
        )
        locator = OfficialSourceLocator(
            source_key="programme-update",
            requirement_id="issuer_pipeline",
            title="Programme update",
            source_url=ISSUER_URL,
            publication_time="2026-05-05T20:00:00Z",
            effective_date=None,
            passages=(),
        )

        with self.assertRaisesRegex(
            OfficialSourceIntegrityError,
            "final response origin is not allowed",
        ):
            adapter.collect(source_request(), (locator,))

    def test_rejects_non_text_empty_or_non_utf8_documents(self) -> None:
        cases = (
            (
                b'{"message":"not a release"}',
                {"Content-Type": "application/json"},
                "content type is invalid",
            ),
            (
                b" \n\t",
                {"Content-Type": "text/html"},
                "document is empty",
            ),
            (
                b"\xff\xfe",
                {"Content-Type": "text/plain"},
                "document is not valid UTF-8",
            ),
        )
        locator = OfficialSourceLocator(
            source_key="programme-update",
            requirement_id="issuer_pipeline",
            title="Programme update",
            source_url=ISSUER_URL,
            publication_time="2026-05-05T20:00:00Z",
            effective_date=None,
            passages=(),
        )

        for body, headers, error_message in cases:
            with self.subTest(error_message=error_message):
                transport = FixtureTransport(
                    {
                        ISSUER_URL: OfficialBytesResponse(
                            body=body,
                            status=200,
                            headers=headers,
                            final_url=ISSUER_URL,
                        )
                    }
                )
                adapter = OfficialIssuerEvidenceAdapter(
                    allowed_hosts=("investors.example-biotech.com",),
                    transport=transport,
                )

                with self.assertRaisesRegex(
                    OfficialSourceIntegrityError,
                    error_message,
                ):
                    adapter.collect(source_request(), (locator,))

    def test_retrieval_clock_must_include_timezone(self) -> None:
        transport = FixtureTransport(
            {
                ISSUER_URL: OfficialBytesResponse(
                    body=b"<html><body>valid release</body></html>",
                    status=200,
                    headers={"Content-Type": "text/html"},
                    final_url=ISSUER_URL,
                )
            }
        )
        adapter = OfficialIssuerEvidenceAdapter(
            allowed_hosts=("investors.example-biotech.com",),
            transport=transport,
            clock=lambda: datetime(2026, 5, 7, 1, 0),
        )
        locator = OfficialSourceLocator(
            source_key="programme-update",
            requirement_id="issuer_pipeline",
            title="Programme update",
            source_url=ISSUER_URL,
            publication_time="2026-05-05T20:00:00Z",
            effective_date=None,
            passages=(),
        )

        with self.assertRaisesRegex(
            OfficialSourceIntegrityError,
            "retrieval clock must include timezone",
        ):
            adapter.collect(source_request(), (locator,))

    def test_missing_or_duplicated_exact_passage_is_reason_coded(self) -> None:
        cases = (
            (
                b"<html><body><p>different disclosure</p></body></html>",
                "unavailable",
                "exact_passage_unavailable",
            ),
            (
                (
                    f"<html><body><p>{PASSAGE}</p><p>{PASSAGE}</p></body></html>"
                ).encode(),
                "ambiguous",
                "exact_passage_ambiguous",
            ),
        )
        locator = OfficialSourceLocator(
            source_key="programme-update",
            requirement_id="issuer_pipeline",
            title="Programme update",
            source_url=ISSUER_URL,
            publication_time="2026-05-05T20:00:00Z",
            effective_date=None,
            passages=(
                OfficialPassageSpec(
                    passage_key="phase-2-timing",
                    locator="main > p",
                    exact_text=PASSAGE,
                ),
            ),
        )

        for body, state, reason_code in cases:
            with self.subTest(state=state):
                transport = FixtureTransport(
                    {
                        ISSUER_URL: OfficialBytesResponse(
                            body=body,
                            status=200,
                            headers={"Content-Type": "text/html"},
                            final_url=ISSUER_URL,
                        )
                    }
                )
                adapter = OfficialIssuerEvidenceAdapter(
                    allowed_hosts=("investors.example-biotech.com",),
                    transport=transport,
                    clock=lambda: RETRIEVED_AT,
                )

                snapshot = adapter.collect(source_request(), (locator,))

                result = snapshot.source_results[0]
                self.assertEqual(result.state, state)
                self.assertEqual(result.reason_code, reason_code)
                self.assertIsNotNone(result.document)
                self.assertEqual(result.passages, ())
                self.assertEqual(snapshot.coverage_state, "incomplete")
                self.assertEqual(
                    snapshot.coverage_results[0].reason_codes,
                    (reason_code,),
                )

    def test_locator_order_does_not_change_snapshot_or_fetch_order(self) -> None:
        first_url = "https://investors.example-biotech.com/news/first-update.html"
        second_url = "https://investors.example-biotech.com/news/second-update.html"
        responses = {
            first_url: OfficialBytesResponse(
                body=b"<html><body>first update</body></html>",
                status=200,
                headers={"Content-Type": "text/html"},
                final_url=first_url,
            ),
            second_url: OfficialBytesResponse(
                body=b"<html><body>second update</body></html>",
                status=200,
                headers={"Content-Type": "text/html"},
                final_url=second_url,
            ),
        }
        first = OfficialSourceLocator(
            source_key="first-update",
            requirement_id="issuer_pipeline",
            title="First update",
            source_url=first_url,
            publication_time="2026-05-04T20:00:00Z",
            effective_date=None,
            passages=(),
        )
        second = OfficialSourceLocator(
            source_key="second-update",
            requirement_id="issuer_pipeline",
            title="Second update",
            source_url=second_url,
            publication_time="2026-05-05T20:00:00Z",
            effective_date=None,
            passages=(),
        )
        forward_transport = FixtureTransport(responses)
        reverse_transport = FixtureTransport(responses)

        forward = OfficialIssuerEvidenceAdapter(
            allowed_hosts=("investors.example-biotech.com",),
            transport=forward_transport,
            clock=lambda: RETRIEVED_AT,
        ).collect(source_request(), (first, second))
        reverse = OfficialIssuerEvidenceAdapter(
            allowed_hosts=("investors.example-biotech.com",),
            transport=reverse_transport,
            clock=lambda: RETRIEVED_AT,
        ).collect(source_request(), (second, first))

        self.assertEqual(forward, reverse)
        self.assertEqual(
            [request[0] for request in forward_transport.requests],
            [first_url, second_url],
        )
        self.assertEqual(
            forward.coverage_results[0].collected_source_keys,
            ("first-update", "second-update"),
        )

    def test_default_all_policy_does_not_mask_required_sibling_failure(
        self,
    ) -> None:
        available_url = "https://investors.example-biotech.com/news/available.html"
        transport = FixtureTransport(
            {
                available_url: OfficialBytesResponse(
                    body=b"<html><body>available disclosure</body></html>",
                    status=200,
                    headers={"Content-Type": "text/html"},
                    final_url=available_url,
                )
            }
        )
        available = OfficialSourceLocator(
            source_key="available-source",
            requirement_id="issuer_pipeline",
            title="Available source",
            source_url=available_url,
            publication_time="2026-05-05T20:00:00Z",
            effective_date=None,
            passages=(),
        )
        unavailable = OfficialSourceLocator(
            source_key="missing-source",
            requirement_id="issuer_pipeline",
            title="Missing source",
            source_url=ISSUER_URL,
            publication_time=None,
            effective_date=None,
            passages=(),
        )
        adapter = OfficialIssuerEvidenceAdapter(
            allowed_hosts=("investors.example-biotech.com",),
            transport=transport,
            clock=lambda: RETRIEVED_AT,
        )

        snapshot = adapter.collect(
            source_request(),
            (unavailable, available),
        )

        self.assertEqual(snapshot.coverage_state, "incomplete")
        coverage = snapshot.coverage_results[0]
        self.assertEqual(coverage.state, "incomplete")
        self.assertEqual(coverage.coverage_mode, "all")
        self.assertEqual(
            coverage.required_source_keys,
            ("available-source", "missing-source"),
        )
        self.assertEqual(coverage.optional_source_keys, ())
        self.assertEqual(
            coverage.unresolved_required_source_keys,
            ("missing-source",),
        )
        self.assertEqual(coverage.unresolved_optional_source_keys, ())
        self.assertEqual(
            coverage.collected_source_keys,
            ("available-source",),
        )
        self.assertEqual(
            coverage.reason_codes,
            ("publication_time_unavailable",),
        )

    def test_default_all_policy_blocks_ambiguous_required_sibling(
        self,
    ) -> None:
        available_url = "https://investors.example-biotech.com/news/available.html"
        ambiguous_url = "https://investors.example-biotech.com/news/ambiguous.html"
        transport = FixtureTransport(
            {
                available_url: OfficialBytesResponse(
                    body=b"<html><body>available disclosure</body></html>",
                    status=200,
                    headers={"Content-Type": "text/html"},
                    final_url=available_url,
                ),
                ambiguous_url: OfficialBytesResponse(
                    body=(
                        f"<html><body><p>{PASSAGE}</p><p>{PASSAGE}</p></body></html>"
                    ).encode(),
                    status=200,
                    headers={"Content-Type": "text/html"},
                    final_url=ambiguous_url,
                ),
            }
        )
        available = OfficialSourceLocator(
            source_key="available-source",
            requirement_id="issuer_pipeline",
            title="Available source",
            source_url=available_url,
            publication_time="2026-05-05T20:00:00Z",
            effective_date=None,
            passages=(),
        )
        ambiguous = OfficialSourceLocator(
            source_key="ambiguous-source",
            requirement_id="issuer_pipeline",
            title="Ambiguous source",
            source_url=ambiguous_url,
            publication_time="2026-05-05T20:00:00Z",
            effective_date=None,
            passages=(
                OfficialPassageSpec(
                    passage_key="duplicated-passage",
                    locator="main > p",
                    exact_text=PASSAGE,
                ),
            ),
        )
        adapter = OfficialIssuerEvidenceAdapter(
            allowed_hosts=("investors.example-biotech.com",),
            transport=transport,
            clock=lambda: RETRIEVED_AT,
        )

        snapshot = adapter.collect(
            source_request(),
            (available, ambiguous),
        )

        self.assertEqual(snapshot.coverage_state, "incomplete")
        coverage = snapshot.coverage_results[0]
        self.assertEqual(
            coverage.unresolved_required_source_keys,
            ("ambiguous-source",),
        )
        self.assertEqual(
            coverage.reason_codes,
            ("exact_passage_ambiguous",),
        )

    def test_explicit_any_policy_allows_alternative_but_keeps_failure_visible(
        self,
    ) -> None:
        available_url = "https://investors.example-biotech.com/news/available.html"
        transport = FixtureTransport(
            {
                available_url: OfficialBytesResponse(
                    body=b"<html><body>available disclosure</body></html>",
                    status=200,
                    headers={"Content-Type": "text/html"},
                    final_url=available_url,
                )
            }
        )
        available = OfficialSourceLocator(
            source_key="available-source",
            requirement_id="issuer_pipeline",
            title="Available source",
            source_url=available_url,
            publication_time="2026-05-05T20:00:00Z",
            effective_date=None,
            passages=(),
            coverage_mode="any",
        )
        unavailable = OfficialSourceLocator(
            source_key="missing-source",
            requirement_id="issuer_pipeline",
            title="Missing source",
            source_url=ISSUER_URL,
            publication_time=None,
            effective_date=None,
            passages=(),
            coverage_mode="any",
        )
        adapter = OfficialIssuerEvidenceAdapter(
            allowed_hosts=("investors.example-biotech.com",),
            transport=transport,
            clock=lambda: RETRIEVED_AT,
        )

        snapshot = adapter.collect(
            source_request(),
            (unavailable, available),
        )

        self.assertEqual(snapshot.coverage_state, "complete")
        coverage = snapshot.coverage_results[0]
        self.assertEqual(coverage.state, "complete")
        self.assertEqual(coverage.coverage_mode, "any")
        self.assertEqual(
            coverage.unresolved_required_source_keys,
            ("missing-source",),
        )
        self.assertEqual(
            coverage.reason_codes,
            ("publication_time_unavailable",),
        )

    def test_optional_sibling_does_not_block_but_remains_visible(self) -> None:
        available_url = "https://investors.example-biotech.com/news/available.html"
        transport = FixtureTransport(
            {
                available_url: OfficialBytesResponse(
                    body=b"<html><body>available disclosure</body></html>",
                    status=200,
                    headers={"Content-Type": "text/html"},
                    final_url=available_url,
                )
            }
        )
        required = OfficialSourceLocator(
            source_key="required-source",
            requirement_id="issuer_pipeline",
            title="Required source",
            source_url=available_url,
            publication_time="2026-05-05T20:00:00Z",
            effective_date=None,
            passages=(),
        )
        optional = OfficialSourceLocator(
            source_key="optional-source",
            requirement_id="issuer_pipeline",
            title="Optional source",
            source_url=ISSUER_URL,
            publication_time=None,
            effective_date=None,
            passages=(),
            coverage_role="optional",
        )
        adapter = OfficialIssuerEvidenceAdapter(
            allowed_hosts=("investors.example-biotech.com",),
            transport=transport,
            clock=lambda: RETRIEVED_AT,
        )

        snapshot = adapter.collect(
            source_request(),
            (optional, required),
        )

        self.assertEqual(snapshot.coverage_state, "complete")
        coverage = snapshot.coverage_results[0]
        self.assertEqual(coverage.required_source_keys, ("required-source",))
        self.assertEqual(coverage.optional_source_keys, ("optional-source",))
        self.assertEqual(coverage.unresolved_required_source_keys, ())
        self.assertEqual(
            coverage.unresolved_optional_source_keys,
            ("optional-source",),
        )
        self.assertEqual(
            coverage.reason_codes,
            ("publication_time_unavailable",),
        )

    def test_mixed_modes_within_requirement_are_rejected_before_fetch(
        self,
    ) -> None:
        all_locator = OfficialSourceLocator(
            source_key="all-source",
            requirement_id="issuer_pipeline",
            title="All source",
            source_url=ISSUER_URL,
            publication_time=None,
            effective_date=None,
            passages=(),
        )
        any_locator = OfficialSourceLocator(
            source_key="any-source",
            requirement_id="issuer_pipeline",
            title="Any source",
            source_url=("https://investors.example-biotech.com/news/alternative.html"),
            publication_time=None,
            effective_date=None,
            passages=(),
            coverage_mode="any",
        )
        transport = FixtureTransport({})
        adapter = OfficialIssuerEvidenceAdapter(
            allowed_hosts=("investors.example-biotech.com",),
            transport=transport,
        )

        with self.assertRaisesRegex(
            OfficialSourceIntegrityError,
            "coverage modes must agree",
        ):
            adapter.collect(source_request(), (all_locator, any_locator))

        self.assertEqual(transport.requests, [])

    def test_requirement_needs_at_least_one_required_locator(self) -> None:
        optional = OfficialSourceLocator(
            source_key="optional-source",
            requirement_id="issuer_pipeline",
            title="Optional source",
            source_url=ISSUER_URL,
            publication_time=None,
            effective_date=None,
            passages=(),
            coverage_role="optional",
        )
        transport = FixtureTransport({})
        adapter = OfficialIssuerEvidenceAdapter(
            allowed_hosts=("investors.example-biotech.com",),
            transport=transport,
        )

        with self.assertRaisesRegex(
            OfficialSourceIntegrityError,
            "at least one required locator",
        ):
            adapter.collect(source_request(), (optional,))

        self.assertEqual(transport.requests, [])

    def test_duplicate_source_key_is_rejected_before_fetch(self) -> None:
        first = OfficialSourceLocator(
            source_key="programme-update",
            requirement_id="issuer_pipeline",
            title="First update",
            source_url=ISSUER_URL,
            publication_time="2026-05-04T20:00:00Z",
            effective_date=None,
            passages=(),
        )
        second = OfficialSourceLocator(
            source_key="programme-update",
            requirement_id="issuer_pipeline",
            title="Second update",
            source_url=("https://investors.example-biotech.com/news/second.html"),
            publication_time="2026-05-05T20:00:00Z",
            effective_date=None,
            passages=(),
        )
        transport = FixtureTransport({})
        adapter = OfficialIssuerEvidenceAdapter(
            allowed_hosts=("investors.example-biotech.com",),
            transport=transport,
        )

        with self.assertRaisesRegex(
            OfficialSourceIntegrityError,
            "source keys must be unique",
        ):
            adapter.collect(source_request(), (first, second))

        self.assertEqual(transport.requests, [])

    def test_empty_locator_set_is_rejected_before_fetch(self) -> None:
        transport = FixtureTransport({})
        adapter = OfficialIssuerEvidenceAdapter(
            allowed_hosts=("investors.example-biotech.com",),
            transport=transport,
        )

        with self.assertRaisesRegex(
            OfficialSourceIntegrityError,
            "at least one locator is required",
        ):
            adapter.collect(source_request(), ())

        self.assertEqual(transport.requests, [])

    def test_empty_passage_contract_fields_are_rejected(self) -> None:
        for field_name, values in (
            (
                "passage key",
                {
                    "passage_key": " ",
                    "locator": "main > p",
                    "exact_text": PASSAGE,
                },
            ),
            (
                "passage locator",
                {
                    "passage_key": "phase-2",
                    "locator": "",
                    "exact_text": PASSAGE,
                },
            ),
            (
                "exact passage text",
                {
                    "passage_key": "phase-2",
                    "locator": "main > p",
                    "exact_text": "\n",
                },
            ),
        ):
            with self.subTest(field_name=field_name):
                with self.assertRaisesRegex(ValueError, field_name):
                    OfficialPassageSpec(**values)

    def test_source_locator_requires_named_unique_contract_fields(self) -> None:
        base = {
            "source_key": "programme-update",
            "requirement_id": "issuer_pipeline",
            "title": "Programme update",
            "source_url": ISSUER_URL,
            "publication_time": "2026-05-05T20:00:00Z",
            "effective_date": None,
            "passages": (),
        }
        for field_name in (
            "source_key",
            "requirement_id",
            "title",
            "source_url",
        ):
            values = dict(base)
            values[field_name] = " "
            with self.subTest(field_name=field_name):
                with self.assertRaisesRegex(
                    ValueError,
                    field_name.replace("_", " "),
                ):
                    OfficialSourceLocator(**values)

        passage = OfficialPassageSpec(
            passage_key="phase-2",
            locator="main > p",
            exact_text=PASSAGE,
        )
        with self.assertRaisesRegex(
            ValueError,
            "passage keys must be unique",
        ):
            OfficialSourceLocator(
                **{
                    **base,
                    "passages": (passage, passage),
                }
            )
        for field_name, invalid_value, error_message in (
            ("coverage_role", "supplemental", "coverage role"),
            ("coverage_mode", "majority", "coverage mode"),
        ):
            with self.subTest(field_name=field_name):
                with self.assertRaisesRegex(ValueError, error_message):
                    OfficialSourceLocator(
                        **{
                            **base,
                            field_name: invalid_value,
                        }
                    )


class FDARegulatoryEvidenceAdapterTests(unittest.TestCase):
    def test_collects_fda_gsrs_json_identity_bridge(self) -> None:
        url = (
            "https://precision.fda.gov/ginas/app/api/v1/"
            "substances(5J61HSP0QJ)?view=internal"
        )
        body = (
            b'{"created":1772553673021,"approvalID":"5J61HSP0QJ",'
            b'"names":[{"name":"REC-4881"},{"name":"TAK-733"}],'
            b'"references":[{"url":"https://www.accessdata.fda.gov/'
            b'scripts/opdlisting/oopd/detailedIndex.cfm?cfgridkey=817621"}]}'
        )
        adapter = FDARegulatoryEvidenceAdapter(
            allowed_hosts=("precision.fda.gov",),
            transport=FixtureTransport(
                {
                    url: OfficialBytesResponse(
                        body=body,
                        status=200,
                        headers={"Content-Type": "application/json"},
                        final_url=url,
                    )
                }
            ),
            clock=lambda: RETRIEVED_AT,
        )
        locator = OfficialSourceLocator(
            source_key="gsrs-rec-4881-identity",
            requirement_id="us_regulatory",
            title="FDA GSRS REC-4881 identity",
            source_url=url,
            publication_time="2026-03-03T16:01:13.021Z",
            effective_date=date(2026, 3, 3),
            passages=(
                OfficialPassageSpec(
                    passage_key="rec-4881-name",
                    locator="names",
                    exact_text='"name":"REC-4881"',
                ),
                OfficialPassageSpec(
                    passage_key="oopd-reference",
                    locator="references",
                    exact_text=(
                        '"url":"https://www.accessdata.fda.gov/'
                        "scripts/opdlisting/oopd/detailedIndex.cfm"
                        '?cfgridkey=817621"'
                    ),
                ),
            ),
        )

        snapshot = adapter.collect(source_request(), (locator,))

        self.assertEqual(snapshot.coverage_state, "complete")
        self.assertEqual(snapshot.source_results[0].state, "available")
        self.assertEqual(
            [item.passage_key for item in snapshot.source_results[0].passages],
            ["rec-4881-name", "oopd-reference"],
        )

    def test_collects_exact_fda_regulatory_evidence_with_same_contract(
        self,
    ) -> None:
        body = Path(
            "tests/fixtures/official_sources/fda-regulatory-update.html"
        ).read_bytes()
        transport = FixtureTransport(
            {
                FDA_URL: OfficialBytesResponse(
                    body=body,
                    status=200,
                    headers={"Content-Type": "text/html"},
                    final_url=FDA_URL,
                )
            }
        )
        adapter = FDARegulatoryEvidenceAdapter(
            allowed_hosts=("www.fda.gov",),
            transport=transport,
            clock=lambda: RETRIEVED_AT,
        )
        locator = OfficialSourceLocator(
            source_key="fast-track-designation",
            requirement_id="us_regulatory",
            title="Regulatory update",
            source_url=FDA_URL,
            publication_time="2026-05-05T18:00:00-04:00",
            effective_date=date(2026, 5, 5),
            passages=(
                OfficialPassageSpec(
                    passage_key="fast-track",
                    locator="main > p",
                    exact_text=FDA_PASSAGE,
                ),
            ),
        )

        snapshot = adapter.collect(source_request(), (locator,))

        self.assertEqual(snapshot.source_class, "regulatory")
        self.assertEqual(snapshot.coverage_state, "complete")
        self.assertEqual(
            snapshot.coverage_results[0].requirement_id,
            "us_regulatory",
        )
        result = snapshot.source_results[0]
        self.assertEqual(result.state, "available")
        assert result.document is not None
        self.assertEqual(result.document.source_class, "regulatory")
        self.assertEqual(result.document.source_url, FDA_URL)
        self.assertEqual(result.passages[0].passage_text, FDA_PASSAGE)

    def test_fda_allowlist_accepts_only_explicit_fda_gov_hosts(self) -> None:
        for allowed_hosts in (
            (),
            ("fda.example",),
            ("www.fda.gov.evil.example",),
            ("*.fda.gov",),
            ("https://www.fda.gov",),
        ):
            with self.subTest(allowed_hosts=allowed_hosts):
                with self.assertRaisesRegex(
                    ValueError,
                    "FDA host allowlist",
                ):
                    FDARegulatoryEvidenceAdapter(
                        allowed_hosts=allowed_hosts,
                        transport=FixtureTransport({}),
                    )


if __name__ == "__main__":
    unittest.main()
