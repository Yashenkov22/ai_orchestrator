from datetime import datetime, timedelta
from typing import Literal

from asyncio import sleep

from arq import Retry

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.job import Job

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy import insert, select, and_, update, func, desc
from sqlalchemy.orm import selectinload

from db.base import Account, get_session
from db.queries import execute_and_catch_db_error, get_message_by_id

from utils.base import get_active_profiles, try_start_profile, try_stop_profile
from utils.tasks import playwright_send_message, test_playwright

from .base import get_redis_pool, acquire_lock, release_lock

from config import JOB_STORE_URL



async def start_polling_for_accounts(cxt):
        print('TASK FROM ARQ ✅')
        query = (
              select(Account)\
              .where(
                    Account.is_active == True,
                    Account.username == 'yashenkov.q',
                    )
                )
        
        sessionmaker= cxt['sessionmaker']
        
        async with sessionmaker() as _session:
            _session: AsyncSession
            result = await execute_and_catch_db_error(_session.execute(query),
                                                      _session)
            accounts: list[Account] = result.scalars().all()

        # http://127.0.0.1:3030/list
        active_profiles = await get_active_profiles()

        print('ACTIVE PROFILES', active_profiles)

        _redis_pool= get_redis_pool()

        for account in accounts:
            folder_id = account.folder_id
            profile_id = account.profile_id

            if folder_id and profile_id:
            # lock acount_id in redis
                available_lock = acquire_lock(account.id, ttl=180)

                if not available_lock:
                    continue

                job = await _redis_pool.enqueue_job(
                    'parse_account',   # имя = __name__ функции, зарегистрированной в воркере
                    account.id,
                    folder_id,
                    profile_id,
                    available_lock,
                    _queue_name='arq:polling',
                )

                print('ACCOUNT PARSE JOB RUNNING...', job)
                # return {"status": "queued", "job_id": job.job_id}
                    #try start profile
        #             actived_profile = await try_start_profile(folder_id,
        #                                                       profile_id)
                    
        #             print(actived_profile)
                    
        #             profile_port = actived_profile.get('port')

        #             print('PORT', profile_port)

        #             if profile_port:
        #                 await sleep(10)

        #                 await test_playwright(account.id,
        #                                       profile_port,
        #                                       sessionmaker)
        #                 # print('RUNNING PROFILE', actived_profile)

        #                 await sleep(10)

        #                 stopped_profile = await try_stop_profile(folder_id,
        #                                                         profile_id)
        #                 print('STOPPED PROFILE', stopped_profile)

        # await sleep(10)

        # active_profiles = await get_active_profiles()

        # print('AFTER ACTIVE PROFILES', active_profiles)


async def parse_account(cxt,
                        account_id: int,
                        folder_id: str,
                        profile_id: str,
                        lock_value: str):
    actived_profile = await try_start_profile(folder_id,
                                              profile_id)
    
    sessionmaker = cxt["sessionmaker"]
    
    print(actived_profile)
    
    profile_port = actived_profile.get('port')

    print('PORT', profile_port)

    if profile_port:

        await sleep(10)
        
        try:
            async with sessionmaker() as _session:
                await test_playwright(account_id,
                                    profile_port,
                                    _session)
            # print('RUNNING PROFILE', actived_profile)

            await sleep(10)

            stopped_profile = await try_stop_profile(folder_id,
                                                    profile_id)
        finally:
            release_lock(account_id, lock_value)
            # print('STOPPED PROFILE', stopped_profile)



async def send_message_to_thread(cxt,
                                 account_id: int,
                                 message_id: int):
    print('TASK TRY SEND MESSAGE ✅')
    query = (
        select(Account)\
        .where(
            Account.is_active == True,
            Account.id == account_id,
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
    
    available_lock = acquire_lock(account.id, ttl=180)

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

                        # async with sessionmaker() as _session:
                        #     _session: AsyncSession
                        # await _session.merge(msg)
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