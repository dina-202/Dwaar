"""Tests for OIDC principal and runtime master-key helpers."""

import base64
import unittest
from datetime import datetime, timedelta, timezone

from domain.auth_models import AuthenticatedPrincipal
from modules.runtime_security import (
    AuthenticationExpiredError,
    AuthenticationNotYetValidError,
    AuthenticationRequiredError,
    RuntimeSecurityConfigurationError,
    decode_document_master_key,
    oidc_principal_from_claims,
    principal_from_streamlit_user,
)


NOW = datetime(2026, 9, 22, 15, 30, tzinfo=timezone.utc)


def claims(**overrides):
    value = {
        "iss": "https://accounts.example.test",
        "sub": "provider-subject-123",
        "exp": (NOW + timedelta(hours=1)).timestamp(),
        "email": "person@example.test",
        "name": "Person Name",
    }
    value.update(overrides)
    return value


class FakeStreamlitUser:
    def __init__(self, *, logged_in=True, values=None):
        self.is_logged_in = logged_in
        self._values = values if values is not None else claims()

    def to_dict(self):
        return dict(self._values)


class OidcPrincipalTests(unittest.TestCase):
    def test_valid_claims_create_opaque_principal(self):
        principal = oidc_principal_from_claims(
            claims(),
            now=NOW,
        )
        self.assertIsInstance(principal, AuthenticatedPrincipal)
        self.assertTrue(principal.user_id.startswith("OIDC-"))
        self.assertEqual(len(principal.user_id), 69)
        self.assertNotIn("person@example.test", principal.user_id)
        self.assertNotIn("provider-subject", principal.user_id)

    def test_same_issuer_and_subject_are_stable_despite_email_change(self):
        first = oidc_principal_from_claims(
            claims(email="old@example.test"),
            now=NOW,
        )
        second = oidc_principal_from_claims(
            claims(email="new@example.test", name="New Name"),
            now=NOW,
        )
        self.assertEqual(first, second)

    def test_subject_change_changes_internal_identity(self):
        first = oidc_principal_from_claims(claims(sub="A"), now=NOW)
        second = oidc_principal_from_claims(claims(sub="B"), now=NOW)
        self.assertNotEqual(first.user_id, second.user_id)

    def test_issuer_change_changes_internal_identity(self):
        first = oidc_principal_from_claims(
            claims(iss="https://issuer-a.test"),
            now=NOW,
        )
        second = oidc_principal_from_claims(
            claims(iss="https://issuer-b.test"),
            now=NOW,
        )
        self.assertNotEqual(first.user_id, second.user_id)

    def test_expired_token_is_rejected(self):
        with self.assertRaises(AuthenticationExpiredError):
            oidc_principal_from_claims(
                claims(exp=(NOW - timedelta(seconds=1)).timestamp()),
                now=NOW,
            )

    def test_token_expiring_exactly_now_is_rejected(self):
        with self.assertRaises(AuthenticationExpiredError):
            oidc_principal_from_claims(
                claims(exp=NOW.timestamp()),
                now=NOW,
            )

    def test_future_nbf_is_rejected(self):
        with self.assertRaises(AuthenticationNotYetValidError):
            oidc_principal_from_claims(
                claims(
                    nbf=(NOW + timedelta(minutes=1)).timestamp()
                ),
                now=NOW,
            )

    def test_past_nbf_is_allowed(self):
        principal = oidc_principal_from_claims(
            claims(
                nbf=(NOW - timedelta(minutes=1)).timestamp()
            ),
            now=NOW,
        )
        self.assertIsInstance(principal, AuthenticatedPrincipal)

    def test_missing_issuer_is_rejected(self):
        value = claims()
        del value["iss"]
        with self.assertRaises(AuthenticationRequiredError):
            oidc_principal_from_claims(value, now=NOW)

    def test_missing_subject_is_rejected(self):
        value = claims()
        del value["sub"]
        with self.assertRaises(AuthenticationRequiredError):
            oidc_principal_from_claims(value, now=NOW)

    def test_missing_expiry_is_rejected(self):
        value = claims()
        del value["exp"]
        with self.assertRaises(AuthenticationRequiredError):
            oidc_principal_from_claims(value, now=NOW)

    def test_boolean_expiry_is_rejected(self):
        with self.assertRaises(AuthenticationRequiredError):
            oidc_principal_from_claims(
                claims(exp=True),
                now=NOW,
            )

    def test_naive_now_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            oidc_principal_from_claims(
                claims(),
                now=datetime(2026, 9, 22, 15, 30),
            )


class StreamlitUserAdapterTests(unittest.TestCase):
    def test_logged_in_user_adapts_claims(self):
        expected = oidc_principal_from_claims(claims(), now=NOW)
        actual = principal_from_streamlit_user(
            FakeStreamlitUser(),
            now=NOW,
        )
        self.assertEqual(actual, expected)

    def test_logged_out_user_is_rejected(self):
        with self.assertRaises(AuthenticationRequiredError):
            principal_from_streamlit_user(
                FakeStreamlitUser(logged_in=False),
                now=NOW,
            )

    def test_missing_to_dict_is_rejected(self):
        class BrokenUser:
            is_logged_in = True

        with self.assertRaises(AuthenticationRequiredError):
            principal_from_streamlit_user(
                BrokenUser(),
                now=NOW,
            )


class MasterKeyTests(unittest.TestCase):
    def test_valid_32_byte_key_decodes(self):
        raw = bytes(range(32))
        encoded = base64.b64encode(raw).decode("ascii")
        self.assertEqual(
            decode_document_master_key(encoded),
            raw,
        )

    def test_whitespace_around_secret_is_ignored(self):
        raw = b"x" * 32
        encoded = base64.b64encode(raw).decode("ascii")
        self.assertEqual(
            decode_document_master_key(f"  {encoded}\n"),
            raw,
        )

    def test_missing_secret_is_rejected(self):
        for value in ("", "   "):
            with self.subTest(value=value):
                with self.assertRaises(
                    RuntimeSecurityConfigurationError
                ):
                    decode_document_master_key(value)

    def test_invalid_base64_is_rejected(self):
        with self.assertRaisesRegex(
            RuntimeSecurityConfigurationError,
            "valid base64",
        ):
            decode_document_master_key("not@@base64")

    def test_wrong_key_length_is_rejected(self):
        for length in (16, 31, 33):
            encoded = base64.b64encode(
                b"x" * length
            ).decode("ascii")
            with self.subTest(length=length):
                with self.assertRaisesRegex(
                    RuntimeSecurityConfigurationError,
                    "32 bytes",
                ):
                    decode_document_master_key(encoded)


if __name__ == "__main__":
    unittest.main()
