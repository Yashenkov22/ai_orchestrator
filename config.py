import os

from dotenv import load_dotenv

from sqlalchemy.engine import URL


load_dotenv()


#DATABASE
DB_USER = os.environ.get('POSTGRES_USER')
DB_PASS = os.environ.get('POSTGRES_PASSWORD')
DB_HOST = os.environ.get('POSTGRES_HOST')
DB_PORT = os.environ.get('DB_PORT')
DB_NAME = os.environ.get('POSTGRES_DB')


db_url = URL.create(
    'postgresql+asyncpg',
    username=DB_USER,
    password=DB_PASS,
    host=DB_HOST,
    port=DB_PORT,
    database=DB_NAME,
)


#Redis
REDIS_HOST = os.environ.get('REDIS_HOST')
REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD')
REDIS_PORT = os.environ.get('REDIS_PORT')

REDIS_URL = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/0"

# JWT
JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY')
JWT_ALGORITHM = os.environ.get('JWT_ALGORITHM')

# API
API_PREFIX = '/api'

SECRET_FOR_PASSWORD = os.environ.get('SECRET_FOR_PASSWORD')


SECRET_API = os.environ.get('SECRET_API')


ADMIN_URL = os.environ.get('ADMIN_URL')


JOB_STORE_URL= f'postgresql+psycopg2://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}'

X_TOKEN = os.environ.get('X_TOKEN')

VISION_BROWSER_HOST = os.environ.get('VISION_BROWSER_HOST')

VISION_BROWSER_PORT = os.environ.get('VISION_BROWSER_PORT')

UPLOAD_DIR = 'media'

AI_API_TOKEN = os.environ.get('AI_API_TOKEN')

TRANSLATOR_URL = os.environ.get('TRANSLATOR_URL')

TRANSLATOR_PORT = os.environ.get('TRANSLATOR_PORT')

if TRANSLATOR_PORT:
    TRANSLATOR_LINK = f'{TRANSLATOR_URL}:{TRANSLATOR_PORT}'
else:
    TRANSLATOR_LINK = TRANSLATOR_URL


MEDIA_PATH = os.environ.get('MEDIA_PATH')