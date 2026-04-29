from fastapi import APIRouter

from .v1 import api_router as v1_router
from auth.endpoints import auth_router

from config import API_PREFIX


main_router = APIRouter(prefix=API_PREFIX)

main_router.include_router(v1_router)
main_router.include_router(auth_router)