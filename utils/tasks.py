import os
import re
import json
import random
import asyncio
import aiofiles
import time
import unicodedata

import aiohttp

from dataclasses import dataclass

from urllib.parse import parse_qs, urlsplit

from typing import Any

from urllib.parse import unquote

from pathlib import Path

from datetime import datetime, timezone, timedelta

from arq import ArqRedis, Retry

from sqlalchemy import select, update, insert

from sqlalchemy.dialects.postgresql import insert as pg_insert

from sqlalchemy.ext.asyncio import AsyncSession

from playwright.async_api import async_playwright

from background.base import acquire_task_lock
from db.queries import (check_insta_user, check_new_messages_in_thread,
                        check_thread_in_db, get_N_last_messages, get_all_threads_by_account, get_comment_notification_by_id, get_last_non_text_message_by_thread_id, get_message_count_after_last_message_id, get_message_only_by_id, get_new_thread_messages, get_thread_by_id,
                        try_add_insta_user,
                        # try_add_messages,
                        try_add_new_thread,
                        execute_and_catch_db_error, update_approve_thread, update_thread_is_unread_by_id)

from db.base import Attachment, Message, Thread, Account, CommentNotification

from utils.ai import ai_extract_user_info, generate_new_message_to_thread, generate_thread_context
from utils.enums import CoffeeStatusEnum, MessageStatusEnum, ThreadColorEnum, MessageTypeEnum

from utils.base import (dismiss_notifications_popup,
                        generate_valid_media_url,
                        is_video_thumbnail_response,
                        try_get_profile_port,
                        get_raw_messages_log_and_new_last_message_id)

from utils.schemas import CoffeeStateSchema
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


async def scroll_inbox_until_loaded_whole_thread_list(
    page,
    collected_data,
    known_map=None,
    max_rounds=200,
    wait_after_scroll=3.0,
    stable_rounds=3,
):

    item_sel = 'div[role="button"]'

    find_scroll_container_js = """() => {
        let best = null;
        let max = 50;
        for (const c of document.querySelectorAll('*')) {
            const s = getComputedStyle(c);
            if (s.overflowY === 'auto' || s.overflowY === 'scroll') {
                const d = c.scrollHeight - c.clientHeight;
                if (d > max) {
                    best = c;
                    max = d;
                }
            }
        }

        if (!best) {
            return null;
        }

        return {
            scrollTop: best.scrollTop,
            scrollHeight: best.scrollHeight,
            clientHeight: best.clientHeight,
        };

    }"""

    scroll_to_bottom_js = """() => {

        let best = null;

        let max = 50;

        for (const c of document.querySelectorAll('*')) {

            const s = getComputedStyle(c);

            if (s.overflowY === 'auto' || s.overflowY === 'scroll') {

                const d = c.scrollHeight - c.clientHeight;

                if (d > max) {

                    best = c;

                    max = d;

                }

            }

        }

        if (!best) {

            return {

                found: false

            };

        }

        const before = {

            scrollTop: best.scrollTop,

            scrollHeight: best.scrollHeight,

            clientHeight: best.clientHeight,

        };

        best.scrollTop = best.scrollHeight;

        return {

            found: true,

            before: before,

            after: {

                scrollTop: best.scrollTop,

                scrollHeight: best.scrollHeight,

                clientHeight: best.clientHeight,

            },

        };

    }"""

    stable_count = 0
    previous_height = None

    for i in range(max_rounds):
        pages_before = len(
            collected_data.get('SlideMailboxPages', [])
        )

        # Скроллим контейнер в самый низ

        res = await page.evaluate(scroll_to_bottom_js)
        count = await page.locator(item_sel).count()

        print(
            f"[scroll-inbox #{i}] "
            f"count={count} "
            f"pages_before={pages_before} "
            f"scroll={res}"
        )

        if not res.get('found'):
            print(
                "[scroll-inbox] "
                "scrollable container not found"
            )

            break

        height_before = res["after"]["scrollHeight"]

        # Ждём загрузку новых сообщений Instagram

        await page.wait_for_timeout(
            int(wait_after_scroll * 1000)
        )

        # Проверяем состояние контейнера после ожидания

        state = await page.evaluate(find_scroll_container_js)

        if state is None:
            print(
                "[scroll-inbox] "
                "scrollable container not found after wait"
            )

            break

        current_height = state["scrollHeight"]
        scroll_top = state["scrollTop"]
        client_height = state["clientHeight"]

        at_bottom = (
            scroll_top + client_height
            >= current_height - 2
        )

        pages_after = len(

            collected_data.get('SlideMailboxPages', [])

        )

        print(
            f"[scroll-inbox #{i}] "
            f"height={height_before}->{current_height} "
            f"pages={pages_before}->{pages_after} "
            f"scrollTop={scroll_top} "
            f"clientHeight={client_height} "
            f"at_bottom={at_bottom}"
        )

        # ---------------------------------------------------------

        # Instagram загрузил новые элементы.

        # Значит, конец ещё не достигнут.

        # ---------------------------------------------------------

        if (
            previous_height is not None
            and current_height > previous_height
        ):

            stable_count = 0

            print(
                f"[scroll-inbox #{i}] "
                f"new content loaded: "
                f"{previous_height} -> {current_height}"
            )

        # ---------------------------------------------------------

        # Высота не изменилась.

        # Если мы внизу — считаем стабильность.

        # ---------------------------------------------------------

        elif at_bottom:
            stable_count += 1

            print(
                f"[scroll-inbox #{i}] "
                f"bottom is stable: "
                f"{stable_count}/{stable_rounds}"
            )

            if stable_count >= stable_rounds:
                print(
                    "[scroll-inbox] "
                    "reached end of inbox"
                )
                break

        else:
            # Мы не внизу — следующая итерация снова скроллит.
            stable_count = 0

        previous_height = current_height

    else:

        print(
            f"[scroll-inbox] "
            f"max_rounds={max_rounds} reached"
        )

    return await page.locator(item_sel).count()


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
            'message_id': str(msg_id),
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
            msg_data['type'] = MessageTypeEnum.SYSTEM

        if ctype == 'TEXT':
            msg_data['text'] = node.get('text_body', '')
            msg_data['type'] = MessageTypeEnum.TEXT

        elif ctype.startswith('REACTION'):
            # text_body = node.get('text_body', '')
            msg_data['text'] = '* реакция на сообщение в чате'
            msg_data['type'] = MessageTypeEnum.REACTION

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
                msg_data['type'] = MessageTypeEnum.SHARED
        else:
            media_urls = extract_media_urls(node)
            if media_urls:
                files = await download_media(media_urls, thread_dir, str(thread_key), msg_id)
                msg_data['media_files'] = files

                if len(files) > 1:
                    msg_data['type'] = MessageTypeEnum.MUTLI_MEDIA
                else:
                    media_type, _ = files[0]
                    msg_data['type'] = media_type

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
                # print('SKIP THIS THREAD CAUSE LAST MESSAGE IN RESPONSE EQUAL WITH LAST MESSAGE FROM DB')
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
                            payload=payload_thread,
                            account_id=account.id)


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
    with_scroll: bool = False,
) -> dict:
    all_thread_data = {}
    thread_key = thread.thread_id
    user_insta_id = thread.insta_user.insta_id

    if with_scroll:
        await scroll_messages_until_seen(
            page, thread_responses, thread_key,
            last_seen_ts=thread.timestamp_last_seen_message
        )
        await page.wait_for_timeout(500)

    # try:
    #     page.remove_listener("response", on_response)
    #     await page.close()
    #     await asyncio.sleep(1)
    # except Exception as ex:
    #     print(' -> ERROR WITH TRY CLOSE PAGE IN FINNALY BLOCK', ex)

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
    # else:
    #     # add extra check for coffee scenario - send message if last message was from user (like reactions) without answer
    #     # maybe check time (типа ответить только не раньше 10 минут с момента последнего неотвечанного сообщения)
    #     if thread.coffee_state is not None:
    #         coffee_state = get_coffee_state(thread)

    #         if coffee_state.status == CoffeeStatusEnum.ACTIVE:
    #             # check last thread message (from user or not)
    #             last_message: Message = await get_last_non_text_message_by_thread_id(thread.id,
    #                                                                                  _session)

    #             if last_message.sender == 'user' and last_message.type != MessageTypeEnum.TEXT:
    #                 job = await redis.enqueue_job(
    #                     'background_how_are_you_generation',
    #                     thread.id,
    #                     _queue_name='arq:ai',
    #                 )


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


