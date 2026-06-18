from fastapi import (FastAPI,
                     WebSocket,
                     WebSocketDisconnect,
                     status)

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from contextlib import asynccontextmanager


from api import translation_router




@asynccontextmanager
async def lifespan(app: FastAPI):
    # Код, который будет выполнен при старте приложения
    print("Приложение запускается...")
    # scheduler.start()
    # app.state.arq_pool = await get_redis_background_pool()
    # Инициализация БД
    # await init_models()
    yield  # Это место, где приложение будет работать

    # await app.state.arq_pool.close()

    # try:
    #     scheduler.shutdown()
    # except Exception as ex:
    #     print(ex)
    #
    print("Приложение останавливается...")


#Initialize web server
app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(translation_router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "detail": exc.errors(),  # можно изменить формат
        },
    )