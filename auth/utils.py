from typing import Annotated, Optional
from datetime import timedelta, datetime, timezone

from fastapi import Depends, status
from fastapi.exceptions import HTTPException
from fastapi.security import OAuth2PasswordBearer, HTTPBearer, HTTPAuthorizationCredentials

from sqlalchemy.ext.asyncio import AsyncSession

from jose import jwt, JWTError

from utils.base import pwd_context

from db.base import get_session, Admin
from db.queries import (save_refresh_token_for_user,
                        get_admin_by_username,
                        get_admin_by_id)
from utils.exc import NOT_AUTHENTICATED_EXCEPTION

from config import API_PREFIX, JWT_ALGORITHM, JWT_SECRET_KEY


EXPIRES_ACCESS_TOKEN = timedelta(days=1)
EXPIRES_REFRESH_TOKEN = timedelta(days=60)


o2auth_bearer = OAuth2PasswordBearer(tokenUrl=f'{API_PREFIX}/auth/token',
                                     scheme_name='Version1')

oauth2_optional = OAuth2PasswordBearer(tokenUrl=f'{API_PREFIX}/auth/token',
                                     auto_error=False)

# security = HTTPBearer(auto_error=False)


async def authenticate_user(username: str,
                            password: str,
                            session: AsyncSession):
    # http_exc_401 = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    admin = await get_admin_by_username(username,
                                       session)
    
    if not admin:
        raise NOT_AUTHENTICATED_EXCEPTION
    
    if not pwd_context.verify(password, admin.password):
        raise NOT_AUTHENTICATED_EXCEPTION

    return admin
    

def create_token(user_id: int,
                 expires_delta: timedelta):
    encode = {
        'userId': user_id,
        }
    expires = datetime.now(timezone.utc) + expires_delta
    encode.update({'exp': expires.timestamp()})

    return jwt.encode(encode,
                      JWT_SECRET_KEY,
                      algorithm=JWT_ALGORITHM)


async def generate_tokens(admin: Admin,
                          session: AsyncSession):
    access_token = create_token(admin.id,
                                EXPIRES_ACCESS_TOKEN)
    refresh_token = create_token(admin.id,
                                 EXPIRES_REFRESH_TOKEN)
    await add_refresh_token_to_db(admin,
                                  refresh_token,
                                  session)
    
    return {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'token_type': 'bearer',
    }


def get_current_user(token: Annotated[str, Depends(o2auth_bearer)]):
    try:
        payload = jwt.decode(token,
                             JWT_SECRET_KEY,
                             algorithms=[JWT_ALGORITHM])
        user_id = payload.get('userId')

        if not user_id:
            raise JWTError()
        
        return user_id
        
    except JWTError:
        raise NOT_AUTHENTICATED_EXCEPTION
    


def get_current_admin(token: Annotated[str, Depends(o2auth_bearer)]):
    try:
        payload = jwt.decode(token,
                             JWT_SECRET_KEY,
                             algorithms=[JWT_ALGORITHM])
        admin_id = payload.get('userId')

        if not admin_id:
            raise JWTError()
        
        return admin_id
        
    except JWTError:
        raise NOT_AUTHENTICATED_EXCEPTION
    

async def get_current_user_optional(
    token: Optional[str] = Depends(oauth2_optional)
):
    if token is None:
        return None

    try:
        payload = jwt.decode(token,
                             JWT_SECRET_KEY,
                             algorithms=[JWT_ALGORITHM])
        user_id = payload.get('userId')
        return user_id
    except Exception:
        return None  # или можно кинуть 401, если токен битый


async def get_user_or_raise_exception(refresh_token: str,
                                      session: AsyncSession):
    http_exc_400 = HTTPException(status_code=400)

    try:
        payload = jwt.decode(refresh_token,
                             JWT_SECRET_KEY,
                             algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise http_exc_400
        # raise NOT_AUTHENTICATED_EXCEPTION
    else:
        user_id = payload.get('userId')

        if not user_id:
            raise http_exc_400
            # raise NOT_AUTHENTICATED_EXCEPTION

        user = await get_admin_by_id(user_id,
                                           session)
        
        if not user:
            raise http_exc_400
            # raise NOT_AUTHENTICATED_EXCEPTION
        
        if refresh_token != user.refresh_token:
            raise http_exc_400
            # raise NOT_AUTHENTICATED_EXCEPTION

        return user


async def add_refresh_token_to_db(admin: Admin,
                                  refresh_token: str,
                                  session: AsyncSession):
    
    await save_refresh_token_for_user(admin,
                                      refresh_token,
                                      session)
