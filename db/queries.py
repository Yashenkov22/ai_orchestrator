from datetime import datetime, timezone

from fastapi import HTTPException

from sqlalchemy import (select,
                        update,
                        insert,
                        and_,
                        exists,)
from sqlalchemy.engine.result import Result
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from db.base import Account, Admin, Message, Thread

from utils.base import moscow_tz
from utils.exc import DB_ERROR_EXCEPTION, ChatNotFound, NotAccessToChat


async def execute_and_catch_db_error(coro,
                                     _session: AsyncSession,
                                     with_rollback: bool = False) -> Result | None:
    try:
        return await coro
    
    except SQLAlchemyError as ex:
        print(ex)

        if with_rollback:
            await _session.rollback()

        raise DB_ERROR_EXCEPTION
    
    except Exception as ex:
        print('NOT SQLALCHEMY ERROR❌❌❌', ex)
        raise DB_ERROR_EXCEPTION



# async def get_user_by_id(user_id: int,
#                          _session: AsyncSession,
#                          check_exists: bool = False) -> UAccountser | None:
#     if check_exists:
#         query = select(1)
#     else:
#         query = select(Account).options(selectinload(User.photos))

#     query = query.where(User.id == user_id)

#     result = await execute_and_catch_db_error(_session.execute(query),
#                                               _session)

#     return result.scalar_one_or_none()


# async def get_user_by_email(email: str,
#                    _session: AsyncSession,
#                    check_exists: bool = False) -> User | None:
#     if check_exists:
#         query = select(1)
#     else:
#         query = select(User).options(selectinload(User.photos))

#     query = query\
#         .where(
#             User.email == email
#         )
#     # try:
#     #     res = await _session.execute(query)
#     #     user = res.scalar_one_or_none()
#     # except SQLAlchemyError as ex:
#     #     print(ex)
#     #     raise DB_ERROR_EXCEPTION
#     user = await execute_and_catch_db_error(_session.execute(query),
#                                             _session)
    
#     return user.scalar_one_or_none()


async def get_admin_by_username(username: str,
                   _session: AsyncSession) -> Admin | None:
    # if check_exists:
    #     query = select(1)
    # else:
    query = select(Admin)

    query = query\
        .where(
            Admin.username == username
        )
    # try:
    #     res = await _session.execute(query)
    #     user = res.scalar_one_or_none()
    # except SQLAlchemyError as ex:
    #     print(ex)
    #     raise DB_ERROR_EXCEPTION
    admin = await execute_and_catch_db_error(_session.execute(query),
                                            _session)
    
    return admin.scalar_one_or_none()


async def get_admin_by_id(_id: str,
                   _session: AsyncSession) -> Admin | None:
    # if check_exists:
    #     query = select(1)
    # else:
    query = select(Admin)

    query = query\
        .where(
            Admin.id == _id
        )
    # try:
    #     res = await _session.execute(query)
    #     user = res.scalar_one_or_none()
    # except SQLAlchemyError as ex:
    #     print(ex)
    #     raise DB_ERROR_EXCEPTION
    admin = await execute_and_catch_db_error(_session.execute(query),
                                            _session)
    
    return admin.scalar_one_or_none()


async def get_account_by_username(username: str,
                                   _session: AsyncSession) -> Account | None:

    query = select(Account)

    query = query\
        .where(
            Account.username == username
        )
    # try:
    #     res = await _session.execute(query)
    #     user = res.scalar_one_or_none()
    # except SQLAlchemyError as ex:
    #     print(ex)
    #     raise DB_ERROR_EXCEPTION
    user = await execute_and_catch_db_error(_session.execute(query),
                                            _session)
    
    return user.scalar_one_or_none()


async def get_account_by_id(_id: int,
                            _session: AsyncSession,
                            check_exists: bool = False) -> Account | None:
    if check_exists:
        query = select(1)
    else:
        query = select(Account)

    query = query\
        .where(
            Account.id == _id
        )
    
    user = await execute_and_catch_db_error(_session.execute(query),
                                            _session)
    
    return user.scalar_one_or_none()


async def get_message_by_id(_id: int,
                            _session: AsyncSession) -> Message | None:

    query = select(Message)

    query = query\
        .where(
            Message.id == _id
        )
    
    message = await execute_and_catch_db_error(_session.execute(query),
                                            _session)
    
    return message.scalar_one_or_none()


async def save_refresh_token_for_user(admin: Admin,
                                      refresh_token: str,
                                      _session: AsyncSession):
    # query = update(User)\
    #         .values(refresh_token=refresh_token)\
    #         .where(User.id == user.id)
    admin.refresh_token = refresh_token
    
    await execute_and_catch_db_error(_session.flush(),
                                     _session)
    # try:
    #     await _session.flush()
    #     # await _session.commit()
    # except SQLAlchemyError as ex:
    #     print(ex)
    #     raise DB_ERROR_EXCEPTION


async def add_and_return_new_user(user_data: dict,
                                  _session: AsyncSession) -> Account:
    # try:
        user = Account(**user_data)
        _session.add(user)
        await execute_and_catch_db_error(_session.flush(),
                                          _session)
        # await _session.flush()    
    # except SQLAlchemyError as ex:
    #     print(ex)
    #     raise DB_ERROR_EXCEPTION    
    
        return user


