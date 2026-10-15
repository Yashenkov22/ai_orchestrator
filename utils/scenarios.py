from random import shuffle

from sqlalchemy.ext.asyncio import AsyncSession

from db.base import Account, CoffeeScenarioPhoto, Thread, Message

from utils.ai import generate_new_message_to_thread_coffee_scenario, like_jev_ai_request
from utils.enums import CoffeeStepTypeSchema
from utils.schemas import CoffeeStateSchema

# from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul

from utils.base import get_raw_messages_log_and_new_last_message_id

from config import GENERATE_PHOTO_CAPTION, TYPESAFE_API_KEY


# coffee_scenario = {
#     'step_1': '''
#         Напиши, что ты устала.
#         Конкретную формулировку выбери самостоятельно в зависимости от контекста переписки:
#         насколько сильно ты устала и от чего именно.
#     ''',
#     'step_2': '''
#         Отправь подготовленное фото «Кофе-Уставшая».
#     ''',
#     'step_3': '''
#         Узнай, сможет ли он угостить тебя кофе. Подразумевается, что ты и собеседник в разных городах.
#     ''',
#     'step_4': '''
#        Отправь подготовленное фото «Кофе-Счастливая».
#     ''',
# }

base_coffee_state = {
    'status': 'active',
    'logs': {},
    'current_step': 1,
    'is_scenario_step': True,
}

# coffee_scenario = {

#     'step_1': {
#         'type': CoffeeStepTypeSchema.TEXT_MESSAGE,
#         'instruction': '''
#             Напиши, что ты устала. Сделай это с легким намеком на то, что впереди еще дела, а у тебя уже нет сил.
#             Конкретную формулировку выбери самостоятельно в зависимости от контекста переписки:
#             насколько сильно ты устала и от чего именно.
#         '''
#     },
#     'step_2': {
#         'type': CoffeeStepTypeSchema.PHOTO_MESSAGE,
#         'instruction': '''
#             Отправь подготовленное фото «Кофе-до».
#         '''
#     },
#     'step_3': {
#         'type': CoffeeStepTypeSchema.TEXT_MESSAGE,
#         'instruction': '''
#             Узнай, сможет ли он угостить(оплатить) тебя кофе. Подразумевается, что ты и собеседник в разных городах.
#         '''
#     },
#     'step_4': {
#         'type': CoffeeStepTypeSchema.MODERATING,
#         'instruction': '''
#             Ожидание модерации, куда скинуть на кофе.
#         '''
#     },






#     'step_5': {
#         'type': CoffeeStepTypeSchema.TEXT_MESSAGE,
#         'instruction': '''
#             Поблагодари собеседника, скажи что скоро отправишь фото.
#         '''
#     },
#     'step_6': {
#         'type': CoffeeStepTypeSchema.PHOTO_MESSAGE,
#         'instruction': '''
#             Отправь подготовленное фото «Кофе-после».
#         '''
#     },
# }

coffee_scenario = {
    'step_1': {
        'type': CoffeeStepTypeSchema.PREPARING,
        'instruction': '''
            Проверь, есть ли в чате 50+ текстовых сообщений. До этого момента обычное общение.
        '''
    },
    'step_2': {
        'type': CoffeeStepTypeSchema.TEXT_MESSAGE,
        'instruction': '''
            Напиши, что ты устала. Сделай это с легким намеком на то, что впереди еще дела, а у тебя уже нет сил.
            Конкретную формулировку выбери самостоятельно в зависимости от контекста переписки:
            насколько сильно ты устала и от чего именно.
        '''
    },
    'step_3': {
        'type': CoffeeStepTypeSchema.PHOTO_MESSAGE,
        'instruction': '''
            Отправь подготовленное фото «Кофе-до».
        '''
    },
    'step_4': {
        'type': CoffeeStepTypeSchema.TEXT_MESSAGE,
        'instruction': '''
            Узнай, сможет ли он угостить(оплатить) тебя кофе. Подразумевается, что ты и собеседник в разных городах.
        '''
    },
    'step_5': {
        'type': CoffeeStepTypeSchema.MODERATING,
        'instruction': '''
            Ожидание модерации, куда скинуть на кофе.
        '''
    },
}




# async def get_request_to_jev_ai(state,
#                                 questions):
#     async with AsyncTypeSafeClient(api_key=TYPESAFE_API_KEY,
#                                    base_url='https://jev-ai.pro/api') as client:
#         response = await client.system_one(
#             state=state,
#             questions=questions,
#         )

#     return response.answers



# choice_prompt = '''Проанализируй сообщения и верни ОДНО слово из перечня [positive, negative, undefined].
#                     Слово выбирается следующим образом: есть вопрос - {question}\n
#                     Варианты ответа "positive": {positive}, "negative": {negative}, "undefined": {undefined}.
#                     Выбери наиболее подходящий ответ и верни соответствующее слово.'''


