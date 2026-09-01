import json

from fastapi import (APIRouter,
                     HTTPException,
                     status)

from sqlalchemy import select, update, and_, func
from sqlalchemy.orm import joinedload

from db.queries import (execute_and_catch_db_error)

from db.base import (Message,
                     Thread,
                     Account,
                     Attachment)

from utils.schemas import (AttachmentListSchema,
                           DetailThreadSchema,
                           EditThreadAIModelSchema,
                           EditThreadAITemperatureSchema,
                           EditThreadColorLevelSchema,
                           EditThreadFullParseSchema, EditThreadLanguageSchema,
                           EditThreadNotesSchema,
                           EditThreadPinMarkSchema,
                           EditThreadUnreadMarkSchema,
                           ThreadSchema)
from utils.dependencies import (admin_dependency,
                                session_dependency)
from utils.base import (generate_valid_insta_url,
                        generate_valid_media_url)

from config import ADMIN_URL, ID_LIST_FOR_PERMISSION



thread_router = APIRouter(tags=['Treads'],
                          prefix='/threads')

# @thread_router.get("/threads")
@thread_router.get("/list")
async def get_threads(admin: admin_dependency,
                      session: session_dependency):
    admin_id, is_main_admin = admin

    query = (
        select(Thread)
        .join(Thread.account)
        .options(
            joinedload(Thread.account),
            joinedload(Thread.insta_user)
        )\
        .order_by(
            Thread.is_pinned.desc(),
            Thread.is_unread.desc(),
            Thread.timestamp_last_seen_message.desc(),
        )\
        .where(Account.is_hidden == False)
    )

    if not is_main_admin:
        query = query.where(
            Thread.account_id.in_(ID_LIST_FOR_PERMISSION),
        )
         
    result = await session.execute(query)

    threads = result.scalars().all()
    thread_list = []

    for t in threads:
        thread_list.append({
            "id": t.id,
            'account_id': t.account_id,
            "account_name": t.account.view_name or t.account.username,
            "user_name": t.insta_user.username,
            'has_unread': t.is_unread,
            'color_level': t.color_level,
            'is_pinned': t.is_pinned,
            'is_approved': t.is_approved,
            'is_banned': t.is_blocked,
            'proccess_block': t.proccess_block,
            "last_activity": (
                t.timestamp_last_seen_message.strftime("%Y-%d-%m %H:%M")
                if t.timestamp_last_seen_message else ""
            ),
        })
    return thread_list


# @thread_router.get("/accounts/{account_id}/threads",
#                  response_model=list[ThreadSchema])
@thread_router.get("/{account_id}/threads",
                 response_model=list[ThreadSchema])
async def get_threads_by_account_id(account_id: int,
                                    admin: admin_dependency,
                                    session: session_dependency):
    admin_id, is_main_admin = admin

    if not is_main_admin:
        if account_id not in ID_LIST_FOR_PERMISSION:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    result = await session.execute(
        select(Thread)
        .options(
            joinedload(Thread.account),
            joinedload(Thread.insta_user)
        )
        .where(
            Thread.account_id == account_id
        )\
        .order_by(
            Thread.is_pinned.desc(),
            Thread.is_unread.desc(),
            Thread.timestamp_last_seen_message.desc(),
            )
    )
    threads = result.scalars().all()
    thread_list = []

    for t in threads:
        thread_list.append(ThreadSchema(**{
            "id": t.id,
            'account_id': t.account_id,
            "account_name": t.account.view_name or t.account.username,
            "user_name": t.insta_user.username,
            'has_unread': t.is_unread,
            'color_level': t.color_level,
            'is_pinned': t.is_pinned,
            'is_approved': t.is_approved,
            'is_blocked': t.is_blocked,
            'proccess_block': t.proccess_block,
            "last_activity": (
                t.timestamp_last_seen_message.strftime("%Y-%d-%m %H:%M")
                if t.timestamp_last_seen_message else ""
            ),
        }))
    return thread_list


# @thread_router.get("/threads/{thread_id}",
#                  response_model=DetailThreadSchema)
@thread_router.get("/{thread_id}",
                 response_model=DetailThreadSchema)
