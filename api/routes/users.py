import json
import os
import shutil

from datetime import datetime, timezone
from collections import defaultdict
from uuid import uuid4

from fastapi import (APIRouter, File,
                     HTTPException, UploadFile,
                     status)

from sqlalchemy import func, select, delete, case, exists, and_, update
from sqlalchemy.orm import joinedload, selectinload, aliased

from db.queries import (get_all_users, get_thread_by_id,
                        update_and_return_user,
                        delete_user_and_return_result,
                        execute_and_catch_db_error,
                        get_account_by_username,
                        get_admin_by_username)

from db.base import Message, Thread, Account, Admin, Attachment, InstaUser

from utils.schemas import (DetailThreadSchema, DetailUserSchema, EditThreadColorLevelSchema,
                           PatchAccountSchema,
                           NewAccountSchema, PatchInformationAccountSchema, PatchPhotoAccountSchema, ThreadSchema, UpdateProfileDataSchema,
                           UpdateUserSchema,
                           NotificationsSchema,
                           CreateAccountSchema,
                           CreateMessageSchema,
                           AccountSchema)
from utils.dependencies import (user_dependency,
                                admin_dependency,
                                session_dependency,
                                current_user_dependency,
                                arq_dependency)
from utils.endpoints import add_notifications_to_user
from utils.encrypt import encrypt_password
from utils.base import generate_valid_insta_url, generate_valid_media_url, get_folder_profiles, get_vision_folder_list

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


# new
@user_router.get("/accounts")
async def get_accounts(admin: admin_dependency,
                       session: session_dependency):
    thread_alias = aliased(Thread)

    query = (
        select(
            Account,
            func.count(Thread.id),
            exists()
            .where(
                and_(
                    thread_alias.account_id == Account.id,
                    thread_alias.is_unread == True,
                )
            ),
        )
        .outerjoin(Thread, Thread.account_id == Account.id)\
        .group_by(Account.id)
    )

    result = await execute_and_catch_db_error(session.execute(query),
                                              session)

    users = result.fetchall()
    accounts = []

    # print(users)

    accounts = [
        {
            "id": u.id,
            "username": u.username,
            "insta_id": u.insta_id,
            'has_error': -(u.has_error),
            'created_at': u.created_at,
            'updated_at': u.updated_at,
            # 'proxy_url': u.proxy_url,
            'is_active': u.is_active,
            'thread_count': thread_count,
            'has_unread': has_unread,
        }
        for u, thread_count, has_unread in users
    ]
    
    return accounts


# new
@user_router.get("/accounts/{account_id}",
                 response_model=NewAccountSchema,
                 response_model_by_alias=False)
async def get_account_by_id(account_id: int,
                            admin: admin_dependency,
                            session: session_dependency):
    thread_alias = aliased(Thread)
    
    query = (
        select(
            Account,
            func.count(Thread.id),
            exists()
            .where(
                and_(
                    thread_alias.account_id == Account.id,
                    thread_alias.is_unread == True,
                )
            ),
        )
        .outerjoin(Thread, Thread.account_id == Account.id)
        .where(
            Account.id == account_id,
        )
        .group_by(Account.id)
    )
    result = await execute_and_catch_db_error(session.execute(query),
                                              session)
    account, thread_count, has_unread = result.one_or_none()

    if account:
        account_data =  {
            "id": account.id,
            "username": account.username,
            "fullname": account.full_name,
            'created_at': account.created_at,
            'updated_at': account.updated_at,
            'photo_url': generate_valid_media_url(account.photo_url),
            'is_active': account.is_active,
            'thread_count': thread_count,
            'has_unread': has_unread,
            'has_error': -(account.has_error),
            'information': account.information,
            'folder_id': account.folder_id,
            'profile_id': account.profile_id,
        }

        return account_data


@user_router.get("/accounts/{account_id}/threads",
                 response_model=list[ThreadSchema])
