import json
import os
import shutil

from datetime import datetime, timezone
from collections import defaultdict
from uuid import uuid4

from fastapi import (APIRouter, File,
                     HTTPException, UploadFile,
                     status)

from sqlalchemy import func, select, delete
from sqlalchemy.orm import joinedload, selectinload

from db.queries import (get_all_users, get_thread_by_id,
                        update_and_return_user,
                        delete_user_and_return_result,
                        execute_and_catch_db_error,
                        get_account_by_username,
                        get_admin_by_username)

from db.base import Message, Thread, Account, Admin, Attachment

from utils.schemas import (DetailUserSchema, PatchAccountSchema,
                           UpdateUserSchema,
                           NotificationsSchema,
                           CreateAccountSchema,
                           CreateMessageSchema,
                           AccountSchema)
from utils.dependencies import (user_dependency,
                                admin_dependency,
                                session_dependency,
                                current_user_dependency)
from utils.endpoints import add_notifications_to_user
from utils.encrypt import encrypt_password
from utils.base import generate_valid_media_url

from instagrapi import Client
from instagrapi.exceptions import (TwoFactorRequired)

from auth.schemas import LoginUserSchema

from config import ADMIN_URL


user_router = APIRouter(tags=['Users'])


def parse_dt(s):
    return datetime.fromisoformat(s) if s else None


@user_router.get('/test_json')
async def test_json(session: session_dependency):
    with open('./seed_data.json') as f:
        data = json.load(f)

    accounts = data.get('users')
    threads = data.get('threads')
    messages = data.get('messages')

    create_account_list = []

    for account in accounts:
        account['updated_at'] = parse_dt(account.get('updated_at'))
        new_account = Account(**account)
        create_account_list.append(new_account)
    
    session.add_all(create_account_list)    
    
    create_thread_list = []
    for thread in threads:
        thread['timestamp_last_seen_message'] = parse_dt(thread.get('timestamp_last_seen_message'))
        try:
            # del thread['updated_at']
            del thread['guest_username']
        except Exception as ex:
            print('ERROR!!!',ex)
            pass
        thread['account_id'] = thread.pop('user_id')
        new_thread = Thread(**thread)
        create_thread_list.append(new_thread)

    session.add_all(create_thread_list)    

    create_message_list = []
    for message in messages:
        message['created_at'] = parse_dt(message.get('created_at'))
        new_message = Message(**message)
        create_message_list.append(new_message)

    session.add_all(create_message_list) 

    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)
    


# @user_router.get("/accounts")
# async def get_accounts(session: session_dependency):
#     result = await session.execute(select(User))
#     users = result.scalars().all()
#     return [
#         {
#             "id": str(u.id),
#             "name": u.username,
#             "username": u.username,
#             "email": u.insta_id or "",
#             "status": "active",
#             "created": u.updated_at.strftime("%Y-%m-%d") if u.updated_at else "",
#         }
#         for u in users
#     ]


# @user_router.get("/threads")
# async def get_threads(session: session_dependency):
#     result = await session.execute(select(Thread))
#     threads = result.scalars().all()
#     grouped = defaultdict(list)
#     for t in threads:
#         # треды без user_id идут в отдельную группу
#         account_key = str(t.user_id) if t.user_id else "unassigned"
#         grouped[account_key].append({
#             "id": str(t.id),
#             "title": str(t.id),
#             "model": "assistant",
#             "last_activity": (
#                 t.timestamp_last_seen_message.strftime("%Y-%m-%d %H:%M")
#                 if t.timestamp_last_seen_message else ""
#             ),
#         })
#     return dict(grouped)

@user_router.post("/new_account")
async def create_account(data: CreateAccountSchema,
                         admin: admin_dependency,
                         session: session_dependency):
    check_account = await get_account_by_username(data.username,
                                                  session)

    if check_account:
        raise HTTPException(status_code=400,
                            detail='Такая запись уже есть в БД')
    
    insert_data = {
        'username': data.username,
        'password': encrypt_password(data.password),
        'created_at': datetime.now(tz=timezone.utc),
        'updated_at': datetime.now(tz=timezone.utc),
    }
    new_account = Account(**insert_data)

    session.add(new_account)

    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)
    
    return {
        "id": str(new_account.id),
        "username": new_account.username,
        "insta_id": new_account.insta_id,
        'is_active': new_account.is_active,
    }


