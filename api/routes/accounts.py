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


account_router = APIRouter(tags=['Accounts'],
                           prefix='/account')


# @user_router.post("/new_account")
@account_router.post("/create")
async def create_account(data: CreateAccountSchema,
                         admin: admin_dependency,
                         session: session_dependency):
    admin_id, is_main_admin = admin

    if not is_main_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail='Dont have permissions')

    check_account = await get_account_by_username(data.username,
                                                  session)

    if check_account:
        raise HTTPException(status_code=400,
                            detail='Такая запись уже есть в БД')
    
    insert_data = {
        'username': data.username,
        'password': encrypt_password(data.password),
        'created_at': datetime.now(tz=timezone.utc),
        'updated_at': datetime.now(tz=timezone.utc),
    }
    new_account = Account(**insert_data)

    session.add(new_account)

    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)
    
    return {
        "id": str(new_account.id),
        "username": new_account.username,
        "insta_id": new_account.insta_id,
        'is_active': new_account.is_active,
    }


# new
# @user_router.get("/accounts")
@account_router.get("/list")
async def get_accounts(admin: admin_dependency,
                       session: session_dependency):
    thread_alias = aliased(Thread)

    admin_id, is_main_admin = admin

    query = (
        select(
            Account,
            func.count(Thread.id),
            exists()
            .where(
                and_(
                    thread_alias.account_id == Account.id,
                    thread_alias.is_unread == True,
                )
            ),
        )
        .outerjoin(Thread, Thread.account_id == Account.id)\
        .group_by(Account.id)
    )

    if not is_main_admin:
        query = query.where(
            Account.id.in_(ID_LIST_FOR_PERMISSION),
        )

    result = await execute_and_catch_db_error(session.execute(query),
                                              session)

    users = result.fetchall()
    accounts = []

    accounts = [
        {
            "id": u.id,
            "username": u.view_name or u.username,
            "insta_id": u.insta_id,
            'has_error': -(u.has_error),
            'created_at': u.created_at,
            'updated_at': u.updated_at,
            'is_active': u.is_active,
            'thread_count': thread_count,
            'has_unread': has_unread,
        }
        for u, thread_count, has_unread in users
    ]
    
    return accounts


# new
# @user_router.get("/accounts/{account_id}",
#                  response_model=NewAccountSchema,
#                  response_model_by_alias=False)
@account_router.get("/{account_id}",
                 response_model=NewAccountSchema,
                 response_model_by_alias=False)
async def get_account_by_id(account_id: int,
                            admin: admin_dependency,
                            session: session_dependency):
    thread_alias = aliased(Thread)

    admin_id, is_main_admin = admin

    if not is_main_admin:
        if account_id not in ID_LIST_FOR_PERMISSION:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail='Dont have permissions')
    
    query = (
        select(
            Account,
            func.count(Thread.id),
            exists()
            .where(
                and_(
                    thread_alias.account_id == Account.id,
                    thread_alias.is_unread == True,
                )
            ),
        )
        .outerjoin(Thread, Thread.account_id == Account.id)
        .where(
            Account.id == account_id,
        )
        .group_by(Account.id)
    )
    result = await execute_and_catch_db_error(session.execute(query),
                                              session)
    account, thread_count, has_unread = result.one_or_none()

    if account:
        account_data =  {
            "id": account.id,
            "username": account.username,
            'view_name': account.view_name,
            "fullname": account.full_name,
            'created_at': account.created_at,
            'updated_at': account.updated_at,
            'photo_url': generate_valid_media_url(account.photo_url),
            'is_active': account.is_active,
            'is_hidden': account.is_hidden,
            'parse_whole_thread_list': account.parse_whole_thread_list,
            'thread_count': thread_count,
            'has_unread': has_unread,
            'has_error': -(account.has_error),
            'information': account.information,
            'folder_id': account.folder_id,
            'profile_id': account.profile_id,
        }

        return account_data
    

# @user_router.patch("/update_profile_data_by_account")
@account_router.patch("/update_profile_data")
async def update_profile_data_by_account(data: UpdateProfileDataSchema,
                                         admin: admin_dependency,
                                         session: session_dependency):
    admin_id, is_main_admin = admin

    if not is_main_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail='Dont have permissions')

    account_query = (
        select(Account)\
        .where(
            Account.id == data.account_id,
        )
    )

    res = await execute_and_catch_db_error(session.execute(account_query),
                                           session)
    
    account: Account = res.scalar_one_or_none()

    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Account not found by given account_id')
    
    check_query = (
        select(1)\
        .where(
            and_(
                Account.folder_id == data.folder_id,
                Account.profile_id == data.profile_id,
                Account.id != data.account_id,
            )
        )
    )
    has_record_res = await execute_and_catch_db_error(session.execute(check_query),
                                                      session)
    
    has_record = has_record_res.scalar_one_or_none()
    
    if has_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='This profile link with another account already')

    account.folder_id = data.folder_id
    account.profile_id = data.profile_id

    try:
        await execute_and_catch_db_error(session.commit(),
                                        session,
                                        with_rollback=True)
        
        return {
            'status': 'success',
            'detail': 'Profile successfully linked',
        }

    except Exception as ex:
        print(ex)
        raise


