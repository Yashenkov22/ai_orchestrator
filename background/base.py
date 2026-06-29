import redis
import uuid

from arq import create_pool
from arq.connections import RedisSettings

from config import REDIS_HOST, REDIS_PASSWORD, REDIS_PORT


redis_client = redis.Redis(host=REDIS_HOST,
                           password=REDIS_PASSWORD,
                           port=REDIS_PORT)

redis_settings = RedisSettings(
    host=REDIS_HOST,
    password=REDIS_PASSWORD,
    port=REDIS_PORT,
    )

_redis_pool = None


async def get_redis_background_pool():
    global _redis_pool
    
    if _redis_pool is None:
        # print(22)
        _redis_pool = await create_pool(settings_=redis_settings) 
        # print(_redis_pool)
    
    return _redis_pool



def get_redis_pool():
    if _redis_pool is None:
        raise RuntimeError("Redis pool not initialized. Call init_redis_pool() first.")
    return _redis_pool



async def background_task_wrapper(func_name, *args, _queue_name):

    _redis_pool = get_redis_pool()

    _args_str = '.'.join([f'{arg}' for arg in args])

    _job_id = f'{func_name}_{_args_str}'

    await _redis_pool.enqueue_job(func_name,
                                  *args,
                                  _queue_name=_queue_name,
                                  _job_id=_job_id)
    

lock_key = "lock:instagram:account:{account_id}:thread:{thread_id}"

def acquire_lock(account_id,
                 thread_id,
                 ttl=6000):
    # lock_key = f"lock:instagram:account:{account_id}:thread:{thread_id}"
    _lock_key = lock_key.format(**{'account_id': account_id,
                                   'thread_id': thread_id})

    lock_value = str(uuid.uuid4())

    acquired = redis_client.set(_lock_key, lock_value, nx=True, ex=ttl)
    return lock_value if acquired else None


def release_lock(account_id, thread_id, lock_value):
    _lock_key = lock_key.format(**{'account_id': account_id,
                                   'thread_id': thread_id})

    lua = """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        return redis.call("del", KEYS[1])
    else
        return 0
    end
    """
    redis_client.eval(lua, 1, _lock_key, lock_value)


def acquire_task_lock(key,
                      ttl=6000):
    # lock_key = f"lock:instagram:account:{account_id}:thread:{thread_id}"
    # _lock_key = lock_key.format(**{'account_id': account_id,
    #                                'thread_id': thread_id})

    lock_value = str(uuid.uuid4())

    acquired = redis_client.set(key, lock_value, nx=True, ex=ttl)
    return lock_value if acquired else None


def release_task_lock(key, lock_value):
    # _lock_key = lock_key.format(**{'account_id': account_id,
    #                                'thread_id': thread_id})

    lua = """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        return redis.call("del", KEYS[1])
    else
        return 0
    end
    """
    redis_client.eval(lua, 1, key, lock_value)