@user_router.get("/accounts")
async def get_accounts(admin: admin_dependency,
                       session: session_dependency):
    result = await session.execute(select(Account))
    # query = (
    #     select(
    #         Account
    #     )\
    #     .options(
    #         selectinload(Account.threads)
    #     )
    # )
    # query = (
    #     select(Account)
    #     .options(
    #         selectinload(Account.threads)
    #             .joinedload(Thread.insta_user),
    #     )
    # )
    # result = await execute_and_catch_db_error(session.execute(query),
    #                                           session)
    users = result.scalars().all()
    accounts = []

    # for user in users:
    #     user_data =  {
    #         "id": str(user.id),
    #         "username": user.username,
    #         "insta_id": user.insta_id,
    #         'is_active': user.is_active,
    #         'created_at': user.created_at,
    #         'updated_at': user.updated_at,
    #     }
        # threads = []
        # for thread in user.threads:
        #     # print(user.threads)
        #     # grouped = defaultdict(list)
        #     # for t in threads:
        #     # account_key = str(thread) if thread.account_id else "unassigned"
        #     threads.append({
        #         "id": str(thread.id),
        #         "thread_id": thread.thread_id,
        #         "guest_id": thread.insta_user_id,
        #         "guest_username": f'{user.username} - {thread.insta_user.username}',
        #         "last_activity": (
        #             thread.timestamp_last_seen_message.strftime("%Y-%m-%d %H:%M")
        #             if thread.timestamp_last_seen_message else ""
        #         ),
        #     })
        #     print(threads)
        # user_data['threads'] = threads

        # print(user_data)

        # accounts.append(user_data)

    accounts = [
        {
            "id": str(u.id),
            "username": u.username,
            "insta_id": u.insta_id,
            'is_active': u.is_active,
            'created_at': u.created_at,
            'updated_at': u.updated_at,
            'proxy_url': u.proxy_url,
            'is_parse': u.is_parse,
        }
        for u in users
    ]
    # print(accounts)
    return accounts


@user_router.get("/accounts/{account_id}",
                 response_model=AccountSchema)
async def get_account_by_id(account_id: int,
                            admin: admin_dependency,
                            session: session_dependency):
    query = (
        select(Account)
        .options(
            selectinload(Account.threads)
                .joinedload(Thread.insta_user),
        )\
        .where(
            Account.id == account_id,
        )
    )
    result = await execute_and_catch_db_error(session.execute(query),
                                              session)
    account = result.scalar_one_or_none()

    if account:
        account_data =  {
            "id": str(account.id),
            "username": account.username,
            "insta_id": account.insta_id,
            'is_active': account.is_active,
            'created_at': account.created_at,
            'updated_at': account.updated_at,
            'proxy_url': account.proxy_url,
            'is_parse': account.is_parse,
        }
        
        threads = []
        for thread in account.threads:
            threads.append({
                "id": str(thread.id),
                "thread_id": thread.thread_id,
                "guest_id": thread.insta_user_id,
                "guest_username": f'{account.username} - {thread.insta_user.username}',
                'pending_msgs': thread.messages_count,
                "last_activity": (
                    thread.timestamp_last_seen_message.strftime("%Y-%m-%d %H:%M")
                    if thread.timestamp_last_seen_message else ""
                ),
            })

        account_data['threads'] = threads

        return account_data


@user_router.patch("/accounts")
async def get_account_by_id(data: PatchAccountSchema,
                            admin: admin_dependency,
                            session: session_dependency):
    query = (
        select(
            Account
        )\
        .where(
            Account.id == data.account_id
        )
    )

    res = await execute_and_catch_db_error(session.execute(query),
                                           session)
    
    account = res.scalar_one_or_none()

    print(account.username)

    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Account not found')
    
    has_edit = False

    if data.proxy_url:
        if not account.proxy_url:
            account.proxy_url = data.proxy_url
            has_edit = True
        elif account.proxy_url != data.proxy_url:
            account.proxy_url = data.proxy_url
            has_edit = True
    else:
        if account.proxy_url:
            account.proxy_url = None
            has_edit = True

    if account.is_parse != data.is_parse:
        account.is_parse = data.is_parse
        has_edit = True

    if not has_edit:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail='Nothing change')
    else:
        await execute_and_catch_db_error(session.commit(),
                                         session,
                                         with_rollback=True)
        return {
            'status': 'success',
        }
    


