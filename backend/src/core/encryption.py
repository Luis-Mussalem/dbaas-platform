from functools import lru_cache

from cryptography.fernet import Fernet

from src.core.config import settings


@lru_cache(maxsize=1)
def get_fernet() -> Fernet:
    return Fernet(settings.FERNET_KEY.encode())


def encrypt_value(plain_text: str) -> str:
    f = get_fernet()
    return f.encrypt(plain_text.encode()).decode()


def decrypt_value(encrypted_text: str) -> str:
    f = get_fernet()
    return f.decrypt(encrypted_text.encode()).decode()