async def route_jev_coffee_scenario(thread: Thread,
                                    coffee_state: CoffeeStateSchema,
                                    last_messages: list[Message],
                                    session: AsyncSession):
    state = 'Тебе даны последние сообщения из переписки с пользователем. Ты общаешься от лица assistant, пользователь — от лица user. Вот сообщения: {}'
    
    # coffee_state: CoffeeStateSchema = coffee_scenario_data.get('coffee_state')

    # last_messages = coffee_scenario_data.get('last_messages')

    current_step = coffee_state.current_step

    print(f'route step {current_step} with jev...')

    raw_messages_log, _, _ = await get_raw_messages_log_and_new_last_message_id(last_messages)
    
    match current_step:
        case 1:
            message_limit = 50

            if len(last_messages) < message_limit:
                    return {
                        'current_step': current_step,
                        'action': False,
                    }
            else:
                    return {
                        'current_step': current_step,
                        'action': True,
                        'last_messages': raw_messages_log,
                    }
        case 2:
            _state = state.format(raw_messages_log)
            # _state += '\nХочу написать от лица assistant в следующем сообщении, что я(assistant) устала на работе(от работы)'
            # questions = {
            #     "question_1": Choice(
            #         instructions=(
            #             "Уместно ли в следующем сообщении написать от лица assistant, "
            #             "что assistant устала от работы(на работе)?"
            #         ),
            #         criteria={
            #             "yes": "Такая реплика уместна в контексте этой переписки",
            #             "no": "Такая реплика неуместна в контексте этой переписки",
            #             # "undefined": "По переписке нельзя однозначно сказать, уместно это или нет",
            #         },
            #     ),
            #     "question_2": Noul(
            #         instructions=(
            #             "Есть ли сообщение(я) от user, по типу 'Как дела', которые пока остались без ответа?"
            #         ),
            #     ),
            # }

            # jev_answer = await get_request_to_jev_ai(_state,
            #                                          questions)
            
            choice_question_kwargs = {
                'question': 'Уместно ли в следующем сообщении написать от лица assistant, что assistant устала от работы(на работе)?',
                'positive': "Да, уместно",
                # 'negative': "Такая реплика неуместна в контексте этой переписки",
                # 'have_question': 'Есть сообщение(я) от user, по типу "Как дела", без ответа',
                'negative': "Нет, не уместно",
            }

            nual_question_kwargs = {
                'question': 'Есть ли сообщение(я) от user`а где он спрашивает как дела у assistant, которые остались без ответа?',
                'positive': "Да, есть",
                # 'negative': "Такая реплика неуместна в контексте этой переписки",
                # 'have_question': 'Есть сообщение(я) от user, по типу "Как дела", без ответа',
                'negative': "Нет, таких сообщений нет",
            }

            choice_answer = await like_jev_ai_request(system_prompt_kwargs=choice_question_kwargs,
                                                   user_prompt=_state)

            nual_answer = await like_jev_ai_request(system_prompt_kwargs=nual_question_kwargs,
                                                   user_prompt=_state)
            # print(' -> jev answer', jev_answer)
            
            choice_result = choice_answer.lower()

            nual_result = nual_answer.lower()

            if choice_result not in {'positive', 'negative'}:
                print(f'error with validate like jev answer - {choice_result}')
                raise

            if nual_result not in {'positive', 'negative'}:
                print(f'error with validate like jev answer - {nual_result}')
                raise

            if choice_result == 'positive':
                    return {
                        'current_step': current_step,
                        'action': True,
                        'last_messages': raw_messages_log,
                    }
            elif nual_result == 'positive':
                    return {
                        'current_step': current_step,
                        'action': True,
                        'last_messages': raw_messages_log,
                    }
            else:
                    return {
                        'current_step': current_step,
                        'action': False,
                    }

            # answer_1 = jev_answer.get('question_1') # Choice
            # answer_2 = jev_answer.get('question_2') # Noul


            # if not answer_1 and not answer_2:
            #     print('ERROR')
            # else:
            #     if answer_1.choice == 'yes' and answer_1.confidence >= 0.5:
            #         print(' -> STEP 1 | POSITIVE QUESTION 1')
            #         return {
            #             'current_step': current_step,
            #             'action': True,
            #             'last_messages': raw_messages_log,
            #         }
            #     elif answer_2.noul >= 0.6:
            #         print(' -> STEP 1 | POSITIVE QUESTION 2')
            #         return {
            #             'current_step': current_step,
            #             'action': True,
            #             'last_messages': raw_messages_log,
            #         }
            #     else:
            #         print(' -> STEP 1 | NEGATIVE')
            #         return {
            #             'current_step': current_step,
            #             'action': False,
            #             'last_messages': raw_messages_log,
            #         }
        case 3:
            # raw_messages_log, _, _ = await get_raw_messages_log_and_new_last_message_id(last_messages)
            # _state = state.format(raw_messages_log)
            # state += '\nХочу узнать как собеседник отреагировал на мое последнее сообщение(сообщение от assistant)'
            # questions = {
            #     "step_2": Choice(
            #         instructions=(
            #             "Как отреагировал собеседник на последнее сообщение от assistant?"
            #         ),
            #         criteria={
            #             "positive": "Собеседник хочет помочь/жалеет assistant",
            #             "neutral": "Собеседник не проявляет заинтересованность",
            #             "negative": "Собеседник переводит тему",
            #             # 'undefined': 'По переписке нельзя однозначно сказать, как отреагировал'
            #         },
            #     ),
            # }

            # jev_answer = await get_request_to_jev_ai(state,
            #                                          questions)

            # print(' -> jev answer', jev_answer)

            # step_answer = jev_answer.get('step_2')
            
            # if not step_answer:
            #     print('ERROR')
            # else:
            #     if step_answer.choice == 'positive' and step_answer.confidence >= 0.5:
                    # good result
                    # do step 1 (внутри меняем шаг на 2)
                    # switch to step_2 ?
            return {
                'current_step': current_step,
                'action': True,
                'last_messages': raw_messages_log,
            }
            #     else:
            #         return {
            #             'current_step': current_step,
            #             'action': False,
            #         }
            # pass
        case 4:
            # после отправки фото "До кофе"
            # raw_messages_log, _, _ = await get_raw_messages_log_and_new_last_message_id(last_messages)
            # _state = state.format(raw_messages_log)
            # state += '\nХочу узнать как собеседник отреагировал на мое последнее сообщение(сообщение от assistant)'
            # questions = {
            #     "step_3": Choice(
            #         instructions=(
            #             "Как отреагировал собеседник на последнее сообщение от assistant?"
            #         ),
            #         criteria={
            #             "positive": "Собеседник хочет помочь исправить ситуацию/жалеет assistant",
            #             # "neutral": "Собеседник не проявляет заинтересованность",
            #             # "negative": "Собеседник переводит тему",
            #             'undefined': 'По переписке нельзя однозначно сказать, как отреагировал'
            #         },
            #     ),
            # }

            # jev_answer = await get_request_to_jev_ai(state,
            #                                          questions)

            # step_answer = jev_answer.get('step_3')

            # print(' -> jev answer', jev_answer)
            
            # if not step_answer:
            #     print('ERROR')
            # else:
            #     if step_answer.choice == 'positive' and step_answer.confidence >= 0.5:
                    # good result
                    # do step 1 (внутри меняем шаг на 2)
                    # switch to step_2 ?
            return {
                'current_step': current_step,
                'action': True,
                'last_messages': raw_messages_log,
            }
                # else:
                #     return {
                #         'current_step': current_step,
                #         'action': False,
                #     }
        case 5:
            # raw_messages_log, _, _ = await get_raw_messages_log_and_new_last_message_id(last_messages)

            # print(f' -> last messages log\n{raw_messages_log}')

            _state = state.format(raw_messages_log)
            # state += '\nХочу узнать как собеседник(user) отреагировал на последние сообщения от assistant\nВ частности, на вопрос от assistant про кофе(если такой был)'
            # questions = {
            #     "question_1": Choice(
            #         instructions=(
            #             "Как собеседник отреагировал на вопрос assistant про кофе?"
            #         ),
            #         criteria={
            #             "positive": "Положительно",
            #             # "neutral": "Собеседник не проявляет заинтересованность",
            #             "negative": "Отрицательно",
            #             # 'undefined': 'По переписке пока нельзя однозначно сказать, как отреагировал'
            #         },
            #     ),
            #     "question_2": Noul(
            #         instructions=(
            #             "Есть ли в переданных сообщениях вопрос от assistant про кофе?"
            #         ),
            #         # criteria={
            #         #     "positive": "Положительно",
            #         #     # "neutral": "Собеседник не проявляет заинтересованность",
            #         #     "negative": "Отрицательно",
            #         #     # 'undefined': 'По переписке пока нельзя однозначно сказать, как отреагировал'
            #         # },
            #     ),
            # }
            # prompt = 'Проанализируй сообщения и верни ОДНО слово из перечня [positive, negative, undefined]. Слово выбирается следующим образом: есть вопрос - Как собеседник отреагировал на вопрос assistant <Сможет ли он угостить assistant кофе>?\nВарианты ответа "positive": "Положительно", "negative": "Отрицательно", "undefined": "По переписке пока нельзя однозначно сказать, как отреагировал".Выбери наиболее подходящий ответ и верни соответствующее слово.'

            # questions = {
            #     "step_4": Noul(
            #         instructions=(
            #             "Заинтересован ли собеседник вопросом от assistant "
            #             "о том, сможет ли он угостить assistant кофе?"
            #         ),
            #     ),
            # }

            # jev_answer = await get_request_to_jev_ai(state, questions)

            # jev_answer = await get_request_to_jev_ai(state,
            #                                          questions)
            choice_question_kwargs = {
                'question': 'Как собеседник отреагировал на вопрос assistant <Сможет ли он угостить assistant кофе>?',
                'positive': "Положительно",
                # 'negative': "Негативно",
                'negative': "Отрицательно",
            }

            nual_question_kwargs = {
                'question': 'Есть ли в переданных сообщениях вопрос от assistant про кофе?',
                'positive': "Да, есть",
                # 'negative': "Негативно",
                'negative': "Нет, такого вопроса",
            }

            choice_answer = await like_jev_ai_request(system_prompt_kwargs=choice_question_kwargs,
                                                      user_prompt=_state)

            nual_answer = await like_jev_ai_request(system_prompt_kwargs=nual_question_kwargs,
                                                      user_prompt=_state)

            # print(' -> jev answer', jev_answer)

            nual_result = nual_answer.lower()

            choice_result = choice_answer.lower()

            if nual_result not in {'positive', 'negative'}:
                print(f'error with validate like jev answer - {nual_result}')
                raise
            if choice_result not in {'positive', 'negative'}:
                print(f'error with validate like jev answer - {choice_result}')
                raise

            if nual_result != 'positive':
                return {
                    'current_step': current_step,
                    'action': False,
                }
            if choice_result != 'positive':
                return {
                    'current_step': current_step,
                    'action': False,
                }

            return {
                'current_step': current_step,
                'action': True,
                'last_messages': raw_messages_log,
            }
            # answer_1 = jev_answer.get('question_1')
            # answer_2 = jev_answer.get('question_2')
            
            # if not answer_1 and not answer_2:
            #     print('ERROR')
            # else:
            #     if answer_1.choice == 'positive' and answer_1.confidence >= 0.5:
            #         print(' -> STEP 4 | POSITIVE QUESTION 1')
            #         print(' -> перевод на модератора...')
            #         return {
            #             'current_step': current_step,
            #             'action': True,
            #             'last_messages': raw_messages_log,
            #         }
            #     elif answer_2.noul >= 0.6:
            #         print(' -> STEP 4 | POSITIVE QUESTION 2')
            #         print(' -> перевод на модератора...')
            #         return {
            #             'current_step': current_step,
            #             'action': True,
            #             'last_messages': raw_messages_log,
            #         }
            #     else:
            #         print(' -> STEP 4 | NEGATIVE')
            #         # print(' -> остался на шаге 4...')
            #         return {
            #             'current_step': current_step,
            #             'action': False,
            #         }


