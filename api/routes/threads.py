import json

from fastapi import (APIRouter,
                     HTTPException,
                     status)

from sqlalchemy import select, update, and_
from sqlalchemy.orm import joinedload

from db.queries import (execute_and_catch_db_error)

from db.base import (Message,
                     Thread)

from utils.schemas import (DetailThreadSchema,
                           EditThreadColorLevelSchema,
                           ThreadSchema)
from utils.dependencies import (admin_dependency,
                                session_dependency)
from utils.base import (generate_valid_insta_url,
                        generate_valid_media_url)

from config import ADMIN_URL



thread_router = APIRouter(tags=['Treads'],
                          prefix='/threads')

# @thread_router.get("/threads")
@thread_router.get("/list")
async def get_threads(admin: admin_dependency,
                      session: session_dependency):
    result = await session.execute(
        select(Thread)
        .options(
            joinedload(Thread.account),
            joinedload(Thread.insta_user)
        )\
        .order_by(
            and_(
                Thread.is_unread.desc(),
                Thread.timestamp_last_seen_message.desc()
            )
        )
    )
    threads = result.scalars().all()
    thread_list = []

    for t in threads:
        thread_list.append({
            "id": t.id,
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


# @thread_router.get("/accounts/{account_id}/threads",
#                  response_model=list[ThreadSchema])
@thread_router.get("/{account_id}/threads",
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
        )\
        .order_by(
            and_(
                Thread.is_unread.desc(),
                Thread.timestamp_last_seen_message.desc()
            )
        )
    )
    threads = result.scalars().all()
    thread_list = []

    for t in threads:
        thread_list.append(ThreadSchema(**{
            "id": t.id,
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


# @thread_router.get("/threads/{thread_id}",
#                  response_model=DetailThreadSchema)
@thread_router.get("/{thread_id}",
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
        .order_by(Message.created_at.asc())
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

    thread_info['messages'] = message_list

    return thread_info


# @thread_router.patch("/threads/edit_color_level")
@thread_router.patch("/edit_color_level")
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