async def iterate_inbox_folders(page, inbox_received, collected_data, account, _session):
    tabs = await get_inbox_tabs(page)

    if account.parse_whole_thread_list:
        print('parse whole thread list...')
        known_map = None
        scroll_func = scroll_inbox_until_loaded_whole_thread_list
    else:
        print('parse only unread threads...')
        scroll_func = scroll_inbox_until_loaded
        known_map = await load_known_threads_map(account.id, _session)

    print(f"[inbox] найденные вкладки: {tabs}")  # временно, чтобы понять реальные имена

    if not tabs:
        print("[inbox] вкладок нет, единый список")
        await scroll_func(page, collected_data, known_map)
        return

    switched = await switch_inbox_tab(page, "General")
    if switched:
        inbox_received.clear()
        try:
            await asyncio.wait_for(inbox_received.wait(), timeout=15)
        except asyncio.TimeoutError:
            print("[inbox] таймаут ожидания ответа для General")
    # если не переключились — новой сети не будет, ждать нечего

    await scroll_func(page, collected_data, known_map)


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

                        if friendly_name == 'IGDThreadDetailQuery':
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

                            # print('adding...22', parsed)
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

                await iterate_inbox_folders(page, inbox_received, collected_data, account, _session)

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
            print(' -> FINALLY BLOCK...')
            try:
                page.remove_listener("response", on_response)
                await page.close()
                await asyncio.sleep(1)
            except Exception as ex:
                print('ERROR WITH CLOSE PAGE',ex)


async def scroll_and_collect(page,
                             thread_key,
                             thread_responses,
                             thread):
    await scroll_messages_until_seen(
        page, thread_responses, thread_key,
        last_seen_ts=thread.timestamp_last_seen_message
    )
    await page.wait_for_timeout(500)


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
            raise Retry(defer=25)

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

            await scroll_and_collect(detail_thread_page,
                                     thread.thread_id,
                                     thread_responses,
                                     thread)
            try:
                detail_thread_page.remove_listener("response", on_response)
                await detail_thread_page.close()
                await asyncio.sleep(1)
            except Exception as ex:
                print(' -> ERROR WITH TRY CLOSE PAGE IN FINNALY BLOCK', ex)

            await process_thread(thread, account.id, detail_thread_page,
                                thread_responses, thread_received, _session, redis)
            
        finally:
            try:
                detail_thread_page.remove_listener("response", on_response)
                await detail_thread_page.close()
                await asyncio.sleep(1)
            except Exception as ex:
                print(' -> ERROR WITH TRY CLOSE PAGE IN FINNALY BLOCK', ex)


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


