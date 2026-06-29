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


async def try_connect_to_main_instagram_page(profile_port: int):
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(f'http://{VISION_BROWSER_HOST}:{profile_port}')
            print(f"CONNECTED ON {profile_port} PORT")

            context = await browser.new_context()
            page = await context.new_page()

            current_url = page.url
            if 'instagram.com/' in current_url:
                await page.reload(wait_until='domcontentloaded')
            else:
                await page.goto('https://www.instagram.com/',
                                wait_until='domcontentloaded')
            
            await asyncio.sleep(2)
            
            return page.url.startswith('https://www.instagram')


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