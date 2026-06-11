import pytz
import aiohttp

import enum

from passlib.context import CryptContext

from config import ADMIN_URL, X_TOKEN, VISION_BROWSER_HOST, VISION_BROWSER_PORT


INSTA_URL_PREFIX = 'https://www.instagram.com/'



moscow_tz = pytz.timezone('Europe/Moscow')


pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto"
)


def generate_valid_media_url(url: str | None):
    if url is not None and not url.startswith('http'):
        url = f'{ADMIN_URL}{url}'

    if isinstance(url, str):
        url = url.replace('./','')

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
        
        # print('FOLDER LIST', _response)
        return _response
    except Exception as ex:
        print(ex)
        raise


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
        
        # print('FOLDER PROFILES', _response)
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
        
        # print('FOLDER LIST', _response)
        return _response
    except Exception as ex:
        print(ex)
        raise


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
        
        # print('FOLDER LIST', _response)
        return _response
    except Exception as ex:
        print(ex)
        raise
