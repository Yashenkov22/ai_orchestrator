from openai import OpenAI, AsyncOpenAI

# from lingua import LanguageDetectorBuilder, Language

# from .base import AVAILABLE_LANGUAGES

from config import AI_API_TOKEN


client = AsyncOpenAI(
    api_key=AI_API_TOKEN,
    base_url="https://openrouter.ai/api/v1"
)


# detector = LanguageDetectorBuilder.from_languages(*AVAILABLE_LANGUAGES).build()


async def ai_generate_text(text: str,
                        account_information: str = None,
                        for_db: bool = False):
    print('запрос к нейронке...')
    
    if for_db:
        system_content =  "Ты — помощник, который делает выжимку из сообщений чата в инстаграм, сохраняя контект и смысл. Тебе будет приходить текст с предыдущей выжимкой и новыми непрочитанными сообщениями(новые сообщения будут в формате {текст сообщения} | {время сообщения} | {отправитель})"
        user_content = f"Вот новые сообщения и возможно предыдущая выжимка:\n{text}\n\nСделай краткую вижимку переписки, сохрани смысл и контекст"
    else:
        system_content = account_information
        # system_content =  "Ты — симпатичная девушка, которая игриво отвечает на сообщения в инстаграм, сохраняя контекcт и смысл переписки. Я буду присылать тебе текст с предыдущей выжимкой и новыми непрочитанными сообщениями(новые сообщения будут в формате {текст сообщения} | {время сообщения} | {отправитель}). Представь, что ты общаешься с этим человеком. Не пиши ничего, что может выдать тебя за искусственный интеллект! Не добавляй объяснения своего сообщения, только само сообщение"
        user_content = f"Вот новые сообщения и возможно предыдущая выжимка из чата:\n{text}\n\nПроанализируй и сгенерируй сообщение, которое я отправлю в этот чат"

    response = await client.chat.completions.create(
        model="deepseek/deepseek-chat",
        messages=[
            {
                "role": "system",
                "content": system_content
            },
            {
                "role": "user",
                "content": user_content
            }
        ]
    )
    result = response.choices[0].message.content
    print('ответ нейронки',result)

    return result



async def ai_translate_message(text: str):
    print('запрос к нейронке для перевода сообщения...')
    
    system_content =  "Ты — сервис для определения языка в сообщениях и для перевода этих сообщений на русский язык с сохранением смысла. Ты должен возвращать ответ в формате: если сообщение нужно переводить - <оригинальное сообщение>|<новое переведенное сообщение>|<язык исходного сообщения>, если сообщение не нужно переводить - то просто <оригинальное сообщение>"
    user_content = f"Вот сообщение - {text}"

    response = await client.chat.completions.create(
        model="deepseek/deepseek-chat",
        messages=[
            {
                "role": "system",
                "content": system_content
            },
            {
                "role": "user",
                "content": user_content
            }
        ]
    )
    result = response.choices[0].message.content
    print('ответ нейронки', result)

    return result