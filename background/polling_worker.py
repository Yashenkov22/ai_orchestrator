from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from background.base import (redis_settings,
                             _redis_pool,
                             get_redis_background_pool)

from db.base import session

from .tasks import (start_polling_for_accounts,
                    parse_account,
                    parse_thread)

from config import REDIS_HOST, REDIS_PASSWORD, JOB_STORE_URL


async def startup(ctx):
    global _redis_pool
    jobstores = {
        'sqlalchemy': SQLAlchemyJobStore(url=JOB_STORE_URL),
    }

    # Создание и настройка планировщика
    scheduler = AsyncIOScheduler(jobstores=jobstores)

    if not _redis_pool:
        _redis_pool = await get_redis_background_pool()

    scheduler.start()
    ctx['scheduler'] = scheduler
    ctx['sessionmaker'] = session
    ctx['redis_pool'] = _redis_pool
    
    print("Worker for account polling is starting up...")

async def shutdown(ctx):
    print("Worker for account polling is shutting down...")

class WorkerSettings:
    functions = [
        start_polling_for_accounts,
        parse_account,
        # parse_thread,
    ]
    on_startup = startup
    on_shutdown = shutdown
    queue_name = "arq:polling"
    redis_settings = redis_settings
    max_jobs = 10
    keep_result = 0
    job_timeout = 900
    job_defaults = {
        'max_tries': 1, 
    }


