"""Unit tests for the six approved deep workflow definitions and the
deterministic workflow registry (ARCHITECTURE_SPEC_v1_1 §10, §10.1-§10.3,
§13 Step 5).

Fully offline and deterministic. No LLM calls, no network, no fixtures.

Verifies:

  - WorkflowDefinition has exactly the §10 field contract;
  - exactly six workflow objects exist, keyed by ProceedingType; UNKNOWN
    has no workflow and get_workflow has no fallback;
  - default severities match §10;
  - every workflow's required_facts, evidence_requirements, issue_types,
    output_structure and special_rules match §10.3 verbatim (including the
    fraud and Section 129 safety rules, pinned as exact spec strings);
  - no Section 74A / Section 130 / non-deep NoticeForm workflows exist;
  - each workflow owns distinct list objects (mutation isolation);
  - workflow code imports only stdlib + domain.models;
  - the old prohibited Section 129 assumptions are absent as affirmative
    workflow requirements.

Runnable with Python's standard library unittest only:
    python -m unittest tests/test_workflows.py -v
No pytest, no external dependencies.
"""

import pathlib
import unittest
from dataclasses import fields, is_dataclass
from typing import List

from domain.models import IssueSeverity, ProceedingType

import workflows
import workflows.gst as gst_pkg
from workflows.gst import GST_WORKFLOW_REGISTRY, get_workflow
from workflows.gst.base import WorkflowDefinition

LIST_FIELDS = (
    "required_facts",
    "evidence_requirements",
    "issue_types",
    "output_structure",
    "special_rules",
)

