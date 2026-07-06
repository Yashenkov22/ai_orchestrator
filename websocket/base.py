from collections import defaultdict
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        # user_id -> set[WebSocket]
        self.connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.connections[user_id].add(websocket)
        print(self.connections)

    def disconnect(self, user_id: int, websocket: WebSocket):
        if user_id in self.connections:
            self.connections[user_id].discard(websocket)

            if not self.connections[user_id]:
                del self.connections[user_id]

    async def send_to_user(self, user_id: int, message: dict):
        print('try send to listeners...')
        if user_id not in self.connections:
            print('eeror 1')
            return

        dead_connections = []

        for ws in self.connections[user_id]:
            try:
                print(' + ws update send!')
                await ws.send_json(message)
            except Exception:
                dead_connections.append(ws)

        for ws in dead_connections:
            self.disconnect(user_id, ws)


manager = ConnectionManager()