from datetime import datetime

from fastapi import (APIRouter,
                     HTTPException,
                     status)

from db.queries import (get_all_users,
                        update_and_return_user,
                        delete_user_and_return_result)

from utils.base import moscow_tz
from utils.schemas import (DetailUserSchema,
                           UpdateUserSchema,
                           NotificationsSchema,
                           ListVeiwChatSchema,
                           DetailViewChatSchema,
                           AddMessageSchema,
                           DetailMessageSchema)
from utils.dependencies import (user_dependency,
                                session_dependency,
                                current_user_dependency)
from utils.endpoints import add_notifications_to_user
from utils.exc import ChatNotFound, NotAccessToChat
from utils.enums import MessageStatusEnum


chat_router = APIRouter(prefix='/chats',
                        tags=['Chats'])


# @chat_router.post('/create',
#                  response_model=ListVeiwChatSchema,
#                  response_model_by_alias=True)
# async def create_new_chat(user_id: user_dependency,
#                           session: session_dependency):
#     user = await get_user_by_id(user_id=user_id,
#                                 _session=session)
#     if not user:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#                             detail=f'User not found by given "id" {user_id}')
    
#     insert_data = {
#         'created_at': datetime.now(moscow_tz),
#         'updated_at': datetime.now(moscow_tz),
#     }

#     chat = await add_new_chat_to_db_return_id(insert_data,
#                                               session,
#                                               user)
#     # chat = await get_chat_by_id(chat_id,
#     #                             session)
#     # print(chat)
#     # print(chat.__dict__)
    
#     # chat.participants = [user]
    
#     return ListVeiwChatSchema.model_construct(**chat.__dict__)


# @chat_router.get('',
#                  response_model=list[ListVeiwChatSchema])
# async def get_all_user_chats(user_id: user_dependency,
#                              session: session_dependency):
#     user = await get_user_by_id(user_id=user_id,
#                                 _session=session,
#                                 check_exists=True)
#     if not user:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#                             detail=f'User not found by given "id" {user_id}')
    
#     chats = await get_chats_by_user_id(user_id,
#                                        session)
    
#     add_participant_to_chats(chats,
#                              user_id)
    
#     # for chat in chats:
#     #     print(chat.__dict__)
#     #     print(chat.users)

#     # return [ListVeiwChatSchema.model_construct(**chat.__dict__) for chat in chats]
#     return chats


# @chat_router.get('{chat_id}',
#                  response_model=DetailViewChatSchema)
# async def return_chat_by_id(user_id: user_dependency,
#                             session: session_dependency,
#                             chat_id: int):
#     user = await get_user_by_id(user_id=user_id,
#                                 _session=session,
#                                 check_exists=True)
#     if not user:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#                             detail=f'User not found by given "id" {user_id}')
#     try:
#         chat = await get_chat_by_id(chat_id,
#                                     user_id,
#                                     session)
#     except ChatNotFound:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#                             detail=f'Chat not found by given "chat_id" {chat_id}')
#     except NotAccessToChat:
#         raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
#                             detail=f'Not access to chat by given "chat_id" {chat_id}')
#     else:
#         chat.participants = [p.id for p in chat.users]
    
#         return chat
    

# @chat_router.post('{chat_id}/message',
#                  response_model=DetailMessageSchema)
# async def add_new_message_to_chat_by_id(user_id: user_dependency,
#                                         session: session_dependency,
#                                         chat_id: int,
#                                         new_message: AddMessageSchema):
#     user = await get_user_by_id(user_id=user_id,
#                                 _session=session,
#                                 check_exists=True)
#     if not user:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#                             detail=f'User not found by given "id" {user_id}')
#     try:
#         chat = await get_chat_by_id(chat_id,
#                                     user_id,
#                                     session)
#     except ChatNotFound:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#                             detail=f'Chat not found by given "chat_id" {chat_id}')
#     except NotAccessToChat:
#         raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
#                             detail=f'Not access to chat by given "chat_id" {chat_id}')
    
#     data = new_message.model_dump() | {'sender_id': user_id,
#                                         'chat_id': chat_id}

#     message = await add_and_return_new_message(data,
#                                                session)

#     message.is_read = message.status not in {MessageStatusEnum.SENT, MessageStatusEnum.DELIVERED}

#     return message