import os
import re
import json
import random
import asyncio
import aiofiles

import aiohttp

from urllib.parse import unquote

from pathlib import Path

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from playwright.async_api import async_playwright

from db.queries import (check_insta_user, check_new_messages_in_thread,
                        check_thread_in_db,
                        try_add_insta_user,
                        try_add_messages,
                        try_add_new_thread,
                        execute_and_catch_db_error, update_approve_thread)

from db.base import Message, Thread

from utils.enums import MessageStatusEnum

from utils.base import dismiss_notifications_popup

from config import VISION_BROWSER_HOST, MEDIA_PATH

# === Конфигурация ===

TARGET_QUERIES = {
    'PolarisDirectInboxQuery',
    'useIGDSystemFolderUnreadThreadCountQuery',
    'IGDInboxTrayQuery',
    'IGDBadgeCountOffMsysQuery',
    'IGDThreadDetailQuery',
    'PolarisDirectMessageRequestQuery',
}

# === Утилиты ===

# def extract_friendly_name(payload: str) -> str | None:
#     for part in payload.split('&'):
#         if 'friendly_name=' in part:
#             return unquote(part.split('=', 1)[1])
#     return None

# def extract_variables(payload: str) -> dict | None:
#     for part in payload.split('&'):
#         if part.startswith('variables='):
#             raw = unquote(part.split('=', 1)[1])
#             try:
#                 return json.loads(raw)
#             except json.JSONDecodeError:
#                 return None
#     return None

# def parse_ig_response(text: str) -> list[dict]:
#     results = []
#     for line in text.strip().split('\n'):
#         line = line.strip()
#         if not line:
#             continue
#         for prefix in ['for (;;);', ')]}\'']:
#             if line.startswith(prefix):
#                 line = line[len(prefix):]
#         try:
#             results.append(json.loads(line))
#         except json.JSONDecodeError:
#             continue
#     return results


# # === Навигация в тред ===

# async def enter_thread(page, thread_key, thread_received, timeout=15):
#     thread_received.clear()

#     selector = f'a[href*="/direct/t/{thread_key}"]'

#     try:
#         await page.wait_for_selector(selector, timeout=5000)
#         await page.click(selector)
#     except Exception:
#         await page.evaluate(
#             f'window.location.assign("/direct/t/{thread_key}/")'
#         )

#     try:
#         await asyncio.wait_for(thread_received.wait(), timeout=timeout)
#         print(f"Thread {thread_key} data received!")
#     except asyncio.TimeoutError:
#         print(f"Timeout for thread {thread_key}")

#     await page.wait_for_timeout(2000)


# def extract_media_urls(node: dict) -> list[dict]:
#     """Извлекает все медиа URL из сообщения"""
#     content = node.get('content', {})
#     typename = content.get('__typename', '')
#     urls = []

#     if typename == 'SlideMessageImageContent':
#         for att in content.get('attachments', []):
#             # Приоритет: полное качество > превью
#             url = att.get('attachment_cdn_url') or att.get('preview_cdn_url')
#             if url:
#                 urls.append({'url': url, 'type': 'image', 'ext': '.jpg'})

#     elif typename == 'SlideMessageMultiMediaContent':
#         for att in content.get('ordered_photo_video_attachments', []):
#             url = att.get('attachment_cdn_url') or att.get('preview_cdn_url')
#             if url:
#                 att_type = att.get('attachment_type', 2)
#                 if att_type == 4:  # видео
#                     urls.append({'url': url, 'type': 'video', 'ext': '.mp4'})
#                 else:  # фото
#                     urls.append({'url': url, 'type': 'image', 'ext': '.jpg'})

#     elif typename == 'SlideMessageVideosContent':
#         for vid in content.get('videos', []):
#             # Само видео
#             video_url = vid.get('attachment_cdn_url')
#             if video_url:
#                 urls.append({'url': video_url, 'type': 'video', 'ext': '.mp4'})
#             # Превью-картинка
#             preview = vid.get('preview_cdn_url')
#             if preview:
#                 urls.append({'url': preview, 'type': 'video_preview', 'ext': '.jpg'})

#     elif typename == 'SlideMessageAudiosContent':
#         for audio in content.get('audio_attachments', []):
#             audio_url = audio.get('attachment_cdn_url')
#             if audio_url:
#                 urls.append({'url': audio_url, 'type': 'audio', 'ext': '.mp4'})

#     return urls


# # === Скачивание файлов ===

# async def download_media(urls: list[dict], save_dir: str,
#                          thread_key: str, msg_id: str):
#     """Скачивает медиа файлы"""
#     downloaded = []

#     async with aiohttp.ClientSession() as session:
#         for i, media in enumerate(urls):
#             url = media['url']
#             ext = media['ext']
#             media_type = media['type']

#             filename = f"{thread_key}_{msg_id}_{media_type}_{i}{ext}"
#             filepath = os.path.join(save_dir, filename)

#             try:
#                 async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
#                     if resp.status == 200:
#                         data = await resp.read()
#                         with open(filepath, 'wb') as f:
#                             f.write(data)
#                         size_kb = len(data) / 1024
#                         print(f"      Downloaded: {filename} ({size_kb:.1f} KB)")
                        
