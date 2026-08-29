"""Unit tests for the five authoritative workflow validation profiles and
the deterministic profile lookup (ARCHITECTURE_SPEC_v1_1 §19.16,
§19.33–§19.39, §19.46).

Fully offline and deterministic. No LLM calls, no network, no fixtures.

Verifies:

  - get_validation_profile exists, returns the authoritative profile for
    each of the five deep ProceedingTypes, and None for UNKNOWN with no
    fallback;
  - exactly five profiles exist, one per deep proceeding, none for
    UNKNOWN;
  - the exact 29 §19.16 requirement mappings: IDs, kinds, fact types,
    fact roles, calculation types, accepted_fact_statuses and
    absent_on_success values;
  - every requirement_text equals the corresponding workflow
    required_facts string verbatim at the same index;
  - the exact 24 §19.35–§19.39 special-rule index mappings (handling
    tuples and ReviewLevel review_rules), covering every special-rule
    index of every workflow with no orphans and no out-of-range keys;
  - profile proceeding types match both the registry key and the
    corresponding WorkflowDefinition;
  - the profile module is pure static data plus one deterministic lookup:
    no LLM/network technology, no semantic string matching, no validation
    engine implementation, no PotentialDefence / EvidenceGap generation.

Runnable with Python's standard library unittest only:
    python -m unittest tests/test_workflow_validation_profiles.py -v
No pytest, no external dependencies.
"""

import inspect
import pathlib
import unittest

from domain.models import (
    ArithmeticCalculationType,
    FactRole,
    FactStatus,
    FactType,
    ProceedingType,
    RequirementKind,
    RequirementStatus,
    ReviewLevel,
    SpecialRuleHandling,
    WorkflowRequirementSpec,
    WorkflowValidationProfile,
)

import workflows.gst.validation_profiles as profiles_module
from workflows.gst import GST_WORKFLOW_REGISTRY
from workflows.gst.validation_profiles import (
    VALIDATION_PROFILE_REGISTRY,
    get_validation_profile,
)

DEEP_TYPES = (
    ProceedingType.GST_SEC73_ITC,
    ProceedingType.GST_SEC73_GENERAL,
    ProceedingType.GST_SEC73_RCM,
    ProceedingType.GST_SEC74_FRAUD,
    ProceedingType.GST_SEC129_ENFORCE,
)

