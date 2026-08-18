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

from arq import ArqRedis, Retry

from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession

from playwright.async_api import async_playwright

from background.base import acquire_task_lock
from db.queries import (check_insta_user, check_new_messages_in_thread,
                        check_thread_in_db, get_all_threads_by_account, get_message_count_after_last_message_id, get_message_only_by_id, get_new_thread_messages, get_thread_by_id,
                        try_add_insta_user,
                        # try_add_messages,
                        try_add_new_thread,
                        execute_and_catch_db_error, update_approve_thread, update_thread_is_unread_by_id)

from db.base import Attachment, Message, Thread, Account

from utils.ai import ai_extract_user_info, generate_new_message_to_thread, generate_thread_context
from utils.enums import MessageStatusEnum, ThreadColorEnum

from utils.base import dismiss_notifications_popup, generate_valid_media_url, try_get_profile_port

from websocket.redis_listener import publish_event

from config import LIMIT_FOR_RAW_LOG_MESSAGES, VISION_BROWSER_HOST, MEDIA_PATH

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
    'IGDThreadListOffMsysPaginationQuery',
}

# === Утилиты ===
async def load_known_threads_map(account_id: int, _session: AsyncSession) -> dict:
    result = await _session.execute(
        select(Thread.thread_id, Thread.timestamp_last_seen_message)
        .where(Thread.account_id == account_id)
    )
    return {tid: ts for tid, ts in result.all() if tid}
    
def _thread_last_activity_dt(thread: dict):
    # ts_ms = thread.get('last_activity') or thread.get('last_message_ts')
    ts_ms = thread.get('last_message_ts')
    if not ts_ms:
        return None
    try:
        return datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc)
    except (ValueError, TypeError):
        return None


def thread_has_new_messages(thread: dict, known_map: dict) -> bool:
    tid = thread.get('thread_key')
    if not tid:
        return True  # нет id — не рискуем терять данные, считаем свежим

    last_activity_dt = _thread_last_activity_dt(thread)
    if last_activity_dt is None:
        return True  # нет таймстампа — то же самое

    known_ts = known_map.get(tid)
    if known_ts is None:
        return True  # тред ещё не видели в БД

    return last_activity_dt > known_ts


def batch_has_new_messages(threads: list, known_map: dict) -> bool:
    return any(thread_has_new_messages(t, known_map) for t in threads)


async def scroll_inbox_until_loaded(page, collected_data, known_map=None, max_rounds=80,
                                    wait_after_scroll=8.0, poll_interval=0.3):
    item_sel = 'div[role="button"]'

    scroll_js = """() => {
        let best = null, max = 50;
        for (const c of document.querySelectorAll('*')) {
            const s = getComputedStyle(c);
            if (s.overflowY === 'auto' || s.overflowY === 'scroll') {
                const d = c.scrollHeight - c.clientHeight;
                if (d > max) { best = c; max = d; }
            }
        }
        if (!best) return {found: false};
        const before = best.scrollTop;
        best.scrollTop = best.scrollHeight;
        return {found: true, before: before, after: best.scrollTop,
                sh: best.scrollHeight, ch: best.clientHeight};
    }"""

    if known_map is not None:
        initial_threads = extract_threads_from_inbox(collected_data.get('PolarisDirectInboxQuery', []))
        if initial_threads and not batch_has_new_messages(initial_threads, known_map):
            print("[scroll-inbox] первый экран без новых сообщений — скролл не нужен")
            return await page.locator(item_sel).count()

    empty_rounds = 0

    for i in range(max_rounds):
        pages_before = len(collected_data.get('SlideMailboxPages', []))

        res = await page.evaluate(scroll_js)
        count = await page.locator(item_sel).count()
        print(f"[scroll-inbox #{i}] count={count} pages_before={pages_before} scroll={res}")

        if not res.get('found'):
            empty_rounds += 1
            print(f"[scroll-inbox] нет скроллируемого контейнера на #{i}, empty={empty_rounds}")
            if empty_rounds >= 2:
                print(f"[scroll-inbox] stop after {empty_rounds} empty rounds (no scrollable container)")
                break
            await page.wait_for_timeout(500)
            continue

        waited = 0.0
        while waited < wait_after_scroll:
            await page.wait_for_timeout(int(poll_interval * 1000))
            waited += poll_interval
            if len(collected_data.get('SlideMailboxPages', [])) > pages_before:
                break

        pages_after = len(collected_data.get('SlideMailboxPages', []))

        if pages_after == pages_before:
            empty_rounds += 1
            print(f"[scroll-inbox] no new page at #{i}, empty={empty_rounds}")
            if empty_rounds >= 2:
                print(f"[scroll-inbox] stop after {empty_rounds} empty rounds")
                break
            continue

        empty_rounds = 0

        if known_map is not None:
            new_pages = collected_data['SlideMailboxPages'][pages_before:pages_after]
            new_threads = extract_threads_from_inbox(new_pages)
            if new_threads and not batch_has_new_messages(new_threads, known_map):
                print(f"[scroll-inbox] батч #{i} без новых сообщений — стоп")
                break


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
    content = node.get('content') or {}
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

    elif typename == 'SlideMessageXMAContent':
        # репост чужого контента (сторис/рилс/пост) — MESSAGE_INLINE_SHARE, MONTAGE_SHARE_XMA
        xma = content.get('xma') or {}
        preview = xma.get('preview_image') or {}
        preview_url = preview.get('url')
        if preview_url:
            urls.append({'url': preview_url, 'type': 'xma_preview', 'ext': '.jpg'})

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
                        if media_type in ('image', 'video_preview', 'xma_preview'):
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
        
        view_sender = 'user' if _sender == user_insta_id else 'assistant'

        msg_data = {
            'id': msg_id,
            'sender': view_sender,
            'type': ctype,
            'timestamp': _ts,
            'text': None,
            'media_files': [],
        }

        mark_as_unread = _sender == user_insta_id

        content = node.get('content') or {}
        content_typename = content.get('__typename')

        if content_typename == 'SlideMessageAdminText':
            fragments = content.get('text_fragments') or []
            admin_text = ' '.join(
                f.get('plaintext', '') for f in fragments
            ).strip()
            msg_data['text'] = admin_text

        if ctype == 'TEXT':
            msg_data['text'] = node.get('text_body', '')

        elif ctype.startswith('REACTION'):
            # text_body = node.get('text_body', '')
            msg_data['text'] = '* реакция на сообщение в чате'

        elif ctype in ('MESSAGE_INLINE_SHARE', 'MONTAGE_SHARE_XMA'):
            content = node.get('content') or {}
            xma = content.get('xma') or {}
            
            comment_text = content.get('xma_text_body') or node.get('text_body') or ''
            shared_author = xma.get('header_title_text', '')
            eyebrow = xma.get('eyebrow_text')  # напр. "Replied to @X's story"

            # текст для сохранения: комментарий отправителя + пометка о репосте
            if eyebrow:
                msg_data['text'] = f"{comment_text} [{eyebrow}]" if comment_text else f"[{eyebrow}]"
            elif shared_author:
                msg_data['text'] = f"{comment_text} [shared post by {shared_author}]" if comment_text else f"[shared post by {shared_author}]"
            else:
                msg_data['text'] = comment_text

            media_urls = extract_media_urls(node)
            if media_urls:
                files = await download_media(media_urls, thread_dir, str(thread_key), msg_id)
                msg_data['media_files'] = files
        else:
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