#                         if media_type in ('image', 'video_preview'):
#                             media_type = 'photo'
                        
#                         downloaded.append((media_type, filepath))
#                     else:
#                         print(f"      Failed: {filename} — status {resp.status}")
#             except Exception as e:
#                 print(f"      Error: {filename} — {e}")

#     return downloaded


# async def process_thread_messages(messages: list,
#                                   thread: Thread,
#                                   user_insta_id: str,
#                                   thread_key: str,
#                                   save_dir: str = './media'):
#     """Обрабатывает сообщения треда и скачивает медиа"""
#     # Создаём папку для треда
#     thread_dir = os.path.join(save_dir, str(thread_key))
#     Path(thread_dir).mkdir(parents=True, exist_ok=True)

#     result = {
#         'thread_id': thread.id,
#     }

#     all_messages = []

#     for msg in messages:
#         node = msg['node']
#         # sender_id = node.get('sender_fbid', '?')
#         ctype = node.get('content_type', '?')
#         msg_id = node.get('id', 'unknown')
#         _ts = node.get('timestamp_ms', '')
#         valid_ts = None

#         _sender = node.get('sender')

#         if _sender:
#             _sender = _sender.get('igid')
#         else:
#             _sender = None

#         # print('MESSAGE PROCCESS!!!!', msg)

#         if _ts:
#             valid_ts = datetime.fromtimestamp(
#                 int(_ts) / 1000,
#                 tz=timezone.utc
#             )
#         try:
#             if thread.timestamp_last_seen_message and thread.timestamp_last_seen_message >= valid_ts:
#                 print('ALL NEW MESSAGES', all_messages)
#                 break
#         except Exception as ex:
#             print(ex)
#             raise

#         print('MATCH.    !!!!', _sender, user_insta_id)

#         msg_data = {
#             'id': msg_id,
#             'sender': 'user' if _sender == user_insta_id else 'assistant',
#             'type': ctype,
#             'timestamp': _ts,
#             'text': None,
#             'media_files': [],
#         }

#         if ctype == 'TEXT':
#             text = node.get('text_body', '')
#             msg_data['text'] = text
#         else:
#             content = node.get('content', {})

#             # Извлекаем и скачиваем медиа
#             media_urls = extract_media_urls(node)

#             if media_urls:
#                 files: list[tuple] = await download_media(
#                     media_urls, thread_dir, str(thread_key), msg_id
#                 )
#                 msg_data['media_files'] = files

#         all_messages.append(msg_data)

#     result['messages'] = all_messages

#     return result


# async def download_profile_pic(user_data: dict, save_dir: str = './media'):
#     """Скачивает фото профиля пользователя"""
#     url = user_data.get('profile_pic_url')
#     username = user_data.get('username', 'unknown')
    
#     if not url:
#         return None

#     Path(save_dir).mkdir(parents=True, exist_ok=True)
#     filepath = os.path.join(save_dir, f"{username}.jpg")

#     async with aiohttp.ClientSession() as session:
#         try:
#             async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
#                 if resp.status == 200:
#                     data = await resp.read()

#                     async with aiofiles.open(filepath, 'wb') as f:
#                         await f.write(data)

#                     print(f"  Profile pic: {username}.jpg ({len(data)/1024:.1f} KB)")

#                     return filepath

#                 else:
#                     print(f"  Failed: {username} — status {resp.status}")
#         except Exception as e:
#             print(f"  Error: {username} — {e}")

#     return None


# async def human_pause(a=0.4, b=1.2):
#     await asyncio.sleep(random.uniform(a, b))


# # === Основная функция ===

# async def test_playwright(account_id: int,
#                           profile_port: int,
#                           _session: AsyncSession):
#     collected_data = {}
#     thread_responses = []
#     inbox_received = asyncio.Event()
#     thread_received = asyncio.Event()
#     request_message_received = asyncio.Event()

#     async with async_playwright() as p:
#         browser = await p.chromium.connect_over_cdp(f'http://{VISION_BROWSER_HOST}:{profile_port}')
#         print(f"CONNECTED ON {profile_port} PORT")

#         context = browser.contexts[0] if browser.contexts else await browser.new_context()
#         page = context.pages[0] if context.pages else await context.new_page()

#         # === Обработчик ответов ===

#         async def on_response(response):
#             req = response.request
#             if req.resource_type not in ('xhr', 'fetch'):
#                 return
#             url = response.url
#             if '/api/graphql' not in url and '/graphql/query' not in url:
#                 return
#             if not req.post_data:
#                 return

#             friendly_name = extract_friendly_name(req.post_data)
#             variables = extract_variables(req.post_data)
            
#             if friendly_name not in TARGET_QUERIES:
#                 return

#             try:
#                 body = await response.text()
#                 parsed = parse_ig_response(body)
#                 variables = extract_variables(req.post_data)

#                 key = friendly_name
#                 if variables and 'folder' in variables:
#                     key = f"{friendly_name}:{variables['folder']}"

