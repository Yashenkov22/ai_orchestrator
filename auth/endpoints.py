import pytz

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from instagrapi import Client

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, delete
from sqlalchemy.exc import SQLAlchemyError

from db.base import get_session, Account, Message
from db.queries import (add_and_return_new_user,
                        update_time_and_return_user,
                        execute_and_catch_db_error,
                        get_admin_by_username,
                        get_account_by_id,
                        get_message_by_id)

from utils.base import pwd_context, moscow_tz
from utils.encrypt import decrypt_password
from utils.exc import DB_ERROR_EXCEPTION
from utils.commands import create_admin_accounts
from utils.enums import SessionStatusEnum, MessageStatusEnum

from utils.dependencies import user_dependency, session_dependency, admin_dependency
from utils.celery import run_task
from utils.scheduler import scheduler

from background.tasks import start_polling_for_accounts

from background.base import get_redis_pool, background_task_wrapper

from .utils import (authenticate_user,
                    generate_tokens,
                    get_user_or_raise_exception,
                    create_token,
                    EXPIRES_ACCESS_TOKEN,
                    get_current_user)

from .schemas import (RegisterUserSchema,
                      LoginUserSchema,
                      RefreshToken,
                      DetailUserSchema,
                      RegisterEndpointResponse,
                      SendMessageSchema,
                      SecretShcema)

from config import SECRET_API


auth_router = APIRouter(prefix='/auth',
                        tags=['Auth'])


@auth_router.get('/test_arq')
async def test_arq(admin: admin_dependency,
                   session: session_dependency):
    
    # _redis_pool = get_redis_pool()

    # await _redis_pool.enqueue_job('start_polling_for_accounts',
    #                               _queue_name='arq:polling',
    #                               _job_id='polling_accounts_task')

    func_name = 'start_polling_for_accounts'

    job = scheduler.add_job(background_task_wrapper,
                            trigger='interval',
                            minutes=1,
                            id='start_polling_for_accounts',
                            jobstore='sqlalchemy',
                            coalesce=True,
                            args=(func_name, ),
                            kwargs={'_queue_name': 'arq:polling'})
    
    print(job)
    # print(job.__dict__)

    
    # scheduler.add_job(start_polling_for_accounts,
    #                   id='polling_accounts_task',
    #                       trigger="interval",
    #                       seconds=120)
    print('success!!!')


@auth_router.post('/create_admins')
async def create_admins(secret: SecretShcema,
                        session: session_dependency):
    if secret.secret != SECRET_API:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    
    await create_admin_accounts(session)


@auth_router.post('/get_insta_session_by_id')
async def get_insta_session_by_id(account_id: int,
                                  admin: admin_dependency,
                                  session: session_dependency):
    account = await get_account_by_id(account_id,
                                      session)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    # result = run_task('get_session_by_id',
    #                   data={'account_id': account_id})
    
    account.is_active = SessionStatusEnum.PROCESS

    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)
    await get_session_by_id(account,
                            session)
    
    return

@auth_router.post('/test_session')
async def test_session(admin: admin_dependency,
                                  session: session_dependency):
    insta_client = Client()
    insta_client.logger.setLevel("DEBUG")
    insta_client.load_settings('././ses.json')

    info = insta_client.account_info()

    print('Вход в аккаунт✅')
    print(info.__dict__)
    pass


async def get_session_by_id(account: Account,
                            session: AsyncSession):
    print('Задача получения сессии запущена✅!!!')

    # if not account.session:
    password = decrypt_password(account.password)

    # print(password)
    # try:
    #     if not insta_client:
    insta_client = Client()
    
    insta_client.logger.setLevel("DEBUG")
    # insta_client.set_proxy("http://cdsepibb:h4j3h7cmanp8@82.23.102.45:7272")
    try:
        print('пробую залогиниться...')
        print(f'login - {account.username}\npassword - {password}')
        insta_client.login(username=account.username,
                            password=password)
        _session = insta_client.get_settings()
        info = insta_client.account_info()

        account.session = _session
        account.insta_id = info.pk
        account.is_active = SessionStatusEnum.ACTIVE
    except Exception as ex:
        print('ERROR WITH TRY GET INSTA SESSION!!!', ex)
        account.is_active = SessionStatusEnum.INACTIVE

        # print('Введи код...')
        # code = input()
        # insta_client.login(username=account.username,
        #                    password=password,
        #                    verification_code=code)
    finally:
        await execute_and_catch_db_error(session.commit(),
                                        session,
                                        with_rollback=True)