# Exact §10.3 authoritative content, transcribed verbatim so the tests
# detect any future workflow drift.
EXPECTED_WORKFLOWS = {
    ProceedingType.GST_SEC61_SCRUTINY: {
        "default_severity": IssueSeverity.MEDIUM,
        "required_facts": [
            "Discrepancy / issue stated by the department in FORM GST ASMT-10",
            "FY / tax period under scrutiny",
            "Response period stated in the notice, where stated",
        ],
        "evidence_requirements": [
            "Return(s) and statements under scrutiny for the relevant period",
            "Reconciliation and supporting records relevant to each discrepancy stated in FORM GST ASMT-10",
            "Documents explicitly requested in FORM GST ASMT-10, where stated",
            "Annexures or discrepancy computations referenced by FORM GST ASMT-10, where stated",
        ],
        "issue_types": [
            "RETURN_SCRUTINY_DISCREPANCY",
            "DISCREPANCY_RECONCILIATION",
            "RESPONSE_TIMELINE",
        ],
        "output_structure": [
            "Scrutiny working paper",
            "Discrepancy-by-discrepancy response matrix",
            "Reviewable ASMT-11 explanation",
        ],
        "special_rules": [
            "Every discrepancy stated in FORM GST ASMT-10 remains a departmental allegation unless independently supported by taxpayer evidence.",
            "Address each stated discrepancy separately; never treat the notice wording alone as an admission by the taxpayer.",
            "Do not inject a generic statutory reply period; use only the notice-stated response period or due date and verified service/receipt inputs.",
            "Any acceptance of a discrepancy, payment, or corrective action requires taxpayer evidence and professional confirmation.",
            "Mandatory CA review is required before any ASMT-11 response is filed.",
        ],
    },
    ProceedingType.GST_SEC73_ITC: {
        "default_severity": IssueSeverity.MEDIUM,
        "required_facts": [
            "ITC claimed in GSTR-3B (amount)",
            "ITC reflected in GSTR-2B (amount)",
            "Difference between GSTR-3B and GSTR-2B (INFERRED)",
            "FY / tax period",
            "Interest proposed",
        ],
        "evidence_requirements": [
            "GSTR-2B for all months in the relevant period",
            "GSTR-3B ITC tables for the relevant period",
            "Invoice-level ITC reconciliation",
            "Supplier GSTR-1 filing status / supporting filing evidence where relevant",
            "Payment proof to suppliers where relevant to the claimed ITC eligibility",
        ],
        "issue_types": [
            "ITC_MISMATCH",
            "SUPPLIER_DEFAULT",
            "INTEREST_COMPUTATION",
        ],
        "output_structure": [
            "Working paper",
            "ITC reconciliation table",
            "Reviewable DRC-06 draft",
        ],
        "special_rules": [
            "A GSTR-3B versus GSTR-2B mismatch is not by itself proof that the ITC is legally ineligible.",
            "Any computed difference must be treated as INFERRED and calculated deterministically from sourced amounts.",
            "Never assume invoices, receipt of goods or services, supplier compliance, or payment to suppliers unless supported by evidence.",
            "Final ITC eligibility is a legal/factual conclusion requiring evidence and CA review.",
        ],
    },
    ProceedingType.GST_SEC73_GENERAL: {
        "default_severity": IssueSeverity.MEDIUM,
        "required_facts": [
            "Tax / liability declared in GSTR-1",
            "Tax / liability discharged in GSTR-3B",
            "Difference between GSTR-1 and GSTR-3B (INFERRED)",
            "FY / tax period",
            "Interest proposed",
        ],
        "evidence_requirements": [
            "Monthly GSTR-1 and GSTR-3B for the relevant period",
            "GSTR-9 annual return where applicable/relevant",
            "Credit notes and amendments relevant to the mismatch",
        ],
        "issue_types": [
            "SHORT_PAYMENT",
            "GSTR_MISMATCH",
            "INTEREST_COMPUTATION",
        ],
        "output_structure": [
            "Working paper",
            "Month-wise GSTR-1 versus GSTR-3B reconciliation",
            "Reviewable DRC-06 draft",
        ],
        "special_rules": [
            "A return mismatch is not by itself an admission of tax short-payment.",
            "Any computed difference must be treated as INFERRED and calculated deterministically from sourced amounts.",
            "Credit notes, amendments, timing differences and other reconciliation items must be checked before reaching a liability conclusion.",
            "The workflow identifies reconciliation requirements; it does not itself establish legal liability.",
        ],
    },
    ProceedingType.GST_SEC73_RCM: {
        "default_severity": IssueSeverity.MEDIUM,
        "required_facts": [
            "Service / supply category alleged to attract RCM",
            "Value of services / supplies alleged to be subject to RCM",
            "RCM tax alleged as unpaid or short-paid",
            "FY / tax period",
            "Interest proposed",
        ],
        "evidence_requirements": [
            "Invoices / engagement documents for suppliers alleged to be RCM-covered",
            "Form 26AS / TDS data where the department relies on it",
            "GSTR-3B table 3.1(d) for the relevant period",
            "Vendor-wise ledger / service-category reconciliation where required",
        ],
        "issue_types": [
            "RCM_LIABILITY",
            "ITC_REVERSAL",
            "INTEREST_COMPUTATION",
        ],
        "output_structure": [
            "Working paper",
            "RCM supplier / service-category reconciliation",
            "Reviewable DRC-06 draft with conditional RCM submissions",
        ],
        "special_rules": [
            "Do not assume that every payment appearing under a TDS or professional-services category is subject to GST reverse charge.",
            "Service category and RCM applicability require verification from underlying documents and current legal sources.",
            "Form 26AS or TDS data may be evidentiary input but is not by itself conclusive proof of GST RCM liability.",
            "Do not assume ITC availability, revenue neutrality, or entitlement without verifying the taxpayer's facts and applicable law.",
        ],
    },
    ProceedingType.GST_SEC74_FRAUD: {
        "default_severity": IssueSeverity.CRITICAL,
        "required_facts": [
            "Basis of fraud / wilful-misstatement / suppression allegation",
            "Turnover, tax, refund or ITC amount alleged by the department (ALLEGED unless independently established)",
            "FY / tax period",
            "Penalty proposed in the notice (ALLEGED)",
            "Limitation / extended-period basis invoked in the notice",
        ],
        "evidence_requirements": [
            "Books of accounts for the relevant period",
            "Relevant bank statements",
            "Filed GST returns for the relevant period",
            "Correspondence with the department",
            "Underlying third-party / RERA / external-source documents where relied upon by the department",
        ],
        "issue_types": [
            "FRAUD_ALLEGATION",
            "SUPPRESSION",
            "PENALTY_COMPUTATION",
            "LIMITATION",
        ],
        "output_structure": [
            "Urgent working paper",
            "Senior-review / escalation note",
            "Conditional reviewable DRC-06 draft",
        ],
        "special_rules": [
            "Fraud, wilful misstatement and suppression must remain departmental allegations unless established by evidence.",
            "Never state that fraud is present or absent as an established fact without evidentiary support.",
            "Preserve the provenance of third-party or external data relied upon by the department.",
            "Mandatory senior CA / advocate review is required before filing.",
            "This workflow applies only where the notice expressly invokes Section 74; it must not be used as a substitute for Section 74A.",
        ],
    },
    ProceedingType.GST_SEC129_ENFORCE: {
        "default_severity": IssueSeverity.HIGH,
        "required_facts": [
            "Goods description",
            "Vehicle / conveyance number",
            "Detention / seizure date",
            "Section 129 notice date and service date where available",
            "Penalty amount proposed in the notice",
            "Value of goods and tax payable on the goods where stated and relevant to penalty computation",
            "Whether the owner of the goods has come forward, where relevant and determinable",
            "Explicit hearing / payment / response date stated in the notice or order",
            "Order date / current enforcement status if an order has already been issued",
        ],
        "evidence_requirements": [
            "Tax invoice for the goods",
            "E-Way Bill, or evidence explaining its absence where available",
            "Detention / seizure order, including MOV-06 where issued",
            "Section 129 notice and any subsequent order / MOV documents actually issued",
            "GR / LR / GRN / delivery or transport documents relevant to movement of goods",
        ],
        "issue_types": [
            "EWAY_BILL",
            "DETENTION",
            "PENALTY_COMPUTATION",
            "PROCEDURAL_TIMELINE",
            "SECTION_130_RISK",
        ],
        "output_structure": [
            "URGENT enforcement working paper",
            "Enforcement chronology / deadline alert",
            "Penalty computation verification checklist",
            "Reviewable response / submission appropriate to the actual notice or proceeding",
        ],
        "special_rules": [
            "Never assume the tax invoice is valid; invoice validity remains REQUIRES_VERIFICATION until supported by evidence.",
            "Never invent a reason for a missing or defective E-Way Bill.",
            "Do not hardcode a 100% penalty assumption; extract the proposed penalty and defer statutory computation to the deterministic arithmetic/legal-rule layer.",
            "Do not treat the Section 129 seven-day statutory notice/order timeline as a universal taxpayer reply deadline.",
            "MOV-09 is a departmental order and must never be described as the taxpayer's reply form.",
            "A Section-130-only proceeding does not use this deep workflow and remains TRIAGE_ONLY until a separate workflow exists.",
            "Active detention/seizure requires urgent CA escalation, but deadline status must come from the deterministic Deadline Engine and explicit procedural dates.",
        ],
    },
}


