"""Token encryption service using Fernet symmetric encryption."""

from cryptography.fernet import Fernet

from app.config import get_settings


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
        """
        return self._cipher.decrypt(ciphertext.encode()).decode()


# Singleton instance
_encryption_service: EncryptionService | None = None


def get_encryption_service() -> EncryptionService:
    """Get the encryption service singleton."""
    global _encryption_service
    if _encryption_service is None:
        _encryption_service = EncryptionService()
    return _encryption_service
