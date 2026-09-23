"""Unit tests for the five authoritative workflow drafting profiles and
the deterministic profile lookup (ARCHITECTURE_SPEC_v1_1 §20.19,
§20.21–§20.22).

Fully offline and deterministic. No LLM calls, no network, no fixtures.

Verifies:

  - get_drafting_profile exists, returns the authoritative profile for
    each of the six deep ProceedingTypes, and None for UNKNOWN with no
    fallback;
  - exactly six profiles exist, one per deep proceeding, none for
    UNKNOWN and no triage / Section-74A / Section-130 profile;
  - the exact closed §20.22 prompt keys, all unique, with no filenames or
    paths stored in the profile;
  - every profile's section count equals the current authoritative
    WorkflowDefinition.output_structure length, and every section title
    equals the output_structure string verbatim at the same index — no
    paraphrased titles and no invented requirement/evidence/review
    sections (§20.19, §20.21);
  - one-based section IDs with the exact §20.21 machine prefixes, unique
    within and across profiles, with no zero-based IDs;
  - sections is an immutable tuple of DraftSectionSpec objects in
    deterministic order;
  - the profile module is pure static data plus one deterministic lookup:
    no LLM/network technology, no file/prompt reading, no raw-notice
    concept, no engine imports and no import-time workflow mutation.

Section counts are always verified against the actual workflow objects
(GST_WORKFLOW_REGISTRY), never guessed in the test.

Runnable with Python's standard library unittest only:
    python -m unittest tests/test_drafting_profiles.py -v
No pytest, no external dependencies.
"""

import inspect
import pathlib
import unittest

from domain.models import (
    DraftSectionSpec,
    ProceedingType,
    WorkflowDraftingProfile,
)

import workflows.gst.drafting_profiles as profiles_module
from workflows.gst import GST_WORKFLOW_REGISTRY
from workflows.gst.drafting_profiles import (
    DRAFTING_PROFILE_REGISTRY,
    get_drafting_profile,
)

DEEP_TYPES = (
    ProceedingType.GST_SEC61_SCRUTINY,
    ProceedingType.GST_SEC73_ITC,
    ProceedingType.GST_SEC73_GENERAL,
    ProceedingType.GST_SEC73_RCM,
    ProceedingType.GST_SEC74_FRAUD,
    ProceedingType.GST_SEC129_ENFORCE,
)

# Exact closed §20.22 prompt keys.
EXPECTED_PROMPT_KEYS = {
    ProceedingType.GST_SEC61_SCRUTINY: "sec61_scrutiny",
    ProceedingType.GST_SEC73_ITC: "sec73_itc",
    ProceedingType.GST_SEC73_GENERAL: "sec73_general",
    ProceedingType.GST_SEC73_RCM: "sec73_rcm",
    ProceedingType.GST_SEC74_FRAUD: "sec74_fraud",
    ProceedingType.GST_SEC129_ENFORCE: "sec129",
}

# Exact §20.21 section-ID machine prefixes.
EXPECTED_ID_PREFIXES = {
    ProceedingType.GST_SEC61_SCRUTINY: "sec61_scrutiny",
    ProceedingType.GST_SEC73_ITC: "sec73_itc",
    ProceedingType.GST_SEC73_GENERAL: "sec73_general",
    ProceedingType.GST_SEC73_RCM: "sec73_rcm",
    ProceedingType.GST_SEC74_FRAUD: "sec74_fraud",
    ProceedingType.GST_SEC129_ENFORCE: "sec129",
}