async def type_caption(page, box, text: str):
    """Ввод текста в Lexical-композер Instagram с поддержкой переносов строк."""
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if line:
            await page.keyboard.insert_text(line)   # быстрее и надёжнее, чем type()
        if i < len(lines) - 1:
            await page.keyboard.press('Shift+Enter')  # перенос строки без отправки
    await asyncio.sleep(0.3)


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
                                payload=payload,
                                account_id=message.thread.account_id)
            
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
                                                    with_scroll=True)
            
            if media:
                _attachments = message.attachments
                _attachment = _attachments[0]
                media_url = _attachment.media_url

                if media_url.startswith('./'):
                    media_url = media_url[2:]
                if media_url.startswith('media/'):
                    media_url = media_url[len('media/'):]

                media_url_for_send = f'{MEDIA_PATH}/{media_url}'
                
                # media_url_for_send = f'/Users/skxnny/web/ai_orchestrator{media_url}'

                try:
                    inp = thread_for_send_message_page.locator('input[type="file"]')

                    await inp.set_input_files(media_url_for_send)   # абсолютный путь
                    await asyncio.sleep(2.5)

                    if media == 'photo':
                            # ждём появления превью вложения (кнопка "Remove")
                            await thread_for_send_message_page.wait_for_selector(
                                'button[aria-label^="Remove"], [aria-label^="Remove"]',
                                timeout=20000)

                    # Отправка через Enter в композере
                    box = thread_for_send_message_page.locator('div[role="textbox"]').last
                    await box.click()

                    # вводим подпись ДО нажатия Enter
                    caption = message.text
                    
                    if caption:
                        await type_caption(thread_for_send_message_page, box, caption)

                    # ловим РЕАЛЬНЫЙ сетевой ответ на отправку, не DOM
                    if media == 'photo':
                        async with thread_for_send_message_page.expect_response(
                            lambda r: '/graphql' in r.url and r.request.method == 'POST',
                            timeout=20000
                        ) as resp_info:
                            await thread_for_send_message_page.keyboard.press("Enter")

                        response = await resp_info.value
                        send_success = response.status == 200
                        print(" + фото отправлено")

                    elif media == 'video':
                        async with thread_for_send_message_page.expect_response(
                            is_video_thumbnail_response,
                            timeout=30000  # видео может обрабатываться дольше, чем фото
                        ) as resp_info:
                            await thread_for_send_message_page.keyboard.press("Enter")

                            response = await resp_info.value
                            send_success = response.status == 200                            
                        print(" + видео отправлено")

                except Exception as ex:
                    print('ERROR WITH TRY SEND MESSAGE', ex)

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
                "ts": (
                msg.created_at.strftime("%Y-%d-%m %H:%M")
                if msg.created_at else ""
            ),
            }

            payload['message'] = msg_payload

            await publish_event(redis,
                                type='Message updated',
                                payload=payload,
                                account_id=message.thread.account_id)


async def try_add_messages(message_data: dict,
                           thread: Thread,
                           session: AsyncSession,
                           redis_pool: ArqRedis):
    thread_id = message_data.get('thread_id')
    messages = message_data.get('messages')
    insert_messages = []
    message_ids_for_translate = []

    if thread_id and messages:
        for message in reversed(messages):
            ts = message.get('timestamp')
            sender = message.get('sender')

            if ts:
                ts = datetime.fromtimestamp(int(ts) / 1000,
                                            tz=timezone.utc)
            msg_data = {
                'created_at': ts,
                'updated_at': ts,
                'text': message.get('text'),
                'sender': sender,
                'status': 'approved',
                'thread_id': thread_id,
                'message_id': message.get('message_id')
            }

            if _type := message.get('type'):
                msg_data.update({'type': _type})

            new_message = Message(**msg_data,
                                  attachments=[Attachment(media_type=t, media_url=u) for t, u in message.get("media_files", [])])
            insert_messages.append(new_message)

        if insert_messages:
            session.add_all(insert_messages)

            await execute_and_catch_db_error(session.flush(),
                                             session,
                                             with_rollback=True)

            bg_task_already_exists = False
            
            if thread.coffee_state is not None:
                coffee_state = get_coffee_state(thread)

                if coffee_state.status == CoffeeStatusEnum.ACTIVE:
                    has_text_user_messages = any(msg.get('type', '') == MessageTypeEnum.TEXT and msg.get('sender', '') == 'user'  \
                                                 for msg in messages)
                    
                    if not has_text_user_messages:
                        bg_task_already_exists = True
                    
                    elif coffee_state.is_scenario_step:
                        # check only text message for scenario step
                            # bg job for coffee scenario
                            if not bg_task_already_exists:
                                job = await redis_pool.enqueue_job(
                                    'background_coffee_scenario',
                                    thread.id,
                                    _queue_name='arq:ai',
                                )
                                bg_task_already_exists = True
                    else:
                        # bg job for basic behavior
                        if not bg_task_already_exists:
                                job = await redis_pool.enqueue_job(
                                    'background_ai_generation',
                                    thread.id,
                                    True, # switch_to_scenario_step
                                    _queue_name='arq:ai',
                                )
                                bg_task_already_exists = True
                elif coffee_state.status == CoffeeStatusEnum.MODERATING:
                    bg_task_already_exists = True
                    
            if thread.color_level in (ThreadColorEnum.YELLOW, ThreadColorEnum.GREY) and thread.is_pinned:

                if not bg_task_already_exists:
                    job = await redis_pool.enqueue_job(
                        'background_ai_generation',
                        thread.id,
                        _queue_name='arq:ai',
                    )

            thread.is_unread = sender == 'user'
            thread.timestamp_last_seen_message = ts

            await execute_and_catch_db_error(session.commit(),
                                             session,
                                             with_rollback=True)

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
                    payload=payload,
                    account_id=thread.account_id)

            return True


async def try_update_thread_memory(thread: Thread,
                                   session: AsyncSession,
                                   redis_pool: ArqRedis = None) -> bool:
    # print('here ')

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

    # print('here 2')

    thread.context = new_thread_context
    thread.original_user_information = new_original_user_information
    thread.last_message_id = new_last_message_id

    return True


# async def get_raw_messages_log_and_new_last_message_id(messages: list[Message]):
#     unread_messages_text = ''
#     user_message_text_only = ''

#     new_last_message_id = None

