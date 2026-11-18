from typing import Annotated, Iterable, Optional
from dataclasses import dataclass
from datetime import timedelta, datetime, timezone

from fastapi import Depends, status
from fastapi.exceptions import HTTPException
from fastapi.security import OAuth2PasswordBearer, HTTPBearer, HTTPAuthorizationCredentials

from sqlalchemy.ext.asyncio import AsyncSession

from jose import jwt, JWTError

from utils.base import pwd_context

from db.base import get_session, session as db_session_maker, Admin
from db.queries import (save_refresh_token_for_user,
                        get_admin_by_username,
                        get_admin_by_id,
                        execute_and_catch_db_error)
from utils.exc import NOT_AUTHENTICATED_EXCEPTION

from config import API_PREFIX, JWT_ALGORITHM, JWT_SECRET_KEY


EXPIRES_ACCESS_TOKEN = timedelta(days=1)
EXPIRES_REFRESH_TOKEN = timedelta(days=60)


# Тип токена в claim `typ`. Без него refresh-токен (60 дней) принимался
# как access, потому что отличить их было нечем.
TOKEN_TYPE_ACCESS = 'access'
TOKEN_TYPE_REFRESH = 'refresh'

# Токены, выпущенные до появления claim `typ`.
# False — старые сессии перестают работать сразу после деплоя (разовый
# перелогин всех админов), True — принимаются до истечения, то есть
# мягкий выкат ценой того, что старый refresh ещё какое-то время
# работает как access. Поставьте True, если перелогин не вариант.
ALLOW_LEGACY_TOKENS = False


o2auth_bearer = OAuth2PasswordBearer(tokenUrl=f'{API_PREFIX}/auth/token',
                                     scheme_name='Version1')

oauth2_optional = OAuth2PasswordBearer(tokenUrl=f'{API_PREFIX}/auth/token',
                                     auto_error=False)

# security = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentAdmin:
    """Админ текущего запроса вместе с его правами.

    Права читаются из БД, а не из claims токена: так отзыв права
    срабатывает сразу, а не после истечения access-токена.
    """

    id: int
    username: str
    is_superadmin: bool
    scopes: frozenset[str]
    # None = ограничений по аккаунтам нет. Персональный список появится
    # на этапе 5 вместе с таблицей admin_accounts.
    account_ids: Optional[frozenset[int]] = None

    def __iter__(self):
        """Совместимость с `admin_id, is_main_admin = admin` в ручках.

        До появления прав зависимость возвращала именно такой тупл,
        и так её распаковывают ~34 эндпоинта. Распаковка продолжает
        работать, а новый код пользуется атрибутами.
        """
        yield self.id
        yield self.is_superadmin

    def has_scope(self, scope: str) -> bool:
        return self.is_superadmin or str(scope) in self.scopes

    def can_see_account(self, account_id: Optional[int]) -> bool:
        if self.is_superadmin or self.account_ids is None:
            return True

        if account_id is None:
            return True

        return int(account_id) in self.account_ids


def current_admin_from_model(admin: Admin) -> CurrentAdmin:
    return CurrentAdmin(
        id=admin.id,
        username=admin.username,
        is_superadmin=bool(admin.is_superadmin),
        scopes=frozenset(admin.scopes or ()),
    )


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
                 expires_delta: timedelta,
                 token_type: str = TOKEN_TYPE_ACCESS,
                 scopes: Optional[Iterable[str]] = None,
                 is_superadmin: bool = False):
    encode = {
        'userId': user_id,
        'typ': token_type,
        }

    if token_type == TOKEN_TYPE_ACCESS:
        # Для фронта, чтобы он сразу знал, что рисовать. Проверка прав
        # на бэке всё равно идёт по БД — claims тут не авторитет.
        encode.update({
            'scopes': sorted(scopes or ()),
            'isSuperadmin': bool(is_superadmin),
        })

    expires = datetime.now(timezone.utc) + expires_delta
    encode.update({'exp': expires.timestamp()})

    return jwt.encode(encode,
                      JWT_SECRET_KEY,
                      algorithm=JWT_ALGORITHM)


def decode_token(token: str,
                 expected_type: str = TOKEN_TYPE_ACCESS) -> dict:
    """Декодирует токен и проверяет его тип. Бросает JWTError."""
    payload = jwt.decode(token,
                         JWT_SECRET_KEY,
                         algorithms=[JWT_ALGORITHM])

    token_type = payload.get('typ')

    if token_type is None:
        if not ALLOW_LEGACY_TOKENS:
            raise JWTError('token has no "typ" claim')
    elif token_type != expected_type:
        raise JWTError(f'expected {expected_type} token, got {token_type}')

    if not payload.get('userId'):
        raise JWTError('token has no "userId" claim')

    return payload


async def generate_tokens(admin: Admin,
                          session: AsyncSession):
    access_token = create_token(admin.id,
                                EXPIRES_ACCESS_TOKEN,
                                token_type=TOKEN_TYPE_ACCESS,
                                scopes=admin.scopes or (),
                                is_superadmin=bool(admin.is_superadmin))
    refresh_token = create_token(admin.id,
                                 EXPIRES_REFRESH_TOKEN,
                                 token_type=TOKEN_TYPE_REFRESH)
    await add_refresh_token_to_db(admin,
                                  refresh_token,
                                  session)
    
    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)
    
    return {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'token_type': 'bearer',
    }


def get_current_user(token: Annotated[str, Depends(o2auth_bearer)]):
    try:
        payload = decode_token(token,
                               TOKEN_TYPE_ACCESS)

        return payload.get('userId')
        
    except JWTError:
        raise NOT_AUTHENTICATED_EXCEPTION
    


async def get_current_admin(token: Annotated[str, Depends(o2auth_bearer)],
                            session: Annotated[AsyncSession, Depends(get_session)]) -> CurrentAdmin:
    try:
        payload = decode_token(token,
                               TOKEN_TYPE_ACCESS)
    except JWTError:
        raise NOT_AUTHENTICATED_EXCEPTION

    admin = await get_admin_by_id(payload.get('userId'),
                                  session)

    if not admin:
        raise NOT_AUTHENTICATED_EXCEPTION

    return current_admin_from_model(admin)


async def load_admin_rights(admin_id: int) -> Optional[CurrentAdmin]:
    """Права админа вне контекста запроса (WS-соединение, redis-листенер)."""
    if not admin_id:
        return None

    async with db_session_maker() as _session:
        admin = await get_admin_by_id(admin_id,
                                      _session)

    return current_admin_from_model(admin) if admin else None
    

async def get_current_user_optional(
    token: Optional[str] = Depends(oauth2_optional)
):
    if token is None:
        return None

    try:
        payload = decode_token(token,
                               TOKEN_TYPE_ACCESS)
        return payload.get('userId')
    except Exception:
        return None  # или можно кинуть 401, если токен битый


async def get_user_or_raise_exception(refresh_token: str,
                                      session: AsyncSession):
    http_exc_400 = HTTPException(status_code=400)

    try:
        payload = decode_token(refresh_token,
                               TOKEN_TYPE_REFRESH)
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


async def get_current_user_for_websocket(
    token: Optional[str]
) -> Optional[CurrentAdmin]:
    """Админ с правами для WS-соединения или None, если токен не годится."""
    if not token:
        return None

    try:
        payload = decode_token(token,
                               TOKEN_TYPE_ACCESS)
    except JWTError:
        return None
    except Exception as ex:
        print(f'[ws] не смог разобрать токен: {ex}')
        return None

    return await load_admin_rights(payload.get('userId'))
