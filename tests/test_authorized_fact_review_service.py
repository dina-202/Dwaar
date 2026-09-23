"""Tests for authorized snapshot-bound professional fact review."""

import unittest
from datetime import datetime, timezone
from unittest import mock

from domain.auth_models import (
    AccessPermission,
    AuthenticatedPrincipal,
    FirmAccessGrant,
)
from domain.fact_review_models import (
    FactReviewDecision,
    FactReviewRef,
)
from modules.authorized_fact_review_service import (
    AuthorizedFactReviewService,
)


NOW = datetime(2026, 9, 23, 17, 30, tzinfo=timezone.utc)
PRINCIPAL = AuthenticatedPrincipal("OIDC-" + "a" * 64)


def fact_row(
    *,
    fact_id="F-001",
    source_text="Exact notice source text",
):
    return {
        "fact_id": fact_id,
        "claim": "Model-authored claim must never drive review binding",
        "fact_type": "department_allegation",
        "fact_role": "none",
        "status": "alleged",
        "source_text": source_text,
        "source_page": 2,
        "source_origin": "embedded",
        "source_verification": "verified",
        "allowed_in_draft": "conditional",
    }


def snapshot_payload(facts=None):
    return {
        "extraction": {
            "facts": list(facts or [fact_row()]),
        }
    }


class AuthorizedFactReviewServiceTests(unittest.TestCase):
    def build(self, *, permissions=None, payload=None):
        permissions = (
            {AccessPermission.FACT_REVIEW, AccessPermission.CASE_READ}
            if permissions is None
            else set(permissions)
        )
        case_service = mock.Mock()
        case = mock.Mock()
        case.case_id = "CASE-1"
        case_service.get_case.return_value = case

        snapshot_service = mock.Mock()
        snapshot = mock.Mock()
        snapshot.metadata.snapshot_id = "SNAP-1"
        snapshot.payload = payload or snapshot_payload()
        snapshot_service.load_snapshot.return_value = snapshot

        access = mock.Mock()
        access.get_grant.return_value = FirmAccessGrant(
            user_id=PRINCIPAL.user_id,
            firm_id="F-1",
            permissions=frozenset(permissions),
            active=True,
        )
        reviews = mock.Mock()
        documents = mock.Mock()
        service = AuthorizedFactReviewService(
            case_service,
            snapshot_service,
            access,
            reviews,
            documents,
        )
        return service, case_service, snapshot_service, access, reviews, documents

    def test_list_reviewable_facts_returns_exact_snapshot_source_rows(self):
        service, *_ = self.build()
        facts = service.list_reviewable_facts(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            snapshot_id="SNAP-1",
        )
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["fact_id"], "F-001")
        self.assertEqual(facts[0]["source_text"], "Exact notice source text")
        self.assertNotIn("claim", facts[0])

    def test_fact_without_source_quote_is_not_offered_for_review(self):
        service, *_ = self.build(
            payload=snapshot_payload(
                [
                    fact_row(fact_id="F-EMPTY", source_text="   "),
                    fact_row(fact_id="F-OK", source_text="Verified quote"),
                ]
            )
        )
        facts = service.list_reviewable_facts(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            snapshot_id="SNAP-1",
        )
        self.assertEqual([item["fact_id"] for item in facts], ["F-OK"])

    def test_missing_fact_review_permission_blocks_every_read_surface(self):
        service, case_service, snapshot_service, *_ = self.build(
            permissions={AccessPermission.CASE_READ}
        )
        with self.assertRaises(PermissionError):
            service.list_reviewable_facts(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                snapshot_id="SNAP-1",
            )
        case_service.get_case.assert_not_called()
        snapshot_service.load_snapshot.assert_not_called()

    @mock.patch(
        "modules.authorized_fact_review_service.persist_fact_review"
    )
    def test_save_review_resolves_fact_from_snapshot_not_client_payload(
        self,
        persist,
    ):
        expected = mock.Mock()
        persist.return_value = expected
        service, *_ = self.build()
        result = service.save_review(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            snapshot_id="SNAP-1",
            fact_id="F-001",
            decision=FactReviewDecision.REJECTED,
            reviewer_note="Notice wording was misread.",
            reviewed_at=NOW,
        )
        self.assertIs(result, expected)
        persist.assert_called_once()
        kwargs = persist.call_args.kwargs
        self.assertEqual(kwargs["case_id"], "CASE-1")
        self.assertEqual(kwargs["snapshot_id"], "SNAP-1")
        self.assertEqual(kwargs["fact"]["fact_id"], "F-001")
        self.assertEqual(
            kwargs["fact"]["source_text"],
            "Exact notice source text",
        )
        self.assertNotIn("claim", kwargs["fact"])
        self.assertIs(kwargs["decision"], FactReviewDecision.REJECTED)
        self.assertEqual(kwargs["actor_id"], PRINCIPAL.user_id)

    @mock.patch(
        "modules.authorized_fact_review_service.persist_fact_review"
    )
    def test_unknown_fact_id_fails_without_persistence(self, persist):
        service, *_ = self.build()
        with self.assertRaises(LookupError):
            service.save_review(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                snapshot_id="SNAP-1",
                fact_id="F-NOT-THERE",
                decision=FactReviewDecision.CONFIRMED,
                reviewer_note=None,
                reviewed_at=NOW,
            )
        persist.assert_not_called()

    def test_list_reviews_is_snapshot_scoped_and_permission_checked(self):
        service, _, snapshot_service, _, reviews, _ = self.build()
        expected = [mock.Mock()]
        reviews.list_review_refs.return_value = expected
        result = service.list_reviews(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            snapshot_id="SNAP-1",
        )
        self.assertEqual(result, expected)
        snapshot_service.load_snapshot.assert_called_once()
        reviews.list_review_refs.assert_called_once_with("SNAP-1")

    @mock.patch(
        "modules.authorized_fact_review_service.load_fact_review"
    )
    def test_load_review_rejects_review_from_another_snapshot(self, load):
        service, _, _, _, reviews, _ = self.build()
        reviews.get_review_ref.return_value = FactReviewRef(
            review_id="FREV-1",
            case_id="CASE-1",
            snapshot_id="SNAP-OTHER",
            fact_id="F-001",
            fact_fingerprint="a" * 64,
            source_text_sha256="b" * 64,
            decision=FactReviewDecision.CONFIRMED,
            byte_size=10,
            sha256_hex="c" * 64,
            storage_key="objects/" + "d" * 32,
            reviewed_at=NOW,
            reviewed_by=PRINCIPAL.user_id,
        )
        with self.assertRaises(LookupError):
            service.load_review(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                snapshot_id="SNAP-1",
                review_id="FREV-1",
            )
        load.assert_not_called()

    def test_rejected_fact_ids_requires_fact_review_permission(self):
        service, case_service, *_ = self.build(
            permissions={AccessPermission.CASE_READ}
        )
        with self.assertRaises(PermissionError):
            service.rejected_fact_ids(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                snapshot_id="SNAP-1",
            )
        case_service.get_case.assert_not_called()


if __name__ == "__main__":
    unittest.main()
