from celery import Celery

from config import REDIS_HOST, REDIS_PASSWORD, REDIS_URL

celery_app = Celery(
    "client",
    broker=REDIS_URL
)


def run_task(task_name: str,
             data: dict):
    w = celery_app.send_task(
        name=task_name,
        queue='queue_1',
        kwargs=data,
    )
    print('SEND TASK TO QUEUE!!!',w)
    return {"status": "ok"}