async def get_threads_by_account_id(account_id: int,
                                    admin: admin_dependency,
                                    session: session_dependency):
    result = await session.execute(
        select(Thread)
        .options(
            joinedload(Thread.account),
            joinedload(Thread.insta_user)
        )
        .where(
            Thread.account_id == account_id
        )
    )
    threads = result.scalars().all()
    # grouped = defaultdict(list)
    thread_list = []
    for t in threads:
        # account_key = str(t.account_id) if t.account_id else "unassigned"
        thread_list.append(ThreadSchema(**{
            "id": t.id,
            # "thread_id": t.thread_id,
            # "guest_id": t.insta_user_id,
            "account_name": t.account.username,
            "user_name": t.insta_user.username,
            'has_unread': t.is_unread,
            'color_level': t.color_level,
            "last_activity": (
                t.timestamp_last_seen_message.strftime("%Y-%d-%m %H:%M")
                if t.timestamp_last_seen_message else ""
            ),
        }))
    return thread_list


@user_router.patch("/threads/edit_color_level")
async def edit_color_level_by_thread_id(data: EditThreadColorLevelSchema,
                                        admin: admin_dependency,
                                        session: session_dependency):
    query = (
        select(1)
        .where(
            Thread.id == data.thread_id,
        )
    )

    result = await execute_and_catch_db_error(session.execute(query),
                                              session)
    
    check_exist = result.scalar_one_or_none()

    if not check_exist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Thread not found')
    
    update_query = (
        update(
            Thread
        )\
        .values(color_level=data.color_level)\
        .where(
            Thread.id == data.thread_id,
        )
    )

    result = await execute_and_catch_db_error(session.execute(update_query),
                                              session,
                                              with_rollback=True)
    
    await session.commit()


@user_router.get("/folders")
async def get_vision_folders(admin: admin_dependency,
                             session: session_dependency):
    data: dict = await get_vision_folder_list()

    folders = data.get('data')

    return [{
        'folder_id': folder['id'],
        'folder_name': folder['folder_name'],
        'folder_icon': folder['folder_icon'],
        'folder_icon': folder['folder_icon'],
        'folder_color': folder['folder_color'],
    } for folder in folders if not folder['deleted_at']] # if not folder['deleted_at']



@user_router.get("/folder_profiles")
async def get_vision_folder_profiles(folder_id: str,
                                     admin: admin_dependency,
                                     session: session_dependency):
    data = await get_folder_profiles(folder_id)

    profiles = data.get('data').get('items')

    query = (
        select(
            Account.profile_id,
        )\
        .where(
            Account.folder_id == folder_id,
        )
    )

    res = await execute_and_catch_db_error(session.execute(query),
                                           session)
    
    folder_profile_id_from_db = res.scalars().all()

    if folder_profile_id_from_db:
        folder_profile_id_from_db = set(folder_profile_id_from_db)

    return [{
        'profile_id': profile['id'],
        'folder_id': profile['folder_id'],
        'profile_name': profile['profile_name'],
        'profile_status': profile['profile_status'],
    } for profile in profiles if profile['id'] not in folder_profile_id_from_db]


@user_router.patch("/update_profile_data_by_account")
async def update_profile_data_by_account(data: UpdateProfileDataSchema,
                                         admin: admin_dependency,
                                         session: session_dependency):
    account_query = (
        select(Account)\
        .where(
            Account.id == data.account_id,
        )
    )

    res = await execute_and_catch_db_error(session.execute(account_query),
                                           session)
    
    account: Account = res.scalar_one_or_none()

    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Account not found by given account_id')
    
    check_query = (
        select(1)\
        .where(
            and_(
                Account.folder_id == data.folder_id,
                Account.profile_id == data.profile_id,
                Account.id != data.account_id,
            )
        )
    )
    has_record_res = await execute_and_catch_db_error(session.execute(check_query),
                                                      session)
    
    has_record = has_record_res.scalar_one_or_none()
    
    if has_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='This profile link with another account already')

    account.folder_id = data.folder_id
    account.profile_id = data.profile_id

    try:
        await execute_and_catch_db_error(session.commit(),
                                        session,
                                        with_rollback=True)
        
        return {
            'status': 'success',
            'detail': 'Profile successfully linked',
        }

    except Exception as ex:
        print(ex)
        raise


