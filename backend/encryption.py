import os
from cryptography.fernet import Fernet

_fernet = None

def _get_fernet():
    global _fernet
    if _fernet is None:
        key = os.getenv("BYOK_ENCRYPTION_KEY")
        if not key:
            raise RuntimeError("BYOK_ENCRYPTION_KEY environment variable not set.")
        _fernet = Fernet(key.encode())
    return _fernet

def encrypt_api_key(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()

def decrypt_api_key(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()


def detect_provider_from_key(api_key: str) -> str | None:
    """Try to guess the provider from the API key prefix."""
    mapping = {
        "sk-ant": "anthropic",
        "sk-proj-": "openai",
        "sk-": "openai",
        "xai-": "grok",
        "AIza": "gemini",
    }
    for prefix, provider in mapping.items():
        if api_key.startswith(prefix):
            return provider
    return None