@user_router.get("/threads")
async def get_threads(admin: admin_dependency,
                      session: session_dependency):
    # result = await session.execute(select(Thread))
    # threads = result.scalars().all()
    result = await session.execute(
        select(Thread)
        .options(
            joinedload(Thread.account),
            joinedload(Thread.insta_user)
        )
    )
    threads = result.scalars().all()
    grouped = defaultdict(list)
    for t in threads:
        account_key = str(t.account_id) if t.account_id else "unassigned"
        grouped[account_key].append({
            "id": str(t.id),
            "thread_id": t.thread_id,
            "guest_id": t.insta_user_id,
            "guest_username": f'{t.account.username} - {t.insta_user.username}',
            "last_activity": (
                t.timestamp_last_seen_message.strftime("%Y-%m-%d %H:%M")
                if t.timestamp_last_seen_message else ""
            ),
        })
    return dict(grouped)


@user_router.get("/messages")
async def get_messages(admin: admin_dependency,
                       session: session_dependency):
    result = await session.execute(
        select(Message, Thread.context)
        .join(Thread, Message.thread_id == Thread.id)\
        .options(joinedload(Message.attachment))\
        .order_by(Message.thread_id, Message.created_at)
    )
    rows = result.all()

    grouped = defaultdict(list)
    seen_threads = set()  # чтобы добавить context только один раз на тред

    # подтягиваем context отдельно (нужен до первого сообщения)
    threads_result = await session.execute(select(Thread))
    threads_map = {str(t.id): t.context for t in threads_result.scalars().all()}

    for message, _ in rows:
        tid = str(message.thread_id)

        # первым вставляем system-сообщение из context треда
        if tid not in seen_threads:
            seen_threads.add(tid)
            context = threads_map.get(tid)
            if context:
                grouped[tid].insert(0, {
                    "id": f"system_{tid}",
                    "role": "system",
                    "content": context,
                    "ts": "",
                    "modStatus": None,
                })
        _attachment = message.attachment
        content = message.text or ""
        
        if _attachment:
            _attachment = {
                'media_type': _attachment.media_type,
                'media_url': generate_valid_media_url(_attachment.media_url),
            }
            content = ''

        grouped[tid].append({
            "id": str(message.id),
            "role": message.sender,
            "content": content,
            "ts": (
                message.created_at.strftime("%Y-%m-%d %H:%M")
                if message.created_at else ""
            ),
            "modStatus": message.status,  # pending / approved / moderated
            'attachment': _attachment
        })

    return dict(grouped)


@user_router.post("/create_message")
async def create_new_message(data: CreateMessageSchema,
                             admin: admin_dependency,
                             session: session_dependency):
    thread = await get_thread_by_id(data.thread_id,
                                    session)
    
    print(data)
    
    if not thread or thread.account.id != data.account_id:
        print('here')
        raise HTTPException(status_code=400,
                            detail='not found thread or account by thread')
    
    insert_data = {
        'sender': 'assistant',
        'created_at': datetime.now(tz=timezone.utc),
        'updated_at': datetime.now(tz=timezone.utc),
        'thread_id': thread.id,
        'text': data.text,
    }

    new_message = Message(**insert_data)
    session.add(new_message)

    if data.attachment:
        await execute_and_catch_db_error(session.flush(),
                                        session)
    
        message_id = new_message.id

        insert_data = {
            'media_url': f"{data.attachment['media_url']}",
            'media_type': data.attachment['media_type'],
            'message_id': message_id,
        }

        new_attachment = Attachment(**insert_data)
        session.add(new_attachment)
    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)
    return {
        'status': 'success',
    }


@user_router.delete("/delete_message")
async def delete_message_from_thread(message_id: int,
                                     admin: admin_dependency,
                                     session: session_dependency):
    check_query = (
        select(1)\
        .select_from(Message)\
        .where(
            Message.id == message_id
        )
    )

    check_message = await execute_and_catch_db_error(session.execute(check_query),
                                                     session)

    check_message = check_message.scalar_one_or_none()

    if not check_message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Message not found')
    
    delete_query = (
        delete(
            Message
        )\
        .where(
            Message.id == message_id
        )
    )

    await execute_and_catch_db_error(session.execute(delete_query),
                                     session)
    
    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)
    
    return {
        'status': 'success'
    }


