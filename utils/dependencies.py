from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from jose import jwt, JWTError

from sqlalchemy.ext.asyncio import AsyncSession

from auth.utils import get_current_user, get_current_user_optional, get_current_admin

from db.base import get_session

from config import JWT_ALGORITHM, JWT_SECRET_KEY


user_dependency = Annotated[int, Depends(get_current_user)]

admin_dependency = Annotated[int, Depends(get_current_admin)]

current_user_dependency = Annotated[int, Depends(get_current_user_optional)]

session_dependency = Annotated[AsyncSession, Depends(get_session)]


