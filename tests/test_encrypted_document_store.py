"""Tests for authenticated encrypted local document storage."""

import os
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from modules.encrypted_document_store import (
    DocumentAlreadyExistsError,
    DocumentIntegrityError,
    DocumentNotFoundError,
    EncryptedLocalDocumentStore,
    generate_storage_key,
)


class EncryptedDocumentStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = str(Path(self.temp_dir.name) / "documents")
        self.key = AESGCM.generate_key(bit_length=256)
        self.store = EncryptedLocalDocumentStore(
            self.root,
            self.key,
            max_bytes=1024,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_round_trip(self):
        storage_key = generate_storage_key()
        payload = b"%PDF sensitive tax notice bytes"
        self.store.put(storage_key, payload)
        self.assertTrue(self.store.exists(storage_key))
        self.assertEqual(self.store.get(storage_key), payload)

    def test_ciphertext_does_not_contain_plaintext(self):
        storage_key = generate_storage_key()
        payload = b"GSTIN 06ABCDE1234F1Z5 and sensitive amount 999999"
        self.store.put(storage_key, payload)
        object_id = storage_key.split("/", 1)[1]
        encoded = (Path(self.root) / f"{object_id}.dwaar").read_bytes()
        self.assertNotIn(payload, encoded)
        self.assertNotIn(b"06ABCDE1234F1Z5", encoded)

    def test_fresh_objects_use_different_envelopes_for_same_plaintext(self):
        payload = b"same plaintext"
        key_one = generate_storage_key()
        key_two = generate_storage_key()
        self.store.put(key_one, payload)
        self.store.put(key_two, payload)
        path_one = Path(self.root) / (
            key_one.split("/", 1)[1] + ".dwaar"
        )
        path_two = Path(self.root) / (
            key_two.split("/", 1)[1] + ".dwaar"
        )
        self.assertNotEqual(path_one.read_bytes(), path_two.read_bytes())

    def test_ciphertext_tamper_fails_authentication(self):
        storage_key = generate_storage_key()
        self.store.put(storage_key, b"sensitive")
        object_id = storage_key.split("/", 1)[1]
        path = Path(self.root) / f"{object_id}.dwaar"
        encoded = bytearray(path.read_bytes())
        encoded[-1] ^= 0x01
        path.write_bytes(bytes(encoded))
        with self.assertRaises(DocumentIntegrityError):
            self.store.get(storage_key)

    def test_header_tamper_fails_before_decryption(self):
        storage_key = generate_storage_key()
        self.store.put(storage_key, b"sensitive")
        object_id = storage_key.split("/", 1)[1]
        path = Path(self.root) / f"{object_id}.dwaar"
        encoded = bytearray(path.read_bytes())
        encoded[0] ^= 0x01
        path.write_bytes(bytes(encoded))
        with self.assertRaisesRegex(
            DocumentIntegrityError, "envelope is invalid"
        ):
            self.store.get(storage_key)

    def test_wrong_master_key_cannot_decrypt(self):
        storage_key = generate_storage_key()
        self.store.put(storage_key, b"sensitive")
        other = EncryptedLocalDocumentStore(
            self.root,
            AESGCM.generate_key(bit_length=256),
            max_bytes=1024,
        )
        with self.assertRaises(DocumentIntegrityError):
            other.get(storage_key)

    def test_storage_key_is_authenticated_associated_data(self):
        first = generate_storage_key()
        second = generate_storage_key()
        self.store.put(first, b"sensitive")
        first_path = Path(self.root) / (
            first.split("/", 1)[1] + ".dwaar"
        )
        second_path = Path(self.root) / (
            second.split("/", 1)[1] + ".dwaar"
        )
        second_path.write_bytes(first_path.read_bytes())
        with self.assertRaises(DocumentIntegrityError):
            self.store.get(second)

    def test_existing_key_cannot_be_overwritten(self):
        storage_key = generate_storage_key()
        self.store.put(storage_key, b"first")
        with self.assertRaises(DocumentAlreadyExistsError):
            self.store.put(storage_key, b"second")
        self.assertEqual(self.store.get(storage_key), b"first")

    def test_delete_removes_ciphertext(self):
        storage_key = generate_storage_key()
        self.store.put(storage_key, b"secret")
        self.store.delete(storage_key)
        self.assertFalse(self.store.exists(storage_key))
        with self.assertRaises(DocumentNotFoundError):
            self.store.get(storage_key)

    def test_delete_missing_raises_controlled_error(self):
        with self.assertRaises(DocumentNotFoundError):
            self.store.delete(generate_storage_key())

    def test_get_missing_raises_controlled_error(self):
        with self.assertRaises(DocumentNotFoundError):
            self.store.get(generate_storage_key())

    def test_size_limit_is_enforced_before_write(self):
        storage_key = generate_storage_key()
        with self.assertRaisesRegex(ValueError, "size limit"):
            self.store.put(storage_key, b"x" * 1025)
        self.assertFalse(self.store.exists(storage_key))

    def test_empty_payload_is_rejected(self):
        storage_key = generate_storage_key()
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            self.store.put(storage_key, b"")
        self.assertFalse(self.store.exists(storage_key))

    def test_non_bytes_payload_is_rejected(self):
        with self.assertRaises(TypeError):
            self.store.put(generate_storage_key(), "not bytes")

    def test_invalid_storage_keys_are_rejected(self):
        invalid = [
            "",
            "../secret",
            "objects/../secret",
            "objects/not-hex",
            "uploads/" + "a" * 32,
            "objects/" + "A" * 32,
            "objects/" + "a" * 31,
            "objects/" + "a" * 33,
            "/absolute",
        ]
        for storage_key in invalid:
            with self.subTest(storage_key=storage_key):
                with self.assertRaises(ValueError):
                    self.store.exists(storage_key)

    def test_generated_storage_key_matches_closed_format(self):
        storage_key = generate_storage_key()
        prefix, object_id = storage_key.split("/", 1)
        self.assertEqual(prefix, "objects")
        self.assertEqual(len(object_id), 32)
        self.assertEqual(object_id, object_id.lower())
        int(object_id, 16)

    def test_key_must_be_exactly_32_bytes(self):
        for invalid in (b"", b"x" * 16, b"x" * 31, b"x" * 33):
            with self.subTest(length=len(invalid)):
                with self.assertRaisesRegex(ValueError, "32 bytes"):
                    EncryptedLocalDocumentStore(
                        self.root,
                        invalid,
                    )

    def test_root_directory_is_created(self):
        self.assertTrue(Path(self.root).is_dir())

    @unittest.skipIf(os.name == "nt", "POSIX mode assertion")
    def test_root_and_ciphertext_are_not_world_readable_on_posix(self):
        storage_key = generate_storage_key()
        self.store.put(storage_key, b"secret")
        root_mode = Path(self.root).stat().st_mode & 0o777
        object_id = storage_key.split("/", 1)[1]
        file_mode = (
            Path(self.root) / f"{object_id}.dwaar"
        ).stat().st_mode & 0o777
        self.assertEqual(root_mode & 0o077, 0)
        self.assertEqual(file_mode & 0o077, 0)


if __name__ == "__main__":
    unittest.main()