@user_router.get("/stats")
async def get_stats(session: session_dependency):
    accounts = await session.scalar(select(func.count()).select_from(Account))
    threads  = await session.scalar(select(func.count()).select_from(Thread))
    messages = await session.scalar(select(func.count()).select_from(Message))
    pending  = await session.scalar(
        select(func.count()).select_from(Message)
        .where(Message.sender == 'assistant', Message.status == 'pending')
    )
    return { "accounts": accounts, "threads": threads, "messages": messages, "pending": pending}


# треды конкретного аккаунта
@user_router.get("/accounts/{account_id}/threads")
async def get_account_threads(account_id: str, session: session_dependency):
    if account_id == "unassigned":
        result = await session.execute(
            select(Thread).where(Thread.account_id == None)
        )
    else:
        result = await session.execute(
            select(Thread).where(Thread.account_id == int(account_id))
        )
    threads = result.scalars().all()
    return [
        {
            "id": str(t.id),
            "thread_id": t.thread_id,
            "guest_id": t.guest_id,
            "guest_username": f"username {t.guest_id}",
            "last_activity": (
                t.timestamp_last_seen_message.strftime("%Y-%m-%d %H:%M")
                if t.timestamp_last_seen_message else ""
            ),
        }
        for t in threads
    ]


# сообщения конкретного треда
@user_router.get("/threads/{thread_id}/messages")
async def get_thread_messages(thread_id: str, session: session_dependency):
    thread_result = await session.execute(
        select(Thread).where(Thread.id == int(thread_id))
    )
    thread = thread_result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    msg_result = await session.execute(
        select(Message).options(joinedload(Message.attachment))
        .where(Message.thread_id == int(thread_id))
        .order_by(Message.created_at.desc())
    )
    messages = msg_result.scalars().all()

    result = []
    # system message from thread context
    if thread.context:
        result.append({
            "id": f"system_{thread_id}",
            "role": "system",
            "content": thread.context,
            "ts": "",
            "modStatus": None,
        })

    for m in messages:
        _attachment = m.attachment
        content = m.text or ""
        
        if _attachment:
            _attachment = {
                'media_type': _attachment.media_type,
                'media_url': generate_valid_media_url(_attachment.media_url),
            }
            content = ''
        result.append({
            "id": str(m.id),
            "role": m.sender,
            "content": content,
            "ts": (
                m.created_at.strftime("%Y-%m-%d %H:%M")
                if m.created_at else ""
            ),
            "modStatus": m.status,
            "attachment": _attachment,
        })

    return result



UPLOAD_DIR = "media"