@auth_router.post('/send_message_to_user')
async def send_message_to_user(data: SendMessageSchema,
                               admin: admin_dependency,
                               session: session_dependency):
    check_account = await get_account_by_id(data.account_id,
                                            session,
                                            check_exists=True)
    if not check_account:
        print('account')
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    message = await get_message_by_id(data.message_id,
                                      session)
    if not message:
        print('message')
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    try:
        result = run_task('send_message_to_user',
                        data={'account_id': data.account_id,
                                'message_id': data.message_id,
                                'text': data.text})
        
        message.status = MessageStatusEnum.MODERATED
        message.text = data.text

        await execute_and_catch_db_error(session.commit(),
                                        session,
                                        with_rollback=True)
    except Exception as ex:
        print(ex)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
    else:
        return {'status': 'success'}


@auth_router.post('/token')
async def login_for_access_token(form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
                                 session: session_dependency):
    admin = await authenticate_user(form_data.username,
                                   form_data.password,
                                   session)
    return await generate_tokens(admin,
                                 session)


@auth_router.post('/refresh')
async def new_refresh_tokens(token: RefreshToken,
                             session: session_dependency):
    user = await get_user_or_raise_exception(token.refresh_token,
                                             session)
    return await generate_tokens(user,
                                 session)



# @auth_router.get("/delete_message")
# async def delete_message_from_thread(message_id: int,
#                                      admin: admin_dependency,
#                                      session: session_dependency):
#     check_query = (
#         select(1)\
#         .select_from(Message)\
#         .where(
#             Message.id == message_id
#         )
#     )

#     check_message = await execute_and_catch_db_error(session.execute(check_query),
#                                                      session)

#     check_message = check_message.scalar_one_or_none()

#     if not check_message:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#                             detail='Message not found')
    
#     delete_query = (
#         delete(
#             Message
#         )\
#         .where(
#             Message.id == message_id
#         )
#     )

#     await execute_and_catch_db_error(session.execute(delete_query),
#                                      session,
#                                      with_rollback=True)
    
#     return {
#         'status': 'success'
#     }

# @auth_router.post('/register',
#                   response_model=RegisterEndpointResponse)
# async def register_user(new_user: RegisterUserSchema,
#                         session: session_dependency):
#     user_exists = await get_user_by_email(new_user.email,
#                                           session,
#                                           check_exists=True)
#     if user_exists:
#         raise HTTPException(status_code=status.HTTP_409_CONFLICT,
#                             detail='User with this email already exists')

#     insert_data = new_user.model_dump(exclude={"photos", "main_photo"})

#     password = insert_data.pop('password')

#     insert_data.update({
#         'hash_password': pwd_context.hash(password),
#         'created_at': datetime.now(timezone.utc),
#         'updated_at': datetime.now(timezone.utc),
#     })
    
#     user = await add_and_return_new_user(insert_data,
#                                          session)
#     tokens: dict = await generate_tokens(user,
#                                          session)

#     await execute_and_catch_db_error(session.commit(),
#                                      session,
#                                      with_rollback=True)

#     return RegisterEndpointResponse(user=DetailUserSchema(**user.__dict__),
#                                     token=tokens.get('access_token'))


# @auth_router.post('/login',
#                   response_model=RegisterEndpointResponse)
# async def register_user(login_user: LoginUserSchema,
#                         session: session_dependency):
#     user = await get_user_by_email(login_user.email,
#                                    session)
#     if not user:
#         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
#                             detail=f'User not found by given "email" {login_user.email}')
    
#     if not pwd_context.verify(login_user.password,
#                               user.hash_password):
#         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
#                             detail=f'Incorrect email or password')

#     user = await update_time_and_return_user(user,
#                                             datetime.now(timezone.utc),
#                                             session)
#     tokens: dict = await generate_tokens(user,
#                                          session)
    
#     await execute_and_catch_db_error(session.commit(),
#                                      session,
#                                      with_rollback=True)

#     return RegisterEndpointResponse(user=DetailUserSchema(**user.__dict__),
#                                     token=tokens.get('access_token'))


@auth_router.post('/login')
async def register_admin(login_admin: LoginUserSchema,
                         session: session_dependency):
    admin = await get_admin_by_username(login_admin.username,
                                        session)
    if not admin:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail=f'User not found by given "email" {login_admin.username}')
    
    if not pwd_context.verify(login_admin.password,
                              admin.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail=f'Incorrect email or password')

    # user = await update_time_and_return_user(user,
    #                                         datetime.now(timezone.utc),
    #                                         session)
    tokens: dict = await generate_tokens(admin,
                                         session)
    
    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)

    # return RegisterEndpointResponse(user=DetailUserSchema(**user.__dict__),
    #                                 token=tokens.get('access_token'))
    return {
        'access_token': tokens.get('access_token'),
        'refresh_token': tokens.get('refresh_token'),
    }


# @auth_router.get('/check_password')
async def check_password(email: str,
                         password: str,
                         session: session_dependency):
    query = (
        select(
            Account.password
        )\
        .where(Account.username == email)
    )

    res = await session.execute(query)
    hash_password = res.scalar_one_or_none()
    
    if not hash_password:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f'User not found by given "email" {email}')
    
    return pwd_context.verify(password, hash_password)