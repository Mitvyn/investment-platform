from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
from io import BytesIO
import json
from pathlib import Path
import stat
import unittest
from urllib.parse import urlencode
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from workers.primary_sources.captures import (
    CAPTURE_CONTRACT_VERSION,
    CaptureMiss,
    PrimarySourceCaptureError,
    load_primary_source_capture,
)
from workers.primary_sources.capture_recording import (
    CapturedExchange,
    PrimarySourceCaptureRecorder,
    PrimarySourceExchangeRecorder,
    assemble_primary_source_capture_archive,
)
from workers.sec.collector import BytesResponse
from tests.test_primary_source_plans import (
    OPERATOR_ID,
    SECURITY_ID,
    raw as plan_raw,
    request,
    value as plan_value,
)
from workers.primary_sources.plans import PRIMARY_SOURCE_PLAN_V2


ASSEMBLED_AT = datetime(2026, 5, 7, 2, tzinfo=UTC)
RETRIEVED_AT = datetime(2026, 5, 7, 1, tzinfo=UTC)


def route(role: str) -> dict[str, object]:
    values: dict[str, dict[str, object]] = {
        "sec_security_registry": {"role": role},
        "sec_submissions_root": {"role": role},
        "sec_companyfacts": {"role": role},
        "sec_filing_document": {
            "role": role,
            "accession_number": "0001601830-26-000040",
            "primary_document": "issuer-20260331.htm",
        },
        "sec_filing_index": {
            "role": role,
            "accession_number": "0001601830-26-000040",
        },
        "issuer_document": {
            "role": role,
            "source_key": "pipeline-update",
        },
        "clinical_trials_page": {
            "role": role,
            "page_ordinal": 0,
        },
        "clinical_trials_history_summary": {
            "role": role,
            "nct_id": "NCT05552755",
        },
        "clinical_trials_history_version": {
            "role": role,
            "nct_id": "NCT05552755",
            "version": 22,
        },
        "regulatory_document": {
            "role": role,
            "source_key": "regulatory-update",
        },
    }
    return values[role]


def clinical_url() -> str:
    return "https://clinicaltrials.gov/api/v2/studies?" + urlencode(
        {
            "format": "json",
            "pageSize": 100,
            "countTotal": "true",
            "query.term": '"REC-4881"',
        }
    )


def response_definitions() -> list[tuple[str, str, str, bytes]]:
    return [
        (
            "registry",
            "sec_security_registry",
            "https://www.sec.gov/files/company_tickers_exchange.json",
            b'{"fields":["cik","name","ticker","exchange"],"data":[]}',
        ),
        (
            "submissions",
            "sec_submissions_root",
            "https://data.sec.gov/submissions/CIK0001601830.json",
            b'{"cik":"0001601830"}',
        ),
        (
            "companyfacts",
            "sec_companyfacts",
            (
                "https://data.sec.gov/api/xbrl/companyfacts/"
                "CIK0001601830.json"
            ),
            b'{"cik":1601830}',
        ),
        (
            "filing",
            "sec_filing_document",
            (
                "https://www.sec.gov/Archives/edgar/data/1601830/"
                "000160183026000040/issuer-20260331.htm"
            ),
            b"<html>filing</html>",
        ),
        (
            "index",
            "sec_filing_index",
            (
                "https://www.sec.gov/Archives/edgar/data/1601830/"
                "000160183026000040/"
                "0001601830-26-000040-index.html"
            ),
            b"<html>index</html>",
        ),
        (
            "issuer",
            "issuer_document",
            (
                "https://ir.recursion.com/news-releases/"
                "news-release-details/example"
            ),
            b"<html>issuer</html>",
        ),
        (
            "clinical",
            "clinical_trials_page",
            clinical_url(),
            b'{"studies":[],"totalCount":0}',
        ),
        (
            "regulatory",
            "regulatory_document",
            "https://www.fda.gov/drugs/example",
            b"<html>regulatory</html>",
        ),
    ]


def capture_value(
    *,
    plan_bytes: bytes | None = None,
) -> tuple[dict[str, object], dict[str, bytes], bytes]:
    source_plan = plan_bytes or plan_raw()
    from workers.primary_sources.plans import (
        bind_primary_source_plan,
        load_primary_source_plan,
    )

    plan = bind_primary_source_plan(
        load_primary_source_plan(source_plan),
        request(),
        trusted_issuer_hosts=("ir.recursion.com",),
    )
    payloads: dict[str, bytes] = {}
    responses: list[dict[str, object]] = []
    for response_key, role_name, url, body in response_definitions():
        body_hash = hashlib.sha256(body).hexdigest()
        payloads[f"payloads/{body_hash}.bin"] = body
        media_type = (
            "application/json"
            if role_name
            in {
                "sec_security_registry",
                "sec_submissions_root",
                "sec_companyfacts",
                "clinical_trials_page",
            }
            else "text/html"
        )
        responses.append(
            {
                "response_key": response_key,
                "route": route(role_name),
                "request_url": url,
                "final_url": url,
                "status": 200,
                "headers": {"content-type": media_type},
                "retrieved_at": RETRIEVED_AT.isoformat(),
                "body": {
                    "path": f"payloads/{body_hash}.bin",
                    "byte_length": len(body),
                    "sha256": body_hash,
                },
            }
        )
    return (
        {
            "contract_version": CAPTURE_CONTRACT_VERSION,
            "capture_id": "cf535a4f-b7ff-4aed-9457-8e9d0cbd5535",
            "revision": 1,
            "provenance_mode": "operator_supplied_unverified",
            "assembled_at": ASSEMBLED_AT.isoformat(),
            "context": {
                "operator_id": OPERATOR_ID,
                "security_id": SECURITY_ID,
                "cik": "0001601830",
                "issuer_name": "Recursion Pharmaceuticals, Inc.",
                "primary_listing_exchange": "NASDAQ",
                "as_of_cutoff": request().as_of_cutoff.isoformat(),
                "question_type": "biotech_moonshot_catalyst_assessment",
                "workflow_config_version": (
                    "biotech-moonshot-catalyst-v1"
                ),
            },
            "plan": {
                "path": "primary-source-plan.json",
                "plan_id": plan.loaded.plan_id,
                "revision": plan.loaded.revision,
                "content_hash": plan.content_hash,
            },
            "responses": responses,
        },
        payloads,
        source_plan,
    )


