from typing import Literal

from asyncio import sleep

from arq import Retry


from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from db.base import Account
from db.queries import (execute_and_catch_db_error,
                        get_message_by_id,
                        get_account_by_id,
                        get_thread_by_id)

from utils.base import (try_get_profile_port,
                        try_start_profile,
                        try_stop_profile,
                        try_connect_to_main_instagram_page)
from utils.tasks import (parse_thread_playwright,
                         playwright_send_message,
                         test_playwright)
from utils.enums import MessageStatusEnum

from websocket.redis_listener import publish_event

from .base import (acquire_task_lock,
                   get_redis_pool,
                   acquire_lock,
                   release_lock,
                   release_task_lock)



async def start_polling_for_accounts(cxt):
        print('TASK FROM ARQ ✅')
        query = (
              select(Account)\
              .where(
                  and_(
                    Account.folder_id.isnot(None),
                    Account.profile_id.isnot(None),
                    Account.is_active == True,
                  )
                    )
                )
        
        sessionmaker= cxt['sessionmaker']
        
        async with sessionmaker() as _session:
            _session: AsyncSession
            result = await execute_and_catch_db_error(_session.execute(query),
                                                      _session)
            accounts: list[Account] = result.scalars().all()

        _redis_pool= get_redis_pool()

        for account in accounts:
            folder_id = account.folder_id
            profile_id = account.profile_id

            if folder_id and profile_id:

                _key = f'lock:polling_account:{account.id}'
                task_lock = acquire_task_lock(_key)

                if not task_lock:
                    continue

                job = await _redis_pool.enqueue_job(
                    'parse_account',
                    account.id,
                    folder_id,
                    profile_id,
                    task_lock,
                    _job_id=_key,
                    _queue_name='arq:polling',
                )

                print('ACCOUNT PARSE JOB RUNNING...', job)


async def parse_account(cxt,
                        account_id: int,
                        folder_id: str,
                        profile_id: str,
                        task_lock: str):
    try:
        print(f'TASK PARSE ACCOUNT WITH ID {account_id} ✅')
        
        sessionmaker = cxt["sessionmaker"]
        redis_pool = cxt['redis_pool']
        
        actived_profile = await try_start_profile(folder_id,
                                                  profile_id)
        
        async with sessionmaker() as _session:
            account = await get_account_by_id(account_id,
                                              _session)
        
        if not account:
            print(f'not account with {account_id}')
            return
        
        print(actived_profile)
        
        profile_port = actived_profile.get('port')

        print('PORT', profile_port)

        if not profile_port:
            profile_port = await try_get_profile_port(folder_id,
                                                      profile_id)

        await sleep(5)
        
        async with sessionmaker() as _session:
            await test_playwright(account,
                                profile_port,
                                folder_id,
                                profile_id,
                                redis_pool,
                                _session)
    except Exception as ex:
        print(ex)
    finally:
        _key = f'lock:polling_account:{account_id}'
        release_task_lock(_key,
                          task_lock)


async def parse_thread(cxt,
                       account_id: int,
                       thread_id: int):
    print(f'TASK PARSE THREAD WITH ID {thread_id} ✅')

    sessionmaker = cxt["sessionmaker"]
    redis = cxt['redis_pool']

    async with sessionmaker() as _session:
        account = await get_account_by_id(account_id,
                                          _session)
        thread = await get_thread_by_id(thread_id,
                                       _session)
    
    if not account or not thread:
        return
    
    available_lock = acquire_lock(account.id,
                                  thread_id)

    if not available_lock:
        raise Retry(defer=15)

    actived_profile = await try_start_profile(account.folder_id,
                                              account.profile_id)

    print(actived_profile)
    
    profile_port = actived_profile.get('port')

    print('PORT', profile_port)

    try:
        if profile_port:

            await sleep(5)
            
            async with sessionmaker() as _session:
                _session: AsyncSession
                thread = await _session.merge(thread)
                await parse_thread_playwright(account,
                                              thread,
                                              profile_port,
                                              _session,
                                              redis)
    finally:
        release_lock(account_id, thread_id, available_lock)