# @user_router.get("/start_account_profile")
# async def update_profile_data_by_account(account_id: UpdateProfileDataSchema,
#                                          admin: admin_dependency,
#                                          session: session_dependency):


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

    # print(account.username)

    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Account not found')
    
    has_edit = False

    if account.is_active != data.is_active:
        account.is_active = data.is_active
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


@user_router.patch("/set_account_information")
async def set_account_information(data: PatchInformationAccountSchema,
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
    
    account: Account = res.scalar_one_or_none()

    # print(account.username)

    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Account not found')
    
    has_edit = False

    if account.information != data.information:
        account.information = data.information
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
    

@user_router.patch("/set_account_photo")
async def set_photo_information(data: PatchPhotoAccountSchema,
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
    
    account: Account = res.scalar_one_or_none()

    # print(account.username)

    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Account not found')
    
    # has_edit = False

    # if account.information != data.information:
    #     account.information = data.information
    #     has_edit = True

    # if not has_edit:
    #     raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
    #                         detail='Nothing change')
    account.photo_url = data.media_url

    # else:
    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)
    return {
        'status': 'success',
    }

# old
# @user_router.get("/threads")
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
                t.timestamp_last_seen_message.strftime("%Y-%d-%m %H:%M")
                if t.timestamp_last_seen_message else ""
            ),
        })
    return dict(grouped)

# new
@user_router.get("/threads")
async def get_threads(admin: admin_dependency,
                      session: session_dependency):
    result = await session.execute(
        select(Thread)
        .options(
            joinedload(Thread.account),
            joinedload(Thread.insta_user)
        )
    )
    threads = result.scalars().all()
    # grouped = defaultdict(list)
    thread_list = []
    for t in threads:
        # account_key = str(t.account_id) if t.account_id else "unassigned"
        thread_list.append({
            "id": t.id,
            # "thread_id": t.thread_id,
            # "guest_id": t.insta_user_id,
            "account_name": t.account.username,
            "guest_name": t.insta_user.username,
            'has_unread': t.is_unread,
            'color_level': t.color_level,
            "last_activity": (
                t.timestamp_last_seen_message.strftime("%Y-%d-%m %H:%M")
                if t.timestamp_last_seen_message else ""
            ),
        })
    return thread_list



@user_router.get("/add_user_information")
async def add_info(admin: admin_dependency,
                      session: session_dependency,
                      thread_id: int):

    user_information = {
        'first_name': 'Denis',
        'last_name': 'Rodman',
        'age': 22,
        'jobs': ['programmer', 'basketball player'],
        'prefered_nicknames': ['joker', 'daddy'],
        'first_city': 'Chicago',
        'first_country': 'USA',
        'current_city': 'New-York',
        'current_country': 'USA',
        'hobbies': ['chess', 'cooking', 'beer'],
    }
    try:
        json_information = json.dumps(user_information)
    except Exception as ex:
        print(ex)
        raise

    thread_query = (
        update(Thread)\
        .values(user_information=json_information)
        .where(Thread.id == thread_id)
    )

    await execute_and_catch_db_error(session.execute(thread_query),
                                     session)
    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)


# new
@user_router.get("/threads/{thread_id}",
                 response_model=DetailThreadSchema)
