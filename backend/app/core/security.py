from datetime import datetime, timedelta
from typing import Optional
import bcrypt
from jose import JWTError, jwt
from app.config import get_settings


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_access_token(subject: str, tenant_id: str, expires_delta: Optional[timedelta] = None) -> str:
    settings = get_settings()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    to_encode = {"sub": subject, "tenant_id": tenant_id, "exp": expire}
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> Optional[dict]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