#     for message in messages:
#         _text = f'{message.text} | {message.created_at} | {message.sender}\n'
#         unread_messages_text += _text
#         new_last_message_id = message.id

#         if message.sender == 'user':
#             user_message_text_only += _text
    
#     return (
#         unread_messages_text,
#         user_message_text_only,
#         new_last_message_id,
#     )


async def need_run_coffee_scenario(thread: Thread,
                                   _session: AsyncSession):
        message_limit = 20
        # activate_coffee_scenario = None
        coffee_state = thread.coffee_state # json или None

        if not coffee_state:
            return

        print(type(coffee_state))
        
        # coffee_state = CoffeeStateSchema(**coffee_state)
        try:
            if not isinstance(coffee_state, dict):
                coffee_state = json.loads(coffee_state)
            
            coffee_state = CoffeeStateSchema.model_validate(coffee_state)
        except Exception as ex:
            print('error with try validate', ex)
            # logger.exception("Битый coffee_state у треда %s", thread.id)
            return

    #     # описать сценарий "Кофе" на бэке как json

    #     # либо сделать Pydantic модель и загонять coffee_state в модель валидатор
    #     # coffee_status = coffee_state.get('status')
        coffee_status = coffee_state.status

        if coffee_status != CoffeeStatusEnum.ACTIVE:
            return

        last_N_messages = await get_N_last_messages(message_count=message_limit,
                                                    thread_id=thread.id,
                                                    session=_session)

        if len(last_N_messages) < message_limit:
            # обычное сообщение без сценария "Кофе"
            return
            # else:
                # activate_coffee_scenario = coffee_status == CoffeeStatusEnum.ACTIVE
                # "Кофе"
        
        return {
            'coffee_state': coffee_state,
            'last_messages': last_N_messages,
        }


def get_coffee_state(thread: Thread) -> CoffeeStateSchema:
        coffee_state = thread.coffee_state # json или None

        if not coffee_state:
            return
        
        try:
            if not isinstance(coffee_state, dict):
                coffee_state = json.loads(coffee_state)
            
            coffee_state = CoffeeStateSchema.model_validate(coffee_state)
            
            return coffee_state
        except Exception as ex:
            print('error with try validate', ex)
            return


# import re
# import json
# import asyncio

NOTIF_LABELS = ("Notifications", "Уведомления")


async def _notif_target(page):
    """Ближайший кликабельный предок подписи/иконки «Уведомления»."""
    for label in NOTIF_LABELS:
        span = page.locator("span", has_text=re.compile(rf"^\s*{label}\s*$")).first
        if await span.count() and await span.is_visible():
            return span.locator(
                'xpath=ancestor-or-self::*[self::a or @role="link" or @role="button"][1]'
            )
    # свёрнутый сайдбар — по aria-label иконки
    for label in NOTIF_LABELS:
        icon = page.locator(f'svg[aria-label="{label}"]').first
        if await icon.count():
            return icon.locator(
                'xpath=ancestor::*[self::a or @role="link" or @role="button"][1]'
            )
    return None


async def _wait_box_stable(locator, timeout_ms=1500, step_ms=100):
    """Ждём, пока элемент перестанет двигаться/менять размер (анимация сайдбара)."""
    prev = None
    waited = 0
    while waited < timeout_ms:
        box = await locator.bounding_box()
        if box and prev and all(abs(box[k] - prev[k]) < 1 for k in box):
            return
        prev = box
        await asyncio.sleep(step_ms / 1000)
        waited += step_ms


async def click_sidebar_notifications(page, opened_event: asyncio.Event) -> bool:
    try:
        await page.wait_for_selector(
            ", ".join(f'svg[aria-label="{l}"]' for l in NOTIF_LABELS),
            state="visible",
            timeout=20000,
        )
    except Exception:
        print("Sidebar not rendered")
        return False

    for attempt in range(1, 3):
        target = await _notif_target(page)
        if target is None or not await target.count():
            print("Notifications item not found")
            return False

        await target.hover()                    # раскрываем сайдбар
        await _wait_box_stable(target)          # ждём конца анимации, а не фикс. паузу
        target = await _notif_target(page)      # локатор после раскрытия
        await target.click(force=(attempt == 2))

        try:
            await asyncio.wait_for(opened_event.wait(), timeout=4)
            return True
        except asyncio.TimeoutError:
            print(f"[attempt {attempt}] panel did not open")
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)

    return False
# async def click_sidebar_notifications(page, opened_event: asyncio.Event) -> bool:
#     # ждём, пока сайдбар отрисуется и оживёт
#     try:
#         await page.wait_for_selector(
#             ", ".join(f'svg[aria-label="{l}"]' for l in NOTIF_LABELS),
#             timeout=20000,
#         )
#     except Exception:
#         print("Sidebar not rendered")
#         return False
#     await page.wait_for_timeout(1500)

#     for attempt in range(1, 4):
#         target = await _notif_target(page)
#         if target is None or not await target.count():
#             print("Notifications item not found")
#             return False

#         # отладка: что именно кликаем
#         html = await target.evaluate("el => el.outerHTML.slice(0, 200)")
#         box = await target.bounding_box()
#         print(f"[attempt {attempt}] target={html!r} box={box}")

#         await target.scroll_into_view_if_needed()
#         if attempt == 1:
#             await target.click()
#         elif attempt == 2:
#             await target.hover()
#             await page.wait_for_timeout(300)
#             await target.click(force=True)
#         else:
#             await target.dispatch_event("click")

#         try:
#             await asyncio.wait_for(opened_event.wait(), timeout=6)
#             return True          # пришёл xdt_activity_inbox — панель открылась
#         except asyncio.TimeoutError:
#             print(f"[attempt {attempt}] panel did not open")
#             # await page.screenshot(path=f"notif_attempt_{attempt}.png")
#             await page.keyboard.press("Escape")   # на случай, если панель была открыта и мы её закрыли
#             await page.wait_for_timeout(1000)