# Exact §19.16 requirement-mapping contracts. For each spec:
# (id, kind, fact_type, fact_role, calculation_type,
#  accepted_fact_statuses, absent_on_success). requirement_text is
# compared against the workflow required_facts strings in the tests, not
# duplicated here.
EXPECTED_SPECS = {
    ProceedingType.GST_SEC73_ITC: [
        ("sec73_itc.r1", RequirementKind.FACT, FactType.STATED_AMOUNT,
         FactRole.GSTR3B_ITC_CLAIMED_AMOUNT, None,
         (FactStatus.CONFIRMED,), RequirementStatus.MISSING),
        ("sec73_itc.r2", RequirementKind.FACT, FactType.STATED_AMOUNT,
         FactRole.GSTR2B_ITC_REFLECTED_AMOUNT, None,
         (FactStatus.CONFIRMED,), RequirementStatus.MISSING),
        ("sec73_itc.r3", RequirementKind.DERIVED, None, None,
         ArithmeticCalculationType.ITC_DIFFERENCE,
         (FactStatus.CONFIRMED,), RequirementStatus.MISSING),
        ("sec73_itc.r4", RequirementKind.FACT, FactType.TAX_PERIOD,
         FactRole.NONE, None,
         (FactStatus.CONFIRMED,), RequirementStatus.MISSING),
        ("sec73_itc.r5", RequirementKind.FACT, FactType.STATED_AMOUNT,
         FactRole.INTEREST_PROPOSED_AMOUNT, None,
         (FactStatus.CONFIRMED,), RequirementStatus.MISSING),
    ],
    ProceedingType.GST_SEC73_GENERAL: [
        ("sec73_general.r1", RequirementKind.FACT, FactType.STATED_AMOUNT,
         FactRole.GSTR1_LIABILITY_DECLARED_AMOUNT, None,
         (FactStatus.CONFIRMED,), RequirementStatus.MISSING),
        ("sec73_general.r2", RequirementKind.FACT, FactType.STATED_AMOUNT,
         FactRole.GSTR3B_LIABILITY_DISCHARGED_AMOUNT, None,
         (FactStatus.CONFIRMED,), RequirementStatus.MISSING),
        ("sec73_general.r3", RequirementKind.DERIVED, None, None,
         ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE,
         (FactStatus.CONFIRMED,), RequirementStatus.MISSING),
        ("sec73_general.r4", RequirementKind.FACT, FactType.TAX_PERIOD,
         FactRole.NONE, None,
         (FactStatus.CONFIRMED,), RequirementStatus.MISSING),
        ("sec73_general.r5", RequirementKind.FACT, FactType.STATED_AMOUNT,
         FactRole.INTEREST_PROPOSED_AMOUNT, None,
         (FactStatus.CONFIRMED,), RequirementStatus.MISSING),
    ],
    ProceedingType.GST_SEC73_RCM: [
        ("sec73_rcm.r1", RequirementKind.FACT, FactType.DEPARTMENT_ALLEGATION,
         FactRole.RCM_CATEGORY_ALLEGED, None,
         (FactStatus.ALLEGED,), RequirementStatus.MISSING),
        ("sec73_rcm.r2", RequirementKind.FACT, FactType.DEPARTMENT_ALLEGATION,
         FactRole.RCM_VALUE_ALLEGED_AMOUNT, None,
         (FactStatus.ALLEGED,), RequirementStatus.MISSING),
        ("sec73_rcm.r3", RequirementKind.FACT, FactType.DEPARTMENT_ALLEGATION,
         FactRole.RCM_TAX_ALLEGED_AMOUNT, None,
         (FactStatus.ALLEGED,), RequirementStatus.MISSING),
        ("sec73_rcm.r4", RequirementKind.FACT, FactType.TAX_PERIOD,
         FactRole.NONE, None,
         (FactStatus.CONFIRMED,), RequirementStatus.MISSING),
        ("sec73_rcm.r5", RequirementKind.FACT, FactType.STATED_AMOUNT,
         FactRole.INTEREST_PROPOSED_AMOUNT, None,
         (FactStatus.CONFIRMED,), RequirementStatus.MISSING),
    ],
    ProceedingType.GST_SEC74_FRAUD: [
        ("sec74_fraud.r1", RequirementKind.FACT,
         FactType.DEPARTMENT_ALLEGATION, FactRole.FRAUD_BASIS_ALLEGED, None,
         (FactStatus.ALLEGED,), RequirementStatus.MISSING),
        ("sec74_fraud.r2", RequirementKind.FACT,
         FactType.DEPARTMENT_ALLEGATION, FactRole.DEPARTMENT_ALLEGED_AMOUNT,
         None, (FactStatus.ALLEGED,), RequirementStatus.MISSING),
        ("sec74_fraud.r3", RequirementKind.FACT, FactType.TAX_PERIOD,
         FactRole.NONE, None,
         (FactStatus.CONFIRMED,), RequirementStatus.MISSING),
        ("sec74_fraud.r4", RequirementKind.FACT,
         FactType.DEPARTMENT_ALLEGATION,
         FactRole.FRAUD_PENALTY_PROPOSED_ALLEGED_AMOUNT, None,
         (FactStatus.ALLEGED,), RequirementStatus.MISSING),
        ("sec74_fraud.r5", RequirementKind.FACT, FactType.DOCUMENT_DETAIL,
         FactRole.LIMITATION_BASIS, None,
         (FactStatus.CONFIRMED,), RequirementStatus.MISSING),
    ],
    ProceedingType.GST_SEC129_ENFORCE: [
        ("sec129.r1", RequirementKind.FACT, FactType.DOCUMENT_DETAIL,
         FactRole.GOODS_DESCRIPTION, None,
         (FactStatus.CONFIRMED,), RequirementStatus.MISSING),
        ("sec129.r2", RequirementKind.FACT, FactType.DOCUMENT_DETAIL,
         FactRole.VEHICLE_NUMBER, None,
         (FactStatus.CONFIRMED,), RequirementStatus.MISSING),
        ("sec129.r3", RequirementKind.FACT, FactType.DOCUMENT_DETAIL,
         FactRole.DETENTION_OR_SEIZURE_DATE, None,
         (FactStatus.CONFIRMED,), RequirementStatus.MISSING),
        ("sec129.r4", RequirementKind.FACT, FactType.DOCUMENT_DETAIL,
         FactRole.SECTION129_NOTICE_OR_SERVICE_DATE, None,
         (FactStatus.CONFIRMED,), RequirementStatus.MISSING),
        ("sec129.r5", RequirementKind.FACT, FactType.STATED_AMOUNT,
         FactRole.SEC129_PENALTY_PROPOSED_AMOUNT, None,
         (FactStatus.CONFIRMED,), RequirementStatus.MISSING),
        ("sec129.r6", RequirementKind.FACT, FactType.DOCUMENT_DETAIL,
         FactRole.GOODS_VALUE_OR_TAX_PAYABLE, None,
         (FactStatus.CONFIRMED,), RequirementStatus.REQUIRES_VERIFICATION),
        ("sec129.r7", RequirementKind.FACT, FactType.DOCUMENT_DETAIL,
         FactRole.OWNER_CAME_FORWARD_STATUS, None,
         (FactStatus.CONFIRMED,), RequirementStatus.REQUIRES_VERIFICATION),
        ("sec129.r8", RequirementKind.FACT, None,
         FactRole.EXPLICIT_PROCEDURAL_DATE, None,
         (FactStatus.CONFIRMED,), RequirementStatus.MISSING),
        ("sec129.r9", RequirementKind.FACT, FactType.DOCUMENT_DETAIL,
         FactRole.ORDER_DATE_OR_ENFORCEMENT_STATUS, None,
         (FactStatus.CONFIRMED,), RequirementStatus.REQUIRES_VERIFICATION),
    ],
}