async def do_current_step_coffee_scenario(jev_data: dict,
                                          thread: Thread,
                                          account: Account,
                                          coffee_photos: list[CoffeeScenarioPhoto] | None = None):
    current_step = jev_data.get('current_step')
    last_messages = jev_data.get('last_messages')

    coffee_scenario_key = f'step_{current_step}'

    scenario_step = coffee_scenario.get(coffee_scenario_key)

    scenario_step_type = scenario_step.get('type')
    scenario_step_insctruction = scenario_step.get('instruction')
    purpose = None

    if scenario_step_type == CoffeeStepTypeSchema.TEXT_MESSAGE:
        message_text = await generate_new_message_to_thread_coffee_scenario(account.information,
                                                                            thread,
                                                                            scenario_step_insctruction,
                                                                            new_messages=last_messages)
        attachment = None

    elif scenario_step_type == CoffeeStepTypeSchema.PHOTO_MESSAGE:
        message_text = ''
        match current_step:
            case 2:
                purpose = 'before'
            case 4:
                purpose = 'after'

        photo_urls = [photo.media_url for photo in coffee_photos if photo.purpose == purpose]
        shuffle(photo_urls)
        selected_photo_url = photo_urls[0]

        attachment = {
            'media_type': 'photo',
            'media_url': selected_photo_url,
            'purpose': purpose,
        }

    elif scenario_step_type == CoffeeStepTypeSchema.MODERATING:
         print(' -> waiting for moderate thread...')
         # send notification(ws event to frontend)
         pass
    elif scenario_step_type == CoffeeStepTypeSchema.PREPARING:
        return (
            None,
            None,
            )

    
    return (
        message_text,
        attachment,
        )

    

