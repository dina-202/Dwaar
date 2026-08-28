"""Unit tests for the GST Notice Taxonomy v1 registry
(ARCHITECTURE_SPEC_v1_1 §3, §12, §13 Step 3).

Verifies:

  - the registry imports and contains exactly the 17 recognized
    Taxonomy-v1 forms, each mapping to its specified family;
  - every recognized form is initially TRIAGE_ONLY and no entry is
    DEEP_WORKFLOW (a recognized form alone never unlocks a deep workflow,
    guardrail §15.1);
  - lookup_notice_form() returns the correct family/support for every
    recognized form, and (UNKNOWN, UNKNOWN) for NoticeForm.UNKNOWN;
  - DRC_01 does not map to any ProceedingType or DEEP_WORKFLOW;
  - MOV_SERIES does not unlock GST_SEC129_ENFORCE;
  - there is no Section-130 NoticeForm or registry entry;
  - TAXONOMY_VERSION == "v1";
  - the registry has no LLM/Gemini/Streamlit/network dependency.

Pure deterministic tests. No classifier logic, no LLM calls, no network.

Runnable with Python's standard library unittest only:
    python -m unittest tests/test_taxonomy_registry.py -v
No pytest, no external dependencies.
"""

import pathlib
import unittest

from domain import taxonomy_registry
from domain.models import NoticeFamily, NoticeForm, SupportLevel
from domain.taxonomy_registry import (
    TAXONOMY_REGISTRY,
    TAXONOMY_VERSION,
    lookup_notice_form,
)

# Exactly the 17 recognized Taxonomy-v1 forms -> their spec family
# (ARCHITECTURE_SPEC_v1_1 §3, §12).
EXPECTED_FORM_FAMILIES = {
    NoticeForm.GSTR_3A: NoticeFamily.RETURN_COMPLIANCE,
    NoticeForm.DRC_01B: NoticeFamily.RETURN_COMPLIANCE,
    NoticeForm.DRC_01C: NoticeFamily.RETURN_COMPLIANCE,
    NoticeForm.REG_03: NoticeFamily.REGISTRATION,
    NoticeForm.REG_17: NoticeFamily.REGISTRATION,
    NoticeForm.REG_23: NoticeFamily.REGISTRATION,
    NoticeForm.CMP_05: NoticeFamily.COMPOSITION,
    NoticeForm.PCT_03: NoticeFamily.GST_PRACTITIONER,
    NoticeForm.RFD_08: NoticeFamily.REFUND,
    NoticeForm.ASMT_02: NoticeFamily.ASSESSMENT_SCRUTINY,
    NoticeForm.ASMT_10: NoticeFamily.ASSESSMENT_SCRUTINY,
    NoticeForm.ASMT_14: NoticeFamily.ASSESSMENT_SCRUTINY,
    NoticeForm.ADT_01: NoticeFamily.AUDIT,
    NoticeForm.DRC_01A: NoticeFamily.DEMAND_ADJUDICATION,
    NoticeForm.DRC_01: NoticeFamily.DEMAND_ADJUDICATION,
    NoticeForm.MOV_SERIES: NoticeFamily.ENFORCEMENT,
    NoticeForm.RVN_01: NoticeFamily.REVISION,
}


class RegistryImportTests(unittest.TestCase):
    def test_registry_imports_successfully(self):
        self.assertIsNotNone(TAXONOMY_REGISTRY)
        self.assertTrue(callable(lookup_notice_form))