class WorkflowDefinitionContractTests(unittest.TestCase):
    """WorkflowDefinition has exactly the §10 field contract."""

    def test_workflow_definition_imports_and_is_dataclass(self):
        self.assertTrue(is_dataclass(WorkflowDefinition))

    def test_workflow_definition_field_contract_exact(self):
        self.assertEqual(
            [f.name for f in fields(WorkflowDefinition)],
            [
                "proceeding_type",
                "required_facts",
                "evidence_requirements",
                "issue_types",
                "default_severity",
                "output_structure",
                "special_rules",
            ],
        )
        self.assertEqual(len(fields(WorkflowDefinition)), 7)

    def test_workflow_definition_field_types(self):
        by_name = {f.name: f.type for f in fields(WorkflowDefinition)}
        self.assertIs(by_name["proceeding_type"], ProceedingType)
        self.assertIs(by_name["default_severity"], IssueSeverity)
        for field in LIST_FIELDS:
            self.assertEqual(by_name[field], List[str], field)


class WorkflowRegistryTests(unittest.TestCase):
    """Exactly six registered workflows; UNKNOWN has none; no fallback."""

    EXPECTED_KEYS = {
        ProceedingType.GST_SEC61_SCRUTINY,
        ProceedingType.GST_SEC73_ITC,
        ProceedingType.GST_SEC73_GENERAL,
        ProceedingType.GST_SEC73_RCM,
        ProceedingType.GST_SEC74_FRAUD,
        ProceedingType.GST_SEC129_ENFORCE,
    }

    def test_registry_contains_exactly_these_five_keys(self):
        self.assertEqual(set(GST_WORKFLOW_REGISTRY.keys()), self.EXPECTED_KEYS)

    def test_registry_keys_are_unique(self):
        keys = list(GST_WORKFLOW_REGISTRY.keys())
        self.assertEqual(len(keys), len(set(keys)))

    def test_exactly_six_workflow_definition_objects_exist(self):
        self.assertEqual(len(GST_WORKFLOW_REGISTRY), 6)
        self.assertTrue(
            all(
                isinstance(wf, WorkflowDefinition)
                for wf in GST_WORKFLOW_REGISTRY.values()
            )
        )

    def test_unknown_is_not_a_registry_key(self):
        self.assertNotIn(ProceedingType.UNKNOWN, GST_WORKFLOW_REGISTRY)

    def test_each_workflow_proceeding_type_matches_its_registry_key(self):
        for ptype, wf in GST_WORKFLOW_REGISTRY.items():
            self.assertIs(wf.proceeding_type, ptype, ptype.name)

    def test_get_workflow_returns_definition_for_all_five(self):
        for ptype in self.EXPECTED_KEYS:
            self.assertIs(
                get_workflow(ptype), GST_WORKFLOW_REGISTRY[ptype], ptype.name
            )

    def test_get_workflow_unknown_returns_none(self):
        self.assertIsNone(get_workflow(ProceedingType.UNKNOWN))

    def test_workflow_modules_export_the_registry_objects(self):
        exports = (
            (
                gst_pkg.sec61_scrutiny.SEC61_SCRUTINY_WORKFLOW,
                ProceedingType.GST_SEC61_SCRUTINY,
            ),
            (gst_pkg.sec73_itc.SEC73_ITC_WORKFLOW, ProceedingType.GST_SEC73_ITC),
            (
                gst_pkg.sec73_general.SEC73_GENERAL_WORKFLOW,
                ProceedingType.GST_SEC73_GENERAL,
            ),
            (gst_pkg.sec73_rcm.SEC73_RCM_WORKFLOW, ProceedingType.GST_SEC73_RCM),
            (
                gst_pkg.sec74_fraud.SEC74_FRAUD_WORKFLOW,
                ProceedingType.GST_SEC74_FRAUD,
            ),
            (
                gst_pkg.sec129_enforcement.SEC129_ENFORCEMENT_WORKFLOW,
                ProceedingType.GST_SEC129_ENFORCE,
            ),
        )
        for export, ptype in exports:
            self.assertIs(export, GST_WORKFLOW_REGISTRY[ptype], ptype.name)

    def test_registry_public_api_is_single_get_workflow(self):
        public = [
            name
            for name in dir(gst_pkg)
            if not name.startswith("_")
            and callable(getattr(gst_pkg, name))
            and getattr(gst_pkg, name).__module__ == gst_pkg.__name__
        ]
        self.assertEqual(public, ["get_workflow"])