#                 if friendly_name == 'IGDThreadDetailQuery':
#                     thread_responses.append(parsed)
#                     thread_received.set()

#                 else:
#                     collected_data[key] = parsed

#                 # if friendly_name == 'PolarisDirectInboxQuery':
#                 #     inbox_received.set()
#                 if friendly_name == 'PolarisDirectInboxQuery':
#                     inbox_received.set()

#                 if friendly_name == 'PolarisDirectMessageRequestQuery':
#                     # collected_data['PolarisDirectMessageRequestQuery'] = parsed
#                     request_message_received.set()

#             except Exception as e:
#                 print(f"[ERROR] {friendly_name}: {e}")

#         page.on("response", on_response)

#         ################ PARSE DM THREADS #################

#         # === 1. Заходим на inbox ===

#         current_url = page.url
#         if 'instagram.com/direct/inbox' in current_url:
#             await page.reload(wait_until='domcontentloaded')
#         else:
#             await page.goto(
#                 'https://www.instagram.com/direct/inbox/',
#                 wait_until='domcontentloaded'
#             )

#         try:
#             await asyncio.wait_for(inbox_received.wait(), timeout=15)
#             print("Inbox received!")
#         except asyncio.TimeoutError:
#             print("Inbox timeout")

#         await page.wait_for_timeout(2000)

#         # === 2. Парсим треды ===

#         inbox_data = collected_data.get('PolarisDirectInboxQuery', [])
#         threads = []

#         for obj in inbox_data:
#             edges = (obj.get('data', {})
#                        .get('get_slide_mailbox_for_iris_subscription', {})
#                        .get('threads_by_folder', {})
#                        .get('edges', []))
#             for edge in edges:
#                 node = edge['node'].get('as_ig_direct_thread', {})
#                 threads.append({
#                     'thread_key': node.get('thread_key'),
#                     'users': [u for u in node.get('users', [])],
#                     'last_activity': node.get('last_activity_timestamp_ms'),
#                     'is_group': node.get('is_group'),
#                     'unread': node.get('marked_as_unread'),
#                 })

#         all_thread_data = {}

#         for thread in threads:
#             try:
#                 insta_user = thread['users'][0]
#             except IndexError as ex:
#                 print(ex)
#                 raise

#             _insta_user = await check_insta_user(str(insta_user.get('id')),
#                                                     _session)
                
#             if not _insta_user:
#                 # try download photo
#                 photo_url = await download_profile_pic(insta_user)
#                 # print('PHOTO URL ✅',photo_url)
#                 insta_user['photo_url'] = photo_url
#                 # try add user
#                 _insta_user = await try_add_insta_user(insta_user,
#                                                         _session)
                    
#             user_insta_id = _insta_user.insta_id
#             thread_key = thread['thread_key']
#             # check thread in DB
#             current_thread = await check_thread_in_db(thread_key,
#                                                         _session)

#             if not current_thread:
#                 # add new thread
#                 thread_data = {
#                     'account_id': account_id,
#                     'insta_user_id': _insta_user.id,
#                     'thread_id': thread_key,
#                     'timestamp_last_seen_message': None,
#                     'is_unread': thread.get('unread'),
#                 }

#                 current_thread = await try_add_new_thread(thread_data,
#                                                             _session)

#             thread_responses.clear()
#             await enter_thread(page, thread_key, thread_received)

#             # Ждём ещё чтобы поймать все parts
#             await page.wait_for_timeout(2000)

#             # Фильтруем — оставляем только parts для НАШЕГО thread_key
#             matching_parts = []
#             for parts in thread_responses:
#                 for obj in parts:
#                     thread_data = (obj.get('data', {})
#                                     .get('get_slide_thread_nullable', {})
#                                     .get('as_ig_direct_thread', {}))
#                     # Сравниваем по thread_key или по users
#                     t_users = [u.get('interop_messaging_user_fbid')
#                             for u in thread_data.get('users', [])]
#                     if str(thread_key) in t_users:
#                         matching_parts.append(obj)

#             # Берём самый большой ответ — в нём больше всего сообщений
#             if matching_parts:
#                 best = max(matching_parts,
#                         key=lambda x: len(json.dumps(x)))
#                 all_thread_data[thread_key] = best

#                 # print('BEST', best)

#                 # Извлекаем сообщения
#                 thread_info = (best.get('data', {})
#                                 .get('get_slide_thread_nullable', {})
#                                 .get('as_ig_direct_thread', {}))
#                 messages = (thread_info.get('slide_messages', {})
#                                     .get('edges', []))

#                 messages_data = await process_thread_messages(messages,
#                                                              current_thread,
#                                                              user_insta_id,
#                                                              thread_key,
#                                                              save_dir='./media')
#                 await try_add_messages(messages_data,
#                                         current_thread,
#                                         _session)
#             else:
#                 print(f"  No matching data found")

#             await page.wait_for_timeout(2000)

#         ############# PARSE REQUEST MESSAGES AND SPAM THREADS #############

#         # После парсинга inbox — кликаем на requests:
#         await page.goto(
#             'https://www.instagram.com/direct/requests/',
#             wait_until='domcontentloaded'
#         )

