from typing import Literal

from asyncio import sleep

from arq import Retry

from fastapi import HTTPException, status


from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from db.base import Account, get_session
from db.queries import execute_and_catch_db_error, get_message_by_id, get_account_by_id, get_thread_by_id

from utils.base import get_active_profiles, try_start_profile, try_stop_profile, try_connect_to_main_instagram_page
from utils.tasks import parse_thread_playwright, playwright_send_message, test_playwright

from .base import get_redis_pool, acquire_lock, release_lock, redis_client



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

        active_profiles = await get_active_profiles()

        print('ACTIVE PROFILES', active_profiles)

        _redis_pool= get_redis_pool()

        for account in accounts:
            folder_id = account.folder_id
            profile_id = account.profile_id

            if folder_id and profile_id:
            # lock acount_id in redis
                available_lock = acquire_lock(account.id)

                if not available_lock:
                    continue

                job = await _redis_pool.enqueue_job(
                    'parse_account',
                    account.id,
                    folder_id,
                    profile_id,
                    available_lock,
                    _queue_name='arq:polling',
                )

                print('ACCOUNT PARSE JOB RUNNING...', job)


async def parse_account(cxt,
                        account_id: int,
                        folder_id: str,
                        profile_id: str,
                        lock_value: str):
    print(f'TASK PARSE ACCOUNT WITH ID {account_id} ✅')
    
    actived_profile = await try_start_profile(folder_id,
                                              profile_id)
    
    sessionmaker = cxt["sessionmaker"]
    
    print(actived_profile)
    
    profile_port = actived_profile.get('port')

    print('PORT', profile_port)

    try:
        if profile_port:

            await sleep(10)
            
            async with sessionmaker() as _session:
                await test_playwright(account_id,
                                    profile_port,
                                    _session)

            await sleep(10)

            stopped_profile = await try_stop_profile(folder_id,
                                                    profile_id)
    finally:
        release_lock(account_id, lock_value)


async def parse_thread(cxt,
                       account_id: int,
                       thread_id: int):
    print(f'TASK PARSE THREAD WITH ID {thread_id} ✅')

    sessionmaker = cxt["sessionmaker"]

    async with sessionmaker() as _session:
        account = await get_account_by_id(account_id,
                                          _session)
        thread = await get_thread_by_id(thread_id,
                                       _session)
    
    if not account or not thread:
        return
    
    available_lock = acquire_lock(account.id)

    if not available_lock:
        return

    actived_profile = await try_start_profile(account.folder_id,
                                              account.profile_id)
        
    print(actived_profile)
    
    profile_port = actived_profile.get('port')

    print('PORT', profile_port)

    try:
        if profile_port:

            await sleep(10)
            
            async with sessionmaker() as _session:
                _session: AsyncSession
                thread = await _session.merge(thread)
                await parse_thread_playwright(account_id,
                                                thread,
                                                profile_port,
                                                _session)

            await sleep(10)

            stopped_profile = await try_stop_profile(account.folder_id,
                                                    account.profile_id)
    finally:
        release_lock(account_id, available_lock)



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

    async with sessionmaker() as _session:
        _session: AsyncSession
        res = await execute_and_catch_db_error(_session.execute(query),
                                               _session)

        account = res.scalar_one_or_none()

    if not account:
            return
    
    available_lock = acquire_lock(account.id, ttl=300)

    if not available_lock:
        raise Retry(defer=30)
    
    try:
        async with sessionmaker() as _session:
            _session: AsyncSession
            msg = await get_message_by_id(message_id,
                                            _session)

            if msg:
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
                        
                        await sleep(10)

                        attachments = msg.attachments

                        if attachments:
                            _attachment = attachments[0]

                            media_type = _attachment.media_type

                        await playwright_send_message(msg,
                                                      profile_port,
                                                      _session,
                                                      media_type)      

                        await sleep(10)

                        stopped_profile = await try_stop_profile(folder_id,
                                                                profile_id)
                        
                        print('STOPPED PROFILE', stopped_profile)
    except Exception as ex:
        print('ERROR WITH TRY SEND MESSAGE', ex)
    finally:
        release_lock(account_id, available_lock)


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

            if warning_message:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                    detail=warning_message)

            if profile_port:
                is_success = await try_connect_to_main_instagram_page(profile_port)

            return is_success
        case 'stop':
            await try_stop_profile(account.folder_id,
                                   account.profile_id)
            redis_client.delete(f"lock:instagram:account:{account_id}")