class WorkflowContentTests(unittest.TestCase):
    """Every list field matches §10.3 verbatim; severities match §10."""

    def test_every_workflow_has_non_empty_string_list_fields(self):
        for ptype, wf in GST_WORKFLOW_REGISTRY.items():
            for field in LIST_FIELDS:
                value = getattr(wf, field)
                self.assertIsInstance(value, list, f"{ptype.name}.{field}")
                self.assertTrue(value, f"{ptype.name}.{field} is empty")
                self.assertTrue(
                    all(isinstance(item, str) for item in value),
                    f"{ptype.name}.{field}",
                )

    def test_default_severities_exact(self):
        for ptype, expected in EXPECTED_WORKFLOWS.items():
            self.assertIs(
                GST_WORKFLOW_REGISTRY[ptype].default_severity,
                expected["default_severity"],
                ptype.name,
            )

    def _assert_workflow_exact(self, ptype):
        wf = GST_WORKFLOW_REGISTRY[ptype]
        expected = EXPECTED_WORKFLOWS[ptype]
        self.assertIs(wf.proceeding_type, ptype)
        self.assertIs(wf.default_severity, expected["default_severity"])
        for field in LIST_FIELDS:
            self.assertEqual(
                getattr(wf, field), expected[field], f"{ptype.name}.{field}"
            )

    def test_sec61_scrutiny_workflow_content_matches_contract(self):
        self._assert_workflow_exact(ProceedingType.GST_SEC61_SCRUTINY)

    def test_itc_workflow_content_matches_spec_verbatim(self):
        self._assert_workflow_exact(ProceedingType.GST_SEC73_ITC)

    def test_general_workflow_content_matches_spec_verbatim(self):
        self._assert_workflow_exact(ProceedingType.GST_SEC73_GENERAL)

    def test_rcm_workflow_content_matches_spec_verbatim(self):
        self._assert_workflow_exact(ProceedingType.GST_SEC73_RCM)

    def test_fraud_workflow_content_matches_spec_verbatim(self):
        # Pins the exact §10.3 fraud safety rules: allegation preservation,
        # no unsupported fraud-present/absent conclusion, provenance,
        # mandatory senior CA/advocate review, Section 74 only / no Section
        # 74A substitution.
        self._assert_workflow_exact(ProceedingType.GST_SEC74_FRAUD)

    def test_sec129_workflow_content_matches_spec_verbatim(self):
        # Pins the exact §10.3 Section 129 safety rules: invoice-validity
        # verification, no invented e-way-bill reason, no static 100%
        # penalty, no universal 7-day taxpayer reply deadline, MOV-09 is not
        # a taxpayer reply form, Section-130-only not deep, deadline status
        # belongs to the Deadline Engine.
        self._assert_workflow_exact(ProceedingType.GST_SEC129_ENFORCE)


