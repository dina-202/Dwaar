"""Tests for deterministic and audited Phase 3J case operations."""

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
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
    Client,
    Firm,
)
from domain.case_operations_models import WorkQueueDeadlineStatus
from domain.models import NoticeForm, ProceedingType
from modules.authorized_case_service import AuthorizedCaseService
from modules.case_operations import (
    allowed_status_targets,
    build_case_work_queue,
    deadline_status_for_case,
    validate_status_transition,
)
from modules.sqlite_case_repository import LocalSQLiteCaseRepository


NOW = datetime(2026, 9, 22, 16, 30, tzinfo=timezone.utc)
TODAY = date(2026, 9, 22)
PRINCIPAL = AuthenticatedPrincipal("OIDC-" + "a" * 64)


def client(client_id="C-1", firm_id="F-1", name="Client"):
    return Client(client_id, firm_id, name, NOW)


def case(
    *,
    case_id="CASE-1",
    client_id="C-1",
    status=CaseStatus.INTAKE,
    deadline=None,
    assigned_to=None,
    reviewer_id=None,
    closed_at=None,
):
    return CaseRecord(
        case_id=case_id,
        firm_id="F-1",
        client_id=client_id,
        registration_id=None,
        title=case_id,
        status=status,
        proceeding_type=ProceedingType.GST_SEC73_GENERAL,
        notice_form=NoticeForm.DRC_01,
        opened_at=NOW,
        response_deadline=deadline,
        assigned_to=assigned_to,
        reviewer_id=reviewer_id,
        closed_at=closed_at,
    )


class CaseDeadlinePriorityTests(unittest.TestCase):
    def test_deadline_buckets_exact(self):
        values = [
            (
                case(deadline=date(2026, 9, 21)),
                WorkQueueDeadlineStatus.OVERDUE,
                -1,
            ),
            (
                case(deadline=TODAY),
                WorkQueueDeadlineStatus.DUE_TODAY,
                0,
            ),
            (
                case(deadline=date(2026, 9, 29)),
                WorkQueueDeadlineStatus.DUE_SOON,
                7,
            ),
            (
                case(deadline=date(2026, 9, 30)),
                WorkQueueDeadlineStatus.UPCOMING,
                8,
            ),
            (
                case(deadline=None),
                WorkQueueDeadlineStatus.NO_DEADLINE,
                None,
            ),
            (
                case(
                    status=CaseStatus.CLOSED,
                    deadline=date(2026, 9, 1),
                    closed_at=NOW,
                ),
                WorkQueueDeadlineStatus.CLOSED,
                None,
            ),
        ]
        for item, expected_status, expected_days in values:
            with self.subTest(expected_status=expected_status):
                status, days = deadline_status_for_case(item, TODAY)
                self.assertIs(status, expected_status)
                self.assertEqual(days, expected_days)

    def test_work_queue_orders_urgent_before_closed(self):
        clients = [client()]
        cases = [
            case(
                case_id="CLOSED",
                status=CaseStatus.CLOSED,
                deadline=date(2026, 9, 1),
                closed_at=NOW,
            ),
            case(case_id="NO-DATE"),
            case(case_id="SOON", deadline=date(2026, 9, 25)),
            case(case_id="OVERDUE", deadline=date(2026, 9, 20)),
            case(case_id="TODAY", deadline=TODAY),
            case(case_id="UPCOMING", deadline=date(2026, 10, 10)),
        ]
        queue = build_case_work_queue(cases, clients, TODAY)
        self.assertEqual(
            [item.case_id for item in queue],
            ["OVERDUE", "TODAY", "SOON", "UPCOMING", "NO-DATE", "CLOSED"],
        )

    def test_missing_client_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "unavailable client"):
            build_case_work_queue([case()], [], TODAY)


