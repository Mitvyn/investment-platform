from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from investment_research_os.hosted_verification_inventory import (
    HostedMigrationObjectDisposition,
    HostedVerificationObjectInventory,
    build_hosted_verification_object_inventory,
)


COMPLIANT_MIGRATION = """\
create table public.iros_jobs (id uuid);
alter table public.iros_jobs enable row level security;
revoke all privileges on table public.iros_jobs from anon, authenticated;

create view public.iros_v_jobs
with (security_invoker = true)
as select id from public.iros_jobs;
revoke all privileges on table public.iros_v_jobs from anon, authenticated;

create function public.iros_claim_job()
returns void
language sql
security invoker
as $$ select null $$;
"""


class HostedVerificationObjectInventoryTests(unittest.TestCase):
    def test_freezes_every_created_object_with_explicit_disposition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            migration = Path(directory) / "20260810000000_iros_inventory.sql"
            migration.write_text(COMPLIANT_MIGRATION)

            inventory = build_hosted_verification_object_inventory(
                migration_paths=(migration,),
                execution_targets=("iros_jobs",),
                exclusion_reasons={
                    "iros_v_jobs": "derived_read_model_not_directly_probed",
                    "iros_claim_job": "runtime_rpc_not_directly_probed",
                },
            )

        self.assertEqual(
            inventory.inventory_version, "hosted-verification-object-inventory.v1"
        )
        self.assertEqual(inventory.discovered_count, 3)
        self.assertEqual(inventory.execution_target_count, 1)
        self.assertEqual(inventory.excluded_count, 2)
        self.assertEqual(
            tuple(entry.object_name for entry in inventory.entries),
            ("iros_claim_job", "iros_jobs", "iros_v_jobs"),
        )
        self.assertTrue(inventory.has_valid_content_hash())

    def test_rejects_created_object_without_disposition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            migration = Path(directory) / "20260810000000_iros_inventory.sql"
            migration.write_text(COMPLIANT_MIGRATION)

            with self.assertRaisesRegex(
                ValueError,
                "object disposition is incomplete",
            ):
                build_hosted_verification_object_inventory(
                    migration_paths=(migration,),
                    execution_targets=("iros_jobs",),
                    exclusion_reasons={
                        "iros_v_jobs": "derived_read_model_not_directly_probed",
                    },
                )

    def test_rejects_exclusion_for_unknown_or_dispatched_object(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            migration = Path(directory) / "20260810000000_iros_inventory.sql"
            migration.write_text(COMPLIANT_MIGRATION)

            for exclusion_reasons in (
                {
                    "iros_jobs": "private_persistence_not_directly_probed",
                    "iros_v_jobs": "derived_read_model_not_directly_probed",
                    "iros_claim_job": "runtime_rpc_not_directly_probed",
                },
                {
                    "iros_missing": "private_persistence_not_directly_probed",
                    "iros_v_jobs": "derived_read_model_not_directly_probed",
                    "iros_claim_job": "runtime_rpc_not_directly_probed",
                },
            ):
                with self.subTest(exclusion_reasons=exclusion_reasons):
                    with self.assertRaisesRegex(
                        ValueError,
                        "object exclusion is invalid",
                    ):
                        build_hosted_verification_object_inventory(
                            migration_paths=(migration,),
                            execution_targets=("iros_jobs",),
                            exclusion_reasons=exclusion_reasons,
                        )

    def test_comments_and_literals_do_not_create_inventory_objects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            migration = Path(directory) / "20260810000000_iros_inventory.sql"
            migration.write_text(
                COMPLIANT_MIGRATION
                + "\n-- create table public.iros_comment_only (id uuid);\n"
                + "select 'create view public.iros_literal_only as select 1';\n"
            )

            inventory = build_hosted_verification_object_inventory(
                migration_paths=(migration,),
                execution_targets=("iros_jobs",),
                exclusion_reasons={
                    "iros_v_jobs": "derived_read_model_not_directly_probed",
                    "iros_claim_job": "runtime_rpc_not_directly_probed",
                },
            )

        self.assertEqual(inventory.discovered_count, 3)

    def test_recomputed_hash_cannot_bypass_entry_contract(self) -> None:
        content = {
            "object_name": "iros_jobs",
            "object_kind": "table",
            "migration_filenames": ["20260810000000_iros_inventory.sql"],
            "disposition": "excluded",
            "reason_code": "caller_invented_reason",
        }
        content_sha256 = hashlib.sha256(
            json.dumps(
                content,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        entry = HostedMigrationObjectDisposition(
            object_name="iros_jobs",
            object_kind="table",
            migration_filenames=("20260810000000_iros_inventory.sql",),
            disposition="excluded",
            reason_code="caller_invented_reason",
            content_sha256=content_sha256,
        )

        with self.assertRaisesRegex(
            ValueError,
            "inventory entry hash is invalid",
        ):
            HostedVerificationObjectInventory.freeze(
                migration_manifest_sha256="0" * 64,
                entries=(entry,),
            )


if __name__ == "__main__":
    unittest.main()
