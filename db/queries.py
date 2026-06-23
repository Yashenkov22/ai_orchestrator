from datetime import datetime, timezone

from fastapi import HTTPException

from sqlalchemy import (select,
                        update,
                        insert,
                        and_,
                        exists,)
from sqlalchemy.engine.result import Result
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from db.base import Account, Admin, Message, Thread, InstaUser, Attachment

from utils.ai import ai_generate_text, ai_translate_message
from utils.base import RATIO_LEN_LIMIT, RATIO_LIMIT, moscow_tz, russian_ratio, try_translate_text
from utils.exc import DB_ERROR_EXCEPTION, ChatNotFound, NotAccessToChat


async def execute_and_catch_db_error(coro,
                                     _session: AsyncSession,
                                     with_rollback: bool = False) -> Result | None:
    try:
        return await coro
    
    except SQLAlchemyError as ex:
        print(ex)

        if with_rollback:
            await _session.rollback()

        raise DB_ERROR_EXCEPTION
    
    except Exception as ex:
        print('NOT SQLALCHEMY ERROR❌❌❌', ex)
        raise DB_ERROR_EXCEPTION



# async def get_user_by_id(user_id: int,
#                          _session: AsyncSession,
#                          check_exists: bool = False) -> UAccountser | None:
#     if check_exists:
#         query = select(1)
#     else:
#         query = select(Account).options(selectinload(User.photos))

#     query = query.where(User.id == user_id)

#     result = await execute_and_catch_db_error(_session.execute(query),
#                                               _session)

#     return result.scalar_one_or_none()


# async def get_user_by_email(email: str,
#                    _session: AsyncSession,
#                    check_exists: bool = False) -> User | None:
#     if check_exists:
#         query = select(1)
#     else:
#         query = select(User).options(selectinload(User.photos))

#     query = query\
#         .where(
#             User.email == email
#         )
#     # try:
#     #     res = await _session.execute(query)
#     #     user = res.scalar_one_or_none()
#     # except SQLAlchemyError as ex:
#     #     print(ex)
#     #     raise DB_ERROR_EXCEPTION
#     user = await execute_and_catch_db_error(_session.execute(query),
#                                             _session)
    
#     return user.scalar_one_or_none()


async def get_admin_by_username(username: str,
                   _session: AsyncSession) -> Admin | None:
    # if check_exists:
    #     query = select(1)
    # else:
    query = select(Admin)

    query = query\
        .where(
            Admin.username == username
        )
    # try:
    #     res = await _session.execute(query)
    #     user = res.scalar_one_or_none()
    # except SQLAlchemyError as ex:
    #     print(ex)
    #     raise DB_ERROR_EXCEPTION
    admin = await execute_and_catch_db_error(_session.execute(query),
                                            _session)
    
    return admin.scalar_one_or_none()


async def get_admin_by_id(_id: str,
                   _session: AsyncSession) -> Admin | None:
    # if check_exists:
    #     query = select(1)
    # else:
    query = select(Admin)

    query = query\
        .where(
            Admin.id == _id
        )
    # try:
    #     res = await _session.execute(query)
    #     user = res.scalar_one_or_none()
    # except SQLAlchemyError as ex:
    #     print(ex)
    #     raise DB_ERROR_EXCEPTION
    admin = await execute_and_catch_db_error(_session.execute(query),
                                            _session)
    
    return admin.scalar_one_or_none()


async def get_account_by_username(username: str,
                                   _session: AsyncSession) -> Account | None:

    query = select(Account)

    query = query\
        .where(
            Account.username == username
        )
    # try:
    #     res = await _session.execute(query)
    #     user = res.scalar_one_or_none()
    # except SQLAlchemyError as ex:
    #     print(ex)
    #     raise DB_ERROR_EXCEPTION
    user = await execute_and_catch_db_error(_session.execute(query),
                                            _session)
    
    return user.scalar_one_or_none()


async def get_account_by_id(_id: int,
                            _session: AsyncSession,
                            check_exists: bool = False) -> Account | None:
    if check_exists:
        query = select(1)
    else:
        query = select(Account)

    query = query\
        .where(
            Account.id == _id
        )
    
    user = await execute_and_catch_db_error(_session.execute(query),
                                            _session)
    
    return user.scalar_one_or_none()


async def get_message_by_id(_id: int,
                            _session: AsyncSession) -> Message | None:

    # query = select(Message)

    # query = query\
    #     .where(
    #         Message.id == _id
    #     )

    query = (
        select(Message)
        .options(selectinload(Message.attachments),
                 selectinload(Message.thread))
        .where(Message.id == _id)
    )
    
    message = await execute_and_catch_db_error(_session.execute(query),
                                               _session)
    
    return message.scalar_one_or_none()