async def get_threads(admin: admin_dependency,
                      session: session_dependency,
                      thread_id: int):
    admin_id, is_main_admin = admin

    message_query = (
        select(Message)
        .options(joinedload(Message.attachments))\
        .where(
            Message.thread_id == thread_id,
        )
        .order_by(Message.created_at.desc())\
        .limit(50)
    )
    
    message_query_result = await execute_and_catch_db_error(session.execute(message_query),
                                                            session)
    
    message_count = (
        select(func.count(Message.id))
        .where(Message.thread_id == Thread.id)
        .correlate(Thread)
        .scalar_subquery()
    )

    thread_query = (
        select(
            Thread,
            message_count.label("message_count"),
        )
        .options(
            joinedload(Thread.account),
            joinedload(Thread.insta_user),
        )
        .where(Thread.id == thread_id)
    )

    thread_context_query_result = await execute_and_catch_db_error(session.execute(thread_query),
                                                                   session)

    messages = message_query_result.unique().scalars().all()

    # thread = thread_context_query_result.scalar_one_or_none()
    thread_data = thread_context_query_result.one_or_none()

    if not thread_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Thread not found')

    thread, message_count = thread_data
    
    if not is_main_admin:
        if thread.account_id not in ID_LIST_FOR_PERMISSION:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    message_list = []

    try:
        user_information = json.loads(thread.user_information)
    except Exception as ex:
        print('JSON SERIALIZE ERROR', ex)

        if isinstance(thread.user_information, dict):
            user_information = thread.user_information
        else:
            user_information = thread.original_user_information or None

    thread_info = {
        'thread_name': f'{thread.account.username} - {thread.insta_user.username}',
        'message_count': len(messages),
        'is_approved': thread.is_approved,
        'is_blocked': thread.is_blocked,
        'proccess_block': thread.proccess_block,
        'ai_model': thread.ai_model,
        'ai_temperature': thread.ai_temperature,
        'message_count': message_count,
        'language': thread.language,
        'account_information': {
            'photo_url': generate_valid_media_url(thread.account.photo_url),
            'information': thread.account.information,
            'username': thread.account.view_name or thread.account.username,
            'full_name': thread.account.full_name,
            'account_id': thread.account_id,
        },
        'user_information': {
            'photo_url': generate_valid_media_url(thread.insta_user.photo_url),
            'information': user_information,
            'insta_link': generate_valid_insta_url(thread.insta_user.username),
            'username': thread.insta_user.username,
            'full_name': thread.insta_user.full_name,
        }
    }
    
    thread_info['context'] = thread.context or ''
    thread_info['notes'] = thread.notes or ''
    
    if messages:
        
        for message in messages:
            attachments = message.attachments
            attachment_list = []
            content = message.text or ""
            translated_content = message.translated_text or ""

            for _attachment in attachments:
                
                if _attachment:
                    _attachment = {
                        'media_type': _attachment.media_type,
                        'media_url': generate_valid_media_url(_attachment.media_url),
                    }
                    attachment_list.append(_attachment)
                
            message_dict = {
                "id": str(message.id),
                "role": message.sender,
                "content": content,
                "translated_content": translated_content,
                "ts": (
                    message.created_at.strftime("%Y-%d-%m %H:%M")
                    if message.created_at else ""
                ),
                "modStatus": message.status,  # pending / approved / moderated
                'attachments': attachment_list
            }
            message_list.append(message_dict)

        oldest_message_id = message.id

    thread_info['messages'] = reversed(message_list)
    thread_info['oldest_message_id'] = oldest_message_id

    return thread_info


@thread_router.get("/{thread_id}/attachments",
                   response_model=list[AttachmentListSchema])
