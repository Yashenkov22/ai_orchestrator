from fastapi import APIRouter

from utils import detector, translate, AVAILABLE_LANGUAGES


translation_router = APIRouter(prefix='/translate',
                               tags=['Translate'])


@translation_router.get('/translate_text')
async def translate_text(text: str):
    lang = detector.detect_language_of(text)

    print(text, lang)

    valid_lang = AVAILABLE_LANGUAGES.get(lang)

    if valid_lang:
        res = translate(text, valid_lang)
    else:
        res = f'ERROR WITH VALID LANG -> {lang}'
    
    return res