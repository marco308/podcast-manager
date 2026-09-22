"""Token encryption service using Fernet symmetric encryption."""

import logging

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

logger = logging.getLogger(__name__)


class TokenDecryptionError(Exception):
    """Raised when an at-rest token cannot be decrypted.

    Typically means the ENCRYPTION_KEY has been rotated or the stored
    ciphertext is corrupted. Callers should treat this as "the user's
    Spotify tokens are unrecoverable" and force reauthentication.
    """


class EncryptionService:
    """Service for encrypting and decrypting sensitive data."""

    def __init__(self) -> None:
        settings = get_settings()
        self._cipher = Fernet(settings.ENCRYPTION_KEY.encode())

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext string.

        Args:
            plaintext: The string to encrypt.

        Returns:
            The encrypted string (base64 encoded).
        """
        return self._cipher.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt an encrypted string.

        Args:
            ciphertext: The encrypted string (base64 encoded).

        Returns:
            The decrypted plaintext string.

        Raises:
            TokenDecryptionError: if the ciphertext is invalid, corrupted, or
                was encrypted under a different key. Never includes the
                ciphertext or key material in the message.
        """
        try:
            return self._cipher.decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            # Do not log ciphertext — it's sensitive. Log only that decryption failed.
            logger.error("Fernet decryption failed: token invalid or key mismatch")
            raise TokenDecryptionError("Stored token could not be decrypted") from exc


# Singleton instance
_encryption_service: EncryptionService | None = None


def get_encryption_service() -> EncryptionService:
    """Get the encryption service singleton."""
    global _encryption_service
    if _encryption_service is None:
        _encryption_service = EncryptionService()
    return _encryption_service