# Exact §19.35–§19.39 special-rule handling tuples and §19.35–§19.39
# ReviewLevel mappings, keyed by zero-based workflow special_rules index.
EXPECTED_HANDLING = {
    ProceedingType.GST_SEC73_ITC: {
        0: (SpecialRuleHandling.REVIEW_GATE,),
        1: (SpecialRuleHandling.DETERMINISTIC_CHECK,),
        2: (SpecialRuleHandling.REVIEW_GATE,),
        3: (SpecialRuleHandling.REVIEW_GATE,),
    },
    ProceedingType.GST_SEC73_GENERAL: {
        0: (SpecialRuleHandling.REVIEW_GATE,),
        1: (SpecialRuleHandling.DETERMINISTIC_CHECK,),
        2: (SpecialRuleHandling.REVIEW_GATE,),
        3: (SpecialRuleHandling.REVIEW_GATE,),
    },
    ProceedingType.GST_SEC73_RCM: {
        0: (SpecialRuleHandling.REVIEW_GATE,),
        1: (
            SpecialRuleHandling.FUTURE_LEGAL_RULE,
            SpecialRuleHandling.REVIEW_GATE,
        ),
        2: (SpecialRuleHandling.REVIEW_GATE,),
        3: (SpecialRuleHandling.REVIEW_GATE,),
    },
    ProceedingType.GST_SEC74_FRAUD: {
        0: (SpecialRuleHandling.DETERMINISTIC_CHECK,),
        1: (SpecialRuleHandling.REVIEW_GATE,),
        2: (SpecialRuleHandling.DETERMINISTIC_CHECK,),
        3: (SpecialRuleHandling.REVIEW_GATE,),
        4: (SpecialRuleHandling.UPSTREAM_INVARIANT,),
    },
    ProceedingType.GST_SEC129_ENFORCE: {
        0: (SpecialRuleHandling.REVIEW_GATE,),
        1: (SpecialRuleHandling.REVIEW_GATE,),
        2: (SpecialRuleHandling.UPSTREAM_INVARIANT,),
        3: (SpecialRuleHandling.UPSTREAM_INVARIANT,),
        4: (SpecialRuleHandling.REVIEW_GATE,),
        5: (SpecialRuleHandling.UPSTREAM_INVARIANT,),
        6: (
            SpecialRuleHandling.DETERMINISTIC_CHECK,
            SpecialRuleHandling.REVIEW_GATE,
        ),
    },
}