#     return False


#####

NOTIFICATIONS_RE = re.compile(r'^\s*(Notifications|Уведомления)\s*$', re.I)
COMMENTS_FILTER_RE = re.compile(r'^\s*(Comments|Комментарии)\s*$', re.I)


KEYWORDS = ["test", "тест"]  # <- свои слова
 
 
def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).casefold()
    return s.replace("ё", "е")
 
 
def build_matcher(keywords: list[str]):
    words = sorted({_normalize(k) for k in keywords if k.strip()}, key=len, reverse=True)
    if not words:
        return lambda text: False
    # слово целиком: эмодзи, пунктуация и # вокруг не мешают
    pattern = re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, words)) + r")(?!\w)")
    return lambda text: bool(text) and bool(pattern.search(_normalize(text)))
 
 
matches_keyword = build_matcher(KEYWORDS)


# async def click_sidebar_notifications(page) -> bool:
#     """Ищет в сайдбаре пункт «Notifications»/«Уведомления» и кликает по нему."""
#     # 1. Развёрнутый сайдбар: пункт с видимой подписью
#     item = page.locator('a, [role="link"], [role="button"]').filter(
#         has=page.locator('span', has_text=NOTIFICATIONS_RE)
#     ).first
#     if await item.count() and await item.is_visible():
#         await item.click()
#         return True

#     # 2. Свёрнутый сайдбар (узкое окно): подписи скрыты, но у иконки есть aria-label
#     icon = page.locator(
#         'svg[aria-label="Notifications"], svg[aria-label="Уведомления"]'
#     ).first
#     if await icon.count():
#         clickable = icon.locator(
#             'xpath=ancestor::*[self::a or @role="link" or @role="button"][1]'
#         )
#         await (clickable if await clickable.count() else icon).click()
#         return True

#     return False


@dataclass
class IGComment:
    comment_id: str
    media_pk: str
    shortcode: str
    is_reel: bool
    user_pk: str
    username: str
    follows_me: bool
    text: str | None      # None для комментариев-GIF / аватаров
    ts: float             # unix-время комментария
    notif_pk: str

COMMENT_STORY_TYPE = 12


WATERMARK_MARGIN = timedelta(minutes=30)   # запас на «опоздавшие» уведомления
# MAX_AGE = timedelta(hours=6)               # на более старые комменты не реагируем
 
 
def _dt(ts: float | datetime) -> datetime:
    if isinstance(ts, datetime):
        return ts
    return datetime.fromtimestamp(ts, tz=timezone.utc)
 
 
async def save_new_comments(session: AsyncSession,
                            account_id: int,
                            comments: list[IGComment]) -> dict[str, int]:
    """Вставляет пачку, возвращает {comment_id: id} только для реально новых записей."""
    if not comments:
        return {}
 
    unique = {c.comment_id: c for c in comments}.values()
    rows = [
        {
            "account_id": account_id,
            "username": c.username,
            "comment_id": c.comment_id,
            "timestamp": _dt(c.ts),
            "shortcode": c.shortcode,
            'media_pk': c.media_pk,
            'text': c.text,
        }
        for c in unique if matches_keyword(c.text)
    ]
 
    stmt = (
        pg_insert(CommentNotification)
        .values(rows)
        # имя должно совпадать с UniqueConstraint в модели
        .on_conflict_do_nothing(constraint="uq_comment_notifications_account_comment")
        .returning(CommentNotification.id, CommentNotification.timestamp)
    )
    result = await session.execute(stmt)
    await session.commit()
    return {_id: timestamp for _id, timestamp in result.all()}


async def process_comment_feed(session: AsyncSession,
                               account: Account,
                               comments: list[IGComment]) -> dict[str, int]:
    """
    Сохраняет комментарии и возвращает {comment_id: row_id} для тех,
    на которые нужно реагировать (новые и свежие).
 
    Первый запуск (last_comment_notification_at IS NULL) — bootstrap:
    всё сохраняем, но ничего не возвращаем, чтобы не отвечать на старое.
    """
    # watermark = account.last_comment_notification_at
    # first_run = watermark is None
 
    # if not first_run:
    #     border = watermark - WATERMARK_MARGIN
    #     comments = [c for c in comments if _dt(c.ts) > border]
 
    new = await save_new_comments(session, account.id, comments)
 
    if new:
        print(' save in lasttimestamp in account...')
        newest = max(_dt(ts) for ts in new.values())
        # if first_run or newest > watermark:
        await session.execute(
            update(Account)
            .where(Account.id == account.id)
            .values(last_comment_notification_at=newest)
        )
        await session.commit()
        account.last_comment_notification_at = newest
 
    # if first_run:
    #     return {}
 
    # now = time.time()
    # fresh_ids = {c.comment_id for c in comments
    #              if now - c.ts <= MAX_AGE.total_seconds()}
    # return {cid: rid for cid, rid in new.items() if cid in fresh_ids}
    return {_id: ts for _id, ts in new.items()}


async def click_comments_filter(page) -> bool:
    """Переключает панель уведомлений на фильтр «Комментарии», если он есть."""
    btn = page.get_by_role('button', name=COMMENTS_FILTER_RE).first
    if not await btn.count():
        btn = page.locator('[role="tab"], [role="button"], span').filter(
            has_text=COMMENTS_FILTER_RE
        ).first
    if await btn.count() and await btn.is_visible():
        await btn.click()
        return True
    return False


def _comment_text(args: dict) -> str | None:
    """
    Достаёт текст комментария из строки уведомления, не завися от языка:
    'user commented: nice pic' / 'user heeft een opmerking geplaatst: ❤️'.
    links[0].end — конец юзернейма, дальше ищем первое ': '.
    """
    raw = args.get("text") or ""
    links = args.get("links") or []
    start = links[0].get("end", 0) if links else 0
    idx = raw.find(": ", start)
    return raw[idx + 2:].strip() if idx != -1 else None


