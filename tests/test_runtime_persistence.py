"""Tests for runtime pilot persistence construction."""

import base64
import tempfile
import unittest
from pathlib import Path

from modules.authorized_analysis_snapshot_service import (
    AuthorizedAnalysisSnapshotService,
)
from modules.authorized_case_service import AuthorizedCaseService
from modules.authorized_evidence_workspace_service import (
    AuthorizedEvidenceWorkspaceService,
)
from modules.runtime_persistence import (
    RuntimePersistenceConfigurationError,
    build_authorized_analysis_snapshot_service,
    build_authorized_case_service,
    build_authorized_evidence_workspace_service,
    document_key_from_environment,
    object_root_from_environment,
)


class RuntimePersistenceConfigTests(unittest.TestCase):
    def test_object_root_is_normalized(self):
        self.assertEqual(
            object_root_from_environment(
                {"DWAAR_OBJECT_ROOT": "  ./objects  "}
            ),
            "objects",
        )

    def test_missing_object_root_fails_closed(self):
        with self.assertRaises(RuntimePersistenceConfigurationError):
            object_root_from_environment({})

    def test_document_key_decodes_from_environment(self):
        raw = b"k" * 32
        encoded = base64.b64encode(raw).decode("ascii")
        self.assertEqual(
            document_key_from_environment(
                {"DWAAR_DOCUMENT_KEY_B64": encoded}
            ),
            raw,
        )

    def test_invalid_document_key_is_wrapped_as_runtime_config_error(self):
        with self.assertRaises(RuntimePersistenceConfigurationError):
            document_key_from_environment(
                {"DWAAR_DOCUMENT_KEY_B64": "bad-key"}
            )

    def test_missing_database_path_fails_closed(self):
        raw = base64.b64encode(b"k" * 32).decode("ascii")
        with self.assertRaises(RuntimePersistenceConfigurationError):
            build_authorized_case_service(
                {
                    "DWAAR_OBJECT_ROOT": "./objects",
                    "DWAAR_DOCUMENT_KEY_B64": raw,
                }
            )


class RuntimeAnalysisSnapshotFactoryTests(unittest.TestCase):
    def test_factory_builds_authorized_snapshot_service(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = base64.b64encode(b"k" * 32).decode("ascii")
            service = build_authorized_analysis_snapshot_service(
                {
                    "DWAAR_DB_PATH": str(root / "dwaar.db"),
                    "DWAAR_OBJECT_ROOT": str(root / "documents"),
                    "DWAAR_DOCUMENT_KEY_B64": raw,
                }
            )
            self.assertIsInstance(
                service,
                AuthorizedAnalysisSnapshotService,
            )
            self.assertTrue((root / "dwaar.db").exists())
            self.assertTrue((root / "documents").is_dir())


class RuntimeEvidenceWorkspaceFactoryTests(unittest.TestCase):
    def test_factory_builds_authorized_evidence_workspace_service(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = base64.b64encode(b"k" * 32).decode("ascii")
            service = build_authorized_evidence_workspace_service(
                {
                    "DWAAR_DB_PATH": str(root / "dwaar.db"),
                    "DWAAR_OBJECT_ROOT": str(root / "documents"),
                    "DWAAR_DOCUMENT_KEY_B64": raw,
                }
            )
            self.assertIsInstance(
                service,
                AuthorizedEvidenceWorkspaceService,
            )
            self.assertTrue((root / "dwaar.db").exists())
            self.assertTrue((root / "documents").is_dir())


class RuntimePersistenceFactoryTests(unittest.TestCase):
    def test_factory_builds_real_authorized_service_and_storage(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = base64.b64encode(b"k" * 32).decode("ascii")
            service = build_authorized_case_service(
                {
                    "DWAAR_DB_PATH": str(root / "dwaar.db"),
                    "DWAAR_OBJECT_ROOT": str(root / "documents"),
                    "DWAAR_DOCUMENT_KEY_B64": raw,
                }
            )
            self.assertIsInstance(service, AuthorizedCaseService)
            self.assertTrue((root / "dwaar.db").exists())
            self.assertTrue((root / "documents").is_dir())


if __name__ == "__main__":
    unittest.main()