def archive_bytes(
    value: dict[str, object],
    payloads: dict[str, bytes],
    source_plan: bytes,
    *,
    reverse: bool = False,
    extras: dict[str, bytes] | None = None,
    symlink_name: str | None = None,
) -> bytes:
    entries = {
        "capture.json": json.dumps(value).encode(),
        "primary-source-plan.json": source_plan,
        **payloads,
        **(extras or {}),
    }
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_STORED) as archive:
        names = sorted(entries, reverse=reverse)
        for name in names:
            if name == symlink_name:
                info = ZipInfo(name)
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, entries[name])
            else:
                archive.writestr(name, entries[name])
    return output.getvalue()


def load(
    *,
    value: dict[str, object] | None = None,
    payloads: dict[str, bytes] | None = None,
    source_plan: bytes | None = None,
    archive: bytes | None = None,
):
    if archive is None:
        default_value, default_payloads, default_plan = capture_value(
            plan_bytes=source_plan,
        )
        archive = archive_bytes(
            value or default_value,
            payloads or default_payloads,
            source_plan or default_plan,
        )
    return load_primary_source_capture(
        archive,
        request=request(),
        trusted_issuer_hosts=("ir.recursion.com",),
        accepted_at=lambda: datetime(2026, 5, 7, 3, tzinfo=UTC),
    )


