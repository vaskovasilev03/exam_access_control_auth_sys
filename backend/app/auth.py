import os
import jwt
from datetime import datetime, timedelta
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
print(f"SECRET_KEY: {SECRET_KEY}")  # Debugging line to check if SECRET_KEY is loaded correctly

security_agent = HTTPBearer()

def create_access_token(data: dict, expires_delta: timedelta = timedelta(days=1)):
    """ Генерира JWT токен с роля и ID """
    to_encode = data.copy()
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

def require_admin(current_user: dict = Depends(get_current_user)):
    """ Защитна стена: Допуска само потребители с роля 'admin' """
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Permission denied. Admins only.")
    return current_user