def collect_all_request_pages(collected_data):
    """Собирает все страницы: первый экран запросов + пагинация."""
    pages = []
    pages.extend(collected_data.get('PolarisDirectMessageRequestQuery', []))
    pages.extend(collected_data.get('SlideMailboxPages', []))
    return pages


def extract_threads_from_requests(data_list: list) -> tuple[list, list]:
    """Возвращает (request_threads, spam_threads)"""
    request_threads = []
    spam_threads = []

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

    seen_request_keys = set()
    seen_spam_keys = set()

    for obj in data_list:
        if not isinstance(obj, dict):
            continue
        data = obj.get('data', {})

        # Обычные requests — первый экран
        for edge in (data.get('get_slide_mailbox_for_iris_subscription', {})
                         .get('threads_by_folder', {})
                         .get('edges', [])):
            node = edge['node'].get('as_ig_direct_thread', edge.get('node', {}))
            tk = node.get('thread_key')
            if tk and tk in seen_request_keys:
                continue
            seen_request_keys.add(tk)
            request_threads.append(build_thread(node))

        # Spam — первый экран
        for edge in (data.get('spamMailbox', {})
                         .get('threads_by_folder', {})
                         .get('edges', [])):
            node = edge['node'].get('as_ig_direct_thread', edge.get('node', {}))
            tk = node.get('thread_key')
            if tk and tk in seen_spam_keys:
                continue
            seen_spam_keys.add(tk)
            spam_threads.append(build_thread(node))

        # Пагинация requests — fetch__SlideMailbox.threads_by_folder (тот же путь!)
        for edge in (data.get('fetch__SlideMailbox', {})
                         .get('threads_by_folder', {})
                         .get('edges', [])):
            node = edge['node'].get('as_ig_direct_thread', edge.get('node', {}))
            tk = node.get('thread_key')
            if tk and tk in seen_request_keys:
                continue
            seen_request_keys.add(tk)
            request_threads.append(build_thread(node))

    return request_threads, spam_threads


