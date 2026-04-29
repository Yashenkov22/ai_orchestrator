import pytz

from passlib.context import CryptContext

from config import ADMIN_URL



moscow_tz = pytz.timezone('Europe/Moscow')


pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto"
)


def generate_valid_media_url(url: str):
    if not url.startswith('http'):
        url = f'{ADMIN_URL}{url}'
    
    return url