async def get_message_only_by_id(_id: int,
                            _session: AsyncSession) -> Message | None:

    query = (
        select(Message)
        .where(Message.id == _id)
    )
    
    message = await execute_and_catch_db_error(_session.execute(query),
                                               _session)
    
    return message.scalar_one_or_none()


async def get_thread_by_id(_id: int,
                            _session: AsyncSession) -> Message | None:

    query = (
        select(Thread)\
        .options(selectinload(Thread.insta_user),
                 selectinload(Thread.account))
        .where(Thread.id == _id)
    )
    
    message = await execute_and_catch_db_error(_session.execute(query),
                                               _session)
    
    return message.scalar_one_or_none()


async def save_refresh_token_for_user(admin: Admin,
                                      refresh_token: str,
                                      _session: AsyncSession):
    # query = update(User)\
    #         .values(refresh_token=refresh_token)\
    #         .where(User.id == user.id)
    admin.refresh_token = refresh_token
    
    await execute_and_catch_db_error(_session.flush(),
                                     _session)
    # try:
    #     await _session.flush()
    #     # await _session.commit()
    # except SQLAlchemyError as ex:
    #     print(ex)
    #     raise DB_ERROR_EXCEPTION


async def add_and_return_new_user(user_data: dict,
                                  _session: AsyncSession) -> Account:
    # try:
        user = Account(**user_data)
        _session.add(user)
        await execute_and_catch_db_error(_session.flush(),
                                          _session)
        # await _session.flush()    
    # except SQLAlchemyError as ex:
    #     print(ex)
    #     raise DB_ERROR_EXCEPTION    
    
        return user


async def update_time_and_return_user(user: Account,
                                      time_update: datetime,
                                      _session: AsyncSession) -> Account:
    user.updated_at = time_update

    # try:
        # await _session.flush()
    await execute_and_catch_db_error(_session.flush(),
                                              _session)
    # except SQLAlchemyError as ex:
    #     print(ex)
    #     raise DB_ERROR_EXCEPTION 
    
    return user


async def get_all_users(_session: AsyncSession) -> list[Account]:
    query = select(Account)
    # .options(selectinload(User.photos))

    # if user_id:
    #     query = query.where(
    #         User.id != user_id
    #     )
    #     print('filter!!!✅')
    
    # try:
    result = await execute_and_catch_db_error(_session.execute(query),
                                              _session)
    # res = await _session.execute(query)
    users = result.scalars().all()
    # except SQLAlchemyError as ex:
    #     print(ex)
    #     raise DB_ERROR_EXCEPTION
    
    return users


async def update_and_return_user(user: Account,
                                 update_data: dict,
                                 _session: AsyncSession) -> Account:
    has_update = False
    for key, value in update_data.items():
        if getattr(user, key) != value:
            has_update = True
            break

    if has_update:
        update_data.update({'updated_at': datetime.now(timezone.utc)})
        
        [setattr(user, key, value) for key, value in update_data.items()]
        await execute_and_catch_db_error(_session.commit(),
                                                  _session,
                                                  with_rollback=True)
        # try:
        #     await _session.commit()
        # except SQLAlchemyError as ex:
        #     print(ex)
        #     raise DB_ERROR_EXCEPTION
    else:
        print('nothing')

    return user


async def delete_user_and_return_result(user: Account,
                                        _session: AsyncSession) -> bool:
    try:
        await _session.delete(user)
        await _session.commit()
        has_deleted = True
    except SQLAlchemyError as ex:
        print(ex)
        try:
            await _session.rollback()
        except Exception as ex:
            print(ex)
        has_deleted = False
    
    except Exception as ex:
        print(ex)
        has_deleted = False

    return has_deleted


async def get_thread_by_id(thread_id: int,
                           session: AsyncSession) -> Thread:
    query = (
        select(Thread)
        .options(
            joinedload(Thread.account),
            joinedload(Thread.insta_user)
        )\
        .where(Thread.id == int(thread_id))
    )

    result = await execute_and_catch_db_error(session.execute(query),
                                              session)
    
    return result.scalar_one_or_none()


async def check_insta_user(user_id: str,
                           session: AsyncSession):
    # user_id = insta_user.get('id')

    check_user_query = (
        select(
            InstaUser
        )\
        .where(
            InstaUser.insta_id == str(user_id),
        )
    )

    res = await execute_and_catch_db_error(session.execute(check_user_query),
                                           session)
    
    user = res.scalar_one_or_none()

    return user