async def process_threads(
    threads: list,
    account: Account,
    page,
    thread_responses: list,
    thread_received: asyncio.Event,
    redis_pool: ArqRedis,
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
            if is_request or is_spam:
                print(' -> INDEX ERROR', thread)
                continue
            insta_user = {
                'username': thread['username'],
                'full_name': thread['full_name'],
                'interop_messaging_user_fbid': thread['interop_messaging_user_fbid'],
            }
        
        if not insta_user:
            continue

        _insta_user = await check_insta_user(str(insta_user.get('interop_messaging_user_fbid')),
                                             _session)

        if not _insta_user:
            photo_url = await download_profile_pic(insta_user)
            insta_user['photo_url'] = photo_url
            _insta_user = await try_add_insta_user(insta_user, _session)

        user_insta_id = _insta_user.insta_id
        thread_key = thread['thread_key']
        current_thread = await check_thread_in_db(thread_key,
                                                  account.id,
                                                  _session)

        if not current_thread:
            thread_data = {
                'account_id': account.id,
                'insta_user_id': _insta_user.id,
                'thread_id': thread_key,
                'timestamp_last_seen_message': None,
                'is_unread': thread.get('unread'),
                'is_approved': True,
                'is_spam': False,
                'is_blocked': False,
            }
            if is_request:
                thread_data['is_approved'] = False
            if is_spam:
                thread_data['is_approved'] = False

            current_thread = await try_add_new_thread(thread_data, _session)

        if last_message_ts and current_thread.timestamp_last_seen_message:
            last_message_ts = datetime.fromtimestamp(int(last_message_ts) / 1000, tz=timezone.utc)
            # _last_activity = datetime.fromtimestamp(int(last_activity) / 1000, tz=timezone.utc)
            # if current_thread.thread_id == '18071988617254182':
            #     print('тут 22',last_message_ts, _last_activity, current_thread.timestamp_last_seen_message)

            if last_message_ts <= current_thread.timestamp_last_seen_message:
                print('SKIP THIS THREAD CAUSE LAST MESSAGE IN RESPONSE EQUAL WITH LAST MESSAGE FROM DB')
                continue
            else:
                # current_thread.is_unread = True
                # add background task to queue
                job = await redis_pool.enqueue_job(
                    'parse_thread',
                    account.id,
                    current_thread.id,
                    _job_id=f'parse_thread:acoount:{account.id}:thread:{current_thread.id}',
                    _queue_name='arq:threads',
                )
                await asyncio.sleep(0.5)
                # return {"status": "queued", "job_id": job.job_id}
        
        else:
            # current_thread.is_unread = True
            # add background task to queue
            job = await redis_pool.enqueue_job(
                'parse_thread',
                account.id,
                current_thread.id,
                _job_id=f'parse_thread:acoount:{account.id}:thread:{current_thread.id}',
                _queue_name='arq:threads',
            )
            await asyncio.sleep(0.5)
            # return {"status": "polling", "job_id": job.job_id}

        # await execute_and_catch_db_error(_session.commit(),
        #                                   _session,
        #                                   with_rollback=True)

        # publish update to redis with updated thread info(new or updated)
        payload = {
            'account_id': current_thread.account_id,
        }
        payload_thread = {
            "id": current_thread.id,
            "account_name": account.username,
            "user_name": _insta_user.username,
            "has_unread": current_thread.is_unread,
            "last_activity": current_thread.timestamp_last_seen_message.strftime("%Y-%d-%m %H:%M")\
                if current_thread.timestamp_last_seen_message else "",
            "color_level": current_thread.color_level,
            'is_approved': current_thread.is_approved,
            'is_pinned': current_thread.is_pinned,
            'is_blocked': current_thread.is_blocked,
        }

        payload['thread'] = payload_thread
 
        await publish_event(redis_pool,
                            type='Thread for list updated',
                            payload=payload_thread)


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


async def scroll_messages_until_seen(page, thread_responses, thread_key,
                                     last_seen_ts=None, max_rounds=200,
                                     wait_after_scroll=8.0, poll_interval=0.3):
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


async def process_thread(
    thread: Thread,
    account_id: int,
    page,
    thread_responses: list,
    thread_received: asyncio.Event,
    _session: AsyncSession,
    redis: ArqRedis,
    is_request: bool = False,
    is_spam: bool = False,
    with_scroll: bool = True,
) -> dict:
    all_thread_data = {}
    thread_key = thread.thread_id
    user_insta_id = thread.insta_user.insta_id

    # if with_scroll:
    await scroll_messages_until_seen(
        page, thread_responses, thread_key,
        last_seen_ts=thread.timestamp_last_seen_message
    )
    await page.wait_for_timeout(500)

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
        return await try_add_messages(messages_data, thread, _session, redis)
    else:
        print(f"No matching data found for thread {thread_key}")


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


async def iterate_inbox_folders(page, inbox_received, collected_data, account_id, _session):
    tabs = await get_inbox_tabs(page)
    known_map = await load_known_threads_map(account_id, _session)
    print(f"[inbox] найденные вкладки: {tabs}")  # временно, чтобы понять реальные имена

    if not tabs:
        print("[inbox] вкладок нет, единый список")
        await scroll_inbox_until_loaded(page, collected_data, known_map)
        return

    switched = await switch_inbox_tab(page, "General")
    if switched:
        inbox_received.clear()
        try:
            await asyncio.wait_for(inbox_received.wait(), timeout=15)
        except asyncio.TimeoutError:
            print("[inbox] таймаут ожидания ответа для General")
    # если не переключились — новой сети не будет, ждать нечего

    await scroll_inbox_until_loaded(page, collected_data, known_map)


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

async def test_playwright(account: Account,
                          profile_port: int,
                          folder_id: str,
                          profile_id: str,
                          redis_pool: ArqRedis,
                          _session: AsyncSession,
                          request_messages: bool = False):
    collected_data = {}
    thread_responses = []
    inbox_received = asyncio.Event()
    thread_received = asyncio.Event()
    request_message_received = asyncio.Event()

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(f'http://{VISION_BROWSER_HOST}:{profile_port}')
            print(f"CONNECTED ON {profile_port} PORT")
        except Exception as ex:
            print(f'ERROR WITH TRY CONNECT TO BROWSER WITH {profile_port} PORT', ex)
            # get new port
            new_profile_port = await try_get_profile_port(folder_id,
                                                          profile_id)
            if not new_profile_port:
                return
            
            browser = await p.chromium.connect_over_cdp(f'http://{VISION_BROWSER_HOST}:{new_profile_port}')
            print(f"CONNECTED ON {profile_port} PORT")
        
        context = browser.contexts[0] if browser.contexts else await browser.new_context()

        if len(context.pages) >= 6:
            raise Retry(defer=5)

        page = await context.new_page()

        async def on_response(response):
                    pagination_counter = 0
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
                        # print(f"[REQ] {friendly_name}")
                        pass

                    variables = extract_variables(req.post_data)

                    if friendly_name not in TARGET_QUERIES:
                        return

                    try:
                        body = await response.text()
                        parsed = parse_ig_response(body)

                        key = friendly_name
                        if variables and 'folder' in variables:
                            key = f"{friendly_name}:{variables['folder']}"

                        elif friendly_name == 'IGDThreadDetailQuery':
                            thread_responses.append(parsed)
                            thread_received.set()

                        # пагинация списка чатов (бизнес-аккаунт) — накапливаем отдельно
                        elif friendly_name in ('IGDThreadListProfessionalOffMsysPaginationQuery',
                                               'IGDThreadListOffMsysPaginationQuery'):
                            # разовая диагностика структуры
                            try:
                                sample = parsed[0] if isinstance(parsed, list) and parsed else parsed
                                if isinstance(sample, dict):
                                    print("[mailbox-page] data keys:", list(sample.get('data', {}).keys()))
                            except Exception as ex:
                                print('.  ERROR WITH PARSE THREAD LIST')
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

        try:
            page.on("response", on_response)

            if not request_messages:

                # === 1. Inbox ===
                await page.goto('https://www.instagram.com/direct/inbox/',
                                wait_until='domcontentloaded')
                    
                await dismiss_notifications_popup(page)

                try:
                    await asyncio.wait_for(inbox_received.wait(), timeout=15)
                    print("Inbox received!")
                except asyncio.TimeoutError:
                    print("Inbox timeout")

                await page.wait_for_timeout(2000)

                await iterate_inbox_folders(page, inbox_received, collected_data, account.id, _session)

                inbox_threads = collect_all_inbox_threads(collected_data)

                print(f"Found {len(inbox_threads)} inbox threads")
                await process_threads(inbox_threads, account, page,
                                    thread_responses, thread_received, redis_pool, _session)
                
                await asyncio.sleep(1)
            else:

                # # === 2. Message Requests ===

                request_message_received.clear()
                collected_data.clear()

                await page.goto('https://www.instagram.com/direct/requests/',
                                wait_until='domcontentloaded')

                try:
                    await asyncio.wait_for(request_message_received.wait(), timeout=15)
                    print("Message requests received!")
                except asyncio.TimeoutError:
                    print("Message requests timeout")

                await page.wait_for_timeout(2000)

                await scroll_inbox_until_loaded(page, collected_data)
                
                request_pages = collect_all_request_pages(collected_data)
                request_threads, _ = extract_threads_from_requests(request_pages)

                request_message_received.clear()
                collected_data.clear()

                # === Hidden requests (спам) ===
                await page.goto('https://www.instagram.com/direct/requests/hidden/',
                                wait_until='domcontentloaded')

                try:
                    await asyncio.wait_for(request_message_received.wait(), timeout=15)
                    print("Hidden requests received!")
                except asyncio.TimeoutError:
                    print("Hidden requests timeout")

                await page.wait_for_timeout(2000)
                total = await scroll_inbox_until_loaded(page, collected_data)

                hidden_pages = collect_all_request_pages(collected_data)
                # с hidden-страницы ВСЁ, что нашлось, считаем spam — раздельный сбор снимает вопрос
                # различения по полю folder внутри одного смешанного потока
                _, spam_threads_raw = extract_threads_from_requests(hidden_pages)
                spam_threads = spam_threads_raw   # все треды с hidden-страницы — спам

                print(f"Found {len(request_threads)} request threads")
                await process_threads(request_threads, account, page,
                                    thread_responses, thread_received, redis_pool, _session,
                                    is_request=True)

                print(f"Found {len(spam_threads)} spam threads")
                await process_threads(spam_threads, account, page,
                                    thread_responses, thread_received, redis_pool, _session,
                                    is_spam=True)
        finally:
            try:
                page.remove_listener("response", on_response)
                await page.close()
                await asyncio.sleep(1)
            except Exception as ex:
                print('ERROR WITH CLOSE PAGE',ex)


#####
async def parse_thread_playwright(account: Account,
                                  thread: Thread,
                                  profile_port: int,
                                  _session: AsyncSession,
                                  redis: ArqRedis):
    collected_data = {}
    thread_responses = []
    inbox_received = asyncio.Event()
    thread_received = asyncio.Event()
    request_message_received = asyncio.Event()

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(f'http://{VISION_BROWSER_HOST}:{profile_port}')
            print(f"CONNECTED ON {profile_port} PORT")
        except Exception as ex:
            print(f'ERROR WITH TRY CONNECT TO BROWSER WITH {profile_port} PORT', ex)
            # get new port
            new_profile_port = await try_get_profile_port(account.folder_id,
                                                          account.profile_id)
            if not new_profile_port:
                return
            
            browser = await p.chromium.connect_over_cdp(f'http://{VISION_BROWSER_HOST}:{new_profile_port}')
            print(f"CONNECTED ON {profile_port} PORT")

        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        # context = await browser.new_context()

        if len(context.pages) >= 6:
            raise Retry(defer=5)

        detail_thread_page = await context.new_page()

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
                    thread_responses.append(parsed)
                    thread_received.set()

                if friendly_name == 'IGDThreadDetailQuery':
                    thread_responses.append(parsed)
                    thread_received.set()
                else:
                    collected_data.setdefault(key, []).append(parsed)

                if friendly_name == 'PolarisDirectInboxQuery':
                    inbox_received.set()

                if friendly_name == 'PolarisDirectMessageRequestQuery':
                    request_message_received.set()

            except Exception as e:
                print(f"[ERROR] {friendly_name}: {e}")

        try:
            detail_thread_page.on("response", on_response)

            # === 1. Inbox ===

            await detail_thread_page.goto(
                f'https://www.instagram.com/direct/t/{thread.thread_id}/',
                wait_until='domcontentloaded'
            )

            await asyncio.sleep(3)

            await dismiss_notifications_popup(detail_thread_page)

            try:
                await asyncio.wait_for(inbox_received.wait(), timeout=15)
                print("Thread received!")
            except asyncio.TimeoutError:
                print("Thread timeout")

            await detail_thread_page.wait_for_timeout(2000)

            await process_thread(thread, account.id, detail_thread_page,
                                thread_responses, thread_received, _session, redis)
            
            detail_thread_page.remove_listener("response", on_response)
        finally:
            await detail_thread_page.close()
            await asyncio.sleep(1)


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
    await asyncio.sleep(2)

    # После Accept может появиться диалог выбора папки (Primary/General/Cancel)
    # ждём его и кликаем General, если он появился
    # try:
    #     general_btn = page.get_by_role("button", name=re.compile(r"^General$|Общ", re.I))
    #     # у тебя на скрине это выглядит как строка в модалке, не button — попробуем оба варианта
    #     await general_btn.wait_for(timeout=5000)
    #     await general_btn.first.click()
    #     print("выбрана папка General")
    #     await asyncio.sleep(1.5)
    # except Exception:
    #     # диалог не появился (например, в другой версии интерфейса) — это нормально, идём дальше
    #     print("диалог выбора папки не появился, продолжаем")
    try:
        general_locator = page.locator(
            'button:has-text("General"), div[role="button"]:has-text("General")'
        )
        await general_locator.first.wait_for(timeout=5000)
        await general_locator.first.click()
        print("выбрана папка General")
        await asyncio.sleep(1.5)
    except Exception:
        print("диалог выбора папки не появился (или уже в General), продолжаем")

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
                                  folder_id: str,
                                  profile_id: str,
                                  session: AsyncSession,
                                  redis: ArqRedis,
                                  media: str = None):
    send_success = False

    is_approved_thread = message.thread.is_approved

    collected_data = {}
    thread_responses = []
    inbox_received = asyncio.Event()
    thread_received = asyncio.Event()
    request_message_received = asyncio.Event()

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(f'http://{VISION_BROWSER_HOST}:{profile_port}')
            print(f"CONNECTED ON {profile_port} PORT")
        except Exception as ex:
            print(f'ERROR WITH TRY CONNECT TO BROWSER WITH {profile_port} PORT', ex)
            # get new port
            new_profile_port = await try_get_profile_port(folder_id,
                                                          profile_id)
            if not new_profile_port:
                return
            
            browser = await p.chromium.connect_over_cdp(f'http://{VISION_BROWSER_HOST}:{new_profile_port}')
            print(f"CONNECTED ON {profile_port} PORT")
        
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        
        # value for limit page count in one time
        if len(context.pages) >= 6:
            payload = {
                'thread_id': message.thread_id,
            }
            msg_payload = {
                'id': str(message.id),
                "retry_send_count": message.retry_send_count,
            }

            payload['message'] = msg_payload

            await publish_event(redis,
                                type='Message send count updated',
                                payload=payload)
            
            raise Retry(defer=15)
        
        # context = await browser.new_context()
        thread_for_send_message_page = await context.new_page()

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

            if friendly_name not in TARGET_QUERIES:
                return

            try:
                body = await response.text()
                parsed = parse_ig_response(body)

                key = friendly_name
                if variables and 'folder' in variables:
                    key = f"{friendly_name}:{variables['folder']}"

                if friendly_name == 'IGDMessageListOffMsysQuery':
                    thread_responses.append(parsed)
                    thread_received.set()

                if friendly_name == 'IGDThreadDetailQuery':
                    thread_responses.append(parsed)
                    thread_received.set()
                else:
                    collected_data.setdefault(key, []).append(parsed)

                if friendly_name == 'PolarisDirectInboxQuery':
                    inbox_received.set()

                if friendly_name == 'PolarisDirectMessageRequestQuery':
                    request_message_received.set()

            except Exception as e:
                print(f"[ERROR] {friendly_name}: {e}")

        try:
            try:
                thread_for_send_message_page.on("response", on_response)

                _res = await thread_for_send_message_page.goto(
                    f'https://www.instagram.com/direct/t/{message.thread.thread_id}/',
                    wait_until='domcontentloaded'
                )

                print(
                    "INSTAGRAM HOME:",
                    _res.status if _res else None,
                    thread_for_send_message_page.url,
                )
            except Exception as ex:
                print('RESPONSE ERROR', ex)
                raise

            await asyncio.sleep(3)

            await dismiss_notifications_popup(thread_for_send_message_page)

            if not is_approved_thread:
                is_approved = await approve_request_chat(thread_for_send_message_page,
                                                        thread_for_send_message_page.url)
                
                await update_approve_thread(message.thread_id,
                                            is_approved,
                                            session)
                
                print('NEW APPROVE STATUS', is_approved)

            
            # check new messages in this thread
            thread = await get_thread_by_id(message.thread_id,
                                            session)
            
            has_new_messages = await process_thread(thread,
                                                    thread.account_id,
                                                    thread_for_send_message_page,
                                                    thread_responses,
                                                    thread_received,
                                                    session,
                                                    redis,
                                                    with_scroll=False)
            
            # if has_new_messages or \
            #     (thread.timestamp_last_seen_message and thread.timestamp_last_seen_message >= message.created_at):
            #     msg = await get_message_only_by_id(message.id,
            #                                        session)
                
            #     if msg:

            #         msg.status = MessageStatusEnum.REJECTED

            #         await execute_and_catch_db_error(session.commit(),
            #                                         session,
            #                                         with_rollback=True)
                    
            #         payload = {
            #             'thread_id': msg.thread_id,
            #         }
            #         msg_payload = {
            #             'id': str(msg.id),
            #             "modStatus": msg.status,
            #         }

            #         payload['message'] = msg_payload

            #         await publish_event(redis,
            #                             type='Message updated',
            #                             payload=payload)
                    
            #         thread_for_send_message_page.remove_listener("response", on_response)
            #         await thread_for_send_message_page.close()
            #         await asyncio.sleep(1)

            #         return



            #
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
                            inp = thread_for_send_message_page.locator('input[type="file"]')

                            await inp.set_input_files(media_url_for_send)   # абсолютный путь
                            await asyncio.sleep(2.5)

                            # ждём появления превью вложения (кнопка "Remove")
                            await thread_for_send_message_page.wait_for_selector(
                                'button[aria-label^="Remove"], [aria-label^="Remove"]',
                                timeout=20000)

                            # Отправка через Enter в композере
                            box = thread_for_send_message_page.locator('div[role="textbox"]').last
                            await box.click()
                            # await thread_for_send_message_page.keyboard.press("Enter")

                            # Подтверждение: кнопка удаления вложения исчезла = ушло
                            # await thread_for_send_message_page.wait_for_selector(
                            #     'button[aria-label^="Remove"]',
                            #     state="detached", timeout=20000)
                            # ловим РЕАЛЬНЫЙ сетевой ответ на отправку, не DOM
                            async with thread_for_send_message_page.expect_response(
                                lambda r: '/graphql' in r.url and r.request.method == 'POST',
                                timeout=20000
                            ) as resp_info:
                                await thread_for_send_message_page.keyboard.press("Enter")

                            response = await resp_info.value
                            send_success = response.status == 200
                            print(" + фото отправлено")
                            # send_success = True
                        except Exception as ex:
                            print('ERROR WITH TRY SEND MESSAGE', ex)

                    case _:
                        pass
            else:
                try:
                    message_text = message.text
                    box = thread_for_send_message_page.locator('div[role="textbox"]').last
                    await box.click()                  # фокус — обязательно для Lexical
                    await human_pause(0.3, 0.7)

                    # await box.type(message_text, delay=random.uniform(30, 90))   # человеческий ввод
                    # await human_pause(0.4, 1.0)
                    char_delay = random.uniform(30, 90)
                    type_timeout = int(len(message_text) * char_delay) + 5_000  # запас 15с

                    await box.press_sequentially(message_text, delay=char_delay, timeout=type_timeout)
                    await human_pause(0.4, 1.0)

                    await thread_for_send_message_page.keyboard.press("Enter")

                    # подтверждение: композер очистился = сообщение ушло
                    await thread_for_send_message_page.wait_for_function(
                        """() => {
                            const el = document.querySelectorAll('div[role="textbox"]');
                            const last = el[el.length - 1];
                            return last && last.innerText.trim() === '';
                        }""",
                        timeout=15000)
                    await human_pause(0.8, 1.5)
                    print(" + текст отправлен")
                    # await asyncio.sleep(1.5)
                    send_success = True
                    is_need_new_context = True
                except Exception as ex:
                    print(ex)
                    pass
    
            thread_for_send_message_page.remove_listener("response", on_response)
        finally:
            await asyncio.sleep(2)
            await thread_for_send_message_page.close()
            await asyncio.sleep(1)
        
        if send_success:
            msg = await get_message_only_by_id(message.id,
                                               session)
            
            # if is_need_new_context:
            #     _text = f'{msg.text} | {msg.created_at} | {msg.sender}'

            #     context_from_db = thread.context or ''

            #     text_for_ai = 'Контекст:\n' + context_from_db + '\nНовые сообщения:\n' + _text

            #     new_context = await ai_generate_text(text=text_for_ai,
            #                                          for_db=True)
            #     thread.context = new_context
            
            msg.status = 'approved'
            ts = datetime.now(tz=timezone.utc)
            msg.created_at = ts
            msg.updated_at = ts
            thread.timestamp_last_seen_message = ts
            thread.is_unread = False

            await execute_and_catch_db_error(session.commit(),
                                             session,
                                             with_rollback=True)
            payload = {
                'thread_id': msg.thread_id,
            }
            msg_payload = {
                'id': str(msg.id),
                "modStatus": msg.status,
            }

            payload['message'] = msg_payload

            await publish_event(redis,
                                type='Message updated',
                                payload=payload)


