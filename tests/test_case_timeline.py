"""Tests for Phase 3M unified case timeline projection."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from domain.auth_models import (
    AccessPermission,
    AuthenticatedPrincipal,
    FirmAccessGrant,
)
from domain.case_models import (
    CaseEvent,
    CaseEventType,
    CaseRecord,
    CaseStatus,
)
from domain.case_timeline_models import TimelineCategory
from domain.models import NoticeForm, ProceedingType
from modules.authorized_case_service import AuthorizedCaseService
from modules.case_timeline import build_case_timeline


NOW = datetime(2026, 9, 22, 18, 0, tzinfo=timezone.utc)
PRINCIPAL = AuthenticatedPrincipal("OIDC-" + "a" * 64)


def event(
    event_id,
    event_type,
    *,
    offset=0,
    actor="OIDC-ACTOR",
    payload=None,
):
    return CaseEvent(
        event_id=event_id,
        case_id="CASE-1",
        event_type=event_type,
        occurred_at=NOW + timedelta(minutes=offset),
        actor_id=actor,
        payload={} if payload is None else payload,
    )


class CaseTimelineProjectionTests(unittest.TestCase):
    def test_all_current_event_types_have_timeline_projection(self):
        events = [
            event(
                f"EV-{index:02d}",
                event_type,
                offset=index,
            )
            for index, event_type in enumerate(CaseEventType)
        ]
        items = build_case_timeline(events)
        self.assertEqual(len(items), len(CaseEventType))
        self.assertEqual(
            {item.event_type for item in items},
            set(CaseEventType),
        )
        self.assertTrue(
            all(item.title and item.summary for item in items)
        )

    def test_projection_is_chronological_with_stable_event_id_tiebreak(self):
        events = [
            event("EV-B", CaseEventType.CASE_CREATED, offset=2),
            event("EV-C", CaseEventType.ANALYSIS_SAVED, offset=1),
            event("EV-A", CaseEventType.DOCUMENT_ADDED, offset=2),
        ]
        self.assertEqual(
            [item.event_id for item in build_case_timeline(events)],
            ["EV-C", "EV-A", "EV-B"],
        )

    def test_known_metadata_is_rendered_truthfully(self):
        items = build_case_timeline(
            [
                event(
                    "EV-STATUS",
                    CaseEventType.CASE_STATUS_CHANGED,
                    payload={
                        "from_status": "draft_review",
                        "to_status": "filed",
                    },
                ),
                event(
                    "EV-FILE",
                    CaseEventType.FILING_RECORDED,
                    payload={"filing_reference": "ARN-123"},
                ),
                event(
                    "EV-DRAFT",
                    CaseEventType.DRAFT_REVIEWED,
                    payload={
                        "version_number": "4",
                        "from_status": "reviewed",
                        "to_status": "approved",
                    },
                ),
            ]
        )
        text = repr([(item.title, item.summary) for item in items])
        self.assertIn("draft_review", text)
        self.assertIn("filed", text)
        self.assertIn("ARN-123", text)
        self.assertIn("approved", text)

    def test_unknown_payload_keys_do_not_surface(self):
        sentinel = "PRIVATE-SENTINEL-SHOULD-NOT-RENDER"
        item = build_case_timeline(
            [
                event(
                    "EV-1",
                    CaseEventType.ANALYSIS_SAVED,
                    payload={
                        "snapshot_id": "SNAP-1",
                        "unexpected_sensitive_key": sentinel,
                    },
                )
            ]
        )[0]
        self.assertNotIn(sentinel, item.summary)
        self.assertNotIn(sentinel, item.title)

    def test_categories_are_closed_and_meaningful(self):
        events = [
            event("E1", CaseEventType.CASE_CREATED),
            event("E2", CaseEventType.DOCUMENT_ADDED),
            event("E3", CaseEventType.ANALYSIS_SAVED),
            event("E4", CaseEventType.EVIDENCE_REVIEWED),
            event("E5", CaseEventType.DRAFT_CREATED),
            event("E6", CaseEventType.FILING_RECORDED),
            event("E7", CaseEventType.HEARING_RECORDED),
            event("E8", CaseEventType.ORDER_RECORDED),
        ]
        categories = {
            item.category for item in build_case_timeline(events)
        }
        self.assertEqual(categories, set(TimelineCategory))

    def test_non_event_input_fails_closed(self):
        with self.assertRaises(TypeError):
            build_case_timeline([object()])


class AuthorizedCaseTimelineTests(unittest.TestCase):
    def build(self, *, firm_id="F-1"):
        cases = mock.Mock()
        access = mock.Mock()
        documents = mock.Mock()
        access.get_grant.return_value = FirmAccessGrant(
            user_id=PRINCIPAL.user_id,
            firm_id=firm_id,
            permissions=frozenset({AccessPermission.CASE_READ}),
            active=True,
        )
        cases.get_case.return_value = CaseRecord(
            case_id="CASE-1",
            firm_id=firm_id,
            client_id="C-1",
            registration_id=None,
            title="Matter",
            status=CaseStatus.ANALYZED,
            proceeding_type=ProceedingType.GST_SEC73_GENERAL,
            notice_form=NoticeForm.DRC_01,
            opened_at=NOW,
        )
        cases.list_events.return_value = [
            event("EV-1", CaseEventType.CASE_CREATED)
        ]
        return AuthorizedCaseService(cases, access, documents), cases

    def test_authorized_timeline_reads_case_events_only_after_case_check(self):
        service, cases = self.build()
        result = service.get_case_timeline(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
        )
        self.assertEqual(len(result), 1)
        cases.get_case.assert_called_once_with("CASE-1")
        cases.list_events.assert_called_once_with("CASE-1")

    def test_cross_firm_case_id_does_not_expose_events(self):
        service, cases = self.build()
        cases.get_case.return_value = CaseRecord(
            case_id="CASE-1",
            firm_id="F-OTHER",
            client_id="C-X",
            registration_id=None,
            title="Other",
            status=CaseStatus.ANALYZED,
            proceeding_type=ProceedingType.GST_SEC73_GENERAL,
            notice_form=NoticeForm.DRC_01,
            opened_at=NOW,
        )
        with self.assertRaises(LookupError):
            service.get_case_timeline(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
            )
        cases.list_events.assert_not_called()


if __name__ == "__main__":
    unittest.main()