class CaseStatusTransitionTests(unittest.TestCase):
    def test_expected_forward_and_review_loop_transitions_are_allowed(self):
        allowed = [
            (CaseStatus.INTAKE, CaseStatus.ANALYZED),
            (CaseStatus.INTAKE, CaseStatus.EVIDENCE_COLLECTION),
            (CaseStatus.ANALYZED, CaseStatus.DRAFT_REVIEW),
            (CaseStatus.EVIDENCE_COLLECTION, CaseStatus.ANALYZED),
            (CaseStatus.DRAFT_REVIEW, CaseStatus.EVIDENCE_COLLECTION),
            (CaseStatus.DRAFT_REVIEW, CaseStatus.FILED),
            (CaseStatus.FILED, CaseStatus.HEARING),
            (CaseStatus.HEARING, CaseStatus.FILED),
            (CaseStatus.HEARING, CaseStatus.ORDER_RECEIVED),
            (CaseStatus.ORDER_RECEIVED, CaseStatus.CLOSED),
        ]
        for before, after in allowed:
            with self.subTest(before=before, after=after):
                validate_status_transition(before, after)

    def test_illegal_jump_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "not allowed"):
            validate_status_transition(
                CaseStatus.INTAKE,
                CaseStatus.FILED,
            )

    def test_closed_has_no_transition_targets_except_current_display_value(self):
        self.assertEqual(
            allowed_status_targets(CaseStatus.CLOSED),
            (CaseStatus.CLOSED,),
        )


class AtomicCaseOperationsRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "dwaar.db")
        self.repo = LocalSQLiteCaseRepository(self.db_path)
        self.repo.create_firm(Firm("F-1", "Firm", NOW))
        self.repo.create_client(client())
        self.repo.create_case(case())

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_update_and_events_commit_together(self):
        updated = case(
            status=CaseStatus.ANALYZED,
            deadline=date(2026, 10, 1),
        )
        events = [
            CaseEvent(
                "EV-STATUS",
                "CASE-1",
                CaseEventType.CASE_STATUS_CHANGED,
                NOW,
                PRINCIPAL.user_id,
                {
                    "from_status": "intake",
                    "to_status": "analyzed",
                },
            ),
            CaseEvent(
                "EV-OPS",
                "CASE-1",
                CaseEventType.CASE_OPERATIONS_UPDATED,
                NOW,
                PRINCIPAL.user_id,
                {
                    "from_response_deadline": "none",
                    "to_response_deadline": "2026-10-01",
                },
            ),
        ]
        self.repo.update_case_with_events(updated, events)
        stored = self.repo.get_case("CASE-1")
        self.assertIs(stored.status, CaseStatus.ANALYZED)
        self.assertEqual(stored.response_deadline, date(2026, 10, 1))
        self.assertCountEqual(
            [event.event_type for event in self.repo.list_events("CASE-1")],
            [
                CaseEventType.CASE_STATUS_CHANGED,
                CaseEventType.CASE_OPERATIONS_UPDATED,
            ],
        )

    def test_event_failure_rolls_back_case_row(self):
        self.repo.append_event(
            CaseEvent(
                "EV-DUP",
                "CASE-1",
                CaseEventType.CASE_OPERATIONS_UPDATED,
                NOW,
                PRINCIPAL.user_id,
                {"sentinel": "existing"},
            )
        )
        updated = case(status=CaseStatus.ANALYZED)
        with self.assertRaises(Exception):
            self.repo.update_case_with_events(
                updated,
                [
                    CaseEvent(
                        "EV-DUP",
                        "CASE-1",
                        CaseEventType.CASE_STATUS_CHANGED,
                        NOW,
                        PRINCIPAL.user_id,
                        {
                            "from_status": "intake",
                            "to_status": "analyzed",
                        },
                    )
                ],
            )
        self.assertIs(
            self.repo.get_case("CASE-1").status,
            CaseStatus.INTAKE,
        )

    def test_closed_at_invariant_is_repository_enforced(self):
        with self.assertRaisesRegex(Exception, "closed_at"):
            self.repo.update_case(
                case(
                    status=CaseStatus.CLOSED,
                    closed_at=None,
                )
            )


