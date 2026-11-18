import json
import asyncio

from redis.asyncio import Redis

from auth.utils import load_admin_rights

from .base import manager
from .events import ADMIN_RIGHTS_CHANGED, NOTIFICATIONS_CHANNEL

from config import REDIS_HOST, REDIS_PASSWORD, REDIS_PORT

redis = Redis(
    host=REDIS_HOST,
    password=REDIS_PASSWORD,
    port=REDIS_PORT,
    decode_responses=True,
)


async def _apply_rights_changed(event: dict):
    """Перечитывает права админа для его открытых соединений."""
    admin_id = (event.get('payload') or {}).get('admin_id')

    if not admin_id:
        return

    rights = await load_admin_rights(admin_id)

    if rights is None:
        # админа больше нет — закрываем его соединения
        closed = await manager.close_admin_connections(admin_id)
        print(f'[ws] admin {admin_id} не найден, закрыто соединений: {closed}')
        return

    updated = manager.update_rights(admin_id,
                                    is_superadmin=rights.is_superadmin,
                                    scopes=rights.scopes,
                                    account_ids=rights.account_ids)
    print(f'[ws] права admin {admin_id} обновлены на {updated} соединении(ях)')


async def redis_listener():
    pubsub = redis.pubsub()

    await pubsub.subscribe(NOTIFICATIONS_CHANNEL)

    try:
        async for message in pubsub.listen():

            if message["type"] != "message":
                continue

            try:
                event = json.loads(message["data"])
            except (TypeError, ValueError) as ex:
                print(f'[ws] битое событие в канале {NOTIFICATIONS_CHANNEL}: {ex}')
                continue

            if not isinstance(event, dict):
                continue

            if event.get('type') == ADMIN_RIGHTS_CHANGED:
                await _apply_rights_changed(event)
                continue

            await manager.broadcast(event)

    except asyncio.CancelledError:
        pass

    finally:
        await pubsub.unsubscribe(NOTIFICATIONS_CHANNEL)
        await pubsub.close()



async def publish_event(redis,
                        *,
                        type: str,
                        payload: dict,
                        account_id: int = None,
                        thread_id: int = None,
                        origin_admin_id: int = None):
    """Публикует событие в канал уведомлений.

    Получатель не указывается: событие адресуется субъекту (аккаунту),
    а права разрешаются на доставке, в ConnectionManager.can_see.
    """
    if isinstance(payload, dict):
        if account_id is None:
            account_id = payload.get('account_id')
        if thread_id is None:
            thread_id = payload.get('thread_id')

    event = {
        'type': type,
        'account_id': account_id,
        'thread_id': thread_id,
        'origin_admin_id': origin_admin_id,
        'payload': payload,
    }

    await redis.publish(NOTIFICATIONS_CHANNEL,
                        json.dumps(event, default=str))
    print(f' + PUBLISH EVENT {type!r} (account_id={account_id}) TO REDIS SUCCESSFULLY')


async def publish_admin_rights_changed(redis,
                                       admin_id: int):
    """Сообщает открытым соединениям админа, что права поменялись.

    Вызывать из CRUD прав (этап 5), иначе соединение доживёт со старыми
    правами до переподключения.
    """
    await redis.publish(NOTIFICATIONS_CHANNEL,
                        json.dumps({
                            'type': ADMIN_RIGHTS_CHANGED,
                            'account_id': None,
                            'thread_id': None,
                            'origin_admin_id': None,
                            'payload': {'admin_id': admin_id},
                        }))
