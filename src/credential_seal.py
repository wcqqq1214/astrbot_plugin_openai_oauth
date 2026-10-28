"""Encrypt stored OAuth credentials with a key kept outside AstrBot's config."""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .credential_store import (
    SEALED_PREFIX,
    CredentialPersistenceError,
    CredentialSchemaError,
)


class FernetCredentialSealer:
    """Seal credential records so the config file never holds usable tokens.

    AstrBot returns provider sources, including the plugin's account records,
    from its dashboard API and keeps them in ``cmd_config.json``. The key lives
    in the plugin data directory, so a shared config or dashboard response no
    longer carries a refresh token.
    """

    def __init__(self, key_path: str | os.PathLike[str]) -> None:
        self.key_path = Path(key_path)
        self._fernet: Fernet | None = None

    def _load(self, *, create: bool) -> Fernet | None:
        if self._fernet is not None:
            return self._fernet
        try:
            key = self.key_path.read_bytes().strip()
        except FileNotFoundError:
            if not create:
                return None
            try:
                key = self._create_key()
            except OSError:
                raise CredentialPersistenceError(
                    "Cannot create the credential encryption key. "
                    "Check the plugin data directory permissions."
                ) from None
        try:
            self._fernet = Fernet(key)
        except ValueError:
            raise CredentialSchemaError(
                "The credential encryption key is invalid. Sign in again."
            ) from None
        return self._fernet

    def _create_key(self) -> bytes:
        self.key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        key = Fernet.generate_key()
        try:
            fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            # Another process created it first; use the key it wrote.
            return self.key_path.read_bytes().strip()
        with os.fdopen(fd, "wb") as stream:
            stream.write(key + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        return key

    def seal(self, text: str) -> str:
        fernet = self._load(create=True)
        assert fernet is not None
        return SEALED_PREFIX + fernet.encrypt(text.encode("utf-8")).decode("ascii")

    def open(self, value: str) -> str:
        try:
            fernet = self._load(create=False)
        except OSError:
            fernet = None
        if fernet is None:
            raise CredentialSchemaError(
                "The credential encryption key is missing. Sign in again."
            )
        try:
            token = value.removeprefix(SEALED_PREFIX).encode("ascii")
            return fernet.decrypt(token).decode("utf-8")
        except (InvalidToken, UnicodeError):
            raise CredentialSchemaError(
                "The stored OpenAI credential cannot be decrypted. Sign in again."
            ) from None