class RegistryCoverageTests(unittest.TestCase):
    def test_registry_contains_exactly_the_17_recognized_forms(self):
        self.assertEqual(
            set(TAXONOMY_REGISTRY.keys()),
            set(EXPECTED_FORM_FAMILIES.keys()),
        )

    def test_unknown_is_not_a_registry_entry(self):
        self.assertNotIn(NoticeForm.UNKNOWN, TAXONOMY_REGISTRY)

    def test_every_recognized_form_maps_to_expected_family(self):
        for form, expected_family in EXPECTED_FORM_FAMILIES.items():
            actual_family, _ = TAXONOMY_REGISTRY[form]
            self.assertIs(actual_family, expected_family, form.name)

    def test_every_recognized_form_is_initial_triage_only(self):
        for form, (_, support_level) in TAXONOMY_REGISTRY.items():
            self.assertIs(support_level, SupportLevel.TRIAGE_ONLY, form.name)

    def test_no_registry_entry_has_deep_workflow(self):
        for form, (_, support_level) in TAXONOMY_REGISTRY.items():
            self.assertIsNot(support_level, SupportLevel.DEEP_WORKFLOW, form.name)

    def test_no_section_130_notice_form_or_registry_entry(self):
        # §3.9 / §5.2: Section 130 is deliberately not a NoticeForm member.
        self.assertFalse(hasattr(NoticeForm, "SECTION_130"))
        self.assertFalse(hasattr(NoticeForm, "SEC_130"))
        self.assertFalse(
            any(form.name in ("SECTION_130", "SEC_130") for form in TAXONOMY_REGISTRY)
        )

    def test_taxonomy_version_is_v1(self):
        self.assertEqual(TAXONOMY_VERSION, "v1")


class LookupTests(unittest.TestCase):
    def test_lookup_returns_expected_family_and_support_for_every_recognized_form(self):
        for form, expected_family in EXPECTED_FORM_FAMILIES.items():
            family, support_level = lookup_notice_form(form)
            self.assertIs(family, expected_family, form.name)
            self.assertIs(support_level, SupportLevel.TRIAGE_ONLY, form.name)

    def test_lookup_unknown_returns_unknown_unknown(self):
        self.assertEqual(
            lookup_notice_form(NoticeForm.UNKNOWN),
            (NoticeFamily.UNKNOWN, SupportLevel.UNKNOWN),
        )

    def test_drc_01_maps_only_to_demand_adjudication_triage_only(self):
        # DRC_01 alone must not map to any ProceedingType or DEEP_WORKFLOW;
        # the lookup API returns only (NoticeFamily, SupportLevel).
        result = lookup_notice_form(NoticeForm.DRC_01)
        self.assertEqual(result, (NoticeFamily.DEMAND_ADJUDICATION, SupportLevel.TRIAGE_ONLY))
        self.assertEqual(len(result), 2)
        self.assertIsNot(result[1], SupportLevel.DEEP_WORKFLOW)

    def test_mov_series_does_not_unlock_gst_sec129_enforce(self):
        # MOV_SERIES alone maps to ENFORCEMENT / TRIAGE_ONLY. GST_SEC129_ENFORCE
        # requires Step 4 statutory markers and is not reachable here.
        self.assertEqual(
            lookup_notice_form(NoticeForm.MOV_SERIES),
            (NoticeFamily.ENFORCEMENT, SupportLevel.TRIAGE_ONLY),
        )
        self.assertNotIn(SupportLevel.DEEP_WORKFLOW, lookup_notice_form(NoticeForm.MOV_SERIES))

    def test_drc_01b_and_drc_01c_map_to_return_compliance_triage_only(self):
        for form in (NoticeForm.DRC_01B, NoticeForm.DRC_01C):
            self.assertEqual(
                lookup_notice_form(form),
                (NoticeFamily.RETURN_COMPLIANCE, SupportLevel.TRIAGE_ONLY),
                form.name,
            )


class DependencyPurityTests(unittest.TestCase):
    def test_registry_has_no_llm_or_external_dependencies(self):
        source_path = pathlib.Path(taxonomy_registry.__file__)
        source_text = source_path.read_text(encoding="utf-8").lower()
        for forbidden_token in (
            "gemini",
            "genai",
            "google",
            "streamlit",
            "requests",
            "urllib",
            "socket",
            "modules",
        ):
            self.assertNotIn(forbidden_token, source_text, forbidden_token)


if __name__ == "__main__":
    unittest.main()
