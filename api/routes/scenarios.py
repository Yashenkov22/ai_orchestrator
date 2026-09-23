from datetime import datetime, timezone

from fastapi import (APIRouter,
                     HTTPException,
                     status)

from sqlalchemy import func, select, exists, and_
from sqlalchemy.orm import  aliased

from db.queries import (execute_and_catch_db_error,
                        get_account_by_username)

from db.base import (Thread,
                     Account)

from utils.schemas import (PatchAccountSchema,
                           NewAccountSchema, PatchHiddenMarkAccountSchema,
                           PatchInformationAccountSchema,
                           PatchPhotoAccountSchema, PatchViewNameAccountSchema,
                           UpdateProfileDataSchema,
                           CreateAccountSchema)
from utils.dependencies import (admin_dependency,
                                session_dependency)

from utils.encrypt import encrypt_password
from utils.base import (generate_valid_media_url)

from config import ID_LIST_FOR_PERMISSION


scenario_router = APIRouter(tags=['Scenarios'],
                           prefix='/scenario')


