import base64
import os
import shutil
import asyncio

from time import time

from uuid import uuid4

from fastapi import (APIRouter,
                     File,
                     UploadFile,
                     HTTPException,
                     status)

from sqlalchemy import select

from sqlalchemy.orm import selectinload

from db.queries import (execute_and_catch_db_error,
                        get_account_by_id, get_message_only_by_id, get_thread_only_by_id, get_threads_by_color, try_update_message_text)

from db.base import Account, Thread

from db.queries import get_message_by_id

from utils.ai import ai_extract_user_info, ai_test_photo, ai_translate_message
from utils.dependencies import (admin_dependency,
                                session_dependency,
                                arq_dependency)
from utils.enums import MessageStatusEnum, ThreadColorEnum, AIModelEnum, LanguageEnum
from auth.schemas import SecretShcema

from utils.base import (generate_valid_media_url,
                        get_folder_profiles,
                        get_vision_folder_list,
                        try_connect_to_main_instagram_page,
                        try_start_profile,
                        try_stop_profile)

from config import SECRET_API, UPLOAD_DIR
from utils.tasks import try_update_thread_memory


utils_router = APIRouter(tags=['Utils'],
                         prefix='/utils')


# @user_router.post("/upload_file")
@utils_router.post("/upload_file")
async def upload_file(admin: admin_dependency,
                      session: session_dependency,
                      file: UploadFile = File(...)):
    # создаём папку если нет
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    # уникальное имя файла
    file_ext = file.filename.split(".")[-1]
    filename = f"{uuid4()}.{file_ext}"
    media_url = os.path.join(UPLOAD_DIR, filename)

    # сохраняем файл
    with open(media_url, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    content_type = file.content_type

    if content_type.startswith('image'):
        media_type = 'photo'
    elif content_type.startswith('audio'):
        media_type = 'audio'
    elif content_type.startswith('video'):
        media_type = 'video'
    else:
        media_type = None

    return {
        'media_type': media_type,
        "media_url": media_url,
        "media_preview": generate_valid_media_url(media_url),
    }


# @user_router.get("/folders")
@utils_router.get("/folders")
async def get_vision_folders(admin: admin_dependency,
                             session: session_dependency):
    data: dict = await get_vision_folder_list()

    folders = data.get('data')

    if not folders:
        return []

    return [{
        'folder_id': folder['id'],
        'folder_name': folder['folder_name'],
        'folder_icon': folder['folder_icon'],
        'folder_icon': folder['folder_icon'],
        'folder_color': folder['folder_color'],
    } for folder in folders if not folder['deleted_at']]


# @user_router.get("/folder_profiles")
@utils_router.get("/folder_profiles")
async def get_vision_folder_profiles(folder_id: str,
                                     admin: admin_dependency,
                                     session: session_dependency):
    data = await get_folder_profiles(folder_id)

    profiles = data.get('data').get('items')

    query = (
        select(
            Account.profile_id,
        )\
        .where(
            Account.folder_id == folder_id,
        )
    )

    res = await execute_and_catch_db_error(session.execute(query),
                                           session)
    
    folder_profile_id_from_db = res.scalars().all()

    if folder_profile_id_from_db:
        folder_profile_id_from_db = set(folder_profile_id_from_db)

    return [{
        'profile_id': profile['id'],
        'folder_id': profile['folder_id'],
        'profile_name': profile['profile_name'],
        'profile_status': profile['profile_status'],
    } for profile in profiles if profile['id'] not in folder_profile_id_from_db]


@utils_router.get("/run_background_send_message")
async def test_hander(admin: admin_dependency,
                      session: session_dependency,
                      arq_pool: arq_dependency,
                      account_id: int,
                      message_id: int,
                      message_text: str):
    success = await try_update_message_text(message_id,
                                            message_text,
                                            session)
    if success:
        job = await arq_pool.enqueue_job(
            'send_message_to_thread',
            account_id,
            message_id,
            _queue_name='arq:messages',
        )
        
        if job:
            msg = await get_message_only_by_id(message_id,
                                               session)
            msg.status = MessageStatusEnum.MODERATED
            await execute_and_catch_db_error(session.commit(),
                                             session,
                                             with_rollback=True)
        
        return {"status": "queued", "job_id": job.job_id}
    

@utils_router.get("/run_background_parse_thread")
async def run_background_parse_thread(admin: admin_dependency,
                      session: session_dependency,
                      arq_pool: arq_dependency,
                      account_id: int,
                      thread_id: int):
    job = await arq_pool.enqueue_job(
        'parse_thread',
        account_id,
        thread_id,
        _queue_name='arq:messages',
    )
    return {"status": "queued", "job_id": job.job_id}


@utils_router.get("/block_thread_by_account_id")
async def run_background_block_thread(admin: admin_dependency,
                      session: session_dependency,
                      arq_pool: arq_dependency,
                      account_id: int,
                      thread_id: int):
    job = await arq_pool.enqueue_job(
        'try_block_thread_by_account_id',
        account_id,
        thread_id,
        _queue_name='arq:messages',
    )
    return {"status": "queued", "job_id": job.job_id}


@utils_router.get("/try_start_vision_profile")
async def try_start_vision_profile(admin: admin_dependency,
                                   arq_pool: arq_dependency,
                                   session: session_dependency,
                                   account_id: int):
    job = await arq_pool.enqueue_job(
        'try_start_stop_vision_profile_by_account_id',
        account_id,
        'start',
        _queue_name='arq:messages',
    )
    return {"status": "queued", "job_id": job.job_id}


@utils_router.get("/try_stop_vision_profile")
async def try_stop_vision_profile(admin: admin_dependency,
                                  arq_pool: arq_dependency,
                                  session: session_dependency,
                                  account_id: int):
    job = await arq_pool.enqueue_job(
        'try_start_stop_vision_profile_by_account_id',
        account_id,
        'stop',
        _queue_name='arq:messages',
    )
    return {"status": "queued", "job_id": job.job_id}


@utils_router.get("/translate")
async def try_translate_text(admin: admin_dependency,
                             session: session_dependency,
                             message_id: int):
    message = await get_message_only_by_id(message_id,
                                           session)
    if not message.text:
        return 'Message don`t have "text" field'
    
    if message.translated_text:
        return message.translated_text
    else:
        try:
            translated_text = await ai_translate_message(message.text)
            message.translated_text = translated_text
            await execute_and_catch_db_error(session.commit(),
                                             session,
                                             with_rollback=True)
            return translated_text
        except Exception as ex:
            print(ex)
            return 'Error with try translate text'


@utils_router.get("/test_translate")
async def try_translate_text2(admin: admin_dependency,
                             session: session_dependency,
                             text: str):    
    try:
        translated_text = await ai_translate_message(text)
        # message.translated_text = translated_text
        # await execute_and_catch_db_error(session.commit(),
        #                                     session,
        #                                     with_rollback=True)
        return translated_text
    except Exception as ex:
        print(ex)
        return 'Error with try translate text'




@utils_router.get("/generate_user_information")
async def generate_user_informations(admin: admin_dependency,
                                     arq_pool: arq_dependency,
                                     session: session_dependency):

    job = await arq_pool.enqueue_job(
            'generate_translated_user_information',
            _queue_name='arq:utils',
        )

    return job.job_id


@utils_router.get("/generate_user_information2")
async def generate_user_informations2(thread_id: int,
                                      admin: admin_dependency,
                                     arq_pool: arq_dependency,
                                     session: session_dependency):

    job = await arq_pool.enqueue_job(
            'translate_user_information_by_thread_id',
            thread_id,
            _queue_name='arq:utils',
        )

    return job.job_id


@utils_router.get("/test_photo_to_ai")
async def test_photo_to_ai(admin: admin_dependency,
                                     arq_pool: arq_dependency,
                                     session: session_dependency):
    phto_url = "./test.jpg"
    with open(phto_url, "rb") as f:

        image_bytes = f.read()

    base64_image = base64.b64encode(image_bytes).decode("utf-8")
    start_time = time()
    print(f' -> start {start_time}')
    await ai_test_photo(base64_image)
    end_time = time()
    print(f' -> end {end_time}')
    print(f' -> result {end_time - start_time}')


@utils_router.get("/get_ai_model_list")
async def get_ai_model_list(admin: admin_dependency,
                            arq_pool: arq_dependency,
                            session: session_dependency):
    return [model.value for model in AIModelEnum]


@utils_router.get("/get_language_list")
async def get_language_list(admin: admin_dependency,
                            arq_pool: arq_dependency,
                            session: session_dependency):
    return sorted(model.value for model in LanguageEnum)


@utils_router.get("/generate_thread_memories_for_color")
async def generate_thread_memories(admin: admin_dependency,
                                   arq_pool: arq_dependency,
                                   session: session_dependency,
                                   secret: str,
                                   color: ThreadColorEnum):
    if secret != SECRET_API:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


    threads = await get_threads_by_color(color='yellow',
                                         session=session)

    task_counter = 0

    for thread in threads:    
        job = await arq_pool.enqueue_job(
            'generate_thread_momory_by_id',
            thread.id,
            _queue_name='arq:utils',
        )
        task_counter += 1

    return f'{task_counter} background tasks was running...'


@utils_router.get("/reorganize_message_types")
async def generate_thread_memories(admin: admin_dependency,
                                   arq_pool: arq_dependency,
                                   session: session_dependency,
                                   secret: str):
    if secret != SECRET_API:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


    # threads = await get_threads_by_color(color='yellow',
    #                                      session=session)

    # task_counter = 0

    # for thread in threads:    
    job = await arq_pool.enqueue_job(
        'organize_new_message_types',
        _queue_name='arq:utils',
    )

    return job.job_id
    # task_counter += 1

    # return f'{task_counter} background tasks was running...'