EXPECTED_REVIEW_RULES = {
    ProceedingType.GST_SEC73_ITC: {
        0: ReviewLevel.CA_REVIEW,
        2: ReviewLevel.CA_REVIEW,
        3: ReviewLevel.CA_REVIEW,
    },
    ProceedingType.GST_SEC73_GENERAL: {
        0: ReviewLevel.CA_REVIEW,
        2: ReviewLevel.CA_REVIEW,
        3: ReviewLevel.CA_REVIEW,
    },
    ProceedingType.GST_SEC73_RCM: {
        0: ReviewLevel.CA_REVIEW,
        1: ReviewLevel.CA_REVIEW,
        2: ReviewLevel.CA_REVIEW,
        3: ReviewLevel.CA_REVIEW,
    },
    ProceedingType.GST_SEC74_FRAUD: {
        1: ReviewLevel.SENIOR_CA_OR_ADVOCATE,
        3: ReviewLevel.SENIOR_CA_OR_ADVOCATE,
    },
    ProceedingType.GST_SEC129_ENFORCE: {
        0: ReviewLevel.CA_REVIEW,
        1: ReviewLevel.CA_REVIEW,
        4: ReviewLevel.CA_REVIEW,
        6: ReviewLevel.URGENT_CA_REVIEW,
    },
}


class RegistryAndApiTests(unittest.TestCase):
    """Exactly five profiles; UNKNOWN → None; no fallback."""

    def test_get_validation_profile_exists(self):
        self.assertTrue(callable(get_validation_profile))

    def test_registry_contains_exactly_five_profiles(self):
        self.assertEqual(
            set(VALIDATION_PROFILE_REGISTRY.keys()), set(DEEP_TYPES)
        )

    def test_every_profile_is_a_workflow_validation_profile(self):
        self.assertTrue(
            all(
                isinstance(profile, WorkflowValidationProfile)
                for profile in VALIDATION_PROFILE_REGISTRY.values()
            )
        )

    def test_unknown_returns_none(self):
        self.assertIsNone(get_validation_profile(ProceedingType.UNKNOWN))

    def test_no_silent_fallback(self):
        # Every supported type returns its own profile by identity; every
        # other ProceedingType member (only UNKNOWN exists) returns None.
        for ptype in ProceedingType:
            if ptype in DEEP_TYPES:
                self.assertIs(
                    get_validation_profile(ptype),
                    VALIDATION_PROFILE_REGISTRY[ptype],
                    ptype.name,
                )
            else:
                self.assertIsNone(get_validation_profile(ptype), ptype.name)


class RequirementCountTests(unittest.TestCase):
    """Counts 5/5/5/5/9, total 29, IDs globally unique and exact."""

    EXPECTED_COUNTS = {
        ProceedingType.GST_SEC73_ITC: 5,
        ProceedingType.GST_SEC73_GENERAL: 5,
        ProceedingType.GST_SEC73_RCM: 5,
        ProceedingType.GST_SEC74_FRAUD: 5,
        ProceedingType.GST_SEC129_ENFORCE: 9,
    }

    def test_requirement_counts_exact(self):
        for ptype, expected in self.EXPECTED_COUNTS.items():
            self.assertEqual(
                len(VALIDATION_PROFILE_REGISTRY[ptype].requirement_specs),
                expected,
                ptype.name,
            )

    def test_total_requirement_specs_is_29(self):
        total = sum(
            len(profile.requirement_specs)
            for profile in VALIDATION_PROFILE_REGISTRY.values()
        )
        self.assertEqual(total, 29)

    def test_all_requirement_ids_globally_unique(self):
        ids = [
            spec.requirement_id
            for profile in VALIDATION_PROFILE_REGISTRY.values()
            for spec in profile.requirement_specs
        ]
        self.assertEqual(len(ids), len(set(ids)))

    def test_requirement_ids_exact(self):
        for ptype, expected_specs in EXPECTED_SPECS.items():
            actual = [
                spec.requirement_id
                for spec in VALIDATION_PROFILE_REGISTRY[ptype].requirement_specs
            ]
            self.assertEqual(
                actual,
                [row[0] for row in expected_specs],
                ptype.name,
            )


