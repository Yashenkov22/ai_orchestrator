import re
import pytz
import aiohttp
import asyncio

from lingua import  Language

from passlib.context import CryptContext

from playwright.async_api import async_playwright

from config import ADMIN_URL, X_TOKEN, VISION_BROWSER_HOST, VISION_BROWSER_PORT, TRANSLATOR_LINK


INSTA_URL_PREFIX = 'https://www.instagram.com/'


# AVAILABLE_LANGUAGES = {
#     Language.RUSSIAN: "rus_Cyrl",
#     Language.ENGLISH: "eng_Latn",
#     Language.SPANISH: "spa_Latn",
#     Language.ARABIC: "arb_Arab",
#     Language.FRENCH: "fra_Latn",
#     Language.PORTUGUESE: "por_Latn",
#     Language.UKRAINIAN: "ukr_Cyrl",
#     Language.BELARUSIAN: "bel_Cyrl",
#     Language.CHINESE: "zho_Hans",
#     Language.ITALIAN: "ita_Latn",
#     Language.HINDI: "hin_Deva",
# }

# AVAILABLE_LANGUAGES = {
#     Language.RUSSIAN: "ru",
#     Language.ENGLISH: "en",
#     Language.SPANISH: "es",
#     Language.ARABIC: "ar",
#     Language.FRENCH: "fr",
#     Language.PORTUGUESE: "pt",
#     Language.UKRAINIAN: "uk",
#     Language.BELARUSIAN: "be",
#     Language.CHINESE: "zh",
#     Language.ITALIAN: "it",
#     Language.HINDI: "hi",
# }



moscow_tz = pytz.timezone('Europe/Moscow')


pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto"
)

RATIO_LIMIT = 0.3
RATIO_LEN_LIMIT = 4


def russian_ratio(text):
    letters = [c for c in text if c.isalpha()]

    if not letters:
        return 0

    russian = sum('А' <= c <= 'я' or c in 'Ёё' for c in letters)
    return russian / len(letters)


def generate_valid_media_url(url: str | None):
    if url is not None and not url.startswith('http'):
        url = f'{ADMIN_URL}{url}'

    if isinstance(url, str):
        url = url.replace('./','')

    if isinstance(url, str):
        url = url.replace('/srv','')

    return url



def generate_valid_insta_url(username: str | None):
    if username is not None:
        username = f'{INSTA_URL_PREFIX}{username}'
    
    return username


async def get_vision_folder_list(_timeout: int = 10):
    timeout = aiohttp.ClientTimeout(connect=_timeout,
                                    sock_connect=_timeout,
                                    sock_read=_timeout)
    headers = {
    'X-Token': X_TOKEN,
    'Content-Type': 'application/json',
    }
    url = 'https://api.browser.vision/api/v1/folders' 
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url=url,
                                   headers=headers) as response:
            # response = await session.get(xml_url,
            #                              headers=headers,
            #                              timeout=_timeout)
                # content_type = response.headers.get('Content-Type', '').lower()
                _response = await response.json()
        
        print('FOLDER LIST', _response)
        return _response
    except Exception as ex:
        print(ex)
        raise


async def dismiss_notifications_popup(page):
    """Закрывает popup с запросом уведомлений"""
    dismiss_texts = [
        'ไม่ใช่ตอนนี้',   # тайский
        'Not Now',          # английский
        'Не сейчас',        # русский
        'Jetzt nicht',      # немецкий
    ]
    for text in dismiss_texts:
        try:
            btn = page.get_by_role('button', name=text)
            if await btn.is_visible():
                await btn.click()
                print(f"Notifications popup dismissed ({text})")
                return
        except Exception:
            continue


async def get_folder_profiles(folder_id: str,
                              _timeout: int = 5):
    timeout = aiohttp.ClientTimeout(connect=_timeout,
                                    sock_connect=_timeout,
                                    sock_read=_timeout)
    headers = {
    'X-Token': X_TOKEN,
    'Content-Type': 'application/json',
    }
    url = f'https://api.browser.vision/api/v1/folders/{folder_id}/profiles' 
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url=url,
                                   headers=headers,
                                timeout=timeout) as response:
            # response = await session.get(xml_url,
            #                              headers=headers,
            #                              timeout=_timeout)
                # content_type = response.headers.get('Content-Type', '').lower()
                _response = await response.json()
        
        print('FOLDER PROFILES', _response)
        return _response
    except Exception as ex:
        print(ex)
        raise


async def get_active_profiles():
    headers = {
    'X-Token': X_TOKEN,
    'Content-Type': 'application/json',
    }
    url = f'http://{VISION_BROWSER_HOST}:{VISION_BROWSER_PORT}/list'
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url=url,
                                   headers=headers) as response:
            # response = await session.get(xml_url,
            #                              headers=headers,
            #                              timeout=_timeout)
                # content_type = response.headers.get('Content-Type', '').lower()
                _response = await response.json()
        
        # print('FOLDER LIST', _response)
        return _response
    except Exception as ex:
        print(ex)
        raise



