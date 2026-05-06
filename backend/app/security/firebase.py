"""Firebase Admin SDK wrapper for verifying ID tokens.

Lazily initializes the SDK on first use so tests can patch the verifier
without needing a real service account file. The verifier callable can be
overridden via FastAPI dependency override during tests.
"""

from __future__ import annotations

import threading
from typing import Any

from app.config import get_settings
from app.logging_config import get_logger

_log = get_logger(__name__)
_init_lock = threading.Lock()
_initialized = False


class FirebaseAuthError(Exception):
    """Raised when Firebase token verification fails."""


def _ensure_initialized() -> None:
    """Initialize the Admin SDK once. Safe under concurrent calls."""
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return

        import firebase_admin
        from firebase_admin import credentials

        settings = get_settings()
        if not settings.firebase_credentials_path:
            raise FirebaseAuthError("FIREBASE_CREDENTIALS_PATH not configured")

        cred = credentials.Certificate(settings.firebase_credentials_path)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred, {"projectId": settings.firebase_project_id})
        _initialized = True
        _log.info("firebase.initialized", project_id=settings.firebase_project_id)


def verify_id_token(id_token: str) -> dict[str, Any]:
    """Verify a Firebase ID token. Raises FirebaseAuthError on any problem.

    Returned dict contains at minimum: uid, phone_number (when phone-auth used),
    iat, exp.
    """
    try:
        _ensure_initialized()
    except FirebaseAuthError:
        raise
    except Exception as e:  # noqa: BLE001
        raise FirebaseAuthError(f"firebase_init_failed: {e}") from e

    from firebase_admin import auth as fb_auth

    try:
        decoded: dict[str, Any] = fb_auth.verify_id_token(id_token, check_revoked=False)
    except fb_auth.ExpiredIdTokenError as e:
        raise FirebaseAuthError("token_expired") from e
    except fb_auth.RevokedIdTokenError as e:
        raise FirebaseAuthError("token_revoked") from e
    except fb_auth.InvalidIdTokenError as e:
        raise FirebaseAuthError(f"token_invalid: {e}") from e
    except Exception as e:  # noqa: BLE001
        raise FirebaseAuthError(f"verify_failed: {e}") from e

    return decoded