class MutabilitySafetyTests(unittest.TestCase):
    """Each workflow owns distinct list objects (mutation isolation)."""

    def test_no_shared_list_objects_between_workflows(self):
        workflow_list = list(GST_WORKFLOW_REGISTRY.values())
        for index, wf_a in enumerate(workflow_list):
            for wf_b in workflow_list[index + 1 :]:
                for field in LIST_FIELDS:
                    self.assertIsNot(
                        getattr(wf_a, field),
                        getattr(wf_b, field),
                        f"{wf_a.proceeding_type.name} / "
                        f"{wf_b.proceeding_type.name} / {field}",
                    )


class ScopeSafetyTests(unittest.TestCase):
    """No workflow exists for UNKNOWN, Section 74A, Section 130, or
    non-deep NoticeForm concepts."""

    def test_no_workflow_contains_proceeding_type_unknown(self):
        self.assertNotIn(ProceedingType.UNKNOWN, GST_WORKFLOW_REGISTRY)
        for ptype, wf in GST_WORKFLOW_REGISTRY.items():
            self.assertIsNot(wf.proceeding_type, ProceedingType.UNKNOWN, ptype.name)

    def test_no_section_74a_workflow_exists(self):
        self.assertFalse(hasattr(ProceedingType, "GST_SEC74A"))
        self.assertFalse(hasattr(ProceedingType, "GST_SEC74A_GENERAL"))
        self.assertFalse(
            any("74A" in key.name for key in GST_WORKFLOW_REGISTRY)
        )

    def test_no_section_130_workflow_exists(self):
        self.assertFalse(hasattr(ProceedingType, "SECTION_130"))
        self.assertFalse(
            any("130" in key.name for key in GST_WORKFLOW_REGISTRY)
        )

    def test_no_workflow_for_taxonomy_triage_forms(self):
        # DRC_01B / DRC_01C / ASMT_10 / REG_17 / RFD_08 are NoticeForm
        # concepts, not deep ProceedingTypes; none may be a registry key.
        for name in ("DRC_01B", "DRC_01C", "ASMT_10", "REG_17", "RFD_08"):
            self.assertFalse(hasattr(ProceedingType, name), name)
            self.assertNotIn(
                name, {key.name for key in GST_WORKFLOW_REGISTRY}, name
            )