class RequirementContentTests(unittest.TestCase):
    """Every §19.16 selector and text mapping, exact."""

    def _specs(self, ptype):
        return VALIDATION_PROFILE_REGISTRY[ptype].requirement_specs

    def test_every_spec_is_workflow_requirement_spec(self):
        for profile in VALIDATION_PROFILE_REGISTRY.values():
            self.assertTrue(
                all(
                    isinstance(spec, WorkflowRequirementSpec)
                    for spec in profile.requirement_specs
                )
            )

    def test_requirement_texts_match_workflows_verbatim_at_index(self):
        for ptype in DEEP_TYPES:
            workflow = GST_WORKFLOW_REGISTRY[ptype]
            specs = self._specs(ptype)
            self.assertEqual(
                len(specs), len(workflow.required_facts), ptype.name
            )
            for index, spec in enumerate(specs):
                self.assertEqual(
                    spec.requirement_text,
                    workflow.required_facts[index],
                    f"{ptype.name} index {index}",
                )

    def test_requirement_kinds_exact(self):
        for ptype, expected_specs in EXPECTED_SPECS.items():
            actual = [spec.kind for spec in self._specs(ptype)]
            self.assertEqual(
                actual, [row[1] for row in expected_specs], ptype.name
            )

    def test_fact_types_exact(self):
        for ptype, expected_specs in EXPECTED_SPECS.items():
            actual = [spec.fact_type for spec in self._specs(ptype)]
            expected = [row[2] for row in expected_specs]
            for index, (got, want) in enumerate(zip(actual, expected)):
                if want is None:
                    self.assertIsNone(got, f"{ptype.name} index {index}")
                else:
                    self.assertIs(got, want, f"{ptype.name} index {index}")

    def test_fact_roles_exact(self):
        for ptype, expected_specs in EXPECTED_SPECS.items():
            actual = [spec.fact_role for spec in self._specs(ptype)]
            expected = [row[3] for row in expected_specs]
            for index, (got, want) in enumerate(zip(actual, expected)):
                if want is None:
                    self.assertIsNone(got, f"{ptype.name} index {index}")
                else:
                    self.assertIs(got, want, f"{ptype.name} index {index}")

    def test_calculation_types_exact(self):
        # Exactly the two DERIVED mappings carry a calculation type; every
        # other spec's calculation_type is None.
        expected_calcs = {
            "sec73_itc.r3": ArithmeticCalculationType.ITC_DIFFERENCE,
            "sec73_general.r3": ArithmeticCalculationType.OUTPUT_TAX_DIFFERENCE,
        }
        for profile in VALIDATION_PROFILE_REGISTRY.values():
            for spec in profile.requirement_specs:
                if spec.requirement_id in expected_calcs:
                    self.assertIs(
                        spec.calculation_type,
                        expected_calcs[spec.requirement_id],
                        spec.requirement_id,
                    )
                    self.assertIs(spec.kind, RequirementKind.DERIVED)
                else:
                    self.assertIsNone(
                        spec.calculation_type, spec.requirement_id
                    )

    def test_accepted_fact_statuses_exact(self):
        for ptype, expected_specs in EXPECTED_SPECS.items():
            actual = [spec.accepted_fact_statuses for spec in self._specs(ptype)]
            self.assertEqual(
                actual, [row[5] for row in expected_specs], ptype.name
            )

    def test_absent_on_success_exact(self):
        for ptype, expected_specs in EXPECTED_SPECS.items():
            actual = [spec.absent_on_success for spec in self._specs(ptype)]
            self.assertEqual(
                actual, [row[6] for row in expected_specs], ptype.name
            )

    def test_rcm_and_fraud_allegation_specs_accept_alleged(self):
        allegation_ids = {
            "sec73_rcm.r1",
            "sec73_rcm.r2",
            "sec73_rcm.r3",
            "sec74_fraud.r1",
            "sec74_fraud.r2",
            "sec74_fraud.r4",
        }
        for profile in VALIDATION_PROFILE_REGISTRY.values():
            for spec in profile.requirement_specs:
                if spec.requirement_id in allegation_ids:
                    self.assertEqual(
                        spec.accepted_fact_statuses,
                        (FactStatus.ALLEGED,),
                        spec.requirement_id,
                    )
                    self.assertNotIn(
                        FactStatus.CONFIRMED,
                        spec.accepted_fact_statuses,
                        spec.requirement_id,
                    )

    def test_tax_period_specs_use_fact_role_none_member(self):
        # §19.16: fact_role = NONE means the FactRole.NONE member, never
        # Python None.
        tax_period_ids = {
            "sec73_itc.r4",
            "sec73_general.r4",
            "sec73_rcm.r4",
            "sec74_fraud.r3",
        }
        for profile in VALIDATION_PROFILE_REGISTRY.values():
            for spec in profile.requirement_specs:
                if spec.requirement_id in tax_period_ids:
                    self.assertIsNotNone(spec.fact_role, spec.requirement_id)
                    self.assertIs(
                        spec.fact_role, FactRole.NONE, spec.requirement_id
                    )
                    self.assertIs(
                        spec.fact_type, FactType.TAX_PERIOD, spec.requirement_id
                    )

    def test_sec129_r8_uses_none_fact_type_with_procedural_date_role(self):
        spec = next(
            s
            for s in self._specs(ProceedingType.GST_SEC129_ENFORCE)
            if s.requirement_id == "sec129.r8"
        )
        self.assertIsNone(spec.fact_type)
        self.assertIs(spec.fact_role, FactRole.EXPLICIT_PROCEDURAL_DATE)
        self.assertIsNone(spec.calculation_type)

    def test_exactly_three_sec129_specs_use_requires_verification_absence(self):
        sec129_specs = self._specs(ProceedingType.GST_SEC129_ENFORCE)
        verifies_absent = {
            spec.requirement_id
            for spec in sec129_specs
            if spec.absent_on_success is RequirementStatus.REQUIRES_VERIFICATION
        }
        self.assertEqual(
            verifies_absent, {"sec129.r6", "sec129.r7", "sec129.r9"}
        )