async def try_start_profile(folder_id: str,
                            profile_id: str):
    headers = {
    'X-Token': X_TOKEN,
    'Content-Type': 'application/json',
    }
    url = f'http://{VISION_BROWSER_HOST}:{VISION_BROWSER_PORT}/start/{folder_id}/{profile_id}'
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url=url,
                                   headers=headers) as response:
            # response = await session.get(xml_url,
            #                              headers=headers,
            #                              timeout=_timeout)
                # content_type = response.headers.get('Content-Type', '').lower()
                _response = await response.json()
                # print('START STATUS -> ',response.status)
                # print('START RESULT -> ', _response)
        
        # print('FOLDER LIST', _response)
        return _response
    except Exception as ex:
        print(ex)
        raise


async def try_get_profile_port(folder_id: str,
                               profile_id: str):
    actived_profile = await try_start_profile(folder_id,
                                              profile_id)
    
    print(actived_profile)
    
    return actived_profile.get('port')


async def try_stop_profile(folder_id: str,
                           profile_id: str):
    headers = {
    'X-Token': X_TOKEN,
    'Content-Type': 'application/json',
    }
    url = f'http://{VISION_BROWSER_HOST}:{VISION_BROWSER_PORT}/stop/{folder_id}/{profile_id}'
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url=url,
                                   headers=headers) as response:
            # response = await session.get(xml_url,
            #                              headers=headers,
            #                              timeout=_timeout)
                # content_type = response.headers.get('Content-Type', '').lower()
                _response = await response.json()
                # print('STOP STATUS -> ',response.status)
                # print('STOP RESULT -> ', _response)
        
        # print('FOLDER LIST', _response)
        return _response
    except Exception as ex:
        print(ex)
        raise


async def cleanup_pages(context):
    """Закрыть все вкладки во всех контекстах браузера профиля."""
    for page in list(context.pages[1:]):
        try:
            await page.close()
            await asyncio.sleep(1)
        except Exception as e:
            print(f"[cleanup] failed to close {page.url}: {e!r}")


async def try_connect_to_main_instagram_page(profile_port: int):
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(f'http://{VISION_BROWSER_HOST}:{profile_port}')
            print(f"CONNECTED ON {profile_port} PORT")

            context = browser.contexts[0] if browser.contexts else await browser.new_context()

            await cleanup_pages(context)

            if len(context.pages) == 0:
                page = await context.new_page()

            return True
        

async def reject_request_chat(page, thread_url: str):
    """
    action: 'delete' — просто удалить тред (без блокировки)
            'block'  — заблокировать пользователя и удалить тред
    """
    await page.goto(thread_url, wait_until="domcontentloaded")

    # ждём реального признака готовности страницы, а не фиксированную паузу
    # try:
    #     await page.wait_for_selector('div[role="textbox"], button:has-text("Block")',
    #                                  timeout=20000)
    # except Exception:
    #     print(f"[reject] page didn't render expected UI in time, url={page.url}")
    
    await asyncio.sleep(4)

    await dismiss_notifications_popup(page)

    btn = page.get_by_role("button", name=re.compile(r"Block|บล็อก", re.I))

    btn_count = 0
    for _ in range(10):
        btn_count = await btn.count()
        if btn_count > 0:
            break
        await asyncio.sleep(1)

    print(f"[reject] Block button count after wait: {btn_count}")

    if await btn.count() == 0:
        return False

    await btn.first.click()
    await asyncio.sleep(2)

    # Block/Delete обычно открывает confirm-диалог — подтверди действие
    # (у Instagram часто всплывает модалка "Block этого пользователя?" с доп. кнопкой Block/Cancel)
    confirm_btn = page.get_by_role("button", name=re.compile(r"^Block$|^Delete$|ยืนยัน", re.I))
    if await confirm_btn.count() > 0:
        await confirm_btn.first.click()
        await asyncio.sleep(1.5)
        return True
        

async def try_block_thread(profile_port: int,
                           thread_url: str):
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(f'http://{VISION_BROWSER_HOST}:{profile_port}')
            print(f"CONNECTED ON {profile_port} PORT")

            context = browser.contexts[0] if browser.contexts else await browser.new_context()

            _page = await context.new_page()

            try:
                await asyncio.sleep(2)
                res = await reject_request_chat(_page,
                                                thread_url)
                
                print(' -> RES ',res)
                return res
            except Exception as ex:
                print(ex)
            finally:
                await _page.close()
                await asyncio.sleep(1)


async def try_translate_text(text: str):
    url = f'http://{TRANSLATOR_LINK}/translate/translate_text?text={text}'
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url=url) as response:
            # response = await session.get(xml_url,
            #                              headers=headers,
            #                              timeout=_timeout)
                # content_type = response.headers.get('Content-Type', '').lower()
                _response = await response.text()
        
        # print('FOLDER LIST', _response)
        return _response
    except Exception as ex:
        print(ex)
        raise