#         try:
#             await asyncio.wait_for(request_message_received.wait(), timeout=15)
#             print("Message requests received!")
#         except asyncio.TimeoutError:
#             print("Message requests timeout")

#         await page.wait_for_timeout(2000)

#         # Парсим request треды — структура аналогична inbox
#         request_data = collected_data.get('PolarisDirectMessageRequestQuery', [])
#         request_threads = []

#         for obj in request_data:
#             # Пробуем оба возможных ключа в data
#             data = obj.get('data', {})
#             edges = (
#                 data.get('get_slide_mailbox_for_iris_subscription', {})
#                     .get('threads_by_folder', {})
#                     .get('edges', [])
#                 or
#                 data.get('viewer', {})
#                     .get('message_threads', {})
#                     .get('edges', [])
#             )
#             for edge in edges:
#                 node = edge['node'].get('as_ig_direct_thread', edge.get('node', {}))
#                 request_threads.append({
#                     'thread_key': node.get('thread_key'),
#                     'users': [u for u in node.get('users', [])],
#                     'last_activity': node.get('last_activity_timestamp_ms'),
#                     'is_group': node.get('is_group'),
#                     'unread': node.get('marked_as_unread'),
#                 })

#         print(f"Found {len(request_threads)} message request threads")

#         for thread in request_threads:
#             try:
#                 insta_user = thread['users'][0]
#             except IndexError:
#                 print(f"No users in request thread {thread.get('thread_key')}")
#                 continue

#             _insta_user = await check_insta_user(str(insta_user.get('id')), _session)

#             if not _insta_user:
#                 photo_url = await download_profile_pic(insta_user)
#                 insta_user['photo_url'] = photo_url
#                 _insta_user = await try_add_insta_user(insta_user, _session)

#             user_insta_id = _insta_user.insta_id
#             thread_key = thread['thread_key']
#             current_thread = await check_thread_in_db(thread_key, _session)

#             if not current_thread:
#                 thread_data = {
#                     'account_id': account_id,
#                     'insta_user_id': _insta_user.id,
#                     'thread_id': thread_key,
#                     'timestamp_last_seen_message': None,
#                     'is_unread': thread.get('unread'),
#                     'is_approved': False,
#                 }
#                 current_thread = await try_add_new_thread(thread_data, _session)

#             thread_responses.clear()
#             await enter_thread(page, thread_key, thread_received)

#             await page.wait_for_timeout(2000)

#             matching_parts = []
#             for parts in thread_responses:
#                 for obj in parts:
#                     thread_data = (obj.get('data', {})
#                                     .get('get_slide_thread_nullable', {})
#                                     .get('as_ig_direct_thread', {}))
#                     t_users = [u.get('interop_messaging_user_fbid')
#                                for u in thread_data.get('users', [])]
#                     if str(thread_key) in t_users:
#                         matching_parts.append(obj)

#             if matching_parts:
#                 best = max(matching_parts, key=lambda x: len(json.dumps(x)))

#                 thread_info = (best.get('data', {})
#                                 .get('get_slide_thread_nullable', {})
#                                 .get('as_ig_direct_thread', {}))
#                 messages = thread_info.get('slide_messages', {}).get('edges', [])

#                 messages_data = await process_thread_messages(
#                     messages, current_thread, user_insta_id, thread_key, save_dir='./media'
#                 )
#                 await try_add_messages(messages_data, current_thread, _session)
#             else:
#                 print(f"  No matching data found for request thread {thread_key}")

#             await page.wait_for_timeout(2000)


def extract_friendly_name(payload: str) -> str | None:
    for part in payload.split('&'):
        if 'friendly_name=' in part:
            return unquote(part.split('=', 1)[1])
    return None


def extract_variables(payload: str) -> dict | None:
    for part in payload.split('&'):
        if part.startswith('variables='):
            raw = unquote(part.split('=', 1)[1])
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return None
    return None


def parse_ig_response(text: str) -> list[dict]:
    results = []
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        for prefix in ['for (;;);', ')]}\'']:
            if line.startswith(prefix):
                line = line[len(prefix):]
        try:
            results.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return results


async def enter_thread(page, thread_key, thread_received, timeout=15):
    thread_received.clear()
    selector = f'a[href*="/direct/t/{thread_key}"]'
    try:
        await page.wait_for_selector(selector, timeout=5000)
        await page.click(selector)
    except Exception:
        await page.evaluate(f'window.location.assign("/direct/t/{thread_key}/")')

    try:
        await asyncio.wait_for(thread_received.wait(), timeout=timeout)
        print(f"Thread {thread_key} data received!")
    except asyncio.TimeoutError:
        print(f"Timeout for thread {thread_key}")

    await page.wait_for_timeout(2000)


