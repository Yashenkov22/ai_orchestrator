from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from arq import ArqRedis

from jose import jwt, JWTError

from sqlalchemy.ext.asyncio import AsyncSession

from auth.utils import get_current_user, get_current_user_optional, get_current_admin

from db.base import get_session

from config import JWT_ALGORITHM, JWT_SECRET_KEY


user_dependency = Annotated[int, Depends(get_current_user)]

admin_dependency = Annotated[int, Depends(get_current_admin)]

current_user_dependency = Annotated[int, Depends(get_current_user_optional)]

session_dependency = Annotated[AsyncSession, Depends(get_session)]


def get_arq_pool(request: Request):
    return request.app.state.arq_pool

arq_dependency = Annotated[ArqRedis, Depends(get_arq_pool)]