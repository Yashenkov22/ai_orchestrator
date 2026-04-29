from datetime import datetime

from fastapi import (APIRouter,
                     HTTPException,
                     status)

from db.queries import (get_all_users,
                        update_and_return_user,
                        delete_user_and_return_result)

from utils.schemas import (DetailUserSchema,
                           UpdateUserSchema,
                           NotificationsSchema)
from utils.dependencies import (user_dependency,
                                session_dependency,
                                current_user_dependency)
from utils.endpoints import add_notifications_to_user

from .routes.users import user_router
from .routes.chats import chat_router


api_router = APIRouter()

api_router.include_router(user_router)
api_router.include_router(chat_router)


# @api_router.get("/user/me",
#                 response_model=DetailUserSchema)
# async def return_authenticated_user(user_id: user_dependency,
#                                     session: session_dependency):
#     user = await get_user_by_id(user_id=user_id,
#                                 _session=session)
#     if not user:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#                             detail=f'User not found by given "id" {user_id}')
    
#     add_notifications_to_user(user)

#     return user


# @api_router.get("/user/{user_id}",
#                 response_model=DetailUserSchema)
# async def return_user_by_id(user_id: int,
#                             session: session_dependency):
#     user = await get_user_by_id(user_id=user_id,
#                                 _session=session)
#     if not user:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#                             detail=f'User not found by given "id" {user_id}')

#     add_notifications_to_user(user)

#     return user


# @api_router.get("/users",
#                 response_model=list[DetailUserSchema])
# async def return_all_users(session: session_dependency,
#                            user_id: current_user_dependency):
#     users = await get_all_users(session,
#                                 user_id)
    
#     [add_notifications_to_user(user) for user in users]

#     return users


# @api_router.patch("/user",
#                 response_model=DetailUserSchema)
# async def update_user_by_id(user_id: user_dependency,
#                             session: session_dependency,
#                             update_data: UpdateUserSchema):
#     user = await get_user_by_id(user_id=user_id,
#                                 _session=session)
#     if not user:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#                             detail=f'User not found by given "id" {user_id}')

#     _update_data = update_data.model_dump(exclude_none=True)

#     updated_user = await update_and_return_user(user,
#                                                 _update_data,
#                                                 session)
#     add_notifications_to_user(user)

#     return updated_user


# @api_router.delete("/user")
# async def delete_user_by_id(user_id: user_dependency,
#                             session: session_dependency):
#     user = await get_user_by_id(user_id=user_id,
#                                 _session=session)
#     if user:
#         has_deleted = await delete_user_and_return_result(user,
#                                                           session)
#     else:
#         has_deleted = False

#     return {
#         'success': has_deleted,
#     }
#     # raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#     #                     detail=f'User not found by given "id" {user_id}')


# @api_router.patch("/user/notifications",
#                 response_model=DetailUserSchema)
# async def update_user_notifications(user_id: user_dependency,
#                                     session: session_dependency,
#                                     update_data: NotificationsSchema):
#     user = await get_user_by_id(user_id=user_id,
#                                 _session=session)
#     if not user:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#                             detail=f'User not found by given "id" {user_id}')

#     _update_data = update_data.model_dump(exclude_none=True)

#     updated_user = await update_and_return_user(user,
#                                                 _update_data,
#                                                 session)
    
#     add_notifications_to_user(user)

#     return updated_user


# @ap