class ImportPurityTests(unittest.TestCase):
    """Workflow code imports only stdlib + domain.models (no LLM, no
    network, no classifier/taxonomy/deadline-engine coupling)."""

    ALLOWED_IMPORT_ROOTS = ("dataclasses", "typing", "domain", "workflows")
    FORBIDDEN_TOKENS = (
        "gemini",
        "genai",
        "google",
        "streamlit",
        "requests",
        "urllib",
        "socket",
        "sqlite",
        "sqlalchemy",
        "database",
        "modules",
        "proceeding_classifier",
        "taxonomy_registry",
        "deadline_engine",
    )

    WORKFLOW_MODULES = (
        workflows,
        gst_pkg,
        gst_pkg.base,
        gst_pkg.sec73_itc,
        gst_pkg.sec73_general,
        gst_pkg.sec73_rcm,
        gst_pkg.sec74_fraud,
        gst_pkg.sec129_enforcement,
    )

    def test_workflow_code_imports_only_stdlib_and_domain_models(self):
        for module in self.WORKFLOW_MODULES:
            source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
            roots = set()
            for line in source.splitlines():
                stripped = line.strip()
                if stripped.startswith("from "):
                    module_name = stripped.split()[1]
                    if module_name.startswith("."):
                        continue  # relative import inside the workflows package
                    roots.add(module_name.split(".")[0])
                elif stripped.startswith("import "):
                    roots.add(stripped.split()[1].split(".")[0])
            self.assertTrue(
                roots <= set(self.ALLOWED_IMPORT_ROOTS),
                f"{module.__name__}: unexpected import roots {sorted(roots)}",
            )

    def test_no_forbidden_technology_in_workflow_source(self):
        for module in self.WORKFLOW_MODULES:
            text = (
                pathlib.Path(module.__file__)
                .read_text(encoding="utf-8")
                .lower()
            )
            for token in self.FORBIDDEN_TOKENS:
                self.assertNotIn(
                    token, text, f"{module.__name__}: forbidden token {token}"
                )


class LegacyAssumptionTests(unittest.TestCase):
    """The old prohibited Section 129 assumptions are absent as affirmative
    workflow requirements (approved prohibition text is still present)."""

    PROHIBITED_PHRASES = (
        "Penalty = 100% of tax",
        "Reply in MOV-09",
        "7 days from service",
    )

    def test_no_legacy_sec129_assumptions_as_affirmative_requirements(self):
        for wf in GST_WORKFLOW_REGISTRY.values():
            content = " ".join(
                wf.required_facts
                + wf.evidence_requirements
                + wf.issue_types
                + wf.output_structure
                + wf.special_rules
            )
            for phrase in self.PROHIBITED_PHRASES:
                self.assertNotIn(phrase, content, phrase)

    def test_approved_sec129_prohibition_text_is_present(self):
        # The prohibitions appear as approved safety-rule text, not as
        # affirmative workflow requirements.
        wf = get_workflow(ProceedingType.GST_SEC129_ENFORCE)
        self.assertIn(
            "Do not hardcode a 100% penalty assumption; extract the proposed "
            "penalty and defer statutory computation to the deterministic "
            "arithmetic/legal-rule layer.",
            wf.special_rules,
        )
        self.assertIn(
            "MOV-09 is a departmental order and must never be described as "
            "the taxpayer's reply form.",
            wf.special_rules,
        )
        self.assertIn(
            "Do not treat the Section 129 seven-day statutory notice/order "
            "timeline as a universal taxpayer reply deadline.",
            wf.special_rules,
        )


if __name__ == "__main__":
    unittest.main()
