import os
import jwt
import bcrypt
from datetime import datetime, timedelta
from typing import Optional
from dotenv import load_dotenv
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"

security_agent = HTTPBearer()

def create_access_token(data: dict, expires_delta: timedelta = timedelta(hours=2)):
    """ Генерира JWT токен с роля и ID """
    to_encode = data.copy()
    if "sub" in to_encode and not isinstance(to_encode["sub"], str):
        to_encode["sub"] = str(to_encode["sub"])
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security_agent)):
    """ Валидира токена от заглавната част на заявката """
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload  # Връща нещо от сорта на: {"user_id": 1, "role": "admin"}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token.")

def is_superadmin_user(user: dict) -> bool:
    """ Проверява дали потребителят притежава права на главен администратор (Superadmin) """
    return user.get("is_superadmin") is True or user.get("role") == "superadmin"

def require_admin(current_user: dict = Depends(get_current_user)):
    """ Защитна стена: Допуска потребители с роля 'admin' или права на Superadmin """
    if current_user.get("role") not in ("admin", "superadmin") and not is_superadmin_user(current_user):
        raise HTTPException(status_code=403, detail="Permission denied. Admins only.")
    return current_user

def require_examiner(current_user: dict = Depends(get_current_user)):
    """ Защитна стена: Допуска потребители с роля 'examiner' или права на Superadmin """
    if current_user.get("role") not in ("examiner", "superadmin") and not is_superadmin_user(current_user):
        raise HTTPException(status_code=403, detail="Permission denied. Examiners only.")
    return current_user

def require_student(current_user: dict = Depends(get_current_user)):
    """ Защитна стена: Допуска потребители с роля 'student' или права на Superadmin """
    if current_user.get("role") not in ("student", "superadmin") and not is_superadmin_user(current_user):
        raise HTTPException(status_code=403, detail="Permission denied. Students only.")
    return current_user

def require_superadmin(current_user: dict = Depends(get_current_user)):
    """ Защитна стена: Допуска единствено потребители с права на Superadmin """
    if not is_superadmin_user(current_user):
        raise HTTPException(status_code=403, detail="Permission denied. Superadmin privileges required.")
    return current_user

def get_password_hash(password: str) -> str:
    """ Генерира сигурен Bcrypt хеш за новата парола """
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def hash_secure_key(raw_token: str) -> str:
    """ Генерира SHA-256 хеш за Secure Key токен """
    import hashlib
    return hashlib.sha256(raw_token.strip().encode('utf-8')).hexdigest()

def generate_secure_key_token(duration_type: str):
    """ Генерира криптографски JWT Secure Key токен и неговия хеш за базата данни """
    import uuid
    from datetime import timezone
    now = datetime.now(timezone.utc)
    expires_at = None

    if duration_type == "1_day":
        expires_at = now + timedelta(days=1)
    elif duration_type == "1_week":
        expires_at = now + timedelta(days=7)
    elif duration_type == "1_month":
        expires_at = now + timedelta(days=30)
    elif duration_type == "indefinite":
        expires_at = None
    else:
        raise ValueError(f"Invalid duration type: {duration_type}")

    payload = {
        "sub": "unattended_registration",
        "key_id": str(uuid.uuid4()),
        "duration": duration_type,
    }
    if expires_at is not None:
        payload["exp"] = expires_at

    raw_token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    key_hash = hash_secure_key(raw_token)
    return raw_token, key_hash, expires_at

def validate_secure_key(db, key_token: Optional[str]) -> bool:
    """ Валидира Secure Key токена спрямо базата данни и срока на годност """
    from datetime import timezone
    from .models import SecureKey

    if not key_token or not key_token.strip():
        return False

    token_clean = key_token.strip()
    try:
        payload = jwt.decode(token_clean, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("sub") != "unattended_registration":
            raise HTTPException(status_code=400, detail="Невалиден или изтекъл Secure Key.")
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        raise HTTPException(status_code=400, detail="Невалиден или изтекъл Secure Key.")

    token_hash = hash_secure_key(token_clean)
    db_key = db.query(SecureKey).filter(SecureKey.key_hash == token_hash, SecureKey.is_active == True).first()
    if not db_key:
        raise HTTPException(status_code=400, detail="Невалиден или изтекъл Secure Key.")

    if db_key.revoked_at is not None:
        raise HTTPException(status_code=400, detail="Невалиден или изтекъл Secure Key.")

    if db_key.expires_at is not None:
        expires_at = db_key.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            db_key.is_active = False
            db.commit()
            raise HTTPException(status_code=400, detail="Невалиден или изтекъл Secure Key.")

    return True