async def get_threads(admin: admin_dependency,
                      session: session_dependency,
                      thread_id: int):
    message_query = (
        select(Message)
        .options(joinedload(Message.attachments))\
        .where(
            Message.thread_id == thread_id,
        )
        .order_by(Message.created_at.desc())
    )
    
    message_query_result = await execute_and_catch_db_error(session.execute(message_query),
                                                            session)
    
    thread_query = (
        select(Thread)\
        .options(
            joinedload(Thread.account),
            joinedload(Thread.insta_user),
        )
        .where(Thread.id == thread_id)
    )

    thread_context_query_result = await execute_and_catch_db_error(session.execute(thread_query),
                                                                   session)

    # messages = message_query_result.scalars().all()
    messages = message_query_result.unique().scalars().all()

    thread = thread_context_query_result.scalar_one_or_none()

    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Thread not found')

    message_list = []

    try:
        user_information = json.loads(thread.user_information)
    except Exception as ex:
        print('JSON SERIALIZE ERROR', ex)
        user_information = None

    thread_info = {
        'thread_name': f'{thread.account.username} - {thread.insta_user.username}',
        'message_count': len(messages),
        'account_information': {
            'photo_url': generate_valid_media_url(thread.account.photo_url),
            'information': thread.account.information,
            'username': thread.account.username,
            'full_name': thread.account.full_name,
        },
        'user_information': {
            'photo_url': generate_valid_media_url(thread.insta_user.photo_url),
            'information': user_information,
            'insta_link': generate_valid_insta_url(thread.insta_user.username),
            'username': thread.insta_user.username,
            'full_name': thread.insta_user.full_name,
        }

        # 'account_photo_url': generate_valid_media_url(thread.account.photo_url),
        # 'user_photo_url': generate_valid_media_url(thread.insta_user.photo_url),
        # 'user_insta_link': generate_valid_insta_url(thread.insta_user.username),
        # 'user_information': user_information,
        # 'account_information': thread.account.information,
    }
    
    # if thread.context:
    thread_info['context'] = thread.context or ''

    if messages:

        # if thread.context:
        #     message_dict = {
        #         'id': None,
        #         'role': 'system',
        #         "content": thread.context,
        #         "ts": "",
        #         "modStatus": None,
        #     }
        #     message_list.append(message_dict)
        
        for message in messages:
            attachments = message.attachments
            attachment_list = []
            content = message.text or ""

            for _attachment in attachments:
            # _attachment = message.attachments
                # content = message.text or ""
                
                if _attachment:
                    _attachment = {
                        'media_type': _attachment.media_type,
                        'media_url': generate_valid_media_url(_attachment.media_url),
                    }
                    # _attachment = None
                    attachment_list.append(_attachment)
                
            message_dict = {
                "id": str(message.id),
                "role": message.sender,
                "content": content,
                "ts": (
                    message.created_at.strftime("%Y-%d-%m %H:%M")
                    if message.created_at else ""
                ),
                "modStatus": message.status,  # pending / approved / moderated
                'attachments': attachment_list
            }
            message_list.append(message_dict)

    thread_info['messages'] = message_list

    return thread_info


# old
# @user_router.get("/messages")
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
                message.created_at.strftime("%Y-%d-%m %H:%M")
                if message.created_at else ""
            ),
            "modStatus": message.status,  # pending / approved / moderated
            'attachment': _attachment
        })

    return dict(grouped)

# new
@user_router.get("/messages")
async def new_get_messages(admin: admin_dependency,
                       session: session_dependency):
    # query = (
    #     select(Message)
    #     .options(
    #         joinedload(Message.thread).joinedload(Thread.account),
    #         joinedload(Message.thread).joinedload(Thread.insta_user),
    #         joinedload(Message.attachment),
    #     )
    #     .order_by(
    #         Message.created_at.desc(),
    #     )
    # )
    query = (
        select(Message)
        .options(
            selectinload(Message.thread).selectinload(Thread.account),
            selectinload(Message.thread).selectinload(Thread.insta_user),
            selectinload(Message.attachments),
        )
        .order_by(
            Message.created_at.desc(),
        )
    )

    result = await execute_and_catch_db_error(session.execute(query),
                                              session)
    
    messages = result.scalars().all()

    message_list = []
    for message in messages:
        _attachments = message.attachments
        content = message.text or ""
        attachment_list = []
        
        if _attachments:
            for _attachment in _attachments:
                _attachment = {
                    'media_type': _attachment.media_type,
                    'media_url': generate_valid_media_url(_attachment.media_url),
                }
                attachment_list.append(_attachment)

        message_list.append({
            "id": message.id,
            "role": message.sender,
            "content": content,
            'account_name': message.thread.account.username,
            'thread_name': f'{message.thread.account.username} - {message.thread.insta_user.username}',
            "ts": (
                message.created_at.strftime("%Y-%d-%m %H:%M")
                if message.created_at else ""
            ),
            "modStatus": message.status,  # pending / approved / moderated
            'attachment': attachment_list,
        })

    return message_list


