"""Каталог прав админов и производных от них фич админ-панели.

Модуль намеренно не импортирует ничего из проекта: его тянут и auth,
и websocket, поэтому любая зависимость тут рискует создать цикл.
"""

from enum import Enum


class ScopeEnum(str, Enum):
    ACCOUNTS_READ = 'accounts:read'
    ACCOUNTS_WRITE = 'accounts:write'
    THREADS_READ = 'threads:read'
    THREADS_WRITE = 'threads:write'
    MESSAGES_READ = 'messages:read'
    MESSAGES_WRITE = 'messages:write'
    COMMENTS_READ = 'comments:read'
    COMMENTS_WRITE = 'comments:write'
    ADMINS_WRITE = 'admins:write'


ALL_SCOPES = tuple(scope.value for scope in ScopeEnum)


# Набор, который получают уже существующие админы при миграции: ровно то,
# что они и так могли делать до введения прав. Без comments:* (новый раздел
# выдаётся точечно) и без admins:write (он только у суперадмина).
LEGACY_ADMIN_SCOPES = (
    ScopeEnum.ACCOUNTS_READ.value,
    ScopeEnum.THREADS_READ.value,
    ScopeEnum.THREADS_WRITE.value,
    ScopeEnum.MESSAGES_READ.value,
    ScopeEnum.MESSAGES_WRITE.value,
)


# Какие разделы панели рисовать. Фронт читает features из /auth/me и не
# разбирает скоупы сам.
FEATURE_BY_SCOPE = {
    ScopeEnum.ACCOUNTS_READ.value: 'accounts',
    ScopeEnum.THREADS_READ.value: 'threads',
    ScopeEnum.MESSAGES_READ.value: 'threads',
    ScopeEnum.COMMENTS_READ.value: 'comments',
    ScopeEnum.ADMINS_WRITE.value: 'admins',
}

ALL_FEATURES = tuple(sorted(set(FEATURE_BY_SCOPE.values())))


def features_for_scopes(scopes, is_superadmin: bool = False) -> list[str]:
    """Список разделов панели для набора скоупов. Суперадмин видит всё."""
    if is_superadmin:
        return list(ALL_FEATURES)

    return sorted({
        FEATURE_BY_SCOPE[scope]
        for scope in (scopes or ())
        if scope in FEATURE_BY_SCOPE
    })