class PrimarySourceCaptureTests(unittest.TestCase):
    def test_plan_bound_recorder_infers_route_and_stable_key(self) -> None:
        url = "https://www.sec.gov/files/company_tickers_exchange.json"

        class Transport:
            def request(self, request_url: str, *, headers):
                del headers
                return BytesResponse(
                    body=b'{"fields":[],"data":[]}',
                    status=200,
                    headers={"Content-Type": "application/json"},
                    final_url=request_url,
                )

        recorder = PrimarySourceCaptureRecorder(
            source_plan=plan_raw(),
            request=request(),
            trusted_issuer_hosts=("ir.recursion.com",),
            clock=lambda: RETRIEVED_AT,
        )
        recorder.transport(Transport()).request(
            url,
            headers={"Authorization": "must-not-enter-capture"},
        )

        archive = recorder.assemble(
            capture_id="cf535a4f-b7ff-4aed-9457-8e9d0cbd5535",
            revision=1,
            assembled_at=ASSEMBLED_AT,
        )
        with ZipFile(BytesIO(archive), "r") as package:
            manifest = json.loads(package.read("capture.json"))
        recorded = manifest["responses"][0]

        self.assertEqual(
            recorded["route"],
            {"role": "sec_security_registry"},
        )
        self.assertEqual(
            recorded["response_key"],
            "sec_security_registry-5b6741a1c4ea19736833749c",
        )
        self.assertNotIn(b"must-not-enter-capture", archive)

    def test_plan_bound_recorder_delegates_duplicate_url_once(self) -> None:
        url = "https://www.sec.gov/files/company_tickers_exchange.json"

        class Transport:
            calls = 0

            def request(self, request_url: str, *, headers):
                del headers
                self.calls += 1
                return BytesResponse(
                    body=b'{"fields":[],"data":[]}',
                    status=200,
                    headers={"Content-Type": "application/json"},
                    final_url=request_url,
                )

        delegate = Transport()
        recorder = PrimarySourceCaptureRecorder(
            source_plan=plan_raw(),
            request=request(),
            trusted_issuer_hosts=("ir.recursion.com",),
            clock=lambda: RETRIEVED_AT,
        )
        transport = recorder.transport(delegate)

        first = transport.request(url, headers={"Accept": "application/json"})
        second = transport.request(
            url,
            headers={"Authorization": "different-request-headers"},
        )

        self.assertIs(first, second)
        self.assertEqual(delegate.calls, 1)

    def test_plan_bound_recorder_normalizes_encoded_content_length(
        self,
    ) -> None:
        url = "https://www.sec.gov/files/company_tickers_exchange.json"

        class Transport:
            def request(self, request_url: str, *, headers):
                del headers
                return BytesResponse(
                    body=b'{"fields":[],"data":[]}',
                    status=200,
                    headers={
                        "Content-Type": "application/json",
                        "Content-Length": "7",
                    },
                    final_url=request_url,
                )

        recorder = PrimarySourceCaptureRecorder(
            source_plan=plan_raw(),
            request=request(),
            trusted_issuer_hosts=("ir.recursion.com",),
            clock=lambda: RETRIEVED_AT,
        )
        recorder.transport(Transport()).request(url, headers={})

        archive = recorder.assemble(
            capture_id="cf535a4f-b7ff-4aed-9457-8e9d0cbd5535",
            revision=1,
            assembled_at=ASSEMBLED_AT,
        )
        with ZipFile(BytesIO(archive), "r") as package:
            manifest = json.loads(package.read("capture.json"))

        self.assertEqual(
            manifest["responses"][0]["headers"]["content-length"],
            str(len(b'{"fields":[],"data":[]}')),
        )

    def test_plan_bound_recorder_preserves_unrelated_sec_xml_rows(
        self,
    ) -> None:
        url = "https://data.sec.gov/submissions/CIK0001601830.json"
        body = json.dumps(
            {
                "filings": {
                    "recent": {
                        "accessionNumber": [
                            "0001959173-26-005384",
                        ],
                        "primaryDocument": [
                            "xsl144X01/primary_doc.xml",
                        ],
                    },
                    "files": [],
                }
            }
        ).encode()

        class Transport:
            def request(self, request_url: str, *, headers):
                del headers
                return BytesResponse(
                    body=body,
                    status=200,
                    headers={"Content-Type": "application/json"},
                    final_url=request_url,
                )

        recorder = PrimarySourceCaptureRecorder(
            source_plan=plan_raw(),
            request=request(),
            trusted_issuer_hosts=("ir.recursion.com",),
            clock=lambda: RETRIEVED_AT,
        )
        recorder.transport(Transport()).request(url, headers={})

        archive = recorder.assemble(
            capture_id="cf535a4f-b7ff-4aed-9457-8e9d0cbd5535",
            revision=1,
            assembled_at=ASSEMBLED_AT,
        )
        with ZipFile(BytesIO(archive), "r") as package:
            manifest = json.loads(package.read("capture.json"))

        self.assertEqual(
            manifest["responses"][0]["route"],
            {"role": "sec_submissions_root"},
        )

    def test_plan_bound_recorder_assembles_core_capture(self) -> None:
        definitions = response_definitions()
        bodies = {
            url: body
            for _key, _role, url, body in definitions
        }
        index_url = next(
            url
            for _key, role_name, url, _body in definitions
            if role_name == "sec_filing_index"
        )
        bodies[index_url] = (
            b'<table summary="Document Format Files"></table>'
        )
        submissions_url = (
            "https://data.sec.gov/submissions/CIK0001601830.json"
        )
        bodies[submissions_url] = json.dumps(
            {
                "cik": "0001601830",
                "filings": {
                    "recent": {
                        "accessionNumber": [
                            "0001601830-26-000040",
                        ],
                        "primaryDocument": [
                            "issuer-20260331.htm",
                        ],
                    },
                    "files": [],
                },
            }
        ).encode()

        class Transport:
            def request(self, request_url: str, *, headers):
                del headers
                role_name = next(
                    role_name
                    for _key, role_name, url, _body in definitions
                    if url == request_url
                )
                media_type = (
                    "application/json"
                    if role_name
                    in {
                        "sec_security_registry",
                        "sec_submissions_root",
                        "sec_companyfacts",
                        "clinical_trials_page",
                    }
                    else "text/html"
                )
                return BytesResponse(
                    body=bodies[request_url],
                    status=200,
                    headers={"Content-Type": media_type},
                    final_url=request_url,
                )

        recorder = PrimarySourceCaptureRecorder(
            source_plan=plan_raw(),
            request=request(),
            trusted_issuer_hosts=("ir.recursion.com",),
            clock=lambda: RETRIEVED_AT,
        )
        transport = recorder.transport(Transport())
        for _key, _role_name, url, _body in reversed(definitions):
            transport.request(url, headers={})

        package = load(
            archive=recorder.assemble(
                capture_id="cf535a4f-b7ff-4aed-9457-8e9d0cbd5535",
                revision=1,
                assembled_at=ASSEMBLED_AT,
            )
        )

        self.assertEqual(
            {response.role for response in package.responses},
            {
                "sec_security_registry",
                "sec_submissions_root",
                "sec_companyfacts",
                "sec_filing_document",
                "sec_filing_index",
                "issuer_document",
                "clinical_trials_page",
                "regulatory_document",
            },
        )

    def test_plan_bound_recorder_infers_response_graph_routes(self) -> None:
        root_url = (
            "https://data.sec.gov/submissions/CIK0001601830.json"
        )
        history_name = "CIK0001601830-submissions-001.json"
        history_url = (
            "https://data.sec.gov/submissions/"
            f"{history_name}"
        )
        accession = "0001193125-25-025185"
        archive_prefix = (
            "https://www.sec.gov/Archives/edgar/data/1601830/"
            "000119312525025185/"
        )
        index_url = archive_prefix + f"{accession}-index.html"
        exhibit_url = archive_prefix + "exhibit991.htm"
        first_clinical_url = clinical_url()
        second_clinical_url = (
            first_clinical_url + "&pageToken=next-page"
        )
        history_summary_url = (
            "https://clinicaltrials.gov/api/int/studies/"
            "NCT05552755?history=true"
        )
        history_version_url = (
            "https://clinicaltrials.gov/api/int/studies/"
            "NCT05552755/history/22"
        )
        bodies = {
            root_url: json.dumps(
                {
                    "filings": {
                        "recent": {
                            "accessionNumber": [],
                            "primaryDocument": [],
                        },
                        "files": [{"name": history_name}],
                    }
                }
            ).encode(),
            history_url: json.dumps(
                {
                    "accessionNumber": [accession],
                    "primaryDocument": ["d915440ds3asr.htm"],
                }
            ).encode(),
            index_url: (
                b'<table summary="Document Format Files"><tr>'
                b"<td>2</td><td>Issuer release</td>"
                b'<td><a href="exhibit991.htm">exhibit991.htm</a></td>'
                b"<td>EX-99.1</td></tr></table>"
            ),
            exhibit_url: b"<html>issuer release</html>",
            first_clinical_url: (
                b'{"studies":[],"nextPageToken":"next-page"}'
            ),
            second_clinical_url: b'{"studies":[]}',
            history_summary_url: b'{"history":{"changes":[]}}',
            history_version_url: b'{"studyVersion":22}',
        }

        class Transport:
            def request(self, request_url: str, *, headers):
                del headers
                return BytesResponse(
                    body=bodies[request_url],
                    status=200,
                    headers={
                        "Content-Type": (
                            "text/html"
                            if request_url
                            in {index_url, exhibit_url}
                            else "application/json"
                        )
                    },
                    final_url=request_url,
                )

        recorder = PrimarySourceCaptureRecorder(
            source_plan=plan_raw(),
            request=request(),
            trusted_issuer_hosts=("ir.recursion.com",),
            clock=lambda: RETRIEVED_AT,
        )
        transport = recorder.transport(Transport())
        for url in reversed(tuple(bodies)):
            transport.request(url, headers={})

        archive = recorder.assemble(
            capture_id="cf535a4f-b7ff-4aed-9457-8e9d0cbd5535",
            revision=1,
            assembled_at=ASSEMBLED_AT,
        )
        with ZipFile(BytesIO(archive), "r") as package:
            manifest = json.loads(package.read("capture.json"))
        routes = {
            response["request_url"]: response["route"]
            for response in manifest["responses"]
        }

        self.assertEqual(
            routes[history_url],
            {
                "role": "sec_submissions_history",
                "history_file": history_name,
            },
        )
        self.assertEqual(
            routes[exhibit_url],
            {
                "role": "sec_filing_exhibit",
                "accession_number": accession,
                "exhibit_type": "EX-99.1",
                "document_name": "exhibit991.htm",
            },
        )
        self.assertEqual(
            routes[second_clinical_url],
            {
                "role": "clinical_trials_page",
                "page_ordinal": 1,
            },
        )
        self.assertEqual(
            routes[history_summary_url],
            {
                "role": "clinical_trials_history_summary",
                "nct_id": "NCT05552755",
            },
        )
        self.assertEqual(
            routes[history_version_url],
            {
                "role": "clinical_trials_history_version",
                "nct_id": "NCT05552755",
                "version": 22,
            },
        )

    def test_plan_bound_recorder_rejects_unknown_route(self) -> None:
        unknown_url = "https://example.com/not-in-plan"

        class Transport:
            def request(self, request_url: str, *, headers):
                del headers
                return BytesResponse(
                    body=b"<html>unknown</html>",
                    status=200,
                    headers={"Content-Type": "text/html"},
                    final_url=request_url,
                )

        recorder = PrimarySourceCaptureRecorder(
            source_plan=plan_raw(),
            request=request(),
            trusted_issuer_hosts=("ir.recursion.com",),
            clock=lambda: RETRIEVED_AT,
        )
        recorder.transport(Transport()).request(
            unknown_url,
            headers={},
        )

        with self.assertRaisesRegex(
            ValueError,
            "capture response route is unknown",
        ):
            recorder.assemble(
                capture_id="cf535a4f-b7ff-4aed-9457-8e9d0cbd5535",
                revision=1,
                assembled_at=ASSEMBLED_AT,
            )

    def test_plan_bound_recorder_rejects_ambiguous_plan_route(self) -> None:
        candidate = plan_value()
        shared_url = candidate["regulatory_sources"][0]["source_url"]
        candidate["issuer_sources"][0]["source_url"] = shared_url
        source_plan = json.dumps(candidate).encode()

        class Transport:
            def request(self, request_url: str, *, headers):
                del headers
                return BytesResponse(
                    body=b"<html>shared source</html>",
                    status=200,
                    headers={"Content-Type": "text/html"},
                    final_url=request_url,
                )

        recorder = PrimarySourceCaptureRecorder(
            source_plan=source_plan,
            request=request(),
            trusted_issuer_hosts=("www.fda.gov",),
            clock=lambda: RETRIEVED_AT,
        )
        recorder.transport(Transport()).request(
            shared_url,
            headers={},
        )

        with self.assertRaisesRegex(
            ValueError,
            "capture response route is ambiguous",
        ):
            recorder.assemble(
                capture_id="cf535a4f-b7ff-4aed-9457-8e9d0cbd5535",
                revision=1,
                assembled_at=ASSEMBLED_AT,
            )

    def test_plan_bound_archive_bytes_ignore_acquisition_order(self) -> None:
        urls = (
            "https://www.sec.gov/files/company_tickers_exchange.json",
            (
                "https://data.sec.gov/api/xbrl/companyfacts/"
                "CIK0001601830.json"
            ),
        )
        bodies = {
            urls[0]: b'{"fields":[],"data":[]}',
            urls[1]: b'{"cik":1601830}',
        }

        class Transport:
            def request(self, request_url: str, *, headers):
                del headers
                return BytesResponse(
                    body=bodies[request_url],
                    status=200,
                    headers={"Content-Type": "application/json"},
                    final_url=request_url,
                )

        def acquire(ordered_urls):
            recorder = PrimarySourceCaptureRecorder(
                source_plan=plan_raw(),
                request=request(),
                trusted_issuer_hosts=("ir.recursion.com",),
                clock=lambda: RETRIEVED_AT,
            )
            transport = recorder.transport(Transport())
            for url in ordered_urls:
                transport.request(url, headers={})
            return recorder.assemble(
                capture_id="cf535a4f-b7ff-4aed-9457-8e9d0cbd5535",
                revision=1,
                assembled_at=ASSEMBLED_AT,
            )

        self.assertEqual(acquire(urls), acquire(tuple(reversed(urls))))

    def test_assembles_loader_accepted_archive_from_recorded_exchanges(
        self,
    ) -> None:
        exchanges = tuple(
            CapturedExchange(
                response_key=response_key,
                route=route(role_name),
                request_url=url,
                final_url=url,
                status=200,
                headers={
                    "content-type": (
                        "application/json"
                        if role_name
                        in {
                            "sec_security_registry",
                            "sec_submissions_root",
                            "sec_companyfacts",
                            "clinical_trials_page",
                        }
                        else "text/html"
                    ),
                    "server": "must-not-enter-capture",
                },
                retrieved_at=RETRIEVED_AT,
                body=body,
            )
            for response_key, role_name, url, body in response_definitions()
        )

        archive = assemble_primary_source_capture_archive(
            exchanges=exchanges,
            source_plan=plan_raw(),
            request=request(),
            trusted_issuer_hosts=("ir.recursion.com",),
            capture_id="cf535a4f-b7ff-4aed-9457-8e9d0cbd5535",
            revision=1,
            assembled_at=ASSEMBLED_AT,
        )
        package = load(archive=archive)

        self.assertEqual(len(package.responses), len(exchanges))
        self.assertTrue(
            all(
                "server" not in dict(response.headers)
                for response in package.responses
            )
        )

    def test_capture_assembly_bytes_are_exchange_order_invariant(self) -> None:
        exchanges = tuple(
            CapturedExchange(
                response_key=response_key,
                route=route(role_name),
                request_url=url,
                final_url=url,
                status=200,
                headers={
                    "content-type": (
                        "application/json"
                        if role_name
                        in {
                            "sec_security_registry",
                            "sec_submissions_root",
                            "sec_companyfacts",
                            "clinical_trials_page",
                        }
                        else "text/html"
                    )
                },
                retrieved_at=RETRIEVED_AT,
                body=body,
            )
            for response_key, role_name, url, body in response_definitions()
        )

        def assemble(items):
            return assemble_primary_source_capture_archive(
                exchanges=items,
                source_plan=plan_raw(),
                request=request(),
                trusted_issuer_hosts=("ir.recursion.com",),
                capture_id="cf535a4f-b7ff-4aed-9457-8e9d0cbd5535",
                revision=1,
                assembled_at=ASSEMBLED_AT,
            )

        self.assertEqual(assemble(exchanges), assemble(tuple(reversed(exchanges))))

    def test_records_exact_exchange_and_exposes_retrieval_clock(self) -> None:
        url = "https://data.sec.gov/submissions/CIK0001601830.json"

        class Transport:
            def request(self, request_url: str, *, headers):
                self.request_url = request_url
                self.headers = dict(headers)
                return BytesResponse(
                    body=b'{"cik":"0001601830"}',
                    status=200,
                    headers={
                        "Content-Type": "application/json",
                        "ETag": '"abc"',
                        "Server": "not-captured",
                    },
                    final_url=request_url,
                )

        recorder = PrimarySourceExchangeRecorder()
        transport = recorder.transport(
            Transport(),
            route_for_response=lambda request_url, _response: (
                "submissions",
                {"role": "sec_submissions_root"},
            ),
            clock=lambda: RETRIEVED_AT,
        )

        response = transport.request(
            url,
            headers={"Accept": "application/json"},
        )

        self.assertEqual(response.body, b'{"cik":"0001601830"}')
        self.assertEqual(transport.clock(), RETRIEVED_AT)
        self.assertEqual(
            recorder.exchanges,
            (
                CapturedExchange(
                    response_key="submissions",
                    route={"role": "sec_submissions_root"},
                    request_url=url,
                    final_url=url,
                    status=200,
                    headers={
                        "content-type": "application/json",
                        "etag": '"abc"',
                    },
                    retrieved_at=RETRIEVED_AT,
                    body=b'{"cik":"0001601830"}',
                ),
            ),
        )

    def test_accepts_cross_validated_clinical_history_responses(self) -> None:
        value, payloads, source_plan = capture_value()
        study = json.loads(
            (
                Path("tests/fixtures/primary_sources")
                / "clinical-trials-programme.json"
            ).read_text()
        )["studies"][0]
        study["protocolSection"]["identificationModule"]["nctId"] = (
            "NCT05552755"
        )
        search_body = json.dumps(
            {"studies": [study], "totalCount": 1}
        ).encode()
        summary_body = json.dumps(
            {
                "study": study,
                "topics": [],
                "history": {
                    "changes": [
                        {
                            "version": 22,
                            "date": "2026-04-13",
                        }
                    ]
                },
            }
        ).encode()
        version_body = json.dumps(
            {"study": study, "studyVersion": 22}
        ).encode()
        clinical = next(
            item
            for item in value["responses"]
            if item["response_key"] == "clinical"
        )
        old_path = clinical["body"]["path"]
        payloads.pop(old_path)
        search_hash = hashlib.sha256(search_body).hexdigest()
        payloads[f"payloads/{search_hash}.bin"] = search_body
        clinical["body"] = {
            "path": f"payloads/{search_hash}.bin",
            "byte_length": len(search_body),
            "sha256": search_hash,
        }
        for response_key, role_name, url, body in (
            (
                "clinical-history-summary",
                "clinical_trials_history_summary",
                (
                    "https://clinicaltrials.gov/api/int/studies/"
                    "NCT05552755?history=true"
                ),
                summary_body,
            ),
            (
                "clinical-history-version",
                "clinical_trials_history_version",
                (
                    "https://clinicaltrials.gov/api/int/studies/"
                    "NCT05552755/history/22"
                ),
                version_body,
            ),
        ):
            body_hash = hashlib.sha256(body).hexdigest()
            payloads[f"payloads/{body_hash}.bin"] = body
            value["responses"].append(
                {
                    "response_key": response_key,
                    "route": route(role_name),
                    "request_url": url,
                    "final_url": url,
                    "status": 200,
                    "headers": {"content-type": "application/json"},
                    "retrieved_at": RETRIEVED_AT.isoformat(),
                    "body": {
                        "path": f"payloads/{body_hash}.bin",
                        "byte_length": len(body),
                        "sha256": body_hash,
                    },
                }
            )

        package = load(
            archive=archive_bytes(value, payloads, source_plan),
        )
        session = package.open_session()
        clinical_transport = session.clinical_trials_transport()
        self.assertEqual(
            json.loads(
                clinical_transport.request(
                    (
                        "https://clinicaltrials.gov/api/int/studies/"
                        "NCT05552755?history=true"
                    ),
                    headers={},
                ).body
            )["history"]["changes"][0]["version"],
            22,
        )
        self.assertEqual(
            json.loads(
                clinical_transport.request(
                    (
                        "https://clinicaltrials.gov/api/int/studies/"
                        "NCT05552755/history/22"
                    ),
                    headers={},
                ).body
            )["studyVersion"],
            22,
        )

    def test_rejects_clinical_history_wrapper_identity_mismatch(self) -> None:
        value, payloads, source_plan = capture_value()
        body = b'{"study":{"protocolSection":{"identificationModule":{"nctId":"NCT05552755"}}},"studyVersion":21}'
        body_hash = hashlib.sha256(body).hexdigest()
        payloads[f"payloads/{body_hash}.bin"] = body
        value["responses"].append(
            {
                "response_key": "clinical-history-version",
                "route": route("clinical_trials_history_version"),
                "request_url": (
                    "https://clinicaltrials.gov/api/int/studies/"
                    "NCT05552755/history/22"
                ),
                "final_url": (
                    "https://clinicaltrials.gov/api/int/studies/"
                    "NCT05552755/history/22"
                ),
                "status": 200,
                "headers": {"content-type": "application/json"},
                "retrieved_at": RETRIEVED_AT.isoformat(),
                "body": {
                    "path": f"payloads/{body_hash}.bin",
                    "byte_length": len(body),
                    "sha256": body_hash,
                },
            }
        )

        with self.assertRaisesRegex(
            PrimarySourceCaptureError,
            "clinical history is invalid",
        ):
            load(
                archive=archive_bytes(value, payloads, source_plan),
            )

    def test_loads_content_addressed_capture_and_protocol_views(self) -> None:
        package = load()
        session = package.open_session()

        sec_transport = session.sec_transport()
        response = sec_transport.request(
            "https://data.sec.gov/submissions/CIK0001601830.json",
            headers={"Accept": "application/json"},
        )
        self.assertEqual(response.body, b'{"cik":"0001601830"}')
        self.assertEqual(response.status, 200)
        self.assertEqual(response.final_url, (
            "https://data.sec.gov/submissions/CIK0001601830.json"
        ))
        self.assertEqual(sec_transport.clock(), RETRIEVED_AT)

        official = session.official_transport("issuer_document")
        self.assertEqual(
            official.request(
                (
                    "https://ir.recursion.com/news-releases/"
                    "news-release-details/example"
                ),
                headers={},
            ).body,
            b"<html>issuer</html>",
        )
        clinical = session.clinical_trials_transport()
        self.assertEqual(
            clinical.request(clinical_url(), headers={}).body,
            b'{"studies":[],"totalCount":0}',
        )
        self.assertEqual(len(package.content_hash), 64)
        self.assertEqual(len(package.receipt.package_sha256), 64)
        self.assertEqual(
            package.receipt.authenticated_operator_id,
            OPERATOR_ID,
        )

    def test_semantic_hash_ignores_zip_and_response_order(self) -> None:
        value, payloads, source_plan = capture_value()
        reversed_value = deepcopy(value)
        reversed_value["responses"].reverse()

        first = load(
            archive=archive_bytes(value, payloads, source_plan),
        )
        second = load(
            archive=archive_bytes(
                reversed_value,
                payloads,
                source_plan,
                reverse=True,
            ),
        )

        self.assertEqual(first.content_hash, second.content_hash)
        self.assertNotEqual(
            first.receipt.package_sha256,
            second.receipt.package_sha256,
        )

    def test_capture_v1_embeds_multi_financing_source_plan_v2(self) -> None:
        candidate = plan_value()
        candidate["contract_version"] = PRIMARY_SOURCE_PLAN_V2
        candidate["revision"] = 2
        candidate["sec_passages"].append(
            {
                "reference_key": "financing:rsus",
                "role": "financing",
                "selected_form": "10-Q",
                "exact_text": "RSU evidence.",
            }
        )
        source_plan = json.dumps(candidate).encode()
        value, payloads, _ = capture_value(plan_bytes=source_plan)

        package = load(
            archive=archive_bytes(value, payloads, source_plan),
        )

        self.assertEqual(
            package.plan.loaded.contract_version,
            PRIMARY_SOURCE_PLAN_V2,
        )
        self.assertEqual(
            len(
                [
                    passage
                    for passage in package.plan.sec_passages
                    if passage.role == "financing"
                ]
            ),
            2,
        )

    def test_rejects_context_or_plan_mismatch(self) -> None:
        for path, invalid in (
            (("context", "security_id"), (
                "11111111-1111-4111-8111-111111111111"
            )),
            (("context", "cik"), "0000000001"),
            (("plan", "content_hash"), "0" * 64),
        ):
            with self.subTest(path=path):
                value, payloads, source_plan = capture_value()
                value[path[0]][path[1]] = invalid
                with self.assertRaisesRegex(
                    PrimarySourceCaptureError,
                    "does not match",
                ):
                    load(
                        archive=archive_bytes(
                            value,
                            payloads,
                            source_plan,
                        )
                    )

    def test_wraps_embedded_plan_errors_as_capture_errors(self) -> None:
        value, payloads, _source_plan = capture_value()

        with self.assertRaisesRegex(
            PrimarySourceCaptureError,
            "embedded source plan is invalid",
        ):
            load(
                archive=archive_bytes(
                    value,
                    payloads,
                    b"{",
                )
            )

    def test_rejects_body_tamper_missing_or_extra_archive_member(self) -> None:
        value, payloads, source_plan = capture_value()
        body_path = value["responses"][0]["body"]["path"]
        tampered = dict(payloads)
        tampered[body_path] += b"x"
        with self.assertRaisesRegex(
            PrimarySourceCaptureError,
            "body integrity is invalid",
        ):
            load(
                archive=archive_bytes(value, tampered, source_plan),
            )

        missing = dict(payloads)
        missing.pop(body_path)
        with self.assertRaisesRegex(
            PrimarySourceCaptureError,
            "body integrity is invalid",
        ):
            load(archive=archive_bytes(value, missing, source_plan))

        with self.assertRaisesRegex(
            PrimarySourceCaptureError,
            "archive members are invalid",
        ):
            load(
                archive=archive_bytes(
                    value,
                    payloads,
                    source_plan,
                    extras={"unexpected.txt": b"x"},
                )
            )

    def test_rejects_route_origin_redirect_media_and_port_drift(self) -> None:
        mutations = (
            (
                "regulatory",
                "request_url",
                "https://example.com/regulatory",
                "route origin is invalid",
            ),
            (
                "companyfacts",
                "final_url",
                (
                    "https://data.sec.gov/api/xbrl/companyfacts/"
                    "CIK0001601830.json?redirected=true"
                ),
                "final URL is invalid",
            ),
            (
                "filing",
                "request_url",
                (
                    "https://www.sec.gov:8443/Archives/edgar/data/"
                    "1601830/000160183026000040/issuer-20260331.htm"
                ),
                "origin is invalid",
            ),
            (
                "clinical",
                "headers",
                {"content-type": "text/html"},
                "media type is invalid",
            ),
        )
        for response_key, field, invalid, message in mutations:
            with self.subTest(response_key=response_key, field=field):
                value, payloads, source_plan = capture_value()
                response = next(
                    item
                    for item in value["responses"]
                    if item["response_key"] == response_key
                )
                response[field] = invalid
                with self.assertRaisesRegex(
                    PrimarySourceCaptureError,
                    message,
                ):
                    load(
                        archive=archive_bytes(
                            value,
                            payloads,
                            source_plan,
                        )
                    )

    def test_accepts_explicit_accessdata_fda_regulatory_origin(self) -> None:
        plan_value = json.loads(plan_raw())
        regulatory_url = (
            "https://www.accessdata.fda.gov/scripts/opdlisting/oopd/"
            "detailedIndex.cfm?cfgridkey=817621"
        )
        plan_value["regulatory_sources"][0]["source_url"] = regulatory_url
        source_plan = json.dumps(plan_value).encode()
        value, payloads, _source_plan = capture_value(
            plan_bytes=source_plan,
        )
        response = next(
            item
            for item in value["responses"]
            if item["response_key"] == "regulatory"
        )
        response["request_url"] = regulatory_url
        response["final_url"] = regulatory_url

        package = load(
            archive=archive_bytes(
                value,
                payloads,
                source_plan,
            )
        )

        regulatory = next(
            item
            for item in package.responses
            if item.response_key == "regulatory"
        )
        self.assertEqual(regulatory.request_url, regulatory_url)

    def test_accepts_filing_agent_accession_under_issuer_archive(self) -> None:
        value, payloads, source_plan = capture_value()
        response = next(
            item
            for item in value["responses"]
            if item["response_key"] == "filing"
        )
        response["route"]["accession_number"] = "0001193125-25-025185"
        response["request_url"] = (
            "https://www.sec.gov/Archives/edgar/data/1601830/"
            "000119312525025185/issuer-20260331.htm"
        )
        response["final_url"] = response["request_url"]

        package = load(
            archive=archive_bytes(
                value,
                payloads,
                source_plan,
            )
        )

        filing = next(
            item
            for item in package.responses
            if item.response_key == "filing"
        )
        self.assertEqual(
            dict(filing.route)["accession_number"],
            "0001193125-25-025185",
        )

    def test_filing_route_uses_accession_and_document_identity(self) -> None:
        value, payloads, source_plan = capture_value()

        package = load(
            archive=archive_bytes(
                value,
                payloads,
                source_plan,
            )
        )

        filing = next(
            item
            for item in package.responses
            if item.response_key == "filing"
        )
        self.assertEqual(
            dict(filing.route),
            {
                "role": "sec_filing_document",
                "accession_number": "0001601830-26-000040",
                "primary_document": "issuer-20260331.htm",
            },
        )

    def test_rejects_noncontiguous_clinical_page_routes(self) -> None:
        value, payloads, source_plan = capture_value()
        response = next(
            item
            for item in value["responses"]
            if item["response_key"] == "clinical"
        )
        response["route"]["page_ordinal"] = 99
        response["request_url"] = clinical_url() + "&pageToken=next"
        response["final_url"] = response["request_url"]

        with self.assertRaisesRegex(
            PrimarySourceCaptureError,
            "clinical capture pagination is invalid",
        ):
            load(
                archive=archive_bytes(
                    value,
                    payloads,
                    source_plan,
                )
            )

    def test_rejects_traversal_symlink_and_duplicate_zip_members(self) -> None:
        value, payloads, source_plan = capture_value()
        with self.assertRaisesRegex(
            PrimarySourceCaptureError,
            "archive member path is invalid",
        ):
            load(
                archive=archive_bytes(
                    value,
                    payloads,
                    source_plan,
                    extras={"../escape": b"x"},
                )
            )

        first_payload = next(iter(payloads))
        with self.assertRaisesRegex(
            PrimarySourceCaptureError,
            "archive symlink is invalid",
        ):
            load(
                archive=archive_bytes(
                    value,
                    payloads,
                    source_plan,
                    symlink_name=first_payload,
                )
            )

        output = BytesIO()
        with ZipFile(output, "w", compression=ZIP_STORED) as archive:
            archive.writestr("capture.json", b"{}")
            archive.writestr("capture.json", b"{}")
        with self.assertRaisesRegex(
            PrimarySourceCaptureError,
            "duplicate archive member",
        ):
            load(archive=output.getvalue())

    def test_no_network_fallback_and_unconsumed_records_fail(self) -> None:
        package = load()
        session = package.open_session()
        with self.assertRaises(CaptureMiss):
            session.sec_transport().request(
                "https://data.sec.gov/submissions/missing.json",
                headers={},
            )
        with self.assertRaisesRegex(
            PrimarySourceCaptureError,
            "unconsumed capture responses",
        ):
            session.assert_all_consumed()

    def test_content_change_changes_hash(self) -> None:
        value, payloads, source_plan = capture_value()
        first = load(
            archive=archive_bytes(value, payloads, source_plan),
        )
        changed = deepcopy(value)
        changed["responses"][0]["retrieved_at"] = (
            "2026-05-07T01:30:00+00:00"
        )
        second = load(
            archive=archive_bytes(changed, payloads, source_plan),
        )
        self.assertNotEqual(first.content_hash, second.content_hash)


if __name__ == "__main__":
    unittest.main()