async def try_add_messages(message_data: dict,
                           thread: Thread,
                           session: AsyncSession,
                           redis_pool: ArqRedis):
    thread_id = message_data.get('thread_id')
    messages = message_data.get('messages')
    # mark_as_unread = message_data.get('mark_as_unread')
    insert_messages = []
    message_ids_for_translate = []
    memory_updated = None

    unread_messages_text = ''

    if thread_id and messages:
        for message in reversed(messages):
            ts = message.get('timestamp')
            sender = message.get('sender')

            if ts:
                ts = datetime.fromtimestamp(
                    int(ts) / 1000,
                    tz=timezone.utc
                )
            msg_data = {
                'created_at': ts,
                'updated_at': ts,
                'text': message.get('text'),
                'sender': sender,
                'status': 'approved',
                'thread_id': thread_id,
            }

            new_message = Message(**msg_data,
                                  attachments=[Attachment(media_type=t, media_url=u) for t, u in message.get("media_files", [])])
            insert_messages.append(new_message)


            if new_message.text:
                _text = f'{new_message.text} | {new_message.created_at} | {new_message.sender}'
                unread_messages_text += _text

        if insert_messages:
            session.add_all(insert_messages)

            await execute_and_catch_db_error(session.flush(),
                                            session,
                                            with_rollback=True)
            
            new_generated_message = None

            if thread.color_level in (ThreadColorEnum.RED, ThreadColorEnum.GREY) and thread.is_pinned:
                # проверить и если нужно обновить контекст 
                # и json о юзере, обновить last_message_id в Thread
                memory_updated = await try_update_thread_memory(thread,
                                                                session,
                                                                redis_pool)

                print(f'is memory updated - {memory_updated}')
                # context_from_db = thread.context or ''
                messages_for_raw_log = await get_new_thread_messages(thread_id=thread.id,
                                                                     last_message_id=thread.last_message_id,
                                                                     session=session)
                raw_messages_log, _, _ = await get_raw_messages_log_and_new_last_message_id(messages_for_raw_log)


                generated_text = await generate_new_message_to_thread(account_info=thread.account.information,
                                                                      thread_context=thread.context,
                                                                      new_messages=raw_messages_log)
                
                insert_data = {
                    'sender': 'assistant',
                    'created_at': datetime.now(tz=timezone.utc),
                    'updated_at': datetime.now(tz=timezone.utc),
                    'thread_id': thread.id,
                    'text': generated_text,
                    'status': MessageStatusEnum.PENDING,
                }

                new_generated_message = Message(**insert_data)

                session.add(new_generated_message)

            # thread.context = new_context
            thread.is_unread = sender == 'user'
            thread.timestamp_last_seen_message = ts
            # thread.user_information = new_user_information

            await execute_and_catch_db_error(session.commit(),
                                             session,
                                             with_rollback=True)

            if memory_updated:
                job = await redis_pool.enqueue_job(
                    'translate_user_information_by_thread_id',
                    thread.id,
                    _queue_name='arq:utils',
                )

            # publish update to redis
            # thread updated
            # publish new messages to thread page
            # new messages(create message [many])
            payload = {
                'account_id': thread.account_id,
            }

            thread_payload = {
                'id': thread.id,
                'context': thread.context,
                'has_unread': thread.is_unread,
                "last_activity": thread.timestamp_last_seen_message.strftime("%Y-%d-%m %H:%M")\
                                if thread.timestamp_last_seen_message else "",
                'is_approved': thread.is_approved,
                'is_pinned': thread.is_pinned,
                'is_blocked': thread.is_blocked,
                        }

            message_list = []

            for message in insert_messages:
                # for transtale background task
                message_ids_for_translate.append(message.id)
                #
                attachments = message.attachments
                attachment_list = []
                content = message.text or ""
                translated_content = message.translated_text or ""

                for _attachment in attachments:
                    
                    if _attachment:
                        _attachment = {
                            'media_type': _attachment.media_type,
                            'media_url': generate_valid_media_url(_attachment.media_url),
                        }
                        attachment_list.append(_attachment)
                    
                message_dict = {
                    "id": str(message.id),
                    "role": message.sender,
                    "content": content,
                    "translated_content": translated_content,
                    "ts": (
                        message.created_at.strftime("%Y-%d-%m %H:%M")
                        if message.created_at else ""
                    ),
                    "modStatus": message.status,  # pending / approved / moderated
                    'attachments': attachment_list
                }
                message_list.append(message_dict)
            
            job = await redis_pool.enqueue_job(
                'try_translate_message_text',
                message_ids_for_translate,
                _queue_name='arq:translate',
            )

            thread_payload['messages'] = message_list

            payload['thread'] = thread_payload
            
            await publish_event(redis_pool,
                    type='Thread detail updated',
                    payload=payload)

            # publish update to redis
            # new message generated
            # publish new message to thread page
            # new message(ai generate)
            if new_generated_message:
                payload = {
                    'thread_id': new_generated_message.thread_id,
                }
                message_payload = {
                    'id': str(new_generated_message.id),
                    'role': new_generated_message.sender,
                    'content': new_generated_message.text,
                    'translated_content': new_generated_message.translated_text or '',
                    'ts': new_generated_message.created_at.strftime("%Y-%d-%m %H:%M") if new_generated_message.created_at else "",
                    "modStatus": new_generated_message.status,
                    'attachment': None,

                }
                payload['message'] = message_payload

                await publish_event(redis_pool,
                        type='message created',
                        payload=payload)

            return True