# @user_router.patch("/accounts")
@account_router.patch("/update_active_status")
async def get_account_by_id(data: PatchAccountSchema,
                            admin: admin_dependency,
                            session: session_dependency):
    admin_id, is_main_admin = admin

    if not is_main_admin:
        if data.account_id not in ID_LIST_FOR_PERMISSION:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail='Dont have permissions')

    query = (
        select(
            Account
        )\
        .where(
            Account.id == data.account_id
        )
    )

    res = await execute_and_catch_db_error(session.execute(query),
                                           session)
    
    account = res.scalar_one_or_none()

    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Account not found')
    
    has_edit = False

    if account.is_active != data.is_active:
        account.is_active = data.is_active
        has_edit = True

    if not has_edit:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail='Nothing change')
    else:
        await execute_and_catch_db_error(session.commit(),
                                         session,
                                         with_rollback=True)
        return {
            'status': 'success',
        }

# @user_router.patch("/set_account_information")
@account_router.patch("/set_information")
async def set_account_information(data: PatchInformationAccountSchema,
                                  admin: admin_dependency,
                                  session: session_dependency):
    admin_id, is_main_admin = admin

    if not is_main_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail='Dont have permissions')

    query = (
        select(
            Account
        )\
        .where(
            Account.id == data.account_id
        )
    )

    res = await execute_and_catch_db_error(session.execute(query),
                                           session)
    
    account: Account = res.scalar_one_or_none()

    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Account not found')
    
    has_edit = False

    if account.information != data.information:
        account.information = data.information
        has_edit = True

    if not has_edit:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail='Nothing change')
    else:
        await execute_and_catch_db_error(session.commit(),
                                         session,
                                         with_rollback=True)
        return {
            'status': 'success',
        }
    
# @user_router.patch("/set_account_photo")
@account_router.patch("/set_photo")
async def set_photo_information(data: PatchPhotoAccountSchema,
                                admin: admin_dependency,
                                session: session_dependency):
    admin_id, is_main_admin = admin

    if not is_main_admin:
        if data.account_id not in ID_LIST_FOR_PERMISSION:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail='Dont have permissions')

    query = (
        select(
            Account
        )\
        .where(
            Account.id == data.account_id
        )
    )

    res = await execute_and_catch_db_error(session.execute(query),
                                           session)
    
    account: Account = res.scalar_one_or_none()

    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Account not found')
    
    account.photo_url = data.media_url

    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)
    return {
        'status': 'success',
    }


@account_router.patch("/set_view_name")
async def set_view_name(data: PatchViewNameAccountSchema,
                        admin: admin_dependency,
                        session: session_dependency):
    admin_id, is_main_admin = admin

    if not is_main_admin:
        if data.account_id not in ID_LIST_FOR_PERMISSION:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail='Dont have permissions')

    query = (
        select(
            Account
        )\
        .where(
            Account.id == data.account_id
        )
    )

    res = await execute_and_catch_db_error(session.execute(query),
                                           session)
    
    account: Account = res.scalar_one_or_none()

    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Account not found')
    
    account.view_name = data.view_name

    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)
    return {
        'status': 'success',
    }


@account_router.patch("/edit_hidden_mark")
async def edit_hidden_mark_by_account_id(data: PatchHiddenMarkAccountSchema,
                        admin: admin_dependency,
                        session: session_dependency):
    admin_id, is_main_admin = admin

    if not is_main_admin:
        if data.account_id not in ID_LIST_FOR_PERMISSION:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail='Dont have permissions')

    query = (
        select(
            Account
        )\
        .where(
            Account.id == data.account_id
        )
    )

    res = await execute_and_catch_db_error(session.execute(query),
                                           session)
    
    account: Account = res.scalar_one_or_none()

    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Account not found')
    
    account.is_hidden = not account.is_hidden

    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)
    return {
        'account_id': account.id,
        'is_hidden': account.is_hidden,
    }


@account_router.patch("/edit_full_parse_by_account_id")
async def edit_hidden_mark_by_account_id(data: PatchHiddenMarkAccountSchema,
                        admin: admin_dependency,
                        session: session_dependency):
    admin_id, is_main_admin = admin

    if not is_main_admin:
        if data.account_id not in ID_LIST_FOR_PERMISSION:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail='Dont have permissions')

    query = (
        select(
            Account
        )\
        .where(
            Account.id == data.account_id
        )
    )

    res = await execute_and_catch_db_error(session.execute(query),
                                           session)
    
    account: Account = res.scalar_one_or_none()

    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Account not found')
    
    account.parse_whole_thread_list = not account.parse_whole_thread_list

    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)
    return {
        'account_id': account.id,
        'parse_whole_thread_list': account.parse_whole_thread_list,
    }