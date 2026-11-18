"""Конверт WS-события и сопоставление типа события требуемому скоупу.

Конверт:
    {
        'type': 'message created',   # тип события, фронт работает по нему
        'account_id': 12,            # субъект события — по нему режутся права
        'thread_id': 345,            # опционально
        'origin_admin_id': 7,        # кто спровоцировал, если это действие админа
        'payload': {...},            # тело события, формат не менялся
    }

Получателей не вычисляет ни публикатор, ни канал: событие адресуется
объекту, а права разрешаются на доставке (см. ConnectionManager.can_see).
"""

from auth.scopes import ScopeEnum


NOTIFICATIONS_CHANNEL = 'notifications'

# Служебное событие: права админа изменились, соединениям нужно их перечитать.
ADMIN_RIGHTS_CHANGED = 'admin.rights_changed'


# Какой скоуп нужен, чтобы получить событие этого типа.
# Карта ведётся на сервере, а не передаётся в конверте: иначе публикатор
# сможет случайно недозащитить событие.
SCOPE_BY_EVENT_TYPE = {
    # сообщения
    'message created': ScopeEnum.MESSAGES_READ.value,
    'message deleted': ScopeEnum.MESSAGES_READ.value,
    'Message updated': ScopeEnum.MESSAGES_READ.value,
    'Message send count updated': ScopeEnum.MESSAGES_READ.value,
    'Thread detail updated': ScopeEnum.MESSAGES_READ.value,
    # треды
    'Thread for list updated': ScopeEnum.THREADS_READ.value,
    'Thread process block': ScopeEnum.THREADS_READ.value,
    'Thread has blocked': ScopeEnum.THREADS_READ.value,
    'thread coffee state changed': ScopeEnum.THREADS_READ.value,
}


def scope_for_event_type(event_type: str | None) -> str | None:
    """Требуемый скоуп или None, если тип события неизвестен.

    None означает «не знаю, кому это можно» — доставка в этом случае
    запрещается (fail-closed), чтобы новый тип события не утёк тем, у кого
    нет на него прав. Суперадмин получает событие всё равно, так что
    забытая строчка в карте видна сразу и не прячется.
    """
    if not event_type:
        return None

    return SCOPE_BY_EVENT_TYPE.get(event_type)