def extract_comment_items(payload: dict) -> list[IGComment]:
    # """Возвращает комментарии из ответа (вкладка «Все» или «Комментарии»)."""
    # inbox = ((payload or {}).get("data") or {}).get("xdt_activity_inbox")
    # if not inbox:
    #     return []
    """Принимает dict или список dict'ов (несколько JSON-чанков одного ответа)."""
    if isinstance(payload, list):
        out = []
        for chunk in payload:
            out.extend(extract_comment_items(chunk))
        return out
    if not isinstance(payload, dict):
        return []

    inbox = (payload.get("data") or {}).get("xdt_activity_inbox")
    if not inbox:
        return []

    stories = (inbox.get("new_stories") or []) + (inbox.get("old_stories") or [])
    out: list[IGComment] = []
 
    for s in stories:
        if s.get("story_type") != COMMENT_STORY_TYPE:
            continue  # лайки, подписки, системные, Threads и т.п.
 
        args = s.get("args") or {}
        dest = args.get("destination") or ""
        # "comments_v2?media_id=..&target_comment_id=.." / "clips_home?id=..&target_comment_id=.."
        qs = parse_qs(urlsplit("x://" + dest).query)
        comment_id = (qs.get("target_comment_id") or [None])[0]
 
        users = args.get("users") or []
        media = args.get("media") or {}
        if not comment_id or not users:
            continue
 
        u = users[0]
        out.append(IGComment(
            comment_id=str(comment_id),
            media_pk=(media.get("id") or "").split("_")[0],
            shortcode=media.get("shortcode") or "",
            is_reel=dest.startswith("clips_home"),
            user_pk=str(u.get("pk") or u.get("id") or ""),
            username=u.get("username") or "",
            follows_me=bool((u.get("friendship_status") or {}).get("followed_by")),
            text=_comment_text(args),
            ts=float(args.get("timestamp") or 0),
            notif_pk=s.get("pk") or "",
        ))
 
    return out


async def parse_comment_notifications_playwright(account: Account,
                                                 profile_port: int,
                                                 _session: AsyncSession,
                                                 redis: ArqRedis,
                                                 use_comments_filter: bool = True):
    activity_responses = []
    activity_received = asyncio.Event()

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(f'http://{VISION_BROWSER_HOST}:{profile_port}')
            print(f"CONNECTED ON {profile_port} PORT")
        except Exception as ex:
            print(f'ERROR WITH TRY CONNECT TO BROWSER WITH {profile_port} PORT', ex)
            new_profile_port = await try_get_profile_port(account.folder_id,
                                                          account.profile_id)
            if not new_profile_port:
                return
            browser = await p.chromium.connect_over_cdp(f'http://{VISION_BROWSER_HOST}:{new_profile_port}')
            print(f"CONNECTED ON {new_profile_port} PORT")

        context = browser.contexts[0] if browser.contexts else await browser.new_context()

        # if len(context.pages) >= 6:
        #     raise Retry(defer=25)

        notifications_page = await context.new_page()

        async def on_response(response):
            req = response.request
            if req.resource_type not in ('xhr', 'fetch'):
                return
            url = response.url
            if '/api/graphql' not in url and '/graphql/query' not in url:
                return
            try:
                body = await response.text()
            except Exception:
                return
            # friendly name не фиксируем — ловим по содержимому
            if '"xdt_activity_inbox"' not in body:
                return
            try:
                parsed = parse_ig_response(body)   # твоя функция; если она ждёт другой формат — json.loads(body)
                activity_responses.append(parsed)
                activity_received.set()
                fn = extract_friendly_name(req.post_data) if req.post_data else None
                print(f"[ACTIVITY] {fn}")
            except Exception as e:
                print(f"[ERROR] activity inbox: {e}")

        try:
            notifications_page.on("response", on_response)

            # === 1. Главная ===
            await notifications_page.goto('https://www.instagram.com/direct',
                                          wait_until='domcontentloaded')
            # await asyncio.sleep(3)
            await dismiss_notifications_popup(notifications_page)

            # === 2. Сайдбар -> Уведомления ===
            if not await click_sidebar_notifications(notifications_page, activity_received):
                print(f"[{account.username}] could not open notifications panel")
                return
            print("Activity inbox received!")

            try:
                await asyncio.wait_for(activity_received.wait(), timeout=15)
                print("Activity inbox received!")
            except asyncio.TimeoutError:
                print("Activity inbox timeout")

            # === 3. Фильтр «Комментарии» (глубже окно по комментам) ===
            if use_comments_filter:
                await notifications_page.wait_for_timeout(1500)
                activity_received.clear()
                if await click_comments_filter(notifications_page):
                    try:
                        await asyncio.wait_for(activity_received.wait(), timeout=15)
                        print("Comments filter received!")
                    except asyncio.TimeoutError:
                        print("Comments filter timeout")
                else:
                    print("Comments filter not found — using 'All' tab")

            # await notifications_page.wait_for_timeout(1000)
            # await notifications_page.keyboard.press('Escape')   # закрыть панель

            # === 4. Разбор и сохранение ===
            comments = []
            for payload in activity_responses:
                comments.extend(extract_comment_items(payload))

            print('1.comments',comments)

            new = await process_comment_feed(_session, account, comments)

            print('2.new',new)

            for comment in new:
                print(' -> на выполенение', comment)
                # run bg tasks

        finally:
            try:
                notifications_page.remove_listener("response", on_response)
                await notifications_page.close()
                await asyncio.sleep(1)
            except Exception as ex:
                print(' -> ERROR WITH TRY CLOSE PAGE IN FINALLY BLOCK', ex)


_SC_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"

