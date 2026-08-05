from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
import hashlib
from pathlib import Path
import unittest

from workers.sec.exhibits import SecFilingExhibit
from workers.sec.documents import SecFilingDocument
from workers.sec.passages import (
    SecExactPassageExtractor,
    SecPassageExtractionError,
)


OPERATOR_ID = "8ed47ebc-d5cf-40ad-80ce-d4d803f7c735"
SECURITY_ID = "f594edb2-7fff-4e40-9c26-2c06bcbecb91"
CIK = "0001601830"
ACCESSION = "0001601830-26-000040"
FIXTURE = (
    Path(__file__).parent / "fixtures" / "primary_sources" / "generic-exhibit-991.html"
)
SOURCE_URL = (
    "https://www.sec.gov/Archives/edgar/data/1601830/000160183026000040/exhibit991.htm"
)
PASSAGE = (
    "The registrational study met its primary endpoint with a statistically "
    "significant improvement over control."
)


def collected_exhibit(
    *,
    content_text: str | None = None,
) -> SecFilingExhibit:
    content = content_text if content_text is not None else FIXTURE.read_text()
    published_at = datetime(2026, 5, 6, 20, 30, tzinfo=UTC)
    return SecFilingExhibit(
        operator_id=OPERATOR_ID,
        security_id=SECURITY_ID,
        cik=CIK,
        accession_number=ACCESSION,
        form="8-K",
        filing_date=date(2026, 5, 6),
        report_date=date(2026, 5, 6),
        sequence="2",
        description="Clinical programme update",
        exhibit_type="EX-99.1",
        document_name="exhibit991.htm",
        source_class="sec_filing_exhibit",
        source_url=SOURCE_URL,
        published_at=published_at,
        publication_date=published_at.date(),
        retrieved_at=datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        content_text=content,
    )


class SecExactPassageExtractorTests(unittest.TestCase):
    def test_extracts_one_exact_normalized_passage_with_stable_provenance(
        self,
    ) -> None:
        source = collected_exhibit()

        result = SecExactPassageExtractor().extract(source, PASSAGE)

        self.assertEqual(result.state, "found")
        self.assertEqual(result.reason_code, "exact_passage_found")
        self.assertEqual(result.occurrence_count, 1)
        self.assertEqual(result.passage_text, PASSAGE)
        self.assertEqual(
            result.passage_sha256,
            hashlib.sha256(PASSAGE.encode()).hexdigest(),
        )
        self.assertEqual(
            result.query_sha256,
            hashlib.sha256(PASSAGE.encode()).hexdigest(),
        )
        self.assertRegex(
            result.locator or "",
            r"^normalized_text_chars:\d+-\d+$",
        )
        self.assertEqual(result.operator_id, OPERATOR_ID)
        self.assertEqual(result.security_id, SECURITY_ID)
        self.assertEqual(result.cik, CIK)
        self.assertEqual(result.accession_number, ACCESSION)
        self.assertEqual(result.document_name, "exhibit991.htm")
        self.assertEqual(result.source_class, "sec_filing_exhibit")
        self.assertEqual(result.source_url, SOURCE_URL)
        self.assertEqual(
            result.source_content_sha256,
            source.content_sha256,
        )

    def test_repeated_exact_passage_returns_ambiguous_outcome(self) -> None:
        source = collected_exhibit(
            content_text=(f"<html><body><p>{PASSAGE}</p><p>{PASSAGE}</p></body></html>")
        )

        result = SecExactPassageExtractor().extract(source, PASSAGE)

        self.assertEqual(result.state, "ambiguous")
        self.assertEqual(
            result.reason_code,
            "exact_passage_ambiguous",
        )
        self.assertEqual(result.occurrence_count, 2)
        self.assertIsNone(result.passage_text)
        self.assertIsNone(result.passage_sha256)
        self.assertIsNone(result.locator)

    def test_content_hash_mismatch_is_rejected_before_extraction(
        self,
    ) -> None:
        source = replace(
            collected_exhibit(),
            content_sha256="0" * 64,
        )

        with self.assertRaisesRegex(
            SecPassageExtractionError,
            "content hash mismatch",
        ):
            SecExactPassageExtractor().extract(source, PASSAGE)

    def test_noncanonical_source_url_is_rejected_before_extraction(
        self,
    ) -> None:
        source = replace(
            collected_exhibit(),
            source_url="https://example.com/exhibit991.htm",
        )

        with self.assertRaisesRegex(
            SecPassageExtractionError,
            "source URL is not canonical",
        ):
            SecExactPassageExtractor().extract(source, PASSAGE)

    def test_primary_filing_document_uses_same_exact_extraction_contract(
        self,
    ) -> None:
        content = f"<html><body><p>{PASSAGE}</p></body></html>"
        published_at = datetime(2026, 5, 6, 20, 30, tzinfo=UTC)
        source = SecFilingDocument(
            operator_id=OPERATOR_ID,
            security_id=SECURITY_ID,
            cik=CIK,
            accession_number=ACCESSION,
            form="10-Q",
            filing_date=date(2026, 5, 6),
            report_date=date(2026, 3, 31),
            primary_document="issuer-20260331.htm",
            source_class="sec_filing",
            source_url=(
                "https://www.sec.gov/Archives/edgar/data/1601830/"
                "000160183026000040/issuer-20260331.htm"
            ),
            published_at=published_at,
            publication_date=published_at.date(),
            retrieved_at=datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
            content_sha256=hashlib.sha256(content.encode()).hexdigest(),
            content_text=content,
        )

        result = SecExactPassageExtractor().extract(source, PASSAGE)

        self.assertEqual(result.state, "found")
        self.assertEqual(result.document_name, "issuer-20260331.htm")
        self.assertEqual(result.source_class, "sec_filing")

    def test_accepts_filing_agent_accession_under_issuer_archive(self) -> None:
        accession = "0001193125-25-025185"
        source = replace(
            collected_exhibit(),
            accession_number=accession,
            source_url=(
                "https://www.sec.gov/Archives/edgar/data/1601830/"
                "000119312525025185/exhibit991.htm"
            ),
        )

        result = SecExactPassageExtractor().extract(source, PASSAGE)

        self.assertEqual(result.state, "found")
        self.assertEqual(result.accession_number, accession)

    def test_unsupported_source_class_is_rejected_before_extraction(
        self,
    ) -> None:
        source = replace(
            collected_exhibit(),
            source_class="untrusted_discovery",
        )

        with self.assertRaisesRegex(
            SecPassageExtractionError,
            "source class is invalid",
        ):
            SecExactPassageExtractor().extract(source, PASSAGE)

    def test_missing_exact_passage_returns_not_found_outcome(self) -> None:
        result = SecExactPassageExtractor().extract(
            collected_exhibit(),
            "This exact statement does not occur in the filing.",
        )

        self.assertEqual(result.state, "not_found")
        self.assertEqual(
            result.reason_code,
            "exact_passage_not_found",
        )
        self.assertEqual(result.occurrence_count, 0)
        self.assertIsNone(result.passage_text)
        self.assertIsNone(result.passage_sha256)
        self.assertIsNone(result.locator)
        self.assertEqual(result.source_url, SOURCE_URL)


if __name__ == "__main__":
    unittest.main()
