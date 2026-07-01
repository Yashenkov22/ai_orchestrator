from datetime import datetime, timezone

from fastapi import (APIRouter,
                     HTTPException,
                     status)

from sqlalchemy import select, delete
from sqlalchemy.orm import joinedload, selectinload

from db.queries import (get_message_only_by_id, get_thread_by_id,
                        execute_and_catch_db_error)

from db.base import (Message,
                     Thread,
                     Attachment)

from utils.schemas import (CreateMessageSchema)
from utils.dependencies import (admin_dependency,
                                session_dependency,
                                arq_dependency)
from utils.enums import MessageStatusEnum
from utils.base import generate_valid_media_url

from websocket.base import manager



message_router = APIRouter(tags=['Messages'],
                           prefix='/messages')


# @user_router.get("/messages")
@message_router.get("/list")
async def new_get_messages(admin: admin_dependency,
                       session: session_dependency):
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
        translated_content = message.translated_text or ""
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
            "translated_content": translated_content,
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

# @user_router.get("threads/{thread_id}/messages")
@message_router.get("/{thread_id}/messages")
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
        .order_by(Message.created_at.asc())
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
        attachment_list = []
        content = m.text or ""
        translated_content = m.translated_text or ""
        
        if _attachments:
            for _attachment in _attachments:
                _attachment = {
                    'media_type': _attachment.media_type,
                    'media_url': generate_valid_media_url(_attachment.media_url),
                }
                attachment_list.append(_attachment)
            content = ''

        result.append({
            "id": str(m.id),
            "role": m.sender,
            "content": content,
            "translated_content": translated_content,
            "ts": (
                m.created_at.strftime("%Y-%d-%m %H:%M")
                if m.created_at else ""
            ),
            "modStatus": m.status,
            "attachment": attachment_list,
        })

    return result


# @user_router.get("/messages/{message_id}")
@message_router.get("/{message_id}")
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
    translated_content = message.translated_text or ""
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
        "translated_content": translated_content,
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


# @user_router.post("/create_message")
@message_router.post("/create")
async def create_new_message(data: CreateMessageSchema,
                             admin: admin_dependency,
                             arq_pool: arq_dependency,
                             session: session_dependency):
    thread = await get_thread_by_id(data.thread_id,
                                    session)
    
    account_id = thread.account_id
    
    if not account_id:
        print('Account_id not found')
        return
    # print(data)
    
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
        'status': MessageStatusEnum.PENDING,
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

        insert_data['text'] = None

        new_attachment = Attachment(**insert_data)
        session.add(new_attachment)
        
    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)
    
    # publish redis update to websocket
    # payload_attachment = None

    # ws_content = new_message.text or ''

    # if data.attachment:
    #     payload_attachment = {
    #         'media_type': data.attachment['media_type'],
    #         'media_url': generate_valid_media_url(f"{data.attachment['media_url']}"),
    #         # 'media_type': _attachment.media_type,
    #         # 'media_url': generate_valid_media_url(_attachment.media_url),
    #     }
    #     ws_content = ''
    # payload = {
    #     'id': str(new_message.id),
    #     'role': new_message.sender,
    #     'content': ws_content,
    #     'translated_content': new_message.translated_text or '',
    #     'ts': new_message.created_at.strftime("%Y-%d-%m %H:%M") if new_message.created_at else "",
    #     "modStatus": new_message.status,
    #     'attachment': payload_attachment,

    # }
    # ws_msg_data = {
    #     'type': 'message created',
    #     'user_id': admin,
    #     'payload': payload,
    # }

    # await manager.send_to_user(admin, ws_msg_data)
    
    # if success:
    job = await arq_pool.enqueue_job(
            'send_message_to_thread',
            account_id,
            new_message.id,
            _queue_name='arq:messages',
        )
    
    msg = await get_message_only_by_id(new_message.id,
                                       session)
    
    msg.status = MessageStatusEnum.MODERATED

    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)
        # return {"status": "queued", "job_id": job.job_id}

    return {
        'status': 'success',
    }


# @user_router.delete("/delete_message")
@message_router.delete("/delete")
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