def extract_media_urls(node: dict) -> list[dict]:
    content = node.get('content', {})
    typename = content.get('__typename', '')
    urls = []

    if typename == 'SlideMessageImageContent':
        for att in content.get('attachments', []):
            url = att.get('attachment_cdn_url') or att.get('preview_cdn_url')
            if url:
                urls.append({'url': url, 'type': 'image', 'ext': '.jpg'})

    elif typename == 'SlideMessageMultiMediaContent':
        for att in content.get('ordered_photo_video_attachments', []):
            url = att.get('attachment_cdn_url') or att.get('preview_cdn_url')
            if url:
                att_type = att.get('attachment_type', 2)
                if att_type == 4:
                    urls.append({'url': url, 'type': 'video', 'ext': '.mp4'})
                else:
                    urls.append({'url': url, 'type': 'image', 'ext': '.jpg'})

    elif typename == 'SlideMessageVideosContent':
        for vid in content.get('videos', []):
            video_url = vid.get('attachment_cdn_url')
            if video_url:
                urls.append({'url': video_url, 'type': 'video', 'ext': '.mp4'})
            preview = vid.get('preview_cdn_url')
            if preview:
                urls.append({'url': preview, 'type': 'video_preview', 'ext': '.jpg'})

    elif typename == 'SlideMessageAudiosContent':
        for audio in content.get('audio_attachments', []):
            audio_url = audio.get('attachment_cdn_url')
            if audio_url:
                urls.append({'url': audio_url, 'type': 'audio', 'ext': '.mp4'})

    return urls


async def download_media(urls: list[dict], save_dir: str, thread_key: str, msg_id: str):
    downloaded = []
    async with aiohttp.ClientSession() as session:
        for i, media in enumerate(urls):
            url = media['url']
            ext = media['ext']
            media_type = media['type']
            filename = f"{thread_key}_{msg_id}_{media_type}_{i}{ext}"
            filepath = os.path.join(save_dir, filename)
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        async with aiofiles.open(filepath, 'wb') as f:
                            await f.write(data)
                        
                        size_kb = len(data) / 1024
                        print(f"      Downloaded: {filename} ({size_kb:.1f} KB)")
                        if media_type in ('image', 'video_preview'):
                            media_type = 'photo'
                        downloaded.append((media_type, filepath))
                    else:
                        print(f"      Failed: {filename} — status {resp.status}")
            except Exception as e:
                print(f"      Error: {filename} — {e}")
    return downloaded


async def process_thread_messages(messages: list,
                                  thread: Thread,
                                  user_insta_id: str,
                                  thread_key: str):
    save_dir = MEDIA_PATH
    
    thread_dir = os.path.join(save_dir, str(thread_key))
    Path(thread_dir).mkdir(parents=True, exist_ok=True)

    result = {'thread_id': thread.id}
    all_messages = []
    mark_as_unread = None

    for msg in messages:
        node = msg['node']
        ctype = node.get('content_type', '?')
        msg_id = node.get('id', 'unknown')
        _ts = node.get('timestamp_ms', '')
        valid_ts = None

        _sender = node.get('sender')
        if _sender:
            _sender = _sender.get('igid')
        else:
            _sender = None

        if _ts:
            valid_ts = datetime.fromtimestamp(int(_ts) / 1000, tz=timezone.utc)

        try:
            if thread.timestamp_last_seen_message and thread.timestamp_last_seen_message >= valid_ts:
                print('ALL NEW MESSAGES', all_messages)
                break
        except Exception as ex:
            print(ex)
            raise

        msg_data = {
            'id': msg_id,
            'sender': 'user' if _sender == user_insta_id else 'assistant',
            'type': ctype,
            'timestamp': _ts,
            'text': None,
            'media_files': [],
        }

        mark_as_unread = _sender == user_insta_id

        if ctype == 'TEXT':
            text_body = node.get('text_body')
            content = node.get('content') or {}
            content_typename = content.get('__typename')
            # print(node)
            msg_data['text'] = node.get('text_body', '')

            if text_body:
                # обычное текстовое сообщение
                msg_data['text'] = text_body

            elif content_typename == 'SlideMessageAdminText':
                # системное сообщение (звонки и прочие служебные события)
                fragments = content.get('text_fragments') or []
                admin_text = ' '.join(
                    f.get('plaintext', '') for f in fragments
                ).strip()

                msg_data['text'] = admin_text
        elif ctype.startswith('REACTION'):
            # temporarily
            continue

        else:
            print('TYPE MESSAGE ->. ',ctype)
            media_urls = extract_media_urls(node)
            if media_urls:
                files = await download_media(media_urls, thread_dir, str(thread_key), msg_id)
                msg_data['media_files'] = files

        all_messages.append(msg_data)

    result['messages'] = all_messages
    result['mark_as_unread'] = mark_as_unread

    return result


async def download_profile_pic(user_data: dict):
    save_dir = MEDIA_PATH

    url = user_data.get('profile_pic_url')
    username = user_data.get('username', 'unknown')

    if not url:
        return None

    Path(save_dir).mkdir(parents=True, exist_ok=True)
    filepath = os.path.join(save_dir, f"{username}.jpg")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    async with aiofiles.open(filepath, 'wb') as f:
                        await f.write(data)
                    print(f"  Profile pic: {username}.jpg ({len(data)/1024:.1f} KB)")
                    return filepath
                else:
                    print(f"  Failed: {username} — status {resp.status}")
        except Exception as e:
            print(f"  Error: {username} — {e}")

    return None