@user_router.post("/upload_file")
async def upload_file(admin: admin_dependency,
                      session: session_dependency,
                      file: UploadFile = File(...)):
    # создаём папку если нет
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    # уникальное имя файла
    file_ext = file.filename.split(".")[-1]
    filename = f"{uuid4()}.{file_ext}"
    media_url = os.path.join(UPLOAD_DIR, filename)

    # сохраняем файл
    with open(media_url, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    content_type = file.content_type

    if content_type.startswith('image'):
        media_type = 'photo'
    elif content_type.startswith('audio'):
        media_type = 'audio'
    elif content_type.startswith('video'):
        media_type = 'video'

    return {
        'media_type': media_type,
        "media_url": media_url,
    }


# @user_router.post("/user")
# async def login_and_get_session_by_account(user: LoginUserSchema,
#                                     session: session_dependency):
#     account_from_db = await get_account_by_username(username=user.username,
#                                               _session=session)
#     if not account_from_db:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#                             detail=f'User not found by given "id" {user.username}')
    
#     if not verify_password(user.password, account_from_db.password):
#         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
#                             detail='invalid password')
    
#     insta_client = Client()
#     insta_client.logger.setLevel("DEBUG")
    
#     if not account_from_db.session:
#         try:
#             insta_client.login(username=user.username,
#                                password=user.password)
#         except TwoFactorRequired as ex:
#             print('Введи код верификации...')
#             code = input()
#             print('Пробую зайти...')
#             insta_client.login(username=user.username,
#                                password=user.password,
#                                verification_code=code)
#         except Exception as ex:
#             print('ERROR WITH TRY GET INSTA SESSION!!!', ex)
#             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
#                                 detail='ERROR WITH TRY GET SESSION, TRY LATER')

#         _session = insta_client.get_settings()
#         acc = insta_client.account_info()

#         account_from_db.session = _session
#         account_from_db.insta_id = str(acc.pk)

#         await execute_and_catch_db_error(session.commit(),
#                                          session,
#                                          with_rollback=True)
#     else:
#         _session = account_from_db.session

#     return _session


# @user_router.get("/user/me",
#                 response_model=DetailUserSchema)
# async def return_authenticated_user(user_id: user_dependency,
#                                     session: session_dependency):
#     user = await get_user_by_id(user_id=user_id,
#                                 _session=session)
#     if not user:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#                             detail=f'User not found by given "id" {user_id}')
    
#     add_notifications_to_user(user)

#     return user


# @user_router.get("/user/{user_id}",
#                 response_model=DetailUserSchema)
# async def return_user_by_id(user_id: int,
#                             session: session_dependency):
#     user = await get_user_by_id(user_id=user_id,
#                                 _session=session)
#     if not user:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#                             detail=f'User not found by given "id" {user_id}')

#     add_notifications_to_user(user)

#     return user


@user_router.get("/users",
                response_model=list[DetailUserSchema])
async def return_all_users(session: session_dependency,
                           user_id: current_user_dependency):
    users = await get_all_users(session,
                                user_id)
    
    [add_notifications_to_user(user) for user in users]

    return users


# @user_router.patch("/user",
#                 response_model=DetailUserSchema)
# async def update_user_by_id(user_id: user_dependency,
#                             session: session_dependency,
#                             update_data: UpdateUserSchema):
#     user = await get_user_by_id(user_id=user_id,
#                                 _session=session)
#     if not user:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#                             detail=f'User not found by given "id" {user_id}')

#     _update_data = update_data.model_dump(exclude_none=True)

#     updated_user = await update_and_return_user(user,
#                                                 _update_data,
#                                                 session)
#     add_notifications_to_user(user)

#     return updated_user


# @user_router.delete("/user")
# async def delete_user_by_id(user_id: user_dependency,
#                             session: session_dependency):
#     user = await get_user_by_id(user_id=user_id,
#                                 _session=session)
#     if user:
#         has_deleted = await delete_user_and_return_result(user,
#                                                           session)
#     else:
#         has_deleted = False

#     return {
#         'success': has_deleted,
#     }


# @user_router.patch("/user/notifications",
#                 response_model=DetailUserSchema)
# async def update_user_notifications(user_id: user_dependency,
#                                     session: session_dependency,
#                                     update_data: NotificationsSchema):
#     user = await get_user_by_id(user_id=user_id,
#                                 _session=session)
#     if not user:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#                             detail=f'User not found by given "id" {user_id}')

#     _update_data = update_data.model_dump(exclude_none=True)

#     updated_user = await update_and_return_user(user,
#                                                 _update_data,
#                                                 session)
    
#     add_notifications_to_user(user)

#     return updated_user




@user_router.get("/test")
async def test_hander(session: session_dependency):
    # ACCOUNT_USERNAME = 'yashenkov.q'
    # ACCOUNT_PASSWORD = 'QazWsxEdc123!'
    # insta_client.login(ACCOUNT_USERNAME, ACCOUNT_PASSWORD)
    users = await get_all_users(session)

    db_user = users[0]

    for user in users:
        insta_client = Client()
        insta_client.logger.setLevel("DEBUG")
        
        insta_client.set_settings(user.session)
        my_acc = insta_client.account_info()

        owner_user_id = my_acc.pk
        
        # print(my_acc)
        # print(my_acc.__dict__)

        threads = insta_client.direct_threads()

        # print('THREADS!!!!', threads)

        for thread in threads:
            # print(thread.messages)
            for message in thread.messages:
                if message.user_id != owner_user_id:
                    print('MESSAGE OBJ', message)
                    print('MESSAGE TEXT!!!',message.text)
                    print(message.user_id)
                    print('*' * 10)
            # print(thread.users)
            # print('*' * 10)
            # print(thread.admin_user_ids)

        db_user.session = insta_client.get_settings()

        await execute_and_catch_db_error(session.commit(),
                                                session,
                                                with_rollback=True)




    # search_username = 'skxnny22th'

    # user = insta_client.user_info_by_username(search_username)

    # print(user)
    # print(user.__dict__)

    # insta_client.direct_send('Hi dude 22!!!',
    #                          user_ids=[user.pk])
    
    # print('Message send!!!')

    # user = await get_user_by_id(user_id=user_id,
    #                             _session=session)
    # if not user:
    #     raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
    #                         detail=f'User not found by given "id" {user_id}')
    
    # add_notifications_to_user(user)

    # return user