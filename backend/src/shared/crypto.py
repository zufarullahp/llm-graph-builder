"""
Encryption utilities for Privas AI backend.
Used to store Neo4j credentials securely in DomainGraph.neo4jSecretEnc.
"""

import base64
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from src.core.config import get_settings


# ============================================================
# Initialization
# ============================================================

cfg = get_settings()

# remove optional prefix 'base64:' and decode
key_b64 = cfg.REGISTRY_ENC_KEY.removeprefix("base64:")
key = base64.b64decode(key_b64)

if len(key) not in (16, 24, 32):
    raise ValueError(
        f"Invalid encryption key length {len(key)} bytes. "
        "AESGCM requires 16/24/32 bytes (128/192/256-bit)."
    )


# ============================================================
# Encrypt / Decrypt
# ============================================================

def encrypt(plaintext: str) -> str:
    """
    Encrypt a plaintext string using AES-GCM and return base64 ciphertext.
    Format: base64(nonce + ciphertext + tag)
    """
    if plaintext is None:
        raise ValueError("Cannot encrypt None")

    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # 96-bit random nonce
    data = plaintext.encode("utf-8")
    encrypted = aesgcm.encrypt(nonce, data, None)
    blob = nonce + encrypted
    return base64.b64encode(blob).decode("utf-8")


def decrypt(ciphertext: str) -> str:
    """
    Decrypt a base64 ciphertext and return the plaintext string.
    """
    if not ciphertext:
        raise ValueError("Empty ciphertext")

    aesgcm = AESGCM(key)
    blob = base64.b64decode(ciphertext)
    nonce, encrypted = blob[:12], blob[12:]
    data = aesgcm.decrypt(nonce, encrypted, None)
    return data.decode("utf-8")