async def human_pause(a=0.4, b=1.2):
    await asyncio.sleep(random.uniform(a, b))


# ===================== НОВЫЕ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====================

def extract_threads_from_inbox(data_list: list) -> list:
    threads = []
    last_message_ts = None

    for obj in data_list:
        edges = (obj.get('data', {})
                    .get('get_slide_mailbox_for_iris_subscription', {})
                    .get('threads_by_folder', {})
                    .get('edges', []))

        for edge in edges:
            node = edge['node'].get('as_ig_direct_thread', {})
            slide_messages = node.get('slide_messages').get('edges')

            if slide_messages:
                last_message = slide_messages[0].get('node')
                last_message_ts = last_message.get('timestamp_ms')

            threads.append({
                'thread_key': node.get('thread_key'),
                'users': list(node.get('users', [])),
                'last_activity': node.get('last_activity_timestamp_ms'),
                'is_group': node.get('is_group'),
                'unread': node.get('marked_as_unread'),
                'last_message_ts': last_message_ts,
            })
    return threads


def extract_threads_from_requests(data_list: list) -> tuple[list, list]:
    """Возвращает (request_threads, spam_threads)"""
    request_threads = []
    spam_threads = []

    for obj in data_list:
        data = obj.get('data', {})

        # Обычные requests
        for edge in (data.get('get_slide_mailbox_for_iris_subscription', {})
                         .get('threads_by_folder', {})
                         .get('edges', [])):
            node = edge['node'].get('as_ig_direct_thread', edge.get('node', {}))
            request_threads.append({
                'thread_key': node.get('thread_key'),
                'users': list(node.get('users', [])),
                'last_activity': node.get('last_activity_timestamp_ms'),
                'is_group': node.get('is_group'),
                'unread': node.get('marked_as_unread'),
            })

        # Spam
        for edge in (data.get('spamMailbox', {})
                         .get('threads_by_folder', {})
                         .get('edges', [])):
            node = edge['node'].get('as_ig_direct_thread', edge.get('node', {}))
            spam_threads.append({
                'thread_key': node.get('thread_key'),
                'users': list(node.get('users', [])),
                'last_activity': node.get('last_activity_timestamp_ms'),
                'is_group': node.get('is_group'),
                'unread': node.get('marked_as_unread'),
            })

    return request_threads, spam_threads


async def process_threads(
    threads: list,
    account_id: int,
    page,
    thread_responses: list,
    thread_received: asyncio.Event,
    _session: AsyncSession,
    is_request: bool = False,
    is_spam: bool = False,
) -> dict:
    all_thread_data = {}

    for thread in threads:
        last_message_ts = thread.get('last_message_ts')

        try:
            insta_user = thread['users'][0]
        except IndexError:
            print(f"No users in thread {thread.get('thread_key')}")
            if is_request or is_spam:
                continue
            raise

        _insta_user = await check_insta_user(str(insta_user.get('id')), _session)

        if not _insta_user:
            photo_url = await download_profile_pic(insta_user)
            insta_user['photo_url'] = photo_url
            _insta_user = await try_add_insta_user(insta_user, _session)

        user_insta_id = _insta_user.insta_id
        thread_key = thread['thread_key']
        current_thread = await check_thread_in_db(thread_key, _session)

        if not current_thread:
            thread_data = {
                'account_id': account_id,
                'insta_user_id': _insta_user.id,
                'thread_id': thread_key,
                'timestamp_last_seen_message': None,
                'is_unread': thread.get('unread'),
            }
            if is_request:
                thread_data['is_approved'] = False
            if is_spam:
                thread_data['is_approved'] = False
                # thread_data['is_spam'] = True

            current_thread = await try_add_new_thread(thread_data, _session)

        if last_message_ts and current_thread.timestamp_last_seen_message:
            last_message_ts = datetime.fromtimestamp(int(last_message_ts) / 1000, tz=timezone.utc)
            if last_message_ts <= current_thread.timestamp_last_seen_message:
                print('SKIP THIS THREAD CAUSE LAST MESSAGE IN RESPONSE EQUAL WITH LAST MESSAGE FROM DB')
                continue
        
        thread_responses.clear()
        await enter_thread(page, thread_key, thread_received)
        await page.wait_for_timeout(2000)

        matching_parts = []
        for parts in thread_responses:
            for obj in parts:
                td = (obj.get('data', {})
                         .get('get_slide_thread_nullable', {})
                         .get('as_ig_direct_thread', {}))
                t_users = [u.get('interop_messaging_user_fbid')
                           for u in td.get('users', [])]
                if str(thread_key) in t_users:
                    matching_parts.append(obj)

        if matching_parts:
            best = max(matching_parts, key=lambda x: len(json.dumps(x)))
            all_thread_data[thread_key] = best

            thread_info = (best.get('data', {})
                              .get('get_slide_thread_nullable', {})
                              .get('as_ig_direct_thread', {}))
            messages = thread_info.get('slide_messages', {}).get('edges', [])


            messages_data = await process_thread_messages(
                messages, current_thread, user_insta_id, thread_key
            )
            await try_add_messages(messages_data, current_thread, _session)
        else:
            print(f"  No matching data found for thread {thread_key}")

        await page.wait_for_timeout(2000)

    return all_thread_data


