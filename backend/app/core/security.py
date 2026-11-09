from datetime import datetime, timedelta, timezone
import uuid
import jwt
from pwdlib import PasswordHash
from app.core.config import get_settings

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    return password_hash.verify(password, encoded)


def create_access_token(subject: str, role: str) -> str:
    settings = get_settings()
    issued = datetime.now(timezone.utc)
    expires = issued + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode({
        "sub": subject, "role": role, "type": "access", "jti": str(uuid.uuid4()),
        "iss": settings.jwt_issuer, "aud": settings.jwt_audience,
        "iat": issued, "nbf": issued, "exp": expires,
    },
                      settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    settings = get_settings()
    payload = jwt.decode(
        token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm],
        issuer=settings.jwt_issuer, audience=settings.jwt_audience,
        options={"require": ["sub", "exp", "iat", "iss", "aud", "jti", "type"]},
    )
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Unexpected token type")
    return payload