def media_pk_to_shortcode(pk: str | int) -> str:
    pk = int(pk)
    out = ""
    while pk:
        pk, r = divmod(pk, 64)
        out = _SC_ALPHABET[r] + out
    return out


POST_BTN_RE = re.compile(r'^\s*(Post|Опубликовать|Plaatsen)\s*$', re.I)


async def type_and_post_comment(page, text: str) -> bool:
    box = page.locator('form textarea').first
    await box.wait_for(state='visible', timeout=10000)
    await box.click()
    await box.press('End')                      # курсор после "@username "
    await human_pause(0.3, 0.7)

    char_delay = random.uniform(40, 100)
    type_timeout = int(len(text) * char_delay) + 5_000
    await box.press_sequentially(text, delay=char_delay, timeout=type_timeout)
    await human_pause(0.5, 1.2)

    # кнопка надёжнее Enter; если не нашли — Enter
    btn = page.locator('form').get_by_role('button', name=POST_BTN_RE).first
    if await btn.count() and await btn.is_enabled():
        await btn.click()
    else:
        await box.press('Enter')

    # подтверждение: поле очистилось
    await page.wait_for_function(
        """() => {
            const t = document.querySelector('form textarea');
            return t && t.value.trim() === '';
        }""",
        timeout=15000,
    )
    await human_pause(0.8, 1.5)
    return True


THREAD_URL_RE = re.compile(r'/direct/t/(\d+)')
NEW_MESSAGE_LABELS = ('New message', 'Новое сообщение')
CHAT_BTN_RE = re.compile(r'^\s*(Chat|Чат)\s*$', re.I)


async def click_new_message(page) -> bool:
    """Кнопка с <svg><title>New message</title></svg> в инбоксе."""
    for label in NEW_MESSAGE_LABELS:
        svg = page.locator(
            f'svg:has(> title:text-is("{label}")), svg[aria-label="{label}"]'
        ).first
        try:
            await svg.wait_for(state='visible', timeout=10000)
        except Exception:
            continue
        # кликаем ближайший кликабельный предок, а не сам svg
        target = svg.locator(
            'xpath=ancestor::*[self::a or self::button or @role="button" or @role="link"][1]'
        )
        if not await target.count():
            target = svg
        await target.hover()
        await human_pause(0.2, 0.5)
        await target.click()
        return True
    return False


# async def open_dialog_with_user(page, username: str) -> str | None:
#     """Окно «Новое сообщение» → поиск → выбор юзера → «Chat». Возвращает thread_id."""
#     dialog = page.get_by_role('dialog').last
#     await dialog.wait_for(state='visible', timeout=10000)

#     search = dialog.locator('input[name="queryBox"], input[type="text"], input[type="search"]').first
#     await search.click()
#     await human_pause(0.3, 0.6)
#     await search.press_sequentially(username, delay=random.uniform(70, 140))

#     # строка выдачи с точным совпадением ника
#     row = dialog.locator('[role="button"], [role="listitem"], label').filter(
#         has=page.get_by_text(username, exact=True)
#     ).first
#     try:
#         await row.wait_for(state='visible', timeout=10000)
#     except Exception:
#         print(f" - {username} не найден в поиске (сменил ник / закрыл ДМ)")
#         return None
#     await human_pause(0.3, 0.8)
#     await row.click()
#     await human_pause(0.4, 0.9)

#     chat_btn = dialog.get_by_role('button', name=CHAT_BTN_RE).first
#     await chat_btn.wait_for(state='visible', timeout=10000)
#     await chat_btn.click()

#     await page.wait_for_url(THREAD_URL_RE, timeout=15000)
#     m = THREAD_URL_RE.search(page.url)
#     return m.group(1) if m else None

async def _chat_btn_enabled(dialog) -> bool:
    btn = dialog.get_by_role('button', name=CHAT_BTN_RE).first
    if not await btn.count():
        return False
    disabled = await btn.get_attribute('aria-disabled')
    return disabled != 'true' and await btn.is_enabled()


async def open_dialog_with_user(page, username: str) -> str | None:
    """Окно «Новое сообщение» → поиск → выбор юзера → «Chat». Возвращает thread_id."""
    dialog = page.get_by_role('dialog').last
    await dialog.wait_for(state='visible', timeout=10000)

    search = dialog.locator('input[name="queryBox"], input[type="text"], input[type="search"]').first
    await search.click()
    await human_pause(0.3, 0.6)
    await search.press_sequentially(username, delay=random.uniform(70, 140))

    # текст ника в выдаче (точное совпадение)
    name_el = dialog.get_by_text(username, exact=True).last
    try:
        await name_el.wait_for(state='visible', timeout=10000)
    except Exception:
        print(f" - {username} не найден в поиске (сменил ник / закрыл ДМ)")
        return None
    await human_pause(0.5, 1.0)          # даём выдаче дорисоваться

    # ближайшая кликабельная строка вокруг ника
    row = name_el.locator(
        'xpath=ancestor::*[@role="button" or @role="option" or @role="checkbox" or self::label][1]'
    )
    if not await row.count():
        row = name_el

    # кликаем и проверяем, что юзер выбран (кнопка Chat активировалась)
    selected = False
    for attempt in range(1, 4):
        await row.hover()
        await human_pause(0.2, 0.4)
        if attempt < 3:
            await row.click()
        else:
            # последний вариант — клик по чекбоксу/радио внутри строки
            checkbox = row.locator('input[type="checkbox"], input[type="radio"], [role="checkbox"]').first
            await (checkbox if await checkbox.count() else row).click(force=True)

        try:
            await page.wait_for_function(
                """(dlg) => {
                    const btns = [...dlg.querySelectorAll('[role="button"], button')];
                    const chat = btns.find(b => /^(Chat|Чат)$/i.test((b.innerText || '').trim()));
                    return chat && chat.getAttribute('aria-disabled') !== 'true' && !chat.disabled;
                }""",
                arg=await dialog.element_handle(),
                timeout=3000,
            )
            selected = True
            break
        except Exception:
            print(f" [attempt {attempt}] юзер не выбран, повторяю")

    if not selected:
        print(f" - не удалось выбрать {username} в выдаче")
        return None

    await human_pause(0.4, 0.9)
    chat_btn = dialog.get_by_role('button', name=CHAT_BTN_RE).first
    await chat_btn.click()

    await page.wait_for_url(THREAD_URL_RE, timeout=15000)
    m = THREAD_URL_RE.search(page.url)
    return m.group(1) if m else None


