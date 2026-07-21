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

from config import ID_LIST_FOR_PERMISSION


message_router = APIRouter(tags=['Messages'],
                           prefix='/messages')


@message_router.get("/list")
async def new_get_messages(admin: admin_dependency,
                       session: session_dependency):
    admin_id, is_main_admin = admin

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

    if not is_main_admin:
        query = query.where(
            Message.thread.has(Thread.account_id.in_(ID_LIST_FOR_PERMISSION)),
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

        _acc_name = message.thread.account.view_name or message.thread.account.username
        message_list.append({
            "id": message.id,
            "role": message.sender,
            "content": content,
            "translated_content": translated_content,
            'account_name': _acc_name,
            'thread_name': f'{_acc_name} - {message.thread.insta_user.username}',
            "ts": (
                message.created_at.strftime("%Y-%d-%m %H:%M")
                if message.created_at else ""
            ),
            "modStatus": message.status,  # pending / approved / moderated
            'retry_send_count': message.retry_send_count,
            'attachment': attachment_list,
        })

    return message_list


@message_router.get("/{thread_id}/messages")
async def get_thread_messages(thread_id: str,
                              admin: admin_dependency,
                              session: session_dependency):
    admin_id, is_main_admin = admin

    thread_result = await session.execute(
        select(Thread).where(Thread.id == int(thread_id))
    )
    thread = thread_result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    if not is_main_admin:
        if thread.account_id not in ID_LIST_FOR_PERMISSION:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

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
            'retry_send_count': m.retry_send_count,
            "attachment": attachment_list,
        })

    return result


@message_router.get("/{message_id}")
async def new_get_messages(admin: admin_dependency,
                           session: session_dependency,
                           message_id: int):
    admin_id, is_main_admin = admin

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
    
    if not is_main_admin:
        if message.thread.account_id not in ID_LIST_FOR_PERMISSION:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

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

    _acc_name = message.thread.account.view_name or message.thread.account.username
    result = {
        "id": message.id,
        'account_id': message.thread.account_id,
        "role": message.sender,
        "content": content,
        "translated_content": translated_content,
        'account_name': _acc_name,
        'thread_name': f'{_acc_name} - {message.thread.insta_user.username}',
        "ts": (
            message.created_at.strftime("%Y-%d-%m %H:%M")
            if message.created_at else ""
        ),
        "modStatus": message.status,  # pending / approved / moderated
        'attachment': attachment_list,
        'retry_send_count': message.retry_send_count,
        'thread_id': message.thread_id,
    }

    return result


@message_router.post("/create")
async def create_new_message(data: CreateMessageSchema,
                             admin: admin_dependency,
                             arq_pool: arq_dependency,
                             session: session_dependency):
    admin_id, is_main_admin = admin

    thread = await get_thread_by_id(data.thread_id,
                                    session)
    
    account_id = thread.account_id
    
    if not is_main_admin:
        if account_id not in ID_LIST_FOR_PERMISSION:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    if not account_id:
        print('Account_id not found')
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Account_id in thread not found')
    
    if not thread or thread.account.id != data.account_id:
        print('here')
        raise HTTPException(status_code=400,
                            detail='not found thread or account by thread')
    
    _text = data.text if not data.attachment else ''
    
    insert_data = {
        'sender': 'assistant',
        'created_at': datetime.now(tz=timezone.utc),
        'updated_at': datetime.now(tz=timezone.utc),
        'thread_id': thread.id,
        'text': _text,
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

        new_attachment = Attachment(**insert_data)
        session.add(new_attachment)
        
    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)
    
    # publish redis update to websocket
    payload_attachment = None

    ws_content = new_message.text or ''

    if data.attachment:
        payload_attachment = [{
            'media_type': data.attachment['media_type'],
            'media_url': generate_valid_media_url(f"{data.attachment['media_url']}"),
        }]
        ws_content = ''
    
    payload = {
        'thread_id': new_message.thread_id,
    }
    message_payload = {
        'id': str(new_message.id),
        'account_id': account_id,
        'role': new_message.sender,
        'content': ws_content,
        'translated_content': new_message.translated_text or '',
        'ts': new_message.created_at.strftime("%Y-%d-%m %H:%M") if new_message.created_at else "",
        "modStatus": new_message.status,
        'attachment': payload_attachment,

    }
    payload['message'] = message_payload
    ws_msg_data = {
        'type': 'message created',
        'user_id': admin_id,
        'payload': payload,
    }

    await manager.send_to_user(admin_id, ws_msg_data)
    
    job = await arq_pool.enqueue_job(
            'send_message_to_thread',
            account_id,
            new_message.id,
            _queue_name='arq:messages',
        )

    return {
        'status': 'success',
    }


@message_router.delete("/delete")
async def delete_message_from_thread(message_id: int,
                                     admin: admin_dependency,
                                     arq_pool: arq_dependency,
                                     session: session_dependency):
    admin_id, is_main_admin = admin

    check_query = (
        select(Message)
        .options(
            joinedload(Message.thread).joinedload(Thread.account),
        )
        .where(
            Message.id == message_id,
        )
    )


    _message = await execute_and_catch_db_error(session.execute(check_query),
                                                     session)

    _message = _message.scalar_one_or_none()

    if not is_main_admin:
        if _message.thread.account_id not in ID_LIST_FOR_PERMISSION:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    if not _message:
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
    
    payload = {
        'thread_id': _message.thread_id,
    }
    message_payload = {
        'id': str(_message.id),
    }
    payload['message'] = message_payload

    ws_msg_data = {
        'type': 'message deleted',
        'user_id': admin_id,
        'payload': payload,
    }

    await manager.send_to_user(admin_id, ws_msg_data)

    return {
        'status': 'success'
    }