class RegistryAndApiTests(unittest.TestCase):
    """Exactly six profiles; UNKNOWN → None; no fallback."""

    def test_get_drafting_profile_exists(self):
        self.assertTrue(callable(get_drafting_profile))

    def test_registry_contains_exactly_six_profiles(self):
        self.assertEqual(len(DRAFTING_PROFILE_REGISTRY), 6)
        self.assertEqual(
            set(DRAFTING_PROFILE_REGISTRY.keys()), set(DEEP_TYPES)
        )

    def test_registry_keys_exact(self):
        self.assertEqual(list(DRAFTING_PROFILE_REGISTRY), list(DEEP_TYPES))

    def test_no_extra_proceeding(self):
        self.assertTrue(
            set(DRAFTING_PROFILE_REGISTRY) <= set(DEEP_TYPES)
        )

    def test_every_profile_is_a_workflow_drafting_profile(self):
        self.assertTrue(
            all(
                isinstance(profile, WorkflowDraftingProfile)
                for profile in DRAFTING_PROFILE_REGISTRY.values()
            )
        )

    def test_unknown_absent(self):
        self.assertNotIn(ProceedingType.UNKNOWN, DRAFTING_PROFILE_REGISTRY)

    def test_unsupported_returns_none(self):
        for ptype in ProceedingType:
            if ptype not in DEEP_TYPES:
                self.assertIsNone(get_drafting_profile(ptype), ptype.name)

    def test_valid_lookup_returns_registry_identity(self):
        for ptype in DEEP_TYPES:
            self.assertIs(
                get_drafting_profile(ptype),
                DRAFTING_PROFILE_REGISTRY[ptype],
                ptype.name,
            )

    def test_profile_registry_has_no_fallback(self):
        # The lookup is a closed registry read: identity for the six deep
        # types, None for UNKNOWN — never a substitute profile.
        self.assertIsNone(get_drafting_profile(ProceedingType.UNKNOWN))
        for ptype in DEEP_TYPES:
            self.assertIs(
                get_drafting_profile(ptype),
                DRAFTING_PROFILE_REGISTRY[ptype],
                ptype.name,
            )


class ProfileKeyTests(unittest.TestCase):
    """Every profile.proceeding_type matches its registry key and the
    authoritative workflow."""

    def test_profile_proceeding_type_equals_registry_key(self):
        for ptype, profile in DRAFTING_PROFILE_REGISTRY.items():
            self.assertIs(profile.proceeding_type, ptype, ptype.name)

    def test_profile_proceeding_type_equals_workflow_proceeding_type(self):
        for ptype, profile in DRAFTING_PROFILE_REGISTRY.items():
            workflow = GST_WORKFLOW_REGISTRY[ptype]
            self.assertIs(
                profile.proceeding_type, workflow.proceeding_type, ptype.name
            )

    def test_no_profile_for_unknown(self):
        for profile in DRAFTING_PROFILE_REGISTRY.values():
            self.assertIsNot(profile.proceeding_type, ProceedingType.UNKNOWN)


class PromptKeyTests(unittest.TestCase):
    """Exact closed §20.22 prompt keys; no filenames or paths."""

    def test_prompt_key_sec61_scrutiny_exact(self):
        self.assertEqual(
            DRAFTING_PROFILE_REGISTRY[
                ProceedingType.GST_SEC61_SCRUTINY
            ].prompt_key,
            "sec61_scrutiny",
        )

    def test_prompt_key_itc_exact(self):
        self.assertEqual(
            DRAFTING_PROFILE_REGISTRY[ProceedingType.GST_SEC73_ITC].prompt_key,
            "sec73_itc",
        )

    def test_prompt_key_general_exact(self):
        self.assertEqual(
            DRAFTING_PROFILE_REGISTRY[
                ProceedingType.GST_SEC73_GENERAL
            ].prompt_key,
            "sec73_general",
        )

    def test_prompt_key_rcm_exact(self):
        self.assertEqual(
            DRAFTING_PROFILE_REGISTRY[ProceedingType.GST_SEC73_RCM].prompt_key,
            "sec73_rcm",
        )

    def test_prompt_key_fraud_exact(self):
        self.assertEqual(
            DRAFTING_PROFILE_REGISTRY[
                ProceedingType.GST_SEC74_FRAUD
            ].prompt_key,
            "sec74_fraud",
        )

    def test_prompt_key_sec129_exact(self):
        self.assertEqual(
            DRAFTING_PROFILE_REGISTRY[
                ProceedingType.GST_SEC129_ENFORCE
            ].prompt_key,
            "sec129",
        )

    def test_prompt_keys_match_exact_mapping(self):
        for ptype, key in EXPECTED_PROMPT_KEYS.items():
            self.assertEqual(
                DRAFTING_PROFILE_REGISTRY[ptype].prompt_key, key, ptype.name
            )

    def test_prompt_keys_unique(self):
        keys = [p.prompt_key for p in DRAFTING_PROFILE_REGISTRY.values()]
        self.assertEqual(len(keys), len(set(keys)))

    def test_prompt_keys_contain_no_filenames_or_paths(self):
        for profile in DRAFTING_PROFILE_REGISTRY.values():
            key = profile.prompt_key
            self.assertNotIn("/", key, key)
            self.assertNotIn("\\", key, key)
            self.assertNotIn(".", key, key)
            self.assertFalse(key.startswith("prompts"), key)

    def test_profile_attributes_are_exactly_the_three_field_contract(self):
        # §20.22: no prompt text and no filenames stored on the profile.
        for profile in DRAFTING_PROFILE_REGISTRY.values():
            self.assertEqual(
                set(vars(profile)),
                {"proceeding_type", "sections", "prompt_key"},
            )