# ===================== ОСНОВНАЯ ФУНКЦИЯ =====================

async def test_playwright(account_id: int,
                          profile_port: int,
                          _session: AsyncSession):
    collected_data = {}
    thread_responses = []
    inbox_received = asyncio.Event()
    thread_received = asyncio.Event()
    request_message_received = asyncio.Event()

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(f'http://{VISION_BROWSER_HOST}:{profile_port}')
        print(f"CONNECTED ON {profile_port} PORT")

        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = context.pages[0] if context.pages else await context.new_page()

        async def on_response(response):
            req = response.request
            if req.resource_type not in ('xhr', 'fetch'):
                return
            url = response.url
            if '/api/graphql' not in url and '/graphql/query' not in url:
                return
            if not req.post_data:
                return

            friendly_name = extract_friendly_name(req.post_data)
            variables = extract_variables(req.post_data)

            # print(f"[ALL] {friendly_name} | folder: {variables.get('folder') if variables else '-'}")

            if friendly_name not in TARGET_QUERIES:
                return

            try:
                body = await response.text()
                parsed = parse_ig_response(body)

                key = friendly_name
                if variables and 'folder' in variables:
                    key = f"{friendly_name}:{variables['folder']}"

                if friendly_name == 'IGDThreadDetailQuery':
                    thread_responses.append(parsed)
                    thread_received.set()
                else:
                    collected_data[key] = parsed

                if friendly_name == 'PolarisDirectInboxQuery':
                    inbox_received.set()

                if friendly_name == 'PolarisDirectMessageRequestQuery':
                    request_message_received.set()

            except Exception as e:
                print(f"[ERROR] {friendly_name}: {e}")

        page.on("response", on_response)

        # === 1. Inbox ===

        current_url = page.url
        if 'instagram.com/direct/inbox' in current_url:
            await page.reload(wait_until='domcontentloaded')
        else:
            await page.goto('https://www.instagram.com/direct/inbox/',
                            wait_until='domcontentloaded')
            
        await dismiss_notifications_popup(page)

        try:
            await asyncio.wait_for(inbox_received.wait(), timeout=15)
            print("Inbox received!")
        except asyncio.TimeoutError:
            print("Inbox timeout")

        await page.wait_for_timeout(2000)

        inbox_threads = extract_threads_from_inbox(
            collected_data.get('PolarisDirectInboxQuery', [])
        )
        print(f"Found {len(inbox_threads)} inbox threads")
        await process_threads(inbox_threads, account_id, page,
                              thread_responses, thread_received, _session)

        # === 2. Message Requests + Spam ===

        request_message_received.clear()

        await page.goto('https://www.instagram.com/direct/requests/',
                        wait_until='domcontentloaded')

        try:
            await asyncio.wait_for(request_message_received.wait(), timeout=15)
            print("Message requests received!")
        except asyncio.TimeoutError:
            print("Message requests timeout")

        await page.wait_for_timeout(2000)

        request_threads, spam_threads = extract_threads_from_requests(
            collected_data.get('PolarisDirectMessageRequestQuery', [])
        )

        print(f"Found {len(request_threads)} request threads")
        await process_threads(request_threads, account_id, page,
                            thread_responses, thread_received, _session,
                            is_request=True)

        print(f"Found {len(spam_threads)} spam threads")
        await process_threads(spam_threads, account_id, page,
                            thread_responses, thread_received, _session,
                            is_spam=True)



async def approve_request_chat(page, thread_url: str):
    await page.goto(thread_url, wait_until="domcontentloaded")
    await asyncio.sleep(3)

    # role=button + текст ловит и <div role="button">, и <button>
    # accept_btn = page.get_by_role("button", name="Accept", exact=True)
    accept_btn = page.get_by_role("button", name=re.compile(r"Accept|ตอบรับ|ยอมรับ", re.I))

    if await accept_btn.count() == 0:
        print("ACCEPT NOT FOUND — чат уже подтверждён или другой язык интерфейса")
        return False

    await accept_btn.first.click()
    await asyncio.sleep(4)

    # Признак успеха: после Accept появляется композер — до подтверждения
    # в request-чате писать нельзя, поля ввода нет.
    try:
        await page.wait_for_selector('div[role="textbox"]', timeout=15000)
        print("чат подтверждён")
        return True
    except Exception:
        print("Accept нажат, но композер не появился — проверь вручную")
        return False