class SpecialRuleMappingTests(unittest.TestCase):
    """Exact §19.35–§19.39 index mappings; complete, in-range, consistent."""

    def test_every_current_special_rule_index_mapped(self):
        for ptype in DEEP_TYPES:
            workflow = GST_WORKFLOW_REGISTRY[ptype]
            profile = VALIDATION_PROFILE_REGISTRY[ptype]
            self.assertEqual(
                set(profile.special_rule_handling.keys()),
                set(range(len(workflow.special_rules))),
                ptype.name,
            )

    def test_total_mapped_indices_is_24(self):
        total = sum(
            len(profile.special_rule_handling)
            for profile in VALIDATION_PROFILE_REGISTRY.values()
        )
        self.assertEqual(total, 24)

    def test_no_out_of_range_index(self):
        for ptype in DEEP_TYPES:
            workflow = GST_WORKFLOW_REGISTRY[ptype]
            profile = VALIDATION_PROFILE_REGISTRY[ptype]
            for index in profile.special_rule_handling:
                self.assertTrue(
                    0 <= index < len(workflow.special_rules),
                    f"{ptype.name} index {index}",
                )

    def test_every_handling_tuple_non_empty(self):
        for profile in VALIDATION_PROFILE_REGISTRY.values():
            for index, handling in profile.special_rule_handling.items():
                self.assertTrue(handling, f"index {index}")
                self.assertTrue(
                    all(
                        isinstance(h, SpecialRuleHandling) for h in handling
                    ),
                    f"index {index}",
                )

    def test_handling_tuples_exact(self):
        for ptype, expected in EXPECTED_HANDLING.items():
            self.assertEqual(
                VALIDATION_PROFILE_REGISTRY[ptype].special_rule_handling,
                expected,
                ptype.name,
            )

    def test_every_review_gate_has_review_rule(self):
        for profile in VALIDATION_PROFILE_REGISTRY.values():
            for index, handling in profile.special_rule_handling.items():
                if SpecialRuleHandling.REVIEW_GATE in handling:
                    self.assertIn(
                        index, profile.review_rules, f"index {index}"
                    )

    def test_no_orphan_review_rule_keys(self):
        for profile in VALIDATION_PROFILE_REGISTRY.values():
            for index in profile.review_rules:
                self.assertIn(
                    SpecialRuleHandling.REVIEW_GATE,
                    profile.special_rule_handling[index],
                    f"index {index}",
                )

    def test_review_level_mappings_exact(self):
        for ptype, expected in EXPECTED_REVIEW_RULES.items():
            self.assertEqual(
                VALIDATION_PROFILE_REGISTRY[ptype].review_rules,
                expected,
                ptype.name,
            )

    def test_fraud_rules_1_and_3_use_senior_review(self):
        fraud = VALIDATION_PROFILE_REGISTRY[ProceedingType.GST_SEC74_FRAUD]
        self.assertIs(
            fraud.review_rules[1], ReviewLevel.SENIOR_CA_OR_ADVOCATE
        )
        self.assertIs(
            fraud.review_rules[3], ReviewLevel.SENIOR_CA_OR_ADVOCATE
        )
        self.assertNotIn(4, fraud.review_rules)

    def test_sec129_rule_6_uses_urgent_review(self):
        sec129 = VALIDATION_PROFILE_REGISTRY[ProceedingType.GST_SEC129_ENFORCE]
        self.assertIs(sec129.review_rules[6], ReviewLevel.URGENT_CA_REVIEW)

    def test_rcm_rule_1_maps_future_legal_rule_then_review_gate(self):
        rcm = VALIDATION_PROFILE_REGISTRY[ProceedingType.GST_SEC73_RCM]
        self.assertEqual(
            rcm.special_rule_handling[1],
            (
                SpecialRuleHandling.FUTURE_LEGAL_RULE,
                SpecialRuleHandling.REVIEW_GATE,
            ),
        )