class SectionContractTests(unittest.TestCase):
    """§20.19: sections correspond one-for-one and in order with the
    current authoritative output_structure."""

    def test_section_count_matches_workflow_output_structure(self):
        for ptype in DEEP_TYPES:
            workflow = GST_WORKFLOW_REGISTRY[ptype]
            profile = DRAFTING_PROFILE_REGISTRY[ptype]
            self.assertEqual(
                len(profile.sections),
                len(workflow.output_structure),
                ptype.name,
            )

    def test_every_section_title_exact_at_index(self):
        for ptype in DEEP_TYPES:
            workflow = GST_WORKFLOW_REGISTRY[ptype]
            profile = DRAFTING_PROFILE_REGISTRY[ptype]
            for index, spec in enumerate(profile.sections):
                self.assertEqual(
                    spec.title,
                    workflow.output_structure[index],
                    f"{ptype.name} index {index}",
                )

    def test_no_missing_workflow_output_section(self):
        for ptype in DEEP_TYPES:
            workflow = GST_WORKFLOW_REGISTRY[ptype]
            titles = [
                s.title for s in DRAFTING_PROFILE_REGISTRY[ptype].sections
            ]
            self.assertTrue(
                set(workflow.output_structure) <= set(titles), ptype.name
            )

    def test_no_extra_drafting_section(self):
        for ptype in DEEP_TYPES:
            workflow = GST_WORKFLOW_REGISTRY[ptype]
            profile = DRAFTING_PROFILE_REGISTRY[ptype]
            self.assertEqual(
                len(profile.sections),
                len(workflow.output_structure),
                ptype.name,
            )

    def test_no_paraphrased_title(self):
        for ptype in DEEP_TYPES:
            workflow = GST_WORKFLOW_REGISTRY[ptype]
            titles = [
                s.title for s in DRAFTING_PROFILE_REGISTRY[ptype].sections
            ]
            self.assertEqual(
                titles, list(workflow.output_structure), ptype.name
            )

    def test_no_invented_requirement_evidence_review_section(self):
        # §20.21: a requirement/evidence/review section may exist only if
        # it already exists in output_structure — enforced by exact
        # title-set equality with the authoritative workflow.
        for ptype in DEEP_TYPES:
            workflow = GST_WORKFLOW_REGISTRY[ptype]
            titles = [
                s.title for s in DRAFTING_PROFILE_REGISTRY[ptype].sections
            ]
            self.assertEqual(
                set(titles), set(workflow.output_structure), ptype.name
            )

    def test_total_sections_derived_from_workflows(self):
        # Verified against the actual workflow objects, never guessed.
        total = sum(
            len(GST_WORKFLOW_REGISTRY[ptype].output_structure)
            for ptype in DEEP_TYPES
        )
        profile_total = sum(
            len(profile.sections)
            for profile in DRAFTING_PROFILE_REGISTRY.values()
        )
        self.assertEqual(profile_total, total)


class SectionIdTests(unittest.TestCase):
    """§20.21: one-based machine IDs with exact prefixes, globally unique."""

    def test_section_ids_exact_one_based(self):
        # ID counts are derived from the authoritative workflow, never
        # hardcoded to a guessed count.
        for ptype in DEEP_TYPES:
            workflow = GST_WORKFLOW_REGISTRY[ptype]
            prefix = EXPECTED_ID_PREFIXES[ptype]
            profile = DRAFTING_PROFILE_REGISTRY[ptype]
            expected = [
                f"{prefix}.s{index + 1}"
                for index in range(len(workflow.output_structure))
            ]
            self.assertEqual(
                [spec.section_id for spec in profile.sections],
                expected,
                ptype.name,
            )

    def test_section_id_prefixes_exact(self):
        for ptype in DEEP_TYPES:
            prefix = EXPECTED_ID_PREFIXES[ptype]
            for spec in DRAFTING_PROFILE_REGISTRY[ptype].sections:
                self.assertTrue(
                    spec.section_id.startswith(f"{prefix}.s"),
                    spec.section_id,
                )

    def test_no_zero_based_ids(self):
        for profile in DRAFTING_PROFILE_REGISTRY.values():
            for spec in profile.sections:
                self.assertNotIn(".s0", spec.section_id, spec.section_id)

    def test_section_ids_unique_within_each_profile(self):
        for ptype in DEEP_TYPES:
            ids = [
                s.section_id
                for s in DRAFTING_PROFILE_REGISTRY[ptype].sections
            ]
            self.assertEqual(len(ids), len(set(ids)), ptype.name)

    def test_section_ids_unique_across_all_profiles(self):
        ids = [
            spec.section_id
            for profile in DRAFTING_PROFILE_REGISTRY.values()
            for spec in profile.sections
        ]
        self.assertEqual(len(ids), len(set(ids)))


