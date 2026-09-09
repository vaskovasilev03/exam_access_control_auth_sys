import os
import jwt
import bcrypt
from datetime import datetime, timedelta
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

def get_password_hash(password: str) -> str:
    """ Генерира сигурен Bcrypt хеш за новата парола """
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))