class AuthorizedCaseOperationsTests(unittest.TestCase):
    def build(self, *, permissions=None, existing=None):
        repo = mock.Mock()
        access = mock.Mock()
        store = mock.Mock()
        if permissions is None:
            permissions = {
                AccessPermission.CASE_READ,
                AccessPermission.CASE_UPDATE,
            }
        access.get_grant.side_effect = lambda user_id, firm_id: (
            FirmAccessGrant(
                user_id=user_id,
                firm_id=firm_id,
                permissions=frozenset(permissions),
                active=True,
            )
            if user_id == PRINCIPAL.user_id
            else None
        )
        repo.get_case.return_value = existing or case()
        repo.list_cases.return_value = [existing or case()]
        repo.list_clients.return_value = [client()]
        service = AuthorizedCaseService(repo, access, store)
        return service, repo, access

    def test_work_queue_requires_case_read(self):
        service, repo, _ = self.build(
            permissions={AccessPermission.CASE_UPDATE}
        )
        with self.assertRaises(PermissionError):
            service.list_case_work_queue(
                PRINCIPAL,
                "F-1",
                today=TODAY,
            )
        repo.list_cases.assert_not_called()

    def test_assignable_members_are_active_case_readers_only(self):
        service, _, access = self.build()
        access.list_grants_for_firm.return_value = [
            FirmAccessGrant(
                "U-READ",
                "F-1",
                frozenset({AccessPermission.CASE_READ}),
                True,
            ),
            FirmAccessGrant(
                "U-INACTIVE",
                "F-1",
                frozenset({AccessPermission.CASE_READ}),
                False,
            ),
            FirmAccessGrant(
                "U-NOREAD",
                "F-1",
                frozenset({AccessPermission.CASE_UPDATE}),
                True,
            ),
        ]
        self.assertEqual(
            service.list_assignable_user_ids(PRINCIPAL, "F-1"),
            ["U-READ"],
        )

    def test_status_and_assignment_update_emits_controlled_events(self):
        service, repo, access = self.build()
        target = FirmAccessGrant(
            "U-READ",
            "F-1",
            frozenset({AccessPermission.CASE_READ}),
            True,
        )
        original_side_effect = access.get_grant.side_effect

        def get_grant(user_id, firm_id):
            if user_id == "U-READ":
                return target
            return original_side_effect(user_id, firm_id)

        access.get_grant.side_effect = get_grant

        updated = service.update_case_operations(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            status=CaseStatus.ANALYZED,
            response_deadline=date(2026, 10, 1),
            assigned_to="U-READ",
            reviewer_id=None,
            updated_at=NOW,
        )

        self.assertIs(updated.status, CaseStatus.ANALYZED)
        self.assertEqual(updated.assigned_to, "U-READ")
        repo.update_case_with_events.assert_called_once()
        saved, events = repo.update_case_with_events.call_args.args
        self.assertIs(saved, updated)
        self.assertEqual(
            [event.event_type for event in events],
            [
                CaseEventType.CASE_STATUS_CHANGED,
                CaseEventType.CASE_OPERATIONS_UPDATED,
            ],
        )
        event_text = repr([event.payload for event in events])
        self.assertNotIn("source_text", event_text)
        self.assertNotIn("reviewer_note", event_text)
        self.assertEqual(
            {event.actor_id for event in events},
            {PRINCIPAL.user_id},
        )

    def test_non_member_assignment_is_rejected_before_repository_write(self):
        service, repo, _ = self.build()
        with self.assertRaisesRegex(ValueError, "active firm case reader"):
            service.update_case_operations(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                status=CaseStatus.INTAKE,
                response_deadline=None,
                assigned_to="OUTSIDER",
                reviewer_id=None,
                updated_at=NOW,
            )
        repo.update_case_with_events.assert_not_called()

    def test_closed_case_is_terminal(self):
        service, repo, _ = self.build(
            existing=case(
                status=CaseStatus.CLOSED,
                closed_at=NOW,
            )
        )
        with self.assertRaisesRegex(ValueError, "closed cases"):
            service.update_case_operations(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                status=CaseStatus.CLOSED,
                response_deadline=None,
                assigned_to=None,
                reviewer_id=None,
                updated_at=NOW,
            )
        repo.update_case_with_events.assert_not_called()

    def test_closing_sets_closed_at(self):
        service, repo, _ = self.build()
        updated = service.update_case_operations(
            PRINCIPAL,
            "F-1",
            case_id="CASE-1",
            status=CaseStatus.CLOSED,
            response_deadline=None,
            assigned_to=None,
            reviewer_id=None,
            updated_at=NOW,
        )
        self.assertEqual(updated.closed_at, NOW)
        self.assertIs(updated.status, CaseStatus.CLOSED)
        repo.update_case_with_events.assert_called_once()

    def test_no_change_is_rejected(self):
        service, repo, _ = self.build()
        with self.assertRaisesRegex(ValueError, "no changes"):
            service.update_case_operations(
                PRINCIPAL,
                "F-1",
                case_id="CASE-1",
                status=CaseStatus.INTAKE,
                response_deadline=None,
                assigned_to=None,
                reviewer_id=None,
                updated_at=NOW,
            )
        repo.update_case_with_events.assert_not_called()


if __name__ == "__main__":
    unittest.main()