async def send_message_to_thread(cxt,
                                 account_id: int,
                                 message_id: int):
    print('TASK TRY SEND MESSAGE ✅')
    query = (
        select(Account)\
        .where(
            and_(
                Account.folder_id.isnot(None),
                    Account.profile_id.isnot(None),
                Account.is_active == True,
                Account.id == account_id,
            )
        )
    )

    sessionmaker= cxt['sessionmaker']
    redis = cxt['redis_pool']

    async with sessionmaker() as _session:
        _session: AsyncSession
        res = await execute_and_catch_db_error(_session.execute(query),
                                            _session)

        account = res.scalar_one_or_none()
        message = await get_message_by_id(message_id,
                                          _session)

    if not account or not message:
        print('Account or Message Not found')
        print(' ### account', account_id, account)
        print(' ### message', message_id, message)
        return
    
    available_lock = acquire_lock(account.id,
                                  message.thread_id)

    if not available_lock:
        print('error 2')
        async with sessionmaker() as _session:
            _session: AsyncSession
            _message = await _session.merge(message)
            _message.retry_send_count += 1
            await execute_and_catch_db_error(_session.commit(),
                                             _session,
                                             with_rollback=True)
        
        # ws событие об изменении message
        payload = {
            'thread_id': message.thread_id,
        }
        msg_payload = {
            'id': str(message.id),
            "retry_send_count": _message.retry_send_count,
        }

        payload['message'] = msg_payload

        await publish_event(redis,
                            type='Message send count updated',
                            payload=payload)

        raise Retry(defer=15)
    
    try:
        _key = f'lock:send_message:acc:{account.id}:msg:{message_id}'
        task_lock = acquire_task_lock(_key)

        if not task_lock:
            return

        if message:
            media_type = None
            folder_id = account.folder_id
            profile_id = account.profile_id

            if folder_id and profile_id:
                #try start profile
                actived_profile = await try_start_profile(folder_id,
                                                        profile_id)
                
                print(actived_profile)
                
                profile_port = actived_profile.get('port')

                print('PORT', profile_port)

                if profile_port:

                    # update message status
                    async with sessionmaker() as _session:
                        _session: AsyncSession
                        message.status = MessageStatusEnum.MODERATED
                        await _session.merge(message)
                        await execute_and_catch_db_error(_session.commit(),
                                                        _session,
                                                        with_rollback=True)
                    payload = {
                        'thread_id': message.thread_id,
                    }
                    message_payload = {
                        'id': str(message.id),
                        "modStatus": message.status,
                    }
                    payload['message'] = message_payload
 
                    await publish_event(redis,
                                        type='Message updated',
                                        payload=payload)
                    
                    await sleep(5)

                    attachments = message.attachments

                    if attachments:
                        _attachment = attachments[0]

                        media_type = _attachment.media_type
                    
                    async with sessionmaker() as _session:
                        _session: AsyncSession
                        await _session.merge(message)
                        await playwright_send_message(message,
                                                    profile_port,
                                                    folder_id,
                                                    profile_id,
                                                    _session,
                                                    redis,
                                                    media_type)  
        else:
            print('error 3')

    except Retry as ex:
        print(f'CATCH RETRY FOR ACC_ID {account_id} MSG_ID {message_id}')

        async with sessionmaker() as _session:
            _session: AsyncSession
            _message = await _session.merge(message)
            _message.retry_send_count += 1
            await execute_and_catch_db_error(_session.commit(),
                                             _session,
                                             with_rollback=True)
        
        # ws событие об изменении message
        payload = {
            'thread_id': message.thread_id,
        }
        msg_payload = {
            'id': str(message.id),
            "retry_send_count": _message.retry_send_count,
        }

        payload['message'] = msg_payload

        await publish_event(redis,
                            type='Message send count updated',
                            payload=payload)
        raise

    except Exception as ex:
        print('ERROR WITH TRY SEND MESSAGE', ex)
    finally:
        try:
            release_lock(account_id, message.thread_id, available_lock)
            release_task_lock(_key, task_lock)
        except Exception:
            pass


async def try_start_stop_vision_profile_by_account_id(cxt,
                                                      account_id: int,
                                                      marker: Literal['start', 'stop']):
    sessionmaker= cxt['sessionmaker']

    async with sessionmaker() as _session:
        _session: AsyncSession
        account = await get_account_by_id(account_id,
                                        _session)
    
    is_success = None
    
    if not account or\
          not (account.folder_id and account.profile_id):
        raise

    match marker:
        case 'start':
            actived_profile = await try_start_profile(account.folder_id,
                                                    account.profile_id)

            profile_port = actived_profile.get('port')

            warning_message = actived_profile.get('message')

            print('PORT', profile_port)

            if profile_port:
                is_success = await try_connect_to_main_instagram_page(profile_port)

            return is_success
        case 'stop':
            await try_stop_profile(account.folder_id,
                                   account.profile_id)