# new
@user_router.get("/messages/{message_id}")
async def new_get_messages(admin: admin_dependency,
                           session: session_dependency,
                           message_id: int):
    query = (
        select(Message)
        .options(
            joinedload(Message.thread).joinedload(Thread.account),
            joinedload(Message.thread).joinedload(Thread.insta_user),
            joinedload(Message.attachments),
        )
        .where(
            Message.id == message_id,
        )
    )

    result = await execute_and_catch_db_error(session.execute(query),
                                              session)
    
    message = result.unique().scalar_one_or_none()

    _attachments = message.attachments
    content = message.text or ""
    attachment_list = []
    
    if _attachments:
        for _attachment in _attachments:
            _attachment = {
                'media_type': _attachment.media_type,
                'media_url': generate_valid_media_url(_attachment.media_url),
            }
            attachment_list.append(_attachment)

        # content = ''

    result = {
        "id": message.id,
        "role": message.sender,
        "content": content,
        'account_name': message.thread.account.username,
        'thread_name': f'{message.thread.account.username} - {message.thread.insta_user.username}',
        "ts": (
            message.created_at.strftime("%Y-%d-%m %H:%M")
            if message.created_at else ""
        ),
        "modStatus": message.status,  # pending / approved / moderated
        'attachment': attachment_list,
        'thread_id': message.thread_id,
    }

    return result


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
# @user_router.get("/accounts/{account_id}/threads")
# async def get_account_threads(account_id: str, session: session_dependency):
#     if account_id == "unassigned":
#         result = await session.execute(
#             select(Thread).where(Thread.account_id == None)
#         )
#     else:
#         result = await session.execute(
#             select(Thread).where(Thread.account_id == int(account_id))
#         )
#     threads = result.scalars().all()
#     return [
#         {
#             "id": str(t.id),
#             "thread_id": t.thread_id,
#             "guest_id": t.guest_id,
#             "guest_username": f"username {t.guest_id}",
#             "last_activity": (
#                 t.timestamp_last_seen_message.strftime("%Y-%m-%d %H:%M")
#                 if t.timestamp_last_seen_message else ""
#             ),
#         }
#         for t in threads
#     ]


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
        _attachments = m.attachments
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
                m.created_at.strftime("%Y-%d-%m %H:%M")
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
    else:
        media_type = None

    return {
        'media_type': media_type,
        "media_url": media_url,
        "media_preview": generate_valid_media_url(media_url),
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


# from background.tasks import send_message_to_thread


@user_router.get("/run_background_send_message")
async def test_hander(admin: admin_dependency,
                      session: session_dependency,
                      arq_pool: arq_dependency,
                      account_id: int,
                      message_id: int):
    job = await arq_pool.enqueue_job(
        'send_message_to_thread',   # имя = __name__ функции, зарегистрированной в воркере
        account_id,
        message_id,
        _queue_name='arq:message',
    )
    return {"status": "queued", "job_id": job.job_id}
    # async with session as _session:
    # await send_message_to_thread(account_id=account_id,
    #                             message_id=message_id,
    #                             session=session)
    # ACCOUNT_USERNAME = 'yashenkov.q'
    # ACCOUNT_PASSWORD = 'QazWsxEdc123!'
    # insta_client.login(ACCOUNT_USERNAME, ACCOUNT_PASSWORD)
    # users = await get_all_users(session)

    # db_user = users[0]

    # for user in users:
    #     insta_client = Client()
    #     insta_client.logger.setLevel("DEBUG")
        
    #     insta_client.set_settings(user.session)
    #     my_acc = insta_client.account_info()

    #     owner_user_id = my_acc.pk
        
    #     # print(my_acc)
    #     # print(my_acc.__dict__)

    #     threads = insta_client.direct_threads()

    #     # print('THREADS!!!!', threads)

    #     for thread in threads:
    #         # print(thread.messages)
    #         for message in thread.messages:
    #             if message.user_id != owner_user_id:
    #                 print('MESSAGE OBJ', message)
    #                 print('MESSAGE TEXT!!!',message.text)
    #                 print(message.user_id)
    #                 print('*' * 10)
    #         # print(thread.users)
    #         # print('*' * 10)
    #         # print(thread.admin_user_ids)

    #     db_user.session = insta_client.get_settings()

    #     await execute_and_catch_db_error(session.commit(),
    #                                             session,
    #                                             with_rollback=True)




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