async def try_update_thread_memory(thread: Thread,
                                   session: AsyncSession,
                                   redis_pool: ArqRedis) -> bool:
    print('here ')

    message_count_after_last_message_id = await get_message_count_after_last_message_id(thread_id=thread.id,
                                                                                        last_message_id=thread.last_message_id,
                                                                                        session=session)
    iter_count = message_count_after_last_message_id // LIMIT_FOR_RAW_LOG_MESSAGES

    if iter_count == 0:
        return False

    new_thread_context = thread.context
    new_original_user_information = thread.original_user_information
    new_last_message_id = thread.last_message_id

    for i in range(iter_count):
        print(f'step {i+1} from {iter_count}...')
        new_thread_messages = await get_new_thread_messages(thread.id,
                                                            new_last_message_id,
                                                            session)

        raw_messages_log, user_message_only, new_last_message_id = await get_raw_messages_log_and_new_last_message_id(new_thread_messages)

        new_thread_context = await generate_thread_context(new_thread_context,
                                                           raw_messages_log)

        await asyncio.sleep(2)
        new_original_user_information = await ai_extract_user_info(user_message_only,
                                                                   new_original_user_information)

        await asyncio.sleep(2)

    # try:
    #     json.loads(new_original_user_information)
    # except Exception as ex:
    #     print(ex)
    # else:
    #     job = await redis_pool.enqueue_job(
    #         'try_translate_message_text',
    #         new_original_user_information,
    #         _queue_name='arq:utils',
    #     )fdssfs

    print('here 2')

    thread.context = new_thread_context
    thread.original_user_information = new_original_user_information
    thread.last_message_id = new_last_message_id

    return True


async def get_raw_messages_log_and_new_last_message_id(messages: list[Message]):
    unread_messages_text = ''
    user_message_text_only = ''

    new_last_message_id = None

    for message in messages:
        _text = f'{message.text} | {message.created_at} | {message.sender}\n'
        unread_messages_text += _text
        new_last_message_id = message.id

        if message.sender == 'user':
            user_message_text_only += _text
    
    return (
        unread_messages_text,
        user_message_text_only,
        new_last_message_id,
    )