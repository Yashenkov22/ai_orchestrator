from transformers import M2M100ForConditionalGeneration
from transformers import M2M100Tokenizer

from lingua import LanguageDetectorBuilder, Language


AVAILABLE_LANGUAGES = {
    Language.RUSSIAN: "ru",
    Language.ENGLISH: "en",
    Language.SPANISH: "es",
    Language.ARABIC: "ar",
    Language.FRENCH: "fr",
    Language.PORTUGUESE: "pt",
    Language.UKRAINIAN: "uk",
    Language.BELARUSIAN: "be",
    Language.CHINESE: "zh",
    Language.ITALIAN: "it",
    Language.HINDI: "hi",
}

detector = LanguageDetectorBuilder.from_languages(*AVAILABLE_LANGUAGES).build()

MODEL_NAME = "facebook/m2m100_418M"

tokenizer = M2M100Tokenizer.from_pretrained(MODEL_NAME)
model = M2M100ForConditionalGeneration.from_pretrained(MODEL_NAME)

model.eval()


def translate(
    text: str,
    source_lang: str,
    target_lang: str = "ru"
):
    tokenizer.src_lang = source_lang

    encoded = tokenizer(
        text,
        return_tensors="pt"
    )

    generated_tokens = model.generate(
        **encoded,
        forced_bos_token_id=tokenizer.get_lang_id(target_lang),
        max_new_tokens=64
    )

    return tokenizer.batch_decode(
        generated_tokens,
        skip_special_tokens=True
    )[0]

