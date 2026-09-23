"""Runtime authentication/key-loading helpers for Dwaar Phase 3E.3."""

from __future__ import annotations

import base64
import hashlib
import re
from datetime import datetime, timezone
from typing import Mapping, Optional

from domain.auth_models import AuthenticatedPrincipal


class AuthenticationRequiredError(PermissionError):
    """No authenticated Streamlit/OIDC user is available."""


class AuthenticationExpiredError(PermissionError):
    """The OIDC identity token is expired."""


class AuthenticationNotYetValidError(PermissionError):
    """The OIDC identity token is not valid yet."""


class RuntimeSecurityConfigurationError(RuntimeError):
    """Required runtime security configuration is missing or malformed."""


_DOCUMENT_KEY_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
)


def _timestamp_claim(
    claims: Mapping[str, object],
    name: str,
    *,
    required: bool,
) -> Optional[float]:
    value = claims.get(name)
    if value is None:
        if required:
            raise AuthenticationRequiredError(
                f"OIDC claim '{name}' is required"
            )
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AuthenticationRequiredError(
            f"OIDC claim '{name}' must be numeric"
        )
    return float(value)


def oidc_principal_from_claims(
    claims: Mapping[str, object],
    *,
    now: Optional[datetime] = None,
) -> AuthenticatedPrincipal:
    """Build an opaque Dwaar principal from validated OIDC identity claims.

    The internal user ID is derived from issuer+subject, not email/name.
    """
    if not isinstance(claims, Mapping):
        raise TypeError("claims must be a mapping")

    issuer = claims.get("iss")
    subject = claims.get("sub")
    if not isinstance(issuer, str) or not issuer.strip():
        raise AuthenticationRequiredError(
            "OIDC issuer claim is required"
        )
    if not isinstance(subject, str) or not subject.strip():
        raise AuthenticationRequiredError(
            "OIDC subject claim is required"
        )

    current = now or datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise ValueError("now must be a timezone-aware datetime")

    now_ts = current.timestamp()
    expires_at = _timestamp_claim(
        claims,
        "exp",
        required=True,
    )
    if expires_at <= now_ts:
        raise AuthenticationExpiredError(
            "OIDC identity token is expired"
        )

    not_before = _timestamp_claim(
        claims,
        "nbf",
        required=False,
    )
    if not_before is not None and not_before > now_ts:
        raise AuthenticationNotYetValidError(
            "OIDC identity token is not valid yet"
        )

    digest = hashlib.sha256(
        issuer.strip().encode("utf-8")
        + b"\x00"
        + subject.strip().encode("utf-8")
    ).hexdigest()
    return AuthenticatedPrincipal(user_id=f"OIDC-{digest}")


def principal_from_streamlit_user(
    user,
    *,
    now: Optional[datetime] = None,
) -> AuthenticatedPrincipal:
    """Adapt Streamlit's st.user object without importing Streamlit here."""
    if not bool(getattr(user, "is_logged_in", False)):
        raise AuthenticationRequiredError(
            "user is not logged in"
        )

    to_dict = getattr(user, "to_dict", None)
    if not callable(to_dict):
        raise AuthenticationRequiredError(
            "authenticated user claims are unavailable"
        )
    claims = to_dict()
    if not isinstance(claims, Mapping):
        raise AuthenticationRequiredError(
            "authenticated user claims are unavailable"
        )
    return oidc_principal_from_claims(claims, now=now)


def decode_document_master_key(secret_value: str) -> bytes:
    """Decode one externally supplied base64 AES-256 document key."""
    if not isinstance(secret_value, str) or not secret_value.strip():
        raise RuntimeSecurityConfigurationError(
            "document master key secret is missing"
        )
    try:
        raw = base64.b64decode(
            secret_value.strip().encode("ascii"),
            validate=True,
        )
    except (ValueError, UnicodeEncodeError) as error:
        raise RuntimeSecurityConfigurationError(
            "document master key must be valid base64"
        ) from error

    if len(raw) != 32:
        raise RuntimeSecurityConfigurationError(
            "document master key must decode to exactly 32 bytes"
        )
    return raw



def validate_document_key_id(value: str) -> str:
    """Validate one non-secret opaque document-key generation identifier."""
    if (
        not isinstance(value, str)
        or _DOCUMENT_KEY_ID_PATTERN.fullmatch(value.strip()) is None
    ):
        raise RuntimeSecurityConfigurationError(
            "document key ID must be a safe opaque identifier"
        )
    return value.strip()