async def playwright_send_message(message: Message,
                                  profile_port: int,
                                  session: AsyncSession,
                                  media: str = None):
    send_success = False

    is_approved_thread = message.thread.is_approved

    # check new messages in this thread
    has_new_messages = await check_new_messages_in_thread(message,
                                                          session)
    
    if has_new_messages:
        message.status = MessageStatusEnum.REJECTED

        await execute_and_catch_db_error(session.commit(),
                                         session,
                                         with_rollback=True)
        print('STOP SEND MESSAGE, EXIST MORE FRESH MESSAGES IN CURRENT THREAD')
        return

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(f'http://{VISION_BROWSER_HOST}:{profile_port}')
        print(f"CONNECTED ON {profile_port} PORT")

        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = context.pages[0] if context.pages else await context.new_page()

        current_url = page.url
        if 'instagram.com/direct/inbox' in current_url or current_url == f'https://www.instagram.com/direct/t/{message.thread.thread_id}/':
            await page.reload(wait_until='domcontentloaded')
        else:
            await page.goto(
                f'https://www.instagram.com/direct/t/{message.thread.thread_id}/',
                wait_until='domcontentloaded'
            )

        await asyncio.sleep(3)

        await dismiss_notifications_popup(page)

        if not is_approved_thread:
            is_approved = await approve_request_chat(page,
                                                     page.url)
            
            await update_approve_thread(message.thread_id,
                                        is_approved,
                                        session)
            
            print('NEW APPROVE STATUS', is_approved)

        if media:
            match media:
                case 'photo':
                    _attachments = message.attachments
                    _attachment = _attachments[0]
                    media_url = _attachment.media_url

                    if media_url.startswith('./'):
                        media_url = media_url[2:]
                    if media_url.startswith('media/'):
                        media_url = media_url[len('media/'):]

                    media_url_for_send = f'{MEDIA_PATH}/{media_url}'

                    try:
                        inp = page.locator('input[type="file"]')

                        await inp.set_input_files(media_url_for_send)   # абсолютный путь
                        await asyncio.sleep(2.5)

                        # ждём появления превью вложения (кнопка "Remove")
                        await page.wait_for_selector(
                            'button[aria-label^="Remove"], [aria-label^="Remove"]',
                            timeout=20000)

                        # Отправка через Enter в композере
                        box = page.locator('div[role="textbox"]').last
                        await box.click()
                        await page.keyboard.press("Enter")

                        # Подтверждение: кнопка удаления вложения исчезла = ушло
                        await page.wait_for_selector(
                            'button[aria-label^="Remove"]',
                            state="detached", timeout=20000)
                        print("фото отправлено")
                        send_success = True
                    except Exception as ex:
                        print('ERROR WITH TRY SEND MESSAGE', ex)

                case _:
                    pass

        # if media:
        #     match media:
        #         case 'photo':
        #             _attachments = message.attachments
        #             _attachment = _attachments[0]
        #             media_url = _attachment.media_url

        #             if media_url.startswith('./'):
        #                 media_url = media_url[2:]
        #             if media_url.startswith('media/'):
        #                 media_url = media_url[len('media/'):]

        #             media_url_for_send = f'{MEDIA_PATH}/{media_url}'

        #             try:
        #                 inp = page.locator('input[type="file"]')

        #                 await inp.set_input_files(media_url_for_send)   # абсолютный путь
        #                 await asyncio.sleep(2.5)

        #                 # print("dialogs:", await page.locator('div[role="dialog"]').count())

        #                 await page.wait_for_selector(
        #                     'button[aria-label^="ลบไฟล์แนบ"], [aria-label^="ลบไฟล์แนบ"]',
        #                     timeout=20000)
        #                 # await human_pause(0.8, 2.0)

        #                 # Отправка через Enter в композере — обходит локализацию кнопки.
        #                 box = page.locator('div[role="textbox"]').last
        #                 await box.click()
        #                 await page.keyboard.press("Enter")

        #                 # Подтверждение: кнопка удаления вложения исчезла = ушло
        #                 await page.wait_for_selector(
        #                     'button[aria-label^="ลบไฟล์แนบ"]',
        #                     state="detached", timeout=20000)
        #                 # await human_pause(1.0, 2.0)
        #                 print("фото отправлено")
        #                 send_success = True
        #             except Exception as ex:
        #                 print('ERROR WITH TRY SEND MESSAGE', ex)
                    
        #         case _:
        #             pass
        else:
            try:
                message_text = message.text
                box = page.locator('div[role="textbox"]').last
                await box.click()                  # фокус — обязательно для Lexical
                await human_pause(0.3, 0.7)

                await box.type(message_text, delay=random.uniform(30, 90))   # человеческий ввод
                await human_pause(0.4, 1.0)

                await page.keyboard.press("Enter")

                # подтверждение: композер очистился = сообщение ушло
                await page.wait_for_function(
                    """() => {
                        const el = document.querySelectorAll('div[role="textbox"]');
                        const last = el[el.length - 1];
                        return last && last.innerText.trim() === '';
                    }""",
                    timeout=15000)
                await human_pause(0.8, 1.5)
                print("текст отправлен")
                send_success = True
            except Exception as ex:
                print(ex)
                pass
        
        if send_success:
            message.status = 'approved'
            ts = datetime.now(tz=timezone.utc)
            message.created_at = ts
            message.updated_at = ts
            message.thread.timestamp_last_seen_message = ts
            message.thread.is_unread = False

            await execute_and_catch_db_error(session.commit(),
                                             session,
                                             with_rollback=True)