async def get_thread_attachments(admin: admin_dependency,
                                 session: session_dependency,
                                 thread_id: int):
    admin_id, is_main_admin = admin

    query = (
        select(
            Attachment,
            Message.created_at,
            Message.sender,
        )
        .join(Message, Attachment.message_id == Message.id)
        .where(Message.thread_id == thread_id)
        .order_by(Message.created_at.asc())
    )

    result = await session.execute(query)

    attachments = result.all()

    if not attachments:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Attachments not found')

    attachment_list = []
        
    for attachment_data in attachments:
        attachment, message_creted_at, message_sender = attachment_data
        data = {
            "ts": (
                message_creted_at.strftime("%Y-%d-%m %H:%M")
                if message_creted_at else ""
            ),
            'sender': message_sender,
        }
        _attachment = {
            'media_type': attachment.media_type,
            'media_url': generate_valid_media_url(attachment.media_url),
        }
        data['attachment'] = _attachment
        attachment_list.append(data)

    return attachment_list


@thread_router.get("/{thread_id}/pagination")
async def get_pagination_messages_by_thread(admin: admin_dependency,
                                            session: session_dependency,
                                            thread_id: int,
                                            oldest_message_id: int):
    admin_id, is_main_admin = admin

    message_query = (
        select(Message)
        .options(joinedload(Message.attachments))\
        .where(
            Message.thread_id == thread_id,
            Message.id < oldest_message_id,
        )
        .order_by(Message.created_at.desc())\
        .limit(50)
    )

    message_query_result = await execute_and_catch_db_error(session.execute(message_query),
                                                            session)

    messages = message_query_result.unique().scalars().all()

    message_list = []

    if messages:
        for message in messages:
            attachments = message.attachments
            attachment_list = []
            content = message.text or ""
            translated_content = message.translated_text or ""

            for _attachment in attachments:
                
                if _attachment:
                    _attachment = {
                        'media_type': _attachment.media_type,
                        'media_url': generate_valid_media_url(_attachment.media_url),
                    }
                    attachment_list.append(_attachment)
                
            message_dict = {
                "id": str(message.id),
                "role": message.sender,
                "content": content,
                "translated_content": translated_content,
                "ts": (
                    message.created_at.strftime("%Y-%d-%m %H:%M")
                    if message.created_at else ""
                ),
                "modStatus": message.status,  # pending / approved / moderated
                'attachments': attachment_list
            }
            message_list.append(message_dict)

        oldest_message_id = message.id

        message_list.reverse()

        return {
            'messages': message_list,
            'oldest_message_id': oldest_message_id,
        }
    else:
        return {
            'messages': None,
            'oldest_message_id': None,
        }


# @thread_router.patch("/threads/edit_color_level")
@thread_router.patch("/edit_color_level")
async def edit_color_level_by_thread_id(data: EditThreadColorLevelSchema,
                                        admin: admin_dependency,
                                        session: session_dependency):
    admin_id, is_main_admin = admin

    query = (
        select(Thread.account_id)
        .where(
            Thread.id == data.thread_id,
        )
    )

    result = await execute_and_catch_db_error(session.execute(query),
                                              session)
    
    account_id = result.scalar_one_or_none()

    if not account_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Thread not found')
    if not is_main_admin:
        if account_id not in ID_LIST_FOR_PERMISSION:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    
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


@thread_router.patch("/edit_unread_mark")
async def edit_unread_mark_by_thread_id(data: EditThreadUnreadMarkSchema,
                                        admin: admin_dependency,
                                        session: session_dependency):
    admin_id, is_main_admin = admin

    query = (
        select(Thread.account_id)
        .where(
            Thread.id == data.thread_id,
        )
    )

    result = await execute_and_catch_db_error(session.execute(query),
                                              session)
    
    account_id = result.scalar_one_or_none()

    if not account_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Thread not found')
    
    if not is_main_admin:
        if account_id not in ID_LIST_FOR_PERMISSION:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    
    update_query = (
        update(
            Thread
        )\
        .values(is_unread=False)\
        .where(
            Thread.id == data.thread_id,
        )
    )

    result = await execute_and_catch_db_error(session.execute(update_query),
                                              session,
                                              with_rollback=True)
    
    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)
    