class CrossContractTests(unittest.TestCase):
    """Profiles agree with the registry keys and the workflow definitions."""

    def test_profile_proceeding_type_equals_registry_key(self):
        for ptype, profile in VALIDATION_PROFILE_REGISTRY.items():
            self.assertIs(profile.proceeding_type, ptype, ptype.name)

    def test_profile_proceeding_type_equals_workflow_proceeding_type(self):
        for ptype, profile in VALIDATION_PROFILE_REGISTRY.items():
            workflow = GST_WORKFLOW_REGISTRY[ptype]
            self.assertIs(
                profile.proceeding_type, workflow.proceeding_type, ptype.name
            )

    def test_no_validation_profile_for_unknown(self):
        self.assertNotIn(ProceedingType.UNKNOWN, VALIDATION_PROFILE_REGISTRY)
        for profile in VALIDATION_PROFILE_REGISTRY.values():
            self.assertIsNot(profile.proceeding_type, ProceedingType.UNKNOWN)

    def test_profile_registry_has_no_fallback(self):
        # The lookup is a closed registry read: identity for the five deep
        # types, None for UNKNOWN — never a substitute profile.
        self.assertIsNone(get_validation_profile(ProceedingType.UNKNOWN))
        for ptype in DEEP_TYPES:
            self.assertIs(
                get_validation_profile(ptype),
                VALIDATION_PROFILE_REGISTRY[ptype],
                ptype.name,
            )


class ModulePurityTests(unittest.TestCase):
    """The profile module is static data + one deterministic lookup."""

    ALLOWED_IMPORT_ROOTS = ("typing", "domain")
    FORBIDDEN_TOKENS = (
        "gemini",
        "genai",
        "google",
        "streamlit",
        "requests",
        "urllib",
        "socket",
        "http",
        "sqlite",
        "llm_client",
        "modules",
        "potentialdefence",
        "evidencegap",
        "run_validation",
    )

    SOURCE = pathlib.Path(profiles_module.__file__).read_text(encoding="utf-8")

    def test_module_imports_only_typing_and_domain(self):
        roots = set()
        for line in self.SOURCE.splitlines():
            stripped = line.strip()
            if stripped.startswith("from "):
                module_name = stripped.split()[1]
                if module_name.startswith("."):
                    continue
                roots.add(module_name.split(".")[0])
            elif stripped.startswith("import "):
                roots.add(stripped.split()[1].split(".")[0])
        self.assertTrue(
            roots <= set(self.ALLOWED_IMPORT_ROOTS),
            f"unexpected import roots {sorted(roots)}",
        )

    def test_no_forbidden_technology_or_behavior_in_source(self):
        lowered = self.SOURCE.lower()
        for token in self.FORBIDDEN_TOKENS:
            self.assertNotIn(token, lowered, token)

    def test_only_public_callable_is_get_validation_profile(self):
        # No semantic-matching helpers, no engine entry points — the sole
        # module-defined callable is the deterministic lookup.
        public_callables = [
            name
            for name, obj in vars(profiles_module).items()
            if not name.startswith("_")
            and callable(obj)
            and getattr(obj, "__module__", None) == profiles_module.__name__
        ]
        self.assertEqual(public_callables, ["get_validation_profile"])

    def test_no_validation_engine_implementation_in_module(self):
        self.assertFalse(hasattr(profiles_module, "run_validation"))
        self.assertEqual(
            inspect.getsource(get_validation_profile).count("return"), 1
        )

    def test_no_defence_or_evidence_gap_generation(self):
        self.assertNotIn("PotentialDefence", self.SOURCE)
        self.assertNotIn("EvidenceGap", self.SOURCE)


if __name__ == "__main__":
    unittest.main()