async def try_add_insta_user(insta_user: dict,
                             session: AsyncSession):

    insert_data = {
        'insta_id': str(insta_user.get('id')),
        'username': insta_user.get('username'),
        'full_name': insta_user.get('full_name'),
        'photo_url': insta_user.get('photo_url'),
    }

    new_user = InstaUser(**insert_data)

    session.add(new_user)

    # insert_query = (
    #     insert(
    #         InstaUser
    #     )\
    #     .values(**insert_data)
    # )

    await execute_and_catch_db_error(session.flush(),
                                     session)
    
    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)
    
    return new_user


async def check_thread_in_db(thread_id: str,
                             session: AsyncSession):
    # query = (
    #     select(
    #         Thread
    #     )\
    #     .where(
    #         Thread.thread_id == thread_id
    #     )
    # )
    query = (

        select(Thread)
        .options(
            joinedload(Thread.account),
            joinedload(Thread.insta_user),
        )
        .where(Thread.thread_id == thread_id)
    )

    res = await execute_and_catch_db_error(session.execute(query),
                                     session)
    
    return res.scalar_one_or_none()


async def try_add_new_thread(thread_data: dict,
                             session: AsyncSession):

    insert_data = {
        'thread_id': thread_data.get('thread_id'),
        'timestamp_last_seen_message': thread_data.get('timestamp_last_seen_message'),
        'last_message_id': '',
        'context': '',
        'is_approved': True,
        'is_unread':  thread_data.get('is_unread'),
        'color_level': 'grey',
        'user_information': None,
        'account_id':  thread_data.get('account_id'),
        'insta_user_id':  thread_data.get('insta_user_id'),
    }

    new_thread = Thread(**insert_data)

    session.add(new_thread)


    await execute_and_catch_db_error(session.flush(),
                                     session)
    
    # await execute_and_catch_db_error(session.commit(),
    #                                  session,
    #                                  with_rollback=True)
    
    return new_thread


async def update_approve_thread(thread_id: int,
                                is_approved: bool,
                                session: AsyncSession):
    query = (
        update(
            Thread
        )\
        .values(is_approved=is_approved)\
        .where(
            Thread.id == thread_id
        )
    )

    await execute_and_catch_db_error(session.execute(query),
                                     session)
    
    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)
    

async def update_thread_is_unread_by_id(thread_id: int,
                                        session: AsyncSession):
    query = (
        update(
            Thread
        )\
        .values(is_unread=True)\
        .where(
            Thread.id == thread_id
        )
    )

    await execute_and_catch_db_error(session.execute(query),
                                     session)

    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)


async def try_add_messages(message_data: dict,
                           thread: Thread,
                           session: AsyncSession):
    thread_id = message_data.get('thread_id')
    messages = message_data.get('messages')
    mark_as_unread = message_data.get('mark_as_unread')
    insert_messages = []

    unread_messages_text = ''

    if thread_id and messages:
        for message in reversed(messages):
            ts = message.get('timestamp')
            sender = message.get('sender')

            if ts:
                ts = datetime.fromtimestamp(
                    int(ts) / 1000,
                    tz=timezone.utc
                )
            msg_data = {
                'created_at': ts,
                'updated_at': ts,
                'text': message.get('text'),
                'sender': sender,
                'status': 'approved',
                'thread_id': thread_id,
            }

            new_message = Message(**msg_data,
                                  attachments=[Attachment(media_type=t, media_url=u) for t, u in message.get("media_files", [])])
            insert_messages.append(new_message)


            if new_message.text:
                _text = f'{new_message.text} | {new_message.created_at} | {new_message.sender}'
                unread_messages_text += _text

        session.add_all(insert_messages)

        thread.timestamp_last_seen_message = ts

        if mark_as_unread is not None:
            thread.is_unread = mark_as_unread

        context_from_db = thread.context or ''

        text_for_ai = 'Контекст:\n' + context_from_db + '\nНовые сообщения:\n' + unread_messages_text

        new_context = await ai_generate_text(text=text_for_ai,
                                             for_db=True)

        thread.context = new_context

        await execute_and_catch_db_error(session.commit(),
                                        session,
                                        with_rollback=True)
        
    

async def check_new_messages_in_thread(message: Message,
                                       session: AsyncSession):
    query = select(
                exists()\
                .where(
                    Message.thread_id == message.thread_id,
                    Message.created_at > message.created_at,
                )
    )

    res = await execute_and_catch_db_error(session.execute(query),
                                           session)

    has_new_messages = res.scalar()

    return has_new_messages


async def try_update_message_text(message_id: int,
                                  message_text: str,
                                  session: AsyncSession):
    query = (
        select(
            Message
        )\
        .where(
            Message.id == message_id
        )
    )

    res = await execute_and_catch_db_error(session.execute(query),
                                           session)
    
    message = res.scalar_one_or_none()

    if not message:
        return
    
    if message.text != message_text:
        message.text = message_text

        await execute_and_catch_db_error(session.commit(),
                                         session,
                                         with_rollback=True)
        
    return True