@thread_router.patch("/edit_pin_mark")
async def edit_pin_mark_by_thread_id(data: EditThreadPinMarkSchema,
                                     admin: admin_dependency,
                                     session: session_dependency):
    admin_id, is_main_admin = admin

    query = (
        select(Thread)
        .where(
            Thread.id == data.thread_id,
        )
    )

    result = await execute_and_catch_db_error(session.execute(query),
                                              session)
    
    thread: Thread = result.scalar_one_or_none()

    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Thread not found')

    if not is_main_admin:
        if thread.account_id not in ID_LIST_FOR_PERMISSION:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    thread.is_pinned = not thread.is_pinned
        
    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)


@thread_router.patch("/edit_ai_model")
async def edit_ai_model_by_thread_id(data: EditThreadAIModelSchema,
                                     admin: admin_dependency,
                                     session: session_dependency):
    admin_id, is_main_admin = admin

    query = (
        select(Thread)
        .where(
            Thread.id == data.thread_id,
        )
    )

    result = await execute_and_catch_db_error(session.execute(query),
                                              session)
    
    thread: Thread = result.scalar_one_or_none()

    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Thread not found')

    if not is_main_admin:
        if thread.account_id not in ID_LIST_FOR_PERMISSION:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    thread.ai_model = data.ai_model
        
    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)


@thread_router.patch("/edit_ai_temperature")
async def edit_ai_temperature_by_thread_id(data: EditThreadAITemperatureSchema,
                                     admin: admin_dependency,
                                     session: session_dependency):
    admin_id, is_main_admin = admin

    query = (
        select(Thread)
        .where(
            Thread.id == data.thread_id,
        )
    )

    result = await execute_and_catch_db_error(session.execute(query),
                                              session)
    
    thread: Thread = result.scalar_one_or_none()

    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Thread not found')

    if not is_main_admin:
        if thread.account_id not in ID_LIST_FOR_PERMISSION:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    thread.ai_temperature = data.ai_temperature
        
    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)


@thread_router.patch("/edit_full_parse_mark_by_thread_id")
async def edit_full_parse_mark_by_thread_id(data: EditThreadFullParseSchema,
                                     admin: admin_dependency,
                                     session: session_dependency):
    admin_id, is_main_admin = admin

    query = (
        select(Thread)
        .where(
            Thread.id == data.thread_id,
        )
    )

    result = await execute_and_catch_db_error(session.execute(query),
                                              session)
    
    thread: Thread = result.scalar_one_or_none()

    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Thread not found')

    if not is_main_admin:
        if thread.account_id not in ID_LIST_FOR_PERMISSION:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    thread.full_parse = not thread.full_parse

    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)

    return {
        'thread_id': data.thread_id,
        'full_parse': thread.full_parse,
    }


@thread_router.patch("/edit_thread_notes")
async def edit_notes_by_thread_id(data: EditThreadNotesSchema,
                                        admin: admin_dependency,
                                        session: session_dependency):
    admin_id, is_main_admin = admin

    query = (
        select(Thread.account_id)
        .where(
            Thread.id == data.thread_id,
        )
    )

    result = await execute_and_catch_db_error(session.execute(query),
                                              session)
    
    account_id = result.scalar_one_or_none()

    if not account_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Thread not found')
    
    if not is_main_admin:
        if account_id not in ID_LIST_FOR_PERMISSION:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    
    update_query = (
        update(
            Thread
        )\
        .values(notes=data.notes)\
        .where(
            Thread.id == data.thread_id,
        )
    )

    result = await execute_and_catch_db_error(session.execute(update_query),
                                              session,
                                              with_rollback=True)
    
    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)



@thread_router.patch("/edit_language_by_thread_id")
async def edit_language_by_thread_id(data: EditThreadLanguageSchema,
                                     admin: admin_dependency,
                                     session: session_dependency):
    admin_id, is_main_admin = admin

    query = (
        select(Thread)
        .where(
            Thread.id == data.thread_id,
        )
    )

    result = await execute_and_catch_db_error(session.execute(query),
                                              session)
    
    thread: Thread = result.scalar_one_or_none()

    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Thread not found')

    if not is_main_admin:
        if thread.account_id not in ID_LIST_FOR_PERMISSION:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    thread.language = data.language

    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)

    return {
        'thread_id': data.thread_id,
        'language': thread.language,
    }