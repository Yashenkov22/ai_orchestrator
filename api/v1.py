from fastapi import (APIRouter)

from .routes.accounts import account_router
from .routes.threads import thread_router
from .routes.messages import message_router
from .routes.utils import utils_router

api_router = APIRouter()


api_router.include_router(account_router)
api_router.include_router(thread_router)
api_router.include_router(message_router)
api_router.include_router(utils_router)