class TupleAndOrderTests(unittest.TestCase):
    """Sections is an immutable tuple in deterministic order."""

    def test_sections_is_tuple_not_mutable_list(self):
        for profile in DRAFTING_PROFILE_REGISTRY.values():
            self.assertIsInstance(profile.sections, tuple)
            self.assertNotIsInstance(profile.sections, list)

    def test_every_section_spec_is_draft_section_spec(self):
        for profile in DRAFTING_PROFILE_REGISTRY.values():
            self.assertTrue(
                all(
                    isinstance(spec, DraftSectionSpec)
                    for spec in profile.sections
                )
            )

    def test_registry_order_is_deterministic(self):
        self.assertEqual(list(DRAFTING_PROFILE_REGISTRY), list(DEEP_TYPES))

    def test_sections_tuple_order_is_deterministic(self):
        for ptype in DEEP_TYPES:
            workflow = GST_WORKFLOW_REGISTRY[ptype]
            profile = DRAFTING_PROFILE_REGISTRY[ptype]
            self.assertEqual(
                [s.title for s in profile.sections],
                list(workflow.output_structure),
                ptype.name,
            )


class CoverageTests(unittest.TestCase):
    """All six deep workflows covered exactly once."""

    def test_all_five_deep_workflows_covered_exactly_once(self):
        self.assertEqual(len(DRAFTING_PROFILE_REGISTRY), len(DEEP_TYPES))
        self.assertEqual(
            {
                profile.proceeding_type
                for profile in DRAFTING_PROFILE_REGISTRY.values()
            },
            set(DEEP_TYPES),
        )


class ModulePurityTests(unittest.TestCase):
    """The profile module is static data + one deterministic lookup."""

    ALLOWED_IMPORT_ROOTS = ("typing", "domain")
    FORBIDDEN_TOKENS = (
        "llm_client",
        "gemini",
        "genai",
        "google",
        "streamlit",
        "requests",
        "urllib",
        "socket",
        "http",
        "sqlite",
        "modules",
        "validation_engine",
        "drafting_engine",
        "fact_engine",
        "preflight_engine",
        "deadline_engine",
        "arithmetic_engine",
        "open(",
        "read_text",
        "readlines",
        "pathlib",
        "raw_text",
        "import workflows",
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

    def test_only_public_callable_is_get_drafting_profile(self):
        # No engine entry points — the sole module-defined callable is
        # the deterministic lookup.
        public_callables = [
            name
            for name, obj in vars(profiles_module).items()
            if not name.startswith("_")
            and callable(obj)
            and getattr(obj, "__module__", None) == profiles_module.__name__
        ]
        self.assertEqual(public_callables, ["get_drafting_profile"])

    def test_lookup_is_a_single_registry_read(self):
        self.assertEqual(
            inspect.getsource(get_drafting_profile).count("return"), 1
        )

    def test_no_engine_or_workflow_mutation_at_import_time(self):
        # The module cannot mutate workflow content at import time: it
        # imports nothing from workflows (import-roots test) and defines
        # only static data plus the lookup.
        self.assertFalse(hasattr(profiles_module, "GST_WORKFLOW_REGISTRY"))
        self.assertFalse(hasattr(profiles_module, "run_drafting"))
        self.assertFalse(hasattr(profiles_module, "generate_specialist_draft"))

    def test_no_import_time_assertions_on_workflows(self):
        # §20.19 note: production code must not crash at import time on
        # profile drift; no assert statements at module level.
        self.assertNotIn("\nassert ", self.SOURCE)


if __name__ == "__main__":
    unittest.main()