async def update_time_and_return_user(user: Account,
                                      time_update: datetime,
                                      _session: AsyncSession) -> Account:
    user.updated_at = time_update

    # try:
        # await _session.flush()
    await execute_and_catch_db_error(_session.flush(),
                                              _session)
    # except SQLAlchemyError as ex:
    #     print(ex)
    #     raise DB_ERROR_EXCEPTION 
    
    return user


async def get_all_users(_session: AsyncSession) -> list[Account]:
    query = select(Account)
    # .options(selectinload(User.photos))

    # if user_id:
    #     query = query.where(
    #         User.id != user_id
    #     )
    #     print('filter!!!✅')
    
    # try:
    result = await execute_and_catch_db_error(_session.execute(query),
                                              _session)
    # res = await _session.execute(query)
    users = result.scalars().all()
    # except SQLAlchemyError as ex:
    #     print(ex)
    #     raise DB_ERROR_EXCEPTION
    
    return users


async def update_and_return_user(user: Account,
                                 update_data: dict,
                                 _session: AsyncSession) -> Account:
    has_update = False
    for key, value in update_data.items():
        if getattr(user, key) != value:
            has_update = True
            break

    if has_update:
        update_data.update({'updated_at': datetime.now(timezone.utc)})
        
        [setattr(user, key, value) for key, value in update_data.items()]
        await execute_and_catch_db_error(_session.commit(),
                                                  _session,
                                                  with_rollback=True)
        # try:
        #     await _session.commit()
        # except SQLAlchemyError as ex:
        #     print(ex)
        #     raise DB_ERROR_EXCEPTION
    else:
        print('nothing')

    return user


async def delete_user_and_return_result(user: Account,
                                        _session: AsyncSession) -> bool:
    try:
        await _session.delete(user)
        await _session.commit()
        has_deleted = True
    except SQLAlchemyError as ex:
        print(ex)
        try:
            await _session.rollback()
        except Exception as ex:
            print(ex)
        has_deleted = False
    
    except Exception as ex:
        print(ex)
        has_deleted = False

    return has_deleted


async def get_thread_by_id(thread_id: str,
                           session: AsyncSession) -> Thread:
    query = (
        select(Thread)
        .options(
            joinedload(Thread.account),
            joinedload(Thread.insta_user)
        )\
        .where(Thread.thread_id == thread_id)
    )

    result = await execute_and_catch_db_error(session.execute(query),
                                              session)
    
    return result.scalar_one_or_none()


# async def add_new_chat_to_db_return_id(insert_data: dict,
#                              _session: AsyncSession,
#                              user: User = None):
#     chat = Chat(**insert_data)
#     chat._participants.append(ChatParticipant(user_id=user.id,
#                                               joined_at=datetime.now(timezone.utc)))
#     _session.add(chat)

#     try:
#         await _session.flush()
#         await _session.commit()
#         await _session.refresh(chat, attribute_names=["users"])
#     except SQLAlchemyError as ex:
#         print(ex)
#         await _session.rollback()
#         raise DB_ERROR_EXCEPTION
    
#     return chat



# async def get_chats_by_user_id(user_id: int,
#                                _session: AsyncSession):
#     stmt = select(Chat)\
#         .join(ChatParticipant)\
#         .where(ChatParticipant.user_id == user_id)\
#         .options(
#             selectinload(Chat.users)\
#             .selectinload(User.photos))\
#         .order_by(Chat.created_at.desc())
    
#     result = await execute_and_catch_db_error(_session.execute(stmt),
#                                                _session)
#     # try:
#     #     result = await _session.execute(stmt)
#     chats = result.scalars().unique().all()
#     # except SQLAlchemyError as ex:
#     #     print(ex)
#     #     raise DB_ERROR_EXCEPTION
    
#     return chats


# async def get_chat_by_id(chat_id: int,
#                          user_id: int,
#                          session: AsyncSession) -> Chat:
#     query = select(
#         exists().where(Chat.id == chat_id)
#     )

#     result = await execute_and_catch_db_error(
#         session.execute(query),
#         session
#     )

#     chat_exists = result.scalar()

#     if not chat_exists:
#         raise ChatNotFound()
    
#     query = select(Chat)\
#         .join(ChatParticipant)\
#         .where(
#             and_(
#                 ChatParticipant.user_id == user_id,
#                 Chat.id == chat_id,
#             )
#         )\
#         .options(
#             selectinload(Chat.users)\
#             .selectinload(User.photos))\
            
#     result = await execute_and_catch_db_error(session.execute(query),
#                                               session)

#     chat = result.scalar_one_or_none()

#     if not chat:
#         raise NotAccessToChat()
    
#     return chat


# async def get_chat_by_id(chat_id: int,
#                          _session: AsyncSession):
#     stmt = (
#         select(Chat)
#         .options(selectinload(Chat.users))
#         .where(Chat.id == chat_id)
#     )

#     result = await execute_and_catch_db_error(_session.execute(stmt),
#                                               _session)
#     # try:
#         # result = await _session.execute(stmt)
#     chat = result.scalar_one()
#     # except SQLAlchemyError as ex:
#         # raise DB_ERROR_EXCEPTION
#     return chat


# async def add_and_return_new_message(data: dict,
#                                      _session: AsyncSession):
#     new_message = Message(**data,
#                           created_at=datetime.now(timezone.utc),
#                           updated_at=datetime.now(timezone.utc))
    
#     _session.add(new_message)

#     await execute_and_catch_db_error(_session.flush(),
#                                      _session,
#                                      with_rollback=True)
    
#     await execute_and_catch_db_error(_session.commit(),
#                                      _session,
#                                      with_rollback=True)
    
#     return new_message