async def send_dm_text(page, message_text: str) -> bool:
    """Твой код отправки в Lexical-композер."""
    box = page.locator('div[role="textbox"]').last
    try:
        await box.wait_for(state='visible', timeout=15000)
    except Exception:
        print(" - поле ввода не найдено (запросы закрыты?)")
        return False

    await box.click()
    await human_pause(0.3, 0.7)

    char_delay = random.uniform(30, 90)
    type_timeout = int(len(message_text) * char_delay) + 5_000
    await box.press_sequentially(message_text, delay=char_delay, timeout=type_timeout)
    await human_pause(0.4, 1.0)

    await page.keyboard.press('Enter')

    await page.wait_for_function(
        """() => {
            const el = document.querySelectorAll('div[role="textbox"]');
            const last = el[el.length - 1];
            return last && last.innerText.trim() === '';
        }""",
        timeout=15000,
    )
    await human_pause(0.8, 1.5)
    return True


REPLY_RE = re.compile(r'^\s*(Reply|Ответить|Beantwoorden)\s*$', re.I)


async def click_reply_under_comment(page, comment_id: str, username: str) -> bool:
    """Находит блок нужного комментария и нажимает «Reply» под ним."""
    # 1. ссылка-время конкретного комментария
    anchor = page.locator(f'a[href*="/c/{comment_id}"]').first
    try:
        await anchor.wait_for(state='visible', timeout=15000)
    except Exception:
        # запасной путь: по ссылке на автора
        anchor = page.locator(f'a[href="/{username}/"]').last
        if not await anchor.count():
            print(" - комментарий не найден (удалён/скрыт?)")
            return False

    # 2. поднимаемся к ближайшему предку, внутри которого есть «Reply»
    reply_btn = None
    for level in range(1, 10):
        container = anchor.locator(f'xpath=ancestor::*[{level}]')
        btn = container.get_by_role('button', name=REPLY_RE)
        if not await btn.count():
            btn = container.locator('span, div').filter(has_text=REPLY_RE)
        if await btn.count():
            reply_btn = btn.first
            break

    if reply_btn is None:
        print(" - кнопка Reply не найдена")
        return False

    await reply_btn.scroll_into_view_if_needed()
    await reply_btn.hover()
    await human_pause(0.3, 0.7)
    await reply_btn.click()

    # 3. проверяем, что в поле подставилось @username
    try:
        await page.wait_for_function(
            """(u) => {
                const t = document.querySelector('form textarea');
                return t && t.value.toLowerCase().includes('@' + u.toLowerCase());
            }""",
            arg=username,
            timeout=5000,
        )
    except Exception:
        print(" - после Reply поле не заполнилось упоминанием")
        return False
    return True


async def answer_to_comment_under_post_and_to_dm(comment: CommentNotification,
                                                 profile_port: int,
                                                 _session: AsyncSession):
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(f'http://{VISION_BROWSER_HOST}:{profile_port}')
            print(f"CONNECTED ON {profile_port} PORT")
        except Exception as ex:
            print(f'ERROR WITH TRY CONNECT TO BROWSER WITH {profile_port} PORT', ex)
            new_profile_port = await try_get_profile_port(comment.account.folder_id,
                                                          comment.account.profile_id)
            if not new_profile_port:
                return
            browser = await p.chromium.connect_over_cdp(f'http://{VISION_BROWSER_HOST}:{new_profile_port}')
            print(f"CONNECTED ON {new_profile_port} PORT")

        context = browser.contexts[0] if browser.contexts else await browser.new_context()

        try:
            post_page = await context.new_page()

            if not comment.comment_answer:
                shortcode = comment.shortcode or media_pk_to_shortcode(comment.media_pk)

                await post_page.goto(f'https://www.instagram.com/p/{shortcode}/c/{comment.comment_id}/',
                                    wait_until='domcontentloaded')

                answer_text = 'test_reply'
                if await click_reply_under_comment(post_page, comment.comment_id, comment.username):
                    text = answer_text                       # @username уже стоит в поле
                else:
                    text = f'@{comment.username} {answer_text}'   # фолбэк: обычный коммент с упоминанием
                # text = f'@{comment.username} {answer_text}'

                if await type_and_post_comment(post_page, text):
                    print(" + ответ на комментарий опубликован")
                    comment.comment_answer = answer_text

                    await execute_and_catch_db_error(_session.commit(),
                                                    _session,
                                                    with_rollback=True)
            if not comment.dm_answer:
                # ....
                await post_page.goto('https://www.instagram.com/direct/inbox/',
                                wait_until='domcontentloaded')
                await dismiss_notifications_popup(post_page)

                if not await click_new_message(post_page):
                    print(" - кнопка New message не найдена")
                    return

                thread_id = await open_dialog_with_user(post_page, comment.username)
                if not thread_id:
                    return
                print(f" + тред открыт: {thread_id}")

                dm_text = 'test_dm'
                if await send_dm_text(post_page, dm_text):
                    print(" + сообщение в директ отправлено")
                    comment.dm_answer = dm_text
                    await execute_and_catch_db_error(_session.commit(),
                                                        _session,
                                                        with_rollback=True)
        finally:
            await asyncio.sleep(2)
            await post_page.close()