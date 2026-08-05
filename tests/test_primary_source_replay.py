from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from io import BytesIO
import json
from pathlib import Path
import unittest
from zipfile import ZIP_STORED, ZipFile

from workers.primary_sources.captures import PrimarySourceCaptureError
from workers.primary_sources.plans import (
    PRIMARY_SOURCE_PLAN_V3,
    bind_primary_source_plan,
    load_primary_source_plan,
)
from workers.primary_sources.replay import replay_primary_source_capture
from workers.sec.collector import SecSettings
from workers.sec.selection import RequiredSecFilingSelector
from workers.sec.submissions import SecSubmissionsCollector

from tests.test_primary_source_end_to_end import (
    CREATED_AT,
    PLATFORM_CASE,
    SecTransport,
    capture_archive,
    request,
    source_plan_value,
)


CORPORATE_ACTION_NO_CHANGE = (
    "From 2025-12-31 through 2026-03-31, no stock split, reverse stock split, "
    "recapitalization, share class conversion, merger conversion, or other "
    "corporate action changed the basic common share economic basis."
)


def _platform_capture_archive(
    *,
    corporate_action_text: str | None = None,
) -> bytes:
    case = PLATFORM_CASE
    source_request = request(case)
    plan_value = source_plan_value(case)
    if corporate_action_text is not None:
        plan_value["contract_version"] = PRIMARY_SOURCE_PLAN_V3
        financing_plan = next(
            passage
            for passage in plan_value["sec_passages"]
            if passage["role"] == "financing"
        )
        financing_plan["exact_text"] = financing_plan["exact_text"].replace(
            ", and no share count growth.",
            ".",
        )
        plan_value["sec_passages"].append(
            {
                "reference_key": "corporate-action:basis-reconciliation",
                "role": "corporate_action",
                "selected_form": "10-Q",
                "selected_accession_number": "0001601830-26-000040",
                "exact_text": corporate_action_text,
            }
        )
    source_plan_bytes = json.dumps(
        plan_value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    source_plan = bind_primary_source_plan(
        load_primary_source_plan(source_plan_bytes),
        source_request,
        trusted_issuer_hosts=case.issuer_trusted_hosts,
    )
    registry_body = json.dumps(
        {
            "fields": ["cik", "name", "ticker", "exchange"],
            "data": [
                [
                    int(case.cik),
                    case.issuer_name,
                    case.display_symbol,
                    "Nasdaq",
                ]
            ],
        }
    ).encode()
    submissions_body = (
        Path("tests/fixtures/primary_sources")
        .joinpath(case.submissions_fixture)
        .read_bytes()
    )
    submissions_url = f"https://data.sec.gov/submissions/CIK{case.cik}.json"
    submissions = SecSubmissionsCollector(
        SecSettings(
            user_agent="Investment Research OS research@example.com",
            base_url="https://data.sec.gov",
        ),
        transport=SecTransport(submissions_body, submissions_url),
        clock=lambda: CREATED_AT,
    ).discover(source_request)
    selection = RequiredSecFilingSelector().select(submissions)
    document_bodies: dict[str, bytes] = {}
    index_bodies: dict[str, bytes] = {}
    for filing in selection.selected_filings:
        planned_passages = tuple(
            plan.exact_text
            for plan in source_plan.sec_passages
            if plan.selected_form == filing.form
        )
        passage_html = "".join(
            f"<p>{passage}</p>" for passage in planned_passages
        )
        document_bodies[filing.archive_url] = (
            f"<html><body>{passage_html or 'selected filing'}</body></html>"
        ).encode()
        index_url = (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{case.cik.lstrip('0') or '0'}/"
            f"{filing.accession_number.replace('-', '')}/"
            f"{filing.accession_number}-index.html"
        )
        index_bodies[index_url] = (
            "<html><body>"
            '<table summary="Document Format Files">'
            "<tr>"
            "<td>1</td><td>Primary filing</td>"
            f'<td><a href="{filing.primary_document}">'
            f"{filing.primary_document}</a></td>"
            f"<td>{filing.form}</td><td>1000</td>"
            "</tr></table></body></html>"
        ).encode()
    issuer_body = (
        Path("tests/fixtures/official_sources")
        .joinpath(case.issuer_fixture)
        .read_bytes()
    )
    trial_body = (
        Path("tests/fixtures/primary_sources")
        .joinpath(case.clinical_fixture)
        .read_bytes()
    )
    regulatory_body = (
        Path("tests/fixtures/official_sources")
        .joinpath(case.regulatory_fixture)
        .read_bytes()
    )
    companyfacts_body = (
        Path("tests/fixtures/primary_sources")
        .joinpath(case.companyfacts_fixture)
        .read_bytes()
    )
    if corporate_action_text is not None:
        companyfacts_payload = json.loads(companyfacts_body)
        observations = companyfacts_payload["facts"]["dei"][
            "EntityCommonStockSharesOutstanding"
        ]["units"]["shares"]
        observations.append(
            {
                "end": "2025-12-31",
                "val": 300000000,
                "accn": "0001601830-26-000030",
                "fy": 2025,
                "fp": "FY",
                "form": "10-K",
                "filed": "2026-02-25",
                "frame": "CY2025Q4I",
            }
        )
        companyfacts_body = json.dumps(
            companyfacts_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    return capture_archive(
        case,
        source_plan_bytes=source_plan_bytes,
        source_plan=source_plan,
        registry_body=registry_body,
        submissions_body=submissions_body,
        selected_filings=selection.selected_filings,
        document_bodies=document_bodies,
        index_bodies=index_bodies,
        issuer_body=issuer_body,
        trial_body=trial_body,
        regulatory_body=regulatory_body,
        companyfacts_body=companyfacts_body,
    )


def _with_unconsumed_exhibit(raw_archive: bytes) -> bytes:
    with ZipFile(BytesIO(raw_archive), "r") as archive:
        entries = {
            name: archive.read(name)
            for name in archive.namelist()
        }
    manifest = json.loads(entries["capture.json"])
    filing = next(
        response
        for response in manifest["responses"]
        if response["route"]["role"] == "sec_filing_document"
    )
    accession = filing["route"]["accession_number"]
    body = b"<html><body>Unrequested exhibit</body></html>"
    body_hash = hashlib.sha256(body).hexdigest()
    body_path = f"payloads/{body_hash}.bin"
    entries[body_path] = body
    manifest["responses"].append(
        {
            "response_key": "unrequested-exhibit",
            "route": {
                "role": "sec_filing_exhibit",
                "accession_number": accession,
                "exhibit_type": "EX-99.1",
                "document_name": "unrequested-exhibit.htm",
            },
            "request_url": (
                "https://www.sec.gov/Archives/edgar/data/"
                f"{PLATFORM_CASE.cik.lstrip('0')}/"
                f"{accession.replace('-', '')}/unrequested-exhibit.htm"
            ),
            "final_url": (
                "https://www.sec.gov/Archives/edgar/data/"
                f"{PLATFORM_CASE.cik.lstrip('0')}/"
                f"{accession.replace('-', '')}/unrequested-exhibit.htm"
            ),
            "status": 200,
            "headers": {"content-type": "text/html"},
            "retrieved_at": CREATED_AT.isoformat(),
            "body": {
                "path": body_path,
                "byte_length": len(body),
                "sha256": body_hash,
            },
        }
    )
    entries["capture.json"] = json.dumps(
        manifest,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_STORED) as archive:
        for name, body in sorted(entries.items()):
            archive.writestr(name, body)
    return output.getvalue()


class PrimarySourceReplayTests(unittest.TestCase):
    def test_replays_accepted_capture_through_all_collectors(self) -> None:
        result = replay_primary_source_capture(
            _platform_capture_archive(),
            request=request(PLATFORM_CASE),
            ticker=PLATFORM_CASE.display_symbol,
            sec_user_agent="Investment Research OS research@example.com",
            trusted_issuer_hosts=PLATFORM_CASE.issuer_trusted_hosts,
            accepted_at=lambda: datetime(2026, 5, 7, 3, tzinfo=UTC),
        )

        self.assertEqual(
            result.registered_security.security_id,
            PLATFORM_CASE.security_id,
        )
        self.assertEqual(result.selection.coverage_state, "complete")
        self.assertEqual(
            tuple(item.plan for item in result.sec_passages),
            result.capture.plan.sec_passages,
        )
        self.assertEqual(result.issuer.coverage_state, "complete")
        self.assertEqual(result.clinical_trials.coverage.status, "covered")
        self.assertEqual(result.regulatory.coverage_state, "complete")
        self.assertEqual(result.companyfacts.coverage_state, "complete")
        self.assertTrue(
            all(
                fact.published_at is not None
                for fact in result.companyfacts.facts
            )
        )

    def test_rejects_capture_with_unconsumed_response(self) -> None:
        with self.assertRaisesRegex(
            PrimarySourceCaptureError,
            "unconsumed capture responses: unrequested-exhibit",
        ):
            replay_primary_source_capture(
                _with_unconsumed_exhibit(_platform_capture_archive()),
                request=request(PLATFORM_CASE),
                ticker=PLATFORM_CASE.display_symbol,
                sec_user_agent=(
                    "Investment Research OS research@example.com"
                ),
                trusted_issuer_hosts=PLATFORM_CASE.issuer_trusted_hosts,
                accepted_at=lambda: datetime(
                    2026,
                    5,
                    7,
                    3,
                    tzinfo=UTC,
                ),
            )


if __name__ == "__main__":
    unittest.main()
