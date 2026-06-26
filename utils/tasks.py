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
                        execute_and_catch_db_error, update_approve_thread, update_thread_is_unread_by_id)

from db.base import Message, Thread

from utils.enums import MessageStatusEnum

from utils.base import dismiss_notifications_popup, generate_valid_media_url

from config import VISION_BROWSER_HOST, MEDIA_PATH

# === Конфигурация ===

TARGET_QUERIES = {
    'PolarisDirectInboxQuery',
    'useIGDSystemFolderUnreadThreadCountQuery',
    'IGDInboxTrayQuery',
    'IGDBadgeCountOffMsysQuery',
    'IGDThreadDetailQuery',
    'PolarisDirectMessageRequestQuery',
    'IGDMessageListOffMsysQuery',
    'IGDThreadListProfessionalOffMsysPaginationQuery',
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

# async def scroll_inbox_until_loaded(page, max_rounds=40, pause_ms=1500):
#     container_sel = '[data-pagelet="IGDInboxThreadListScrollableAreaPagelet"]'

#     prev_count = -1
#     stable = 0

#     for _ in range(max_rounds):
#         count = await page.locator('a[href^="/direct/t/"]').count()

#         if count == prev_count:
#             stable += 1
#             if stable >= 2:          # два круга подряд без прироста — дошли до конца
#                 break
#         else:
#             stable = 0
#         prev_count = count

#         # скроллим контейнер в самый низ
#         await page.evaluate(
#             """(sel) => {
#                 const el = document.querySelector(sel);
#                 if (el) el.scrollTop = el.scrollHeight;
#             }""",
#             container_sel
#         )

#         await page.wait_for_timeout(pause_ms)

#     return prev_count

async def scroll_inbox_until_loaded(page, max_rounds=40,
                                    wait_after_scroll=6.0, poll_interval=0.3):
    item_sel = 'div[role="button"]'   # чаты = div role=button (по твоим probe)

    scroll_js = """() => {
        // находим самый "длинный" скроллируемый контейнер на странице
        let best = null, max = 50;
        for (const c of document.querySelectorAll('*')) {
            const s = getComputedStyle(c);
            if (s.overflowY === 'auto' || s.overflowY === 'scroll') {
                const d = c.scrollHeight - c.clientHeight;
                if (d > max) { max = d; best = c; }
            }
        }
        if (!best) return {found: false};
        const before = best.scrollTop;
        best.scrollTop = best.scrollHeight;   // прыжок в самый низ
        return {found: true, before: before, after: best.scrollTop,
                sh: best.scrollHeight, ch: best.clientHeight};
    }"""

    prev = -1
    stable = 0
    for i in range(max_rounds):
        count = await page.locator(item_sel).count()
        if count == prev:
            stable += 1
            if stable >= 2:
                print(f"[scroll-inbox] stable at {count}, stop #{i}")
                break
        else:
            stable = 0
        prev = count

        res = await page.evaluate(scroll_js)
        print(f"[scroll-inbox #{i}] count={count} scroll={res}")

        # ждём прироста чатов
        waited = 0.0
        while waited < wait_after_scroll:
            await page.wait_for_timeout(int(poll_interval * 1000))
            waited += poll_interval
            if await page.locator(item_sel).count() > count:
                break

    return prev


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
            print('error!!!!')
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
    # print('LEN MESSAGES BEFORE SAVE', len(messages))
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

        _sender = node.get('sender_fbid')

        if not _sender:
            _sender = node.get('sender')
            if _sender:
                _sender = _sender.get('id')

        if _ts:
            valid_ts = datetime.fromtimestamp(int(_ts) / 1000, tz=timezone.utc)

        try:
            if thread.timestamp_last_seen_message and thread.timestamp_last_seen_message >= valid_ts:
                print(valid_ts, thread.timestamp_last_seen_message)
                print('ALL NEW MESSAGES', all_messages)
                break
        except Exception as ex:
            print(ex)
            raise
        
        # print('SENDERS', user_insta_id, type(user_insta_id), _sender, type(_sender))
        view_sender = 'user' if _sender == user_insta_id else 'assistant'
        # print(view_sender)

        msg_data = {
            'id': msg_id,
            'sender': view_sender,
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
            pass

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
    # username = user_data.get('username', 'unknown')

    base = (user_data.get('insta_id')
            or user_data.get('id')
            or user_data.get('interop_messaging_user_fbid'))

    if not url:
        return None

    # Path(save_dir).mkdir(parents=True, exist_ok=True)
    filename = f"{base}.jpg"
    filepath = os.path.join(save_dir, filename)

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    async with aiofiles.open(filepath, 'wb') as f:
                        await f.write(data)
                    print(f"  Profile pic: {base}.jpg ({len(data)/1024:.1f} KB)")
                    return filepath
                else:
                    print(f"  Failed: {base} — status {resp.status}")
        except Exception as e:
            print(f"  Error: {base} — {e}")

    return None


async def human_pause(a=0.4, b=1.2):
    await asyncio.sleep(random.uniform(a, b))


# ===================== НОВЫЕ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====================

# def extract_threads_from_inbox(data_list: list) -> list:
#     threads = []
#     last_message_ts = None

#     for obj in data_list:
#         edges = (obj.get('data', {})
#                     .get('get_slide_mailbox_for_iris_subscription', {})
#                     .get('threads_by_folder', {})
#                     .get('edges', []))

#         for edge in edges:
#             node = edge['node'].get('as_ig_direct_thread', {})
#             slide_messages = node.get('slide_messages').get('edges')

#             if slide_messages:
#                 last_message = slide_messages[0].get('node')
#                 last_message_ts = last_message.get('timestamp_ms')

#             threads.append({
#                 'thread_key': node.get('thread_key'),
#                 'users': list(node.get('users', [])),
#                 'last_activity': node.get('last_activity_timestamp_ms'),
#                 'is_group': node.get('is_group'),
#                 'unread': node.get('marked_as_unread'),
#                 'last_message_ts': last_message_ts,
#             })
#     return threads

# def extract_threads_from_inbox(data_list: list) -> list:
#     threads = []
#     last_message_ts = None

#     # нормализуем: разворачиваем вложенные списки страниц в плоский список объектов
#     flat = []
#     for item in data_list:
#         if isinstance(item, list):
#             flat.extend(item)        # это страница со списком объектов
#         else:
#             flat.append(item)        # это уже объект
#     data_list = flat

#     for obj in data_list:
#         if not isinstance(obj, dict):
#             continue                 # подстраховка от неожиданных типов
#         edges = (obj.get('data', {})
#                     .get('get_slide_mailbox_for_iris_subscription', {})
#                     .get('threads_by_folder', {})
#                     .get('edges', []))

#         for edge in edges:
#             node = edge['node'].get('as_ig_direct_thread', {})
#             slide_messages = node.get('slide_messages', {}).get('edges')

#             if slide_messages:
#                 last_message = slide_messages[0].get('node')
#                 last_message_ts = last_message.get('timestamp_ms')

#             threads.append({
#                 'thread_key': node.get('thread_key'),
#                 'users': list(node.get('users', [])),
#                 'last_activity': node.get('last_activity_timestamp_ms'),
#                 'is_group': node.get('is_group'),
#                 'unread': node.get('marked_as_unread'),
#                 'last_message_ts': last_message_ts,
#             })
#     return threads
# def extract_threads_from_inbox(data_list: list) -> list:
#     threads = []

#     # разворачиваем вложенные списки страниц в плоский список объектов
#     flat = []
#     for item in data_list:
#         if isinstance(item, list):
#             flat.extend(item)
#         else:
#             flat.append(item)

#     for obj in flat:
#         if not isinstance(obj, dict):
#             print("[extract] skip non-dict:", type(obj))   # ← диагностика
#             continue

#         data = obj.get('data', {}) or {}
#         print("[extract] data keys:", list(data.keys()))   # ← диагностика
#         # разные query кладут mailbox под разными корнями — проверяем оба
#         mailbox = (data.get('get_slide_mailbox_for_iris_subscription')
#                    or data.get('fetch__SlideMailbox')
#                    or {})
#         edges = mailbox.get('threads_by_folder', {}).get('edges', [])

#         print("[extract] mailbox keys:", list(mailbox.keys()), "edges:", len(edges))  # ← диагностика

#         for edge in edges:
#             node = (edge.get('node', {}) or {}).get('as_ig_direct_thread', {})
#             if not node:
#                 continue

#             # last_message_ts — ЛОКАЛЬНО для каждого треда (важно!)
#             last_message_ts = None
#             sm = node.get('slide_messages', {}).get('edges')
#             if sm:
#                 last_message = sm[0].get('node') or {}
#                 last_message_ts = last_message.get('timestamp_ms')

#             users = list(node.get('users', []))
#             first_user = users[0] if users else {}

#             threads.append({
#                 'thread_id': node.get('thread_id'),          # ← БЫЛО ПРОПУЩЕНО
#                 'thread_fbid': node.get('thread_fbid'),
#                 'thread_key': node.get('thread_key'),
#                 'thread_title': node.get('thread_title'),
#                 'folder': node.get('folder'),
#                 'system_folder': node.get('system_folder'),
#                 'users': users,
#                 'username': first_user.get('username'),
#                 'full_name': first_user.get('full_name'),
#                 'interop_messaging_user_fbid': first_user.get('interop_messaging_user_fbid'),
#                 'last_activity': node.get('last_activity_timestamp_ms'),
#                 'is_group': node.get('is_group'),
#                 'unread': node.get('marked_as_unread'),
#                 'last_message_ts': last_message_ts,
#             })
#     return threads

def _collect_edges(node):
    """Рекурсивно собирает все списки 'edges' из произвольно вложенной структуры."""
    found = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == 'edges' and isinstance(v, list):
                found.extend(v)
            else:
                found.extend(_collect_edges(v))
    elif isinstance(node, list):
        for item in node:
            found.extend(_collect_edges(item))
    return found


def extract_threads_from_inbox(data_list: list) -> list:
    threads = []
    flat = []
    for item in data_list:
        if isinstance(item, list):
            flat.extend(item)
        else:
            flat.append(item)

    for obj in flat:
        if not isinstance(obj, dict):
            continue
        data = obj.get('data', {}) or {}
        mailbox = (data.get('get_slide_mailbox_for_iris_subscription')
                   or data.get('fetch__SlideMailbox')
                   or {})

        # 1) основной путь — threads_by_folder (первый экран)
        edges = mailbox.get('threads_by_folder', {}).get('edges', [])

        # 2) пагинация кладёт под threads_by_system_folder_and_ig_inbox_folder,
        #    структура вложенная — собираем edges рекурсивно
        if not edges:
            tbsf = mailbox.get('threads_by_system_folder_and_ig_inbox_folder')
            if tbsf:
                edges = _collect_edges(tbsf)

        for edge in edges:
            node = (edge.get('node', {}) or {}).get('as_ig_direct_thread', {})
            if not node:
                # покажем, что реально в edge
                print("[extract] edge node keys:", list((edge.get('node', {}) or {}).keys()))
                continue

            last_message_ts = None
            sm = node.get('slide_messages', {}).get('edges')
            if sm:
                last_message = sm[0].get('node') or {}
                last_message_ts = last_message.get('timestamp_ms')

            users = list(node.get('users', []))
            first_user = users[0] if users else {}

            threads.append({
                'thread_id': node.get('thread_id'),
                'thread_fbid': node.get('thread_fbid'),
                'thread_key': node.get('thread_key'),
                'thread_title': node.get('thread_title'),
                'folder': node.get('folder'),
                'system_folder': node.get('system_folder'),
                'users': users,
                'username': first_user.get('username'),
                'full_name': first_user.get('full_name'),
                'interop_messaging_user_fbid': first_user.get('interop_messaging_user_fbid'),
                'last_activity': node.get('last_activity_timestamp_ms'),
                'is_group': node.get('is_group'),
                'unread': node.get('marked_as_unread'),
                'last_message_ts': last_message_ts,
            })
    return threads


# def extract_threads_from_requests(data_list: list) -> tuple[list, list]:
#     """Возвращает (request_threads, spam_threads)"""
#     request_threads = []
#     spam_threads = []
#     last_message_ts = None

#     for obj in data_list:
#         data = obj.get('data', {})

#         # Обычные requests
#         for edge in (data.get('get_slide_mailbox_for_iris_subscription', {})
#                          .get('threads_by_folder', {})
#                          .get('edges', [])):
#             node = edge['node'].get('as_ig_direct_thread', edge.get('node', {}))
#             slide_messages = node.get('slide_messages').get('edges')

#             if slide_messages:
#                 last_message = slide_messages[0].get('node')
#                 last_message_ts = last_message.get('timestamp_ms')

#             request_threads.append({
#                 'thread_key': node.get('thread_key'),
#                 'users': list(node.get('users', [])),
#                 'last_activity': node.get('last_activity_timestamp_ms'),
#                 'is_group': node.get('is_group'),
#                 'unread': node.get('marked_as_unread'),
#                 'last_message_ts': last_message_ts,
#             })

#         # Spam
#         for edge in (data.get('spamMailbox', {})
#                          .get('threads_by_folder', {})
#                          .get('edges', [])):
#             node = edge['node'].get('as_ig_direct_thread', edge.get('node', {}))
#             slide_messages = node.get('slide_messages').get('edges')

#             if slide_messages:
#                 last_message = slide_messages[0].get('node')
#                 last_message_ts = last_message.get('timestamp_ms')
                
#             spam_threads.append({
#                 'thread_key': node.get('thread_key'),
#                 'users': list(node.get('users', [])),
#                 'last_activity': node.get('last_activity_timestamp_ms'),
#                 'is_group': node.get('is_group'),
#                 'unread': node.get('marked_as_unread'),
#                 'last_message_ts': last_message_ts,
#             })

#     return request_threads, spam_threads
def extract_threads_from_requests(data_list: list) -> tuple[list, list]:
    """Возвращает (request_threads, spam_threads)"""
    request_threads = []
    spam_threads = []

    # нормализуем: разворачиваем вложенные списки страниц в плоский список объектов
    flat = []
    for item in data_list:
        if isinstance(item, list):
            flat.extend(item)
        else:
            flat.append(item)
    data_list = flat

    def build_thread(node: dict) -> dict:
        slide_messages = node.get('slide_messages', {}).get('edges')
        last_message_ts = None
        if slide_messages:
            last_message = slide_messages[0].get('node', {})
            last_message_ts = last_message.get('timestamp_ms')
        return {
            'thread_key': node.get('thread_key'),
            'users': list(node.get('users', [])),
            'last_activity': node.get('last_activity_timestamp_ms'),
            'is_group': node.get('is_group'),
            'unread': node.get('marked_as_unread'),
            'last_message_ts': last_message_ts,
        }

    for obj in data_list:
        if not isinstance(obj, dict):
            continue
        data = obj.get('data', {})

        # Обычные requests
        for edge in (data.get('get_slide_mailbox_for_iris_subscription', {})
                         .get('threads_by_folder', {})
                         .get('edges', [])):
            node = edge['node'].get('as_ig_direct_thread', edge.get('node', {}))
            request_threads.append(build_thread(node))

        # Spam
        for edge in (data.get('spamMailbox', {})
                         .get('threads_by_folder', {})
                         .get('edges', [])):
            node = edge['node'].get('as_ig_direct_thread', edge.get('node', {}))
            spam_threads.append(build_thread(node))

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
        last_activity = thread.get('last_activity')

        try:
            insta_user = thread['users'][0]
        except IndexError:
            # print(f"No users in thread {thread.get('thread_key')}")
            if is_request or is_spam:
                continue
            insta_user = {
                'username': thread['username'],
                'full_name': thread['full_name'],
                'interop_messaging_user_fbid': thread['interop_messaging_user_fbid'],
            }
            if not insta_user:
                continue
            # else:

        _insta_user = await check_insta_user(str(insta_user.get('interop_messaging_user_fbid')),
                                             _session)

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
            _last_activity = datetime.fromtimestamp(int(last_activity) / 1000, tz=timezone.utc)
            if current_thread.thread_id == '18071988617254182':
                print('тут 22',last_message_ts, _last_activity, current_thread.timestamp_last_seen_message)

            if last_message_ts <= current_thread.timestamp_last_seen_message:
                print('SKIP THIS THREAD CAUSE LAST MESSAGE IN RESPONSE EQUAL WITH LAST MESSAGE FROM DB')
                # if current_thread.thread_id == '18071988617254182':
                #     print(last_message_ts, current_thread.timestamp_last_seen_message)
                #     print('SKIP THIS THREAD CAUSE LAST MESSAGE IN RESPONSE EQUAL WITH LAST MESSAGE FROM DB')
                #     print()
                continue
            else:
                current_thread.is_unread = True
                # await update_thread_is_unread_by_id(current_thread.id,
                #                                     _session)
        
        else:
            current_thread.is_unread = True
            # await update_thread_is_unread_by_id(current_thread.id,
            #                                     _session)
            # current_thread.is_unread = True
        await execute_and_catch_db_error(_session.commit(),
                                          _session,
                                          with_rollback=True)
            # continue
        
    #     thread_responses.clear()
    #     await enter_thread(page, thread_key, thread_received)
    #     await page.wait_for_timeout(2000)

    #     matching_parts = []
    #     for parts in thread_responses:
    #         for obj in parts:
    #             td = (obj.get('data', {})
    #                      .get('get_slide_thread_nullable', {})
    #                      .get('as_ig_direct_thread', {}))
    #             t_users = [u.get('interop_messaging_user_fbid')
    #                        for u in td.get('users', [])]
    #             if str(thread_key) in t_users:
    #                 matching_parts.append(obj)

    #     if matching_parts:
    #         best = max(matching_parts, key=lambda x: len(json.dumps(x)))
    #         all_thread_data[thread_key] = best

    #         thread_info = (best.get('data', {})
    #                           .get('get_slide_thread_nullable', {})
    #                           .get('as_ig_direct_thread', {}))
    #         messages = thread_info.get('slide_messages', {}).get('edges', [])


    #         messages_data = await process_thread_messages(
    #             messages, current_thread, user_insta_id, thread_key
    #         )
    #         await try_add_messages(messages_data, current_thread, _session)
    #     else:
    #         print(f"  No matching data found for thread {thread_key}")

    #     await page.wait_for_timeout(2000)

    # return all_thread_data

def _extract_slide_thread(obj: dict) -> dict:
    data = obj.get('data', {})
    return (data.get('get_slide_thread_nullable')
            or data.get('fetch__SlideThread')
            or {}).get('as_ig_direct_thread', {})


def oldest_ts_from_thread_responses(thread_responses: list, thread_key=None) -> int | None:
    oldest = None
    for parts in thread_responses:
        for obj in parts:
            td = _extract_slide_thread(obj)
            # при желании фильтруем по нужному треду (как в твоём matching_parts)
            if thread_key is not None:
                users = [u.get('interop_messaging_user_fbid') for u in td.get('users', [])]
                if str(thread_key) not in users:
                    continue
            for edge in td.get('slide_messages', {}).get('edges', []):
                ts = edge.get('node', {}).get('timestamp_ms')
                if ts is not None:
                    ts = int(ts)
                    if oldest is None or ts < oldest:
                        oldest = ts
    return oldest


def has_more_older_messages(thread_responses: list, thread_key=None) -> bool:
    found_any = False
    has_next = False
    for parts in thread_responses:
        for obj in parts:
            td = _extract_slide_thread(obj)
            if thread_key is not None:
                users = [u.get('interop_messaging_user_fbid') for u in td.get('users', [])]
                if str(thread_key) not in users:
                    continue
            page_info = td.get('slide_messages', {}).get('page_info', {})
            if page_info:
                found_any = True
                has_next = bool(page_info.get('has_next_page', False))
    # если ни одной страницы ещё не пришло — считаем, что грузить можно
    return has_next if found_any else True


# async def scroll_messages_until_seen(page, thread_responses, thread_key,
#                                      last_seen_ts=None,
#                                      max_rounds=50, pause_ms=3000):
#     container_sel = '[data-pagelet="IGDMessagesList"]'
#     last_seen = int(last_seen_ts) if last_seen_ts else None

#     for _ in range(max_rounds):
#         if last_seen is not None:
#             oldest = oldest_ts_from_thread_responses(thread_responses, thread_key)
#             if oldest is not None and oldest <= last_seen:
#                 break

#         if not has_more_older_messages(thread_responses, thread_key):
#             break

#         await page.evaluate(
#             "(sel) => { const el = document.querySelector(sel); if (el) el.scrollTop = 0; }",
#             container_sel
#         )
#         await page.wait_for_timeout(pause_ms)

# async def scroll_messages_until_seen(page, thread_responses, thread_key,
#                                      last_seen_ts=None,
#                                      max_rounds=50, pause_ms=3000):
#     last_seen = int(last_seen_ts) if last_seen_ts else None

#     box = await page.query_selector('[data-pagelet="IGDMessagesList"]')
#     b = await box.bounding_box() if box else None
#     if not b:
#         print("[scroll] messages container not found")
#         return

#     cx = b['x'] + b['width'] / 2
#     cy = b['y'] + b['height'] / 2

#     prev_oldest = None
#     stable = 0

#     for i in range(max_rounds):
#         oldest = oldest_ts_from_thread_responses(thread_responses, thread_key)
#         more = has_more_older_messages(thread_responses, thread_key)

#         if last_seen is not None and oldest is not None and oldest <= last_seen:
#             break
#         if not more:
#             break

#         # детект застоя: если самый старый таймстемп не меняется несколько кругов — выходим
#         if oldest == prev_oldest:
#             stable += 1
#             if stable >= 4:
#                 print("[scroll] no progress, stop")
#                 break
#         else:
#             stable = 0
#         prev_oldest = oldest

#         # реальный скролл колесом вверх
#         await page.mouse.move(cx, cy)
#         await page.mouse.wheel(0, -500)        # вверх
#         print(f"[scroll #{i}] responses={len(thread_responses)} oldest={oldest}")

#         await page.wait_for_timeout(pause_ms)


async def scroll_messages_until_seen(page, thread_responses, thread_key,
                                     last_seen_ts=None, max_rounds=200,
                                     wait_after_scroll=8.0, poll_interval=0.3):
    # last_seen = int(last_seen_ts) if last_seen_ts else None
    if last_seen_ts is None:
        last_seen = None
    elif isinstance(last_seen_ts, datetime):
        last_seen = int(last_seen_ts.timestamp() * 1000)
    else:
        last_seen = int(last_seen_ts)
    container_sel = '[data-pagelet="IGDMessagesList"]'

    # JS: находит скроллящийся reverse-контейнер ленты и гонит его к границе старых сообщений.
    # В reverse-ленте (column-reverse) scrollTop отрицательный: 0 = низ (свежие),
    # минимум = -(scrollHeight - clientHeight) = верх (старые).
    scroll_js = """(sel) => {
        const root = document.querySelector(sel) || document.body;
        const candidates = [root, ...root.querySelectorAll('*')];
        let target = null, maxDelta = 20;
        for (const el of candidates) {
            const s = getComputedStyle(el);
            const scrollable = (s.overflowY === 'auto' || s.overflowY === 'scroll');
            const delta = el.scrollHeight - el.clientHeight;
            if (scrollable && delta > maxDelta) { target = el; maxDelta = delta; }
        }
        if (!target) return {found: false};

        const before = target.scrollTop;
        const minScroll = -(target.scrollHeight - target.clientHeight);  // граница старых

        // жёстко прыгаем к самым старым из загруженных
        target.scrollTop = minScroll;

        // несколько wheel-импульсов "в стену" у границы — reverse-ленты часто
        // триггерят догрузку именно по событию колеса, а не по достижению scrollTop
        for (let k = 0; k < 4; k++) {
            target.dispatchEvent(new WheelEvent('wheel',
                {deltaY: -300, bubbles: true, cancelable: true}));
        }

        return {found: true, before: before, after: target.scrollTop,
                min: minScroll, sh: target.scrollHeight, ch: target.clientHeight};
    }"""

    for i in range(max_rounds):
        oldest = oldest_ts_from_thread_responses(thread_responses, thread_key)
        more = has_more_older_messages(thread_responses, thread_key)

        if last_seen is not None and oldest is not None and oldest <= last_seen:
            print(f"[scroll] reached last_seen at #{i}")
            break
        if not more:
            print(f"[scroll] no more older at #{i}")
            break

        count_before = len(thread_responses)

        res = await page.evaluate(scroll_js, container_sel)
        await page.wait_for_timeout(200)
        print(f"[scroll #{i}] responses={count_before} oldest={oldest} scroll={res}")

        # ждём прироста ответов, а не фиксированную паузу
        waited = 0.0
        while len(thread_responses) == count_before and waited < wait_after_scroll:
            await page.wait_for_timeout(int(poll_interval * 1000))
            waited += poll_interval

        if len(thread_responses) == count_before:
            print(f"[scroll] no new response at #{i}, stop")
            break

# async def scroll_messages_until_seen(page, thread_responses, thread_key,
#                                      last_seen_ts=None,
#                                      max_rounds=50,
#                                      wait_after_scroll=6.0,   # макс. ждём ответ после скролла, сек
#                                      poll_interval=0.3):
#     last_seen = int(last_seen_ts) if last_seen_ts else None

#     box = await page.query_selector('[data-pagelet="IGDMessagesList"]')
#     b = await box.bounding_box() if box else None
#     if not b:
#         print("[scroll] messages container not found")
#         return

#     cx = b['x'] + b['width'] / 2
#     cy = b['y'] + b['height'] / 2

#     for i in range(max_rounds):
#         oldest = oldest_ts_from_thread_responses(thread_responses, thread_key)
#         more = has_more_older_messages(thread_responses, thread_key)

#         if last_seen is not None and oldest is not None and oldest <= last_seen:
#             print(f"[scroll] reached last_seen at #{i}")
#             break
#         if not more:
#             print(f"[scroll] no more older messages at #{i}")
#             break

#         # запоминаем, сколько ответов было ДО скролла
#         count_before = len(thread_responses)

#         # скроллим вверх
#         await page.mouse.move(cx, cy)
#         await page.mouse.wheel(0, -500)
#         print(f"[scroll #{i}] responses={count_before} oldest={oldest}")

#         # ждём, пока придёт новая страница (responses вырастет) или истечёт таймаут
#         waited = 0.0
#         while len(thread_responses) == count_before and waited < wait_after_scroll:
#             await page.wait_for_timeout(int(poll_interval * 1000))
#             waited += poll_interval

#         if len(thread_responses) == count_before:
#             # за таймаут ничего не пришло — подгрузки больше нет
#             print(f"[scroll] no new response after scroll, stop at #{i}")
#             break



# async def process_thread(
#     thread: Thread,
#     account_id: int,
#     page,
#     thread_responses: list,
#     thread_received: asyncio.Event,
#     _session: AsyncSession,
#     is_request: bool = False,
#     is_spam: bool = False,
# ) -> dict:
#     all_thread_data = {}
#     thread_key = thread.thread_id
#     user_insta_id = thread.insta_user.insta_id

#     print('LEN THREAD RESPONSE BEFORE SCROLLING', len(thread_responses))

#     await scroll_messages_until_seen(
#         page, thread_responses, thread_key,
#         last_seen_ts=thread.timestamp_last_seen_message
#     )
#     await page.wait_for_timeout(500)

#     print('LEN THREAD RESPONSE AFTER SCROLLING', len(thread_responses))

#     merged = {}
#     print('LOOK -> ',thread_responses)

#     # try:
#     #     with open('./thread_responses_dump.json', 'w', encoding='utf-8') as f:
#     #         json.dump(thread_responses, f, ensure_ascii=False, indent=2)
#     #     print('DUMPED to thread_responses_dump.json')
#     # except Exception as e:
#     #     print('DUMP ERROR:', e)

#     # return

#     for parts in thread_responses:
#         for obj in parts:
#             td = _extract_slide_thread(obj)
#             users = [u.get('interop_messaging_user_fbid') for u in td.get('users', [])]
#             if str(thread_key) not in users:
#                 continue
#             for edge in td.get('slide_messages', {}).get('edges', []):
#                 node = edge.get('node', {})
#                 mid = node.get('id') or node.get('message_id')
#                 if mid:
#                     merged[mid] = edge          # дедуп по message_id

#     if merged:
#         # сортируем по времени убыванию — как в исходном порядке Instagram
#         messages = sorted(
#             merged.values(),
#             key=lambda e: int(e['node'].get('timestamp_ms', 0)),
#             reverse=True
#         )
#         messages_data = await process_thread_messages(
#             messages, thread, user_insta_id, thread_key
#         )
#         await try_add_messages(messages_data, thread, _session)
#     else:
#         print(f"No matching data found for thread {thread_key}")
async def process_thread(
    thread: Thread,
    account_id: int,
    page,
    thread_responses: list,
    thread_received: asyncio.Event,
    _session: AsyncSession,
    is_request: bool = False,
    is_spam: bool = False,
) -> dict:
    all_thread_data = {}
    thread_key = thread.thread_id
    user_insta_id = thread.insta_user.insta_id

    # print('LEN THREAD RESPONSE BEFORE SCROLLING', len(thread_responses))

    await scroll_messages_until_seen(
        page, thread_responses, thread_key,
        last_seen_ts=thread.timestamp_last_seen_message
    )
    await page.wait_for_timeout(500)

    # print('LEN THREAD RESPONSE AFTER SCROLLING', len(thread_responses))

    # 1) находим thread_fbid целевого треда по детальным ответам.
    #    detail-ответы (get_slide_thread_nullable) содержат users с
    #    interop_messaging_user_fbid == thread_key. Берём их thread_fbid.
    target_fbid = None
    for parts in thread_responses:
        if not isinstance(parts, list):
            parts = [parts]
        for obj in parts:
            if not isinstance(obj, dict):
                continue
            td = _extract_slide_thread(obj)
            if not td:
                continue
            users = [u.get('interop_messaging_user_fbid') for u in td.get('users', [])]
            if str(thread_key) in users:
                # thread_fbid лежит и на уровне треда, и в каждом node
                target_fbid = str(td.get('thread_fbid') or td.get('id') or '')
                if target_fbid:
                    break
        if target_fbid:
            break

    # 2) собираем edges. Фильтр по node.thread_fbid — он есть и в detail,
    #    и в пагинации (fetch__SlideThread), где блока users нет.
    merged = {}
    test_list = []
    for parts in thread_responses:
        if not isinstance(parts, list):
            parts = [parts]
        for obj in parts:
            if not isinstance(obj, dict):
                continue
            td = _extract_slide_thread(obj)
            if not td:
                continue
            for edge in td.get('slide_messages', {}).get('edges', []):
                node = edge.get('node', {})
                # print('RAW MESSAGE', node)
                test_list.append(node)
                # отсекаем чужие префетченные треды (Elly, Антон и т.д.)
                if target_fbid and str(node.get('thread_fbid')) != target_fbid:
                    continue
                mid = node.get('message_id') or node.get('id')
                if mid:
                    merged[mid] = edge          # дедуп по message_id
    
    # with open("./data.json", "w", encoding="utf-8") as f:
    #     json.dump(merged, f, ensure_ascii=False, indent=4)

    if merged:
        # новые → старые
        messages = sorted(
            merged.values(),
            key=lambda e: int(e['node'].get('timestamp_ms', 0)),
            reverse=True
        )
        messages_data = await process_thread_messages(
            messages, thread, user_insta_id, thread_key
        )
        await try_add_messages(messages_data, thread, _session)
    else:
        print(f"No matching data found for thread {thread_key}")


# async def get_inbox_tabs(page):
#     """
#     Возвращает список доступных вкладок инбокса.
#     Если разделения нет — вернёт пустой список (это норма).
#     """
#     found = []
#     for name in ("Primary", "General", "Request"):
#         # Request имеет меняющийся счётчик 'Request (N)' — матчим по префиксу
#         loc = page.get_by_role("span", name=re.compile(rf"^{name}")).first
#         try:
#             if await loc.count() and await loc.is_visible():
#                 found.append(name)
#         except Exception:
#             pass
#     return found


# async def switch_inbox_tab(page, tab_name: str) -> bool:
#     """
#     Переключает на вкладку. True — переключились, False — вкладки нет.
#     Отсутствие вкладки НЕ ошибка: аккаунт без разделения инбокса.
#     """
#     loc = page.get_by_role("span", name=re.compile(rf"^{tab_name}")).first
#     try:
#         if not (await loc.count() and await loc.is_visible()):
#             print(f"[tab] '{tab_name}' отсутствует — пропускаем")
#             return False
#         await loc.scroll_into_view_if_needed()
#         await loc.click()
#         await page.wait_for_timeout(1200)
#         print(f"[tab] переключились на '{tab_name}'")
#         return True
#     except Exception as e:
#         print(f"[tab] клик по '{tab_name}' не удался: {e}")
#         return False

async def get_inbox_tabs(page):
    """
    Возвращает список доступных вкладок инбокса (Primary/General/Request).
    Пустой список — разделения нет (норма).
    """
    found = []
    for name in ("General", "Request"):
        # Request имеет счётчик 'Request (N)' — exact=False ловит по подстроке
        loc = page.get_by_text(name, exact=(name != "Request")).first
        try:
            if await loc.count() and await loc.is_visible():
                found.append(name)
        except Exception:
            pass
    return found


async def switch_inbox_tab(page, tab_name: str) -> bool:
    """
    Переключает на вкладку по тексту. True — переключились, False — вкладки нет.
    """
    loc = page.get_by_text(tab_name, exact=(tab_name != "Request")).first
    try:
        if not (await loc.count() and await loc.is_visible()):
            print(f"[tab] '{tab_name}' отсутствует — пропускаем")
            return False
        await loc.scroll_into_view_if_needed()
        await loc.click()
        await page.wait_for_timeout(1200)
        print(f"[tab] переключились на '{tab_name}'")
        return True
    except Exception as e:
        print(f"[tab] клик по '{tab_name}' не удался: {e}")
        return False


async def iterate_inbox_folders(page, inbox_received, collected_data):
    """
    Проходит по всем вкладкам инбокса и скроллит каждую.
    Если вкладок нет — скроллит текущий единый список один раз.
    """
    tabs = await get_inbox_tabs(page)

    # нет разделения на вкладки — обычный единый инбокс
    if not tabs:
        print("[inbox] вкладок нет, единый список")
        await scroll_inbox_until_loaded(page)
        return

    # есть вкладки — обходим интересующие (Request обычно пропускают)
    # target_tabs = [t for t in tabs if t in ("Primary", "General")]
    # print(f"[inbox] вкладки: {tabs}, обходим: {target_tabs}")

    # for tab in target_tabs:
    switched = await switch_inbox_tab(page, "General")
    if not switched:
        pass
    inbox_received.clear()
    try:
        await asyncio.wait_for(inbox_received.wait(), timeout=15)
    except asyncio.TimeoutError:
        print(f"[inbox] таймаут ожидания ответа для General")
    await scroll_inbox_until_loaded(page)


# def collect_all_inbox_threads(collected_data):
#     all_threads = []
#     for key, value in collected_data.items():
#         if key.startswith('PolarisDirectInboxQuery'):
#             all_threads.extend(extract_threads_from_inbox(value))
#     # дедуп по thread_id, т.к. в теории чат может попасть в разные folder
#     seen, result = set(), []
#     for t in all_threads:
#         tid = t.get('thread_id')
#         if tid and tid not in seen:
#             seen.add(tid)
#             result.append(t)
#     return result

# def collect_all_inbox_threads(collected_data):
#     # диагностика — какие ключи реально есть
#     print("[collect] keys:", list(collected_data.keys()))
#     for k, v in collected_data.items():
#         print(f"[collect] {k}: type={type(v)}, len={len(v) if isinstance(v, list) else 'n/a'}")

#     all_threads = []
#     for key, value in collected_data.items():
#         if key.startswith('PolarisDirectInboxQuery'):
#             extracted = extract_threads_from_inbox(value)
#             print(f"[collect] from {key}: {len(extracted)} threads")
#             all_threads.extend(extracted)

#     seen, result = set(), []
#     for t in all_threads:
#         tid = t.get('thread_id')
#         if tid and tid not in seen:
#             seen.add(tid)
#             result.append(t)
#     print(f"[collect] total after dedup: {len(result)}")
#     return result

# def collect_all_inbox_threads(collected_data):
#     all_threads = []
#     for key, value in collected_data.items():
#         # и PolarisDirectInboxQuery, и пагинация fetch__SlideMailbox
#         if key.startswith('PolarisDirectInboxQuery') or key.startswith('SlideMailboxPages'):
#             all_threads.extend(extract_threads_from_inbox(value))

#     seen, result = set(), []
#     for t in all_threads:
#         tid = t.get('thread_id')
#         if tid and tid not in seen:
#             seen.add(tid)
#             result.append(t)
#     return result

def collect_all_inbox_threads(collected_data):
    all_threads = []
    for key, value in collected_data.items():
        if key.startswith('PolarisDirectInboxQuery') or key.startswith('SlideMailboxPages'):
            extracted = extract_threads_from_inbox(value)
            # print(f"[collect] {key}: pages={len(value)}, threads={len(extracted)}")  # ← диагностика
            all_threads.extend(extracted)

    seen, result = set(), []
    for t in all_threads:
        tid = t.get('thread_id')
        if tid and tid not in seen:
            seen.add(tid)
            result.append(t)
    # print(f"[collect] total after dedup: {len(result)}")

    # with open("./data_t.json", "w", encoding="utf-8") as f:
    #     json.dump(all_threads, f, ensure_ascii=False, indent=4)

    return result


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
                    if friendly_name:
                        print(f"[REQ] {friendly_name}")

                    variables = extract_variables(req.post_data)

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

                        # пагинация списка чатов (бизнес-аккаунт) — накапливаем отдельно
                        elif friendly_name == 'IGDThreadListProfessionalOffMsysPaginationQuery':
                            # разовая диагностика структуры
                            try:
                                sample = parsed[0] if isinstance(parsed, list) and parsed else parsed
                                if isinstance(sample, dict):
                                    print("[mailbox-page] data keys:", list(sample.get('data', {}).keys()))
                            except Exception:
                                pass
                            collected_data.setdefault('SlideMailboxPages', []).append(parsed)

                        else:
                            collected_data.setdefault(key, []).append(parsed)

                        if friendly_name == 'PolarisDirectInboxQuery':
                            inbox_received.set()

                        if friendly_name == 'PolarisDirectMessageRequestQuery':
                            request_message_received.set()

                    except Exception as e:
                        print(f"[ERROR] {friendly_name}: {e}")

        # async def on_response(response):
        #     req = response.request
        #     if req.resource_type not in ('xhr', 'fetch'):
        #         return
        #     url = response.url
        #     if '/api/graphql' not in url and '/graphql/query' not in url:
        #         return
        #     if not req.post_data:
        #         return
        #     fn = extract_friendly_name(req.post_data) if req.post_data else None
        #     if fn:
        #         print(f"[REQ] {fn}")

        #     friendly_name = extract_friendly_name(req.post_data)
        #     variables = extract_variables(req.post_data)

        #     # print(f"[ALL] {friendly_name} | folder: {variables.get('folder') if variables else '-'}")

        #     if friendly_name not in TARGET_QUERIES:
        #         return

        #     try:
        #         body = await response.text()
        #         parsed = parse_ig_response(body)

        #         key = friendly_name
        #         if variables and 'folder' in variables:
        #             key = f"{friendly_name}:{variables['folder']}"

        #         if friendly_name == 'IGDThreadDetailQuery':
        #             thread_responses.append(parsed)
        #             thread_received.set()
        #         else:
        #             # collected_data[key] = parsed
        #             collected_data.setdefault(key, []).append(parsed)

        #         if friendly_name == 'PolarisDirectInboxQuery':
        #             inbox_received.set()

        #         if friendly_name == 'PolarisDirectMessageRequestQuery':
        #             request_message_received.set()

        #     except Exception as e:
        #         print(f"[ERROR] {friendly_name}: {e}")

        page.on("response", on_response)

        # === 1. Inbox ===

        # current_url = page.url
        # if 'instagram.com/direct/inbox' in current_url:
        #     await page.reload(wait_until='domcontentloaded')
        # else:
        await page.goto('https://www.instagram.com/direct/inbox/',
                        wait_until='domcontentloaded')
            
        await dismiss_notifications_popup(page)

        try:
            await asyncio.wait_for(inbox_received.wait(), timeout=15)
            print("Inbox received!")
        except asyncio.TimeoutError:
            print("Inbox timeout")

        await page.wait_for_timeout(2000)

        # for sel in ['a[href^="/direct/t/"]',
        #             'div[role="button"][role]',
        #             '[role="listitem"]',
        #             'div[role="list"] > div']:
        #     cnt = await page.locator(sel).count()
        #     print(f"[probe] {sel}: {cnt}")

        # total = await scroll_inbox_until_loaded(page)
        await iterate_inbox_folders(page, inbox_received, collected_data)

        # debug = await page.evaluate(
        #     """(sel) => {
        #         const named = document.querySelector(sel);
        #         // ищем ВСЕ скроллируемые контейнеры
        #         const scrollables = [];
        #         for (const c of document.querySelectorAll('*')) {
        #             const s = getComputedStyle(c);
        #             if (s.overflowY === 'auto' || s.overflowY === 'scroll') {
        #                 const delta = c.scrollHeight - c.clientHeight;
        #                 if (delta > 50) {
        #                     scrollables.push({
        #                         tag: c.tagName,
        #                         cls: (c.className || '').toString().slice(0, 40),
        #                         sh: c.scrollHeight,
        #                         ch: c.clientHeight,
        #                         top: c.scrollTop,
        #                         delta: delta
        #                     });
        #                 }
        #             }
        #         }
        #         scrollables.sort((a, b) => b.delta - a.delta);
        #         return {
        #             named_found: !!named,
        #             named_sh: named ? named.scrollHeight : null,
        #             named_ch: named ? named.clientHeight : null,
        #             scrollables: scrollables.slice(0, 5)
        #         };
        #     }""",
        #     '[data-pagelet="IGDInboxThreadListScrollableAreaPagelet"]'
        # )
        # print("[scroll-debug]", debug)

        inbox_threads = collect_all_inbox_threads(collected_data)

        # print(f"Scrolled inbox, {total} thread links in DOM")

        # inbox_threads = extract_threads_from_inbox(
        #     collected_data.get('PolarisDirectInboxQuery', [])
        # )
        print(f"Found {len(inbox_threads)} inbox threads")
        await process_threads(inbox_threads, account_id, page,
                              thread_responses, thread_received, _session)

        # === 2. Message Requests + Spam ===

        # request_message_received.clear()

        # await page.goto('https://www.instagram.com/direct/requests/',
        #                 wait_until='domcontentloaded')

        # try:
        #     await asyncio.wait_for(request_message_received.wait(), timeout=15)
        #     print("Message requests received!")
        # except asyncio.TimeoutError:
        #     print("Message requests timeout")

        # await page.wait_for_timeout(2000)

        # # total = await scroll_inbox_until_loaded(page)
        
        # # print(f"Scrolled inbox, {total} thread links in DOM")

        # request_threads, spam_threads = extract_threads_from_requests(
        #     collected_data.get('PolarisDirectMessageRequestQuery', [])
        # )

        # print(f"Found {len(request_threads)} request threads")
        # await process_threads(request_threads, account_id, page,
        #                     thread_responses, thread_received, _session,
        #                     is_request=True)

        # print(f"Found {len(spam_threads)} spam threads")
        # await process_threads(spam_threads, account_id, page,
        #                     thread_responses, thread_received, _session,
        #                     is_spam=True)
        


#####
async def parse_thread_playwright(account_id: int,
                                  thread: Thread,
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
            if req.resource_type in ('xhr', 'fetch'):
                fn = extract_friendly_name(req.post_data) if req.post_data else None
                # print(f"[REQ] {fn}")   # временно
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

                if friendly_name == 'IGDMessageListOffMsysQuery':
                    # print(f"MSGLIST PARSED type={type(parsed)} sample={str(parsed)[:400]}")
                    # print('LOOK -> ',parsed)
                    thread_responses.append(parsed)
                    thread_received.set()

                if friendly_name == 'IGDThreadDetailQuery':
                    thread_responses.append(parsed)
                    thread_received.set()
                # if friendly_name in ('IGDThreadDetailQuery', 'IGDMessageListOffMsysQuery'):
                #     thread_responses.append(parsed)
                #     thread_received.set()
                # else:
                #     collected_data.setdefault(key, []).append(parsed)
                else:
                    # collected_data[key] = parsed
                    collected_data.setdefault(key, []).append(parsed)

                if friendly_name == 'PolarisDirectInboxQuery':
                    inbox_received.set()

                if friendly_name == 'PolarisDirectMessageRequestQuery':
                    request_message_received.set()

            except Exception as e:
                print(f"[ERROR] {friendly_name}: {e}")

        page.on("response", on_response)

        # === 1. Inbox ===

        current_url = page.url
        if current_url.startswith(f'https://www.instagram.com/direct/t/{thread.thread_id}'):
            await page.reload(wait_until='domcontentloaded')
        else:
            await page.goto(
                f'https://www.instagram.com/direct/t/{thread.thread_id}/',
                wait_until='domcontentloaded'
            )

        await asyncio.sleep(3)

        await dismiss_notifications_popup(page)

        try:
            await asyncio.wait_for(inbox_received.wait(), timeout=15)
            print("Thread received!")
        except asyncio.TimeoutError:
            print("Thread timeout")

        await page.wait_for_timeout(2000)

        # total = await scroll_inbox_until_loaded(page)

        # print(f"Scrolled inbox, {total} thread links in DOM")

        # inbox_threads = extract_threads_from_inbox(
        #     collected_data.get('PolarisDirectInboxQuery', [])
        # )
        # print(f"Found {len(inbox_threads)} inbox threads")
        await process_thread(thread, account_id, page,
                              thread_responses, thread_received, _session)

        # # === 2. Message Requests + Spam ===

        # request_message_received.clear()

        # await page.goto('https://www.instagram.com/direct/requests/',
        #                 wait_until='domcontentloaded')

        # try:
        #     await asyncio.wait_for(request_message_received.wait(), timeout=15)
        #     print("Message requests received!")
        # except asyncio.TimeoutError:
        #     print("Message requests timeout")

        # await page.wait_for_timeout(2000)

        # # total = await scroll_inbox_until_loaded(page)
        
        # # print(f"Scrolled inbox, {total} thread links in DOM")

        # request_threads, spam_threads = extract_threads_from_requests(
        #     collected_data.get('PolarisDirectMessageRequestQuery', [])
        # )

        # print(f"Found {len(request_threads)} request threads")
        # await process_threads(request_threads, account_id, page,
        #                     thread_responses, thread_received, _session,
        #                     is_request=True)

        # print(f"Found {len(spam_threads)} spam threads")
        # await process_threads(spam_threads, account_id, page,
        #                     thread_responses, thread_received, _session,
        #                     is_spam=True)

#####

async def parse_thread_list_playwright(account_id: int,
                                       threads: list[Thread],
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
            if req.resource_type in ('xhr', 'fetch'):
                fn = extract_friendly_name(req.post_data) if req.post_data else None
            if '/api/graphql' not in url and '/graphql/query' not in url:
                return
            if not req.post_data:
                return

            friendly_name = extract_friendly_name(req.post_data)
            variables = extract_variables(req.post_data)

            if friendly_name not in TARGET_QUERIES:
                return

            try:
                body = await response.text()
                parsed = parse_ig_response(body)

                key = friendly_name
                if variables and 'folder' in variables:
                    key = f"{friendly_name}:{variables['folder']}"

                # if friendly_name == 'IGDMessageListOffMsysQuery':
                #     thread_responses.append(parsed)
                #     thread_received.set()

                # if friendly_name == 'IGDThreadDetailQuery':
                #     thread_responses.append(parsed)
                #     thread_received.set()
                # else:
                #     collected_data.setdefault(key, []).append(parsed)

                # if friendly_name == 'PolarisDirectInboxQuery':
                #     inbox_received.set()

                # if friendly_name == 'PolarisDirectMessageRequestQuery':
                #     request_message_received.set()
                if friendly_name in ('IGDMessageListOffMsysQuery', 'IGDThreadDetailQuery'):
                    thread_responses.append(parsed)
                    thread_received.set()
                elif friendly_name == 'PolarisDirectInboxQuery':
                    collected_data.setdefault(key, []).append(parsed)
                    inbox_received.set()
                elif friendly_name == 'PolarisDirectMessageRequestQuery':
                    collected_data.setdefault(key, []).append(parsed)
                    request_message_received.set()
                else:
                    collected_data.setdefault(key, []).append(parsed)

            except Exception as e:
                print(f"[ERROR] {friendly_name}: {e}")

        page.on("response", on_response)

        for thread in threads:
            thread_responses.clear()
            thread_received.clear()
            collected_data.clear()
            
            current_url = page.url
            if current_url.startswith(f'https://www.instagram.com/direct/t/{thread.thread_id}'):
                await page.reload(wait_until='domcontentloaded')
            else:
                await page.goto(
                    f'https://www.instagram.com/direct/t/{thread.thread_id}/',
                    wait_until='domcontentloaded'
                )

            await asyncio.sleep(3)

            await dismiss_notifications_popup(page)

            try:
                await asyncio.wait_for(inbox_received.wait(), timeout=15)
                print("Thread received!")
            except asyncio.TimeoutError:
                print("Thread timeout")

            await page.wait_for_timeout(2000)

            await process_thread(thread, account_id, page,
                                thread_responses, thread_received, _session)



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

                    media_url = generate_valid_media_url(media_url)

                    # if media_url.startswith('./'):
                    #     media_url = media_url[2:]
                    # if media_url.startswith('media/'):
                    #     media_url = media_url[len('media/'):]

                    media_url_for_send = f'{MEDIA_PATH}/{media_url}'

                    print(f"[send] url={page.url}")
                    c = await page.locator('input[type=\"file\"]').count()
                    w = await page.locator('div[role=\"textbox\"]').count()
                    print(f"[send] file inputs: {c}")
                    # есть ли композер (поле ввода сообщения)?
                    print(f"[send] textbox: {w}")
                    # не на approve-экране ли (кнопки Accept/Delete у реквестов)
                    body_snippet = (await page.locator('body').inner_text())[:200]
                    print(f"[send] body start: {body_snippet!r}")

                    try:
                        # берём именно тот input по accept или классу, не ждём видимости
                        handle = await page.query_selector('input[type="file"]')
                        if handle is None:
                            # подстраховка: ждём появления в DOM (attached), но НЕ видимости
                            await page.wait_for_selector('input[type="file"]', state='attached', timeout=15000)
                            handle = await page.query_selector('input[type="file"]')

                        await handle.set_input_files(media_url_for_send)
                        await asyncio.sleep(2.5)
                        # inp = page.locator('input[type="file"]')

                        # await inp.set_input_files(media_url_for_send)   # абсолютный путь
                        # await asyncio.sleep(2.5)

                        # # ждём появления превью вложения (кнопка "Remove")
                        # await page.wait_for_selector(
                        #     'button[aria-label^="Remove"], [aria-label^="Remove"]',
                        #     timeout=20000)

                        # # Отправка через Enter в композере
                        # box = page.locator('div[role="textbox"]').last
                        # await box.click()
                        # await page.keyboard.press("Enter")

                        # # Подтверждение: кнопка удаления вложения исчезла = ушло
                        # await page.wait_for_selector(
                        #     'button[aria-label^="Remove"]',
                        #     state="detached", timeout=20000)
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
