import asyncio

from fastapi import (FastAPI,
                     WebSocket,
                     WebSocketDisconnect,
                     status)

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from contextlib import asynccontextmanager

from auth.utils import get_current_user_for_websocket
from db.base import init_models

from api.base import main_router

# from auth.utils import get_user_or_raise_exception

from utils.scheduler import scheduler

from background.base import get_redis_background_pool

from websocket.base import manager
from websocket.redis_listener import redis_listener


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Код, который будет выполнен при старте приложения
    print("Приложение запускается...")
    scheduler.start()
    app.state.arq_pool = await get_redis_background_pool()
    # asyncio.create_task(redis_listener())
    app.state.redis_listener_task = asyncio.create_task(redis_listener())
    # Инициализация БД
    # await init_models()
    yield  # Это место, где приложение будет работать

    await app.state.arq_pool.close()

    app.state.redis_listener_task.cancel()

    try:
        await app.state.redis_listener_task
    except asyncio.CancelledError:
        pass

    try:
        scheduler.shutdown()
    except Exception as ex:
        print(ex)
    #
    print("Приложение останавливается...")


#Initialize web server
app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # allow_origins=["*"],
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(main_router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "detail": exc.errors(),  # можно изменить формат
        },
    )


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    token = websocket.query_params.get("token")

    if token is None:
        await websocket.close(code=1008)
        return

    try:
        user_id = await get_current_user_for_websocket(token)
        print('user id ->', user_id)
    except Exception:
        await websocket.close(code=1008)
        return

    await manager.connect(user_id, websocket)
    print('New ws connection ~')
    try:
        while True:
            message = await websocket.receive_text()

            await websocket.send_text(f"Received: {message}")

    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)