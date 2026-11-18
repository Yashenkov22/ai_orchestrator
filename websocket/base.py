from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from fastapi import WebSocket

from websocket.events import scope_for_event_type


@dataclass(eq=False)
class Connection:
    """Одно WS-соединение вместе с правами админа, который его открыл.

    Права снимаются один раз при подключении, а не на каждое событие.
    Если права поменяли — приходит служебное admin.rights_changed, и
    менеджер обновляет их через update_rights.
    """

    ws: WebSocket
    admin_id: int
    is_superadmin: bool = False
    scopes: frozenset = frozenset()
    # None = ограничений по аккаунтам нет (до этапа 5 так у всех)
    account_ids: Optional[frozenset] = None


class ConnectionManager:
    def __init__(self):
        # admin_id -> set[Connection]
        self.connections: dict[int, set[Connection]] = defaultdict(set)

    async def connect(self, connection: Connection) -> Connection:
        await connection.ws.accept()
        self.connections[connection.admin_id].add(connection)
        print(f'[ws] admin {connection.admin_id} подключился, '
              f'соединений всего: {self.total_connections()}')
        return connection

    def disconnect(self, connection: Connection) -> None:
        admin_connections = self.connections.get(connection.admin_id)

        if not admin_connections:
            return

        admin_connections.discard(connection)

        if not admin_connections:
            self.connections.pop(connection.admin_id, None)

    def total_connections(self) -> int:
        return sum(len(conns) for conns in self.connections.values())

    def _snapshot(self) -> list[Connection]:
        # Снимок: пока идёт рассылка, другой таск может подключиться
        # или отвалиться, а менять set во время итерации нельзя.
        return [
            connection
            for connections in list(self.connections.values())
            for connection in list(connections)
        ]

    def can_see(self, connection: Connection, event: dict) -> bool:
        """Можно ли этому соединению отдать это событие."""
        if connection.is_superadmin:
            return True

        required_scope = scope_for_event_type(event.get('type'))

        if required_scope is None:
            # Неизвестный тип — не рассылаем (fail-closed), чтобы новое
            # событие не утекло тем, у кого на него нет прав.
            print(f'[ws] тип события {event.get("type")!r} не описан в '
                  f'SCOPE_BY_EVENT_TYPE — отдаю только суперадминам')
            return False

        if required_scope not in connection.scopes:
            return False

        if connection.account_ids is None:
            return True

        account_id = event.get('account_id')

        if account_id is None:
            # Событие не привязано к аккаунту — ограничивать нечем.
            return True

        try:
            return int(account_id) in connection.account_ids
        except (TypeError, ValueError):
            return False

    async def broadcast(self, event: dict) -> int:
        """Отдаёт событие всем, кому оно разрешено. Возвращает число отправок."""
        sent = 0
        dead: list[Connection] = []

        for connection in self._snapshot():
            if not self.can_see(connection, event):
                continue

            try:
                await connection.ws.send_json(event)
                sent += 1
            except Exception:
                dead.append(connection)

        for connection in dead:
            self.disconnect(connection)

        print(f'[ws] событие {event.get("type")!r} ушло {sent} соединению(ям)')
        return sent

    def update_rights(self,
                      admin_id: int,
                      *,
                      is_superadmin: bool,
                      scopes: frozenset,
                      account_ids: Optional[frozenset] = None) -> int:
        updated = 0

        for connection in list(self.connections.get(admin_id, ())):
            connection.is_superadmin = is_superadmin
            connection.scopes = scopes
            connection.account_ids = account_ids
            updated += 1

        return updated

    async def close_admin_connections(self,
                                      admin_id: int,
                                      code: int = 1012) -> int:
        """Закрывает соединения админа — фронт переподключится сам."""
        closed = 0

        for connection in list(self.connections.get(admin_id, ())):
            try:
                await connection.ws.close(code=code)
            except Exception:
                pass

            self.disconnect(connection)
            closed += 1

        return closed


manager = ConnectionManager()
