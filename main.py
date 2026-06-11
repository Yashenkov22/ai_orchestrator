from fastapi import (FastAPI,
                     WebSocket,
                     WebSocketDisconnect,
                     status)

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from contextlib import asynccontextmanager

from db.base import init_models

from api.base import main_router

from utils.instagram_client import cl

from utils.scheduler import scheduler

from background.base import get_redis_background_pool

from instagrapi.exceptions import TwoFactorRequired



@asynccontextmanager
async def lifespan(app: FastAPI):
    # Код, который будет выполнен при старте приложения
    print("Приложение запускается...")
    scheduler.start()
    app.state.arq_pool = await get_redis_background_pool()
    # Инициализация БД
    # await init_models()
    yield  # Это место, где приложение будет работать

    await app.state.arq_pool.close()

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
async def websocket_endpoint(websocket: WebSocket): # jwt_dependency:
    await websocket.accept()
    print("WebSocket клиент подключился✅")

    # получаю все непрочитанные(неотправленные) сообщения
    # если есть отправляю сообщения и отчищаю хранилище

    try:
        while True:
            data = await websocket.receive_text()
            print(f"Получено: {data}")
            await websocket.send_text(f"Echo: {data}")
            #.          !  
            # сохраняю в БД
            # формирую промпт для получения ответа (мб в фоновой задаче)
            # нужно вернуться сюда же и отправить ответ через await websocket.send_text()
    except WebSocketDisconnect:
        print("WebSocket клиент отключился❌")