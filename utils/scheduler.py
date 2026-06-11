from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.job import Job

from config import JOB_STORE_URL



# Настройка хранилища задач
jobstores = {
    'sqlalchemy': SQLAlchemyJobStore(url=JOB_STORE_URL),
}

# Создание и настройка планировщика
scheduler = AsyncIOScheduler(jobstores=jobstores)


# scheduler_cron = IntervalTrigger(minutes=15,
#                              timezone=timezone)


# scheduler_interval = IntervalTrigger(hours=1,
#                                      timezone=timezone)