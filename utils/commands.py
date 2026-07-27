from sqlalchemy.ext.asyncio import AsyncSession

from db.base import Admin

from .base import pwd_context

from db.queries import execute_and_catch_db_error



async def create_admin_accounts(session: AsyncSession):
    admin_list = [
        {
            # 'admin': pwd_context.hash('1234'),
            'username': 'moder1',
            'password': pwd_context.hash('GfhjkmGfhjkm123321!!'),
        }
    ]

    create_list = []

    for admin_dict in admin_list:
        create_list.append(Admin(**admin_dict))

    
    session.add_all(create_list)

    await execute_and_catch_db_error(session.commit(),
                                     session,
                                     with_rollback=True)
    print('Admin записи созданы ✅')


    # pwd_context.hash(password)