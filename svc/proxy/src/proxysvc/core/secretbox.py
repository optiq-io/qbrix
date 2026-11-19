from __future__ import annotations

import base64
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VERSION = "v1"
NONCE_BYTES = 12


class SecretUnreadableError(Exception):
    """a sealed secret this box can't open: another key sealed it, it was
    sealed for another row, or it was altered."""


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _bound_to(tenant_id: str, purpose: str, row_id: str) -> bytes:
    return f"{tenant_id}|{purpose}|{row_id}".encode()


class SecretBox:
    """keeps secrets qbrix must read back, such as a signing secret, sealed
    at rest.

    a sealed value reads v1.<key id>.<nonce>.<ciphertext>. it is bound to the
    tenant, purpose and row it was sealed for, so it can't be copied to
    another row and opened there, and the key id names the key that sealed
    it, so a value sealed under an older key is told apart from a forgery.
    """

    def __init__(self, key: bytes):
        self._aead = AESGCM(key)
        self.key_id = hashlib.sha256(key).hexdigest()[:8]

    def seal(self, plaintext: str, *, tenant_id: str, purpose: str, row_id: str) -> str:
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = self._aead.encrypt(
            nonce, plaintext.encode(), _bound_to(tenant_id, purpose, row_id)
        )
        return ".".join((VERSION, self.key_id, _b64(nonce), _b64(ciphertext)))

    def open(self, sealed: str, *, tenant_id: str, purpose: str, row_id: str) -> str:
        parts = sealed.split(".")
        if len(parts) != 4 or parts[0] != VERSION:
            raise SecretUnreadableError("not a sealed secret")
        _, key_id, nonce, ciphertext = parts
        if key_id != self.key_id:
            raise SecretUnreadableError("sealed under another key")
        try:
            plaintext = self._aead.decrypt(
                _unb64(nonce), _unb64(ciphertext), _bound_to(tenant_id, purpose, row_id)
            )
        except (InvalidTag, ValueError) as e:
            raise SecretUnreadableError("the sealed secret doesn